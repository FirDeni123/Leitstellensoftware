"""M6: every connected client receives exactly the same positions (real WebSocket connections)."""

from __future__ import annotations

import uuid

import pytest
from starlette.testclient import TestClient

from app.main import create_app
from app.simulation import clock as clock_module
from app.simulation.runner import tick_once
from tests.conftest import ADMIN_PASSWORD, USER_PASSWORD
from tests.test_realtime import WS, _connect, _login


@pytest.fixture
def tc(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def _positions(ws) -> dict:
    while True:
        msg = ws.receive_json()
        if msg["type"] == "event" and msg["topic"] == "vehicle.positions":
            return msg["data"]


def test_m6_all_clients_see_identical_positions(tc, monkeypatch):
    now = {"t": 1_900_000_000.0}
    monkeypatch.setattr(clock_module, "real_time", lambda: now["t"])
    admin = _login(tc, "admin", ADMIN_PASSWORD)
    h = {"Authorization": f"Bearer {admin['access_token']}"}
    cc = tc.post("/api/v1/control-centers", headers=h, json={"code": "ILS-M6", "name": "M6"}).json()
    users = {u["username"]: u for u in tc.get("/api/v1/users", headers=h).json()["items"]}
    for name in ("admin", "dispo"):
        tc.patch(
            f"/api/v1/users/{users[name]['id']}",
            headers=h,
            json={"control_center_ids": [cc["id"]], "expected_version": users[name]["version"]},
        )
    org = next(o for o in tc.get("/api/v1/organizations", headers=h).json() if o["key"] == "feuerwehr")
    hlf = next(t for t in tc.get("/api/v1/vehicle-types", headers=h).json() if t["code"] == "HLF20")
    station = tc.post(
        "/api/v1/stations",
        headers=h,
        json={
            "control_center_id": cc["id"],
            "organization_id": org["id"],
            "name": "Wache M6",
            "latitude": 53.5,
            "longitude": 10.48,
        },
    ).json()
    vehicle_ids = [
        tc.post(
            "/api/v1/vehicles",
            headers=h,
            json={
                "control_center_id": cc["id"],
                "station_id": station["id"],
                "vehicle_type_id": hlf["id"],
                "call_sign": f"M6 {i}",
            },
        ).json()["id"]
        for i in range(3)
    ]
    incident = tc.post(
        "/api/v1/incidents",
        headers=h,
        json={
            "control_center_id": cc["id"],
            "address": "Weg 1",
            "latitude": 53.53,
            "longitude": 10.53,
        },
    ).json()
    r = tc.post(
        f"/api/v1/incidents/{incident['id']}/alarms",
        headers={**h, "Idempotency-Key": uuid.uuid4().hex},
        json={"vehicle_ids": vehicle_ids, "confirmed": True},
    )
    assert r.status_code == 201, r.text

    dispo = _login(tc, "dispo", USER_PASSWORD)
    with tc.websocket_connect(WS) as ws_a, tc.websocket_connect(WS) as ws_b:
        _connect(ws_a, admin["access_token"])
        _connect(ws_b, dispo["access_token"])
        now["t"] += 91
        tc.portal.call(tick_once, tc.app.state)  # departures
        now["t"] += 30
        tc.portal.call(tick_once, tc.app.state)
        a, b = _positions(ws_a), _positions(ws_b)
        while a["sim_time"] != b["sim_time"]:  # both clients may still hold the departure tick
            a = _positions(ws_a) if a["sim_time"] < b["sim_time"] else a
            b = _positions(ws_b) if b["sim_time"] < a["sim_time"] else b
    assert a == b
    assert len(a["positions"]) == 3 and all(p["kind"] == "to_incident" for p in a["positions"])
