"""WebSocket tests (synchronous Starlette TestClient running its own event loop)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from tests.conftest import ADMIN_PASSWORD, USER_PASSWORD

WS = "/api/v1/ws"


@pytest.fixture
def tc(settings):
    fast = settings.model_copy(update={"ws_auth_timeout_seconds": 0.5})
    with TestClient(create_app(fast)) as client:
        yield client


def _login(tc: TestClient, username: str, password: str) -> dict:
    r = tc.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _connect(ws, token: str) -> dict:
    ws.send_json({"type": "auth", "token": token})
    welcome = ws.receive_json()
    assert welcome["type"] == "welcome", welcome
    return welcome


def _next_event(ws) -> dict:
    while True:
        msg = ws.receive_json()
        if msg["type"] == "event":
            return msg


def test_invalid_token_is_rejected(tc):
    with tc.websocket_connect(WS) as ws:
        ws.send_json({"type": "auth", "token": "ungueltig"})
        assert ws.receive_json()["code"] == "auth_failed"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4001


def test_auth_timeout(tc):
    with tc.websocket_connect(WS) as ws:
        assert ws.receive_json()["code"] == "auth_failed"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4001


def test_ping_pong(tc):
    tokens = _login(tc, "dispo", USER_PASSWORD)
    with tc.websocket_connect(WS) as ws:
        _connect(ws, tokens["access_token"])
        ws.send_json({"type": "ping", "ts": 123})
        pong = ws.receive_json()
        assert pong["type"] == "pong" and pong["ts"] == 123


def test_events_are_filtered_by_permission(tc):
    admin = _login(tc, "admin", ADMIN_PASSWORD)
    dispo = _login(tc, "dispo", USER_PASSWORD)
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    target = next(
        u for u in tc.get("/api/v1/users", headers=headers).json()["items"] if u["username"] == "dispo"
    )

    with tc.websocket_connect(WS) as admin_ws, tc.websocket_connect(WS) as dispo_ws:
        _connect(admin_ws, admin["access_token"])
        _connect(dispo_ws, dispo["access_token"])
        r = tc.patch(
            f"/api/v1/users/{target['id']}",
            headers=headers,
            json={"display_name": "Umbenannt", "expected_version": target["version"]},
        )
        assert r.status_code == 200

        topics = {_next_event(admin_ws)["topic"], _next_event(admin_ws)["topic"]}
        assert topics == {"user.updated", "audit.created"}
        # The dispatcher lacks users.read/audit.read: the first event it sees is its own me.changed.
        mine = _next_event(dispo_ws)
        assert mine["topic"] == "me.changed" and mine["data"]["id"] == target["id"]


def test_deactivation_disconnects_user(tc):
    admin = _login(tc, "admin", ADMIN_PASSWORD)
    dispo = _login(tc, "dispo", USER_PASSWORD)
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    target = next(
        u for u in tc.get("/api/v1/users", headers=headers).json()["items"] if u["username"] == "dispo"
    )
    with tc.websocket_connect(WS) as ws:
        _connect(ws, dispo["access_token"])
        r = tc.put(
            f"/api/v1/users/{target['id']}/active",
            headers=headers,
            json={"is_active": False, "expected_version": target["version"]},
        )
        assert r.status_code == 200
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                ws.receive_json()
    assert exc.value.code == 4001


def test_logout_closes_session_socket(tc):
    dispo = _login(tc, "dispo", USER_PASSWORD)
    with tc.websocket_connect(WS) as ws:
        _connect(ws, dispo["access_token"])
        assert (
            tc.post(
                "/api/v1/auth/logout", headers={"Authorization": f"Bearer {dispo['access_token']}"}
            ).status_code
            == 204
        )
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:
                ws.receive_json()
    assert exc.value.code == 4003


def test_master_data_events_are_scoped_to_control_center(tc):
    admin = _login(tc, "admin", ADMIN_PASSWORD)
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    own = tc.post(
        "/api/v1/control-centers", headers=headers, json={"code": "ILS-OWN", "name": "Eigene"}
    ).json()
    other = tc.post(
        "/api/v1/control-centers", headers=headers, json={"code": "ILS-OTH", "name": "Fremde"}
    ).json()
    users = tc.get("/api/v1/users", headers=headers).json()["items"]
    dispo = next(u for u in users if u["username"] == "dispo")
    tc.patch(
        f"/api/v1/users/{dispo['id']}",
        headers=headers,
        json={"control_center_ids": [own["id"]], "expected_version": dispo["version"]},
    )
    org = next(o for o in tc.get("/api/v1/organizations", headers=headers).json() if o["key"] == "feuerwehr")
    dispo_tokens = _login(tc, "dispo", USER_PASSWORD)
    with tc.websocket_connect(WS) as ws:
        _connect(ws, dispo_tokens["access_token"])
        tc.post(
            "/api/v1/stations",
            headers=headers,
            json={"control_center_id": other["id"], "organization_id": org["id"], "name": "Fremdwache"},
        )
        tc.post(
            "/api/v1/stations",
            headers=headers,
            json={"control_center_id": own["id"], "organization_id": org["id"], "name": "Eigene Wache"},
        )
        event = _next_event(ws)
        assert event["topic"] == "master_data.changed"
        assert event["data"]["collection"] == "stations" and event["data"]["action"] == "created"
        station_id = event["data"]["id"]
    own_station = tc.get(f"/api/v1/stations/{station_id}", headers=headers).json()
    assert own_station["name"] == "Eigene Wache"


def test_ringing_call_reaches_call_takers_of_the_control_center(tc):
    admin = _login(tc, "admin", ADMIN_PASSWORD)
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    cc = tc.post(
        "/api/v1/control-centers", headers=headers, json={"code": "ILS-RT", "name": "Echtzeit"}
    ).json()
    users = tc.get("/api/v1/users", headers=headers).json()["items"]
    dispo = next(u for u in users if u["username"] == "dispo")
    tc.patch(
        f"/api/v1/users/{dispo['id']}",
        headers=headers,
        json={"control_center_ids": [cc["id"]], "expected_version": dispo["version"]},
    )
    dispo_tokens = _login(tc, "dispo", USER_PASSWORD)
    with tc.websocket_connect(WS) as ws:
        _connect(ws, dispo_tokens["access_token"])
        r = tc.post("/api/v1/simulation/calls", headers=headers, json={"control_center_id": cc["id"]})
        assert r.status_code == 201, r.text
        event = _next_event(ws)
        assert event["topic"] == "call.changed" and event["data"]["action"] == "ringing"
        assert event["data"]["id"] == r.json()[0]["id"]
