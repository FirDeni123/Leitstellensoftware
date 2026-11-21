"""Feuersoftware Connect plugin – only ever against a simulated endpoint (httpx.MockTransport).

The real service is never contacted from tests: creating an operation there alarms people.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.models import OperationMode
from app.plugins.base import AlarmMessage, DeliveryResult, PluginMeta
from app.plugins.builtin import feuersoftware
from app.plugins.builtin.feuersoftware import FeuersoftwareConnectPlugin, split_address
from app.services.interface_service import deliver
from tests.test_alarming import (  # noqa: F401 – shared fixtures and helpers
    _fast_retries,
    _incident,
    _interface,
    _ok_alarm,
    _set_mode,
    ctx,
)
from tests.test_operations import setup  # noqa: F401

TOKEN = "fs-connect-test-token-0815"


def _message(**overrides) -> AlarmMessage:
    data = {
        "alarm_id": "a1",
        "control_center": "ILS Demo",
        "incident_number": "2026-000123",
        "keyword": "B2",
        "keyword_name": "Mittelbrand",
        "incident_type": "fire",
        "priority": 1,
        "address": "Industriestraße 30, 21493 Demostadt",
        "location_note": "Parkplatz hinten",
        "latitude": 53.4952,
        "longitude": 10.4968,
        "description": "Pkw brennt",
        "stage": 1,
        "mode": "real",
        "created_at": datetime(2026, 11, 21, 21, 15, 0, tzinfo=UTC),
        "vehicles": ["Florian Demo 1/46-1"],
        "stations": [],
        "rics": ["1000101A"],
    }
    return AlarmMessage(**(data | overrides))


class Recorder:
    def __init__(self, status: int = 204, body: object = None) -> None:
        self.requests: list[httpx.Request] = []
        self.status, self.body = status, body

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.body is not None:
            return httpx.Response(self.status, json=self.body)
        return httpx.Response(self.status)


@pytest.fixture
def endpoint(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(feuersoftware, "TRANSPORT", httpx.MockTransport(recorder))
    return recorder


# --------------------------------------------------------------------------- unit level
def test_address_is_split_into_connect_fields():
    assert split_address("Industriestraße 30, 21493 Demostadt") == {
        "Street": "Industriestraße",
        "HouseNumber": "30",
        "ZipCode": "21493",
        "City": "Demostadt",
    }
    assert split_address("Am Markt 1a, 21493 Demostadt")["HouseNumber"] == "1a"
    assert split_address("Kreuzung Hauptstraße / Mühlenweg, Demostadt") == {
        "Street": "Kreuzung Hauptstraße / Mühlenweg",
        "City": "Demostadt",
    }
    assert split_address(None) is None and split_address("  ") is None


async def test_operation_request_matches_the_documented_format(endpoint):
    plugin = FeuersoftwareConnectPlugin()
    result = await plugin.send_alarm({}, TOKEN, _message())
    assert result.ok and "2026-000123" in result.detail and "mit Alarm" in result.detail
    request = endpoint.requests[0]
    assert request.method == "POST"
    assert str(request.url).startswith("https://connectapi.feuersoftware.com/interfaces/public/operation?")
    assert request.url.params["updateStrategy"] == "ByNumber"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    body = json.loads(request.content)
    assert body["Start"] == "2026-11-21T22:15:00+01:00"  # local time of the alarm with offset
    assert body["Status"] == 0 and body["Priority"] == 3 and body["AlarmEnabled"] is True
    assert body["Keyword"] == "B2 – Mittelbrand" and body["Number"] == "2026-000123"
    assert body["Address"] == {
        "Street": "Industriestraße",
        "HouseNumber": "30",
        "ZipCode": "21493",
        "City": "Demostadt",
    }
    assert body["Position"] == {"Latitude": 53.4952, "Longitude": 10.4968}
    assert body["Facts"] == "Pkw brennt\nOrtshinweis: Parkplatz hinten"
    assert body["Source"] == "ILS-Sim ILS Demo"
    props = {p["Key"]: p["Value"] for p in body["Properties"]}
    assert props["Alarmierte Fahrzeuge"] == "Florian Demo 1/46-1" and props["RIC"] == "1000101A"
    assert "Ric" not in body  # 7-digit RICs do not fit Connect's 5-char field – only when configured


async def test_config_options(endpoint):
    plugin = FeuersoftwareConnectPlugin()
    config = {"alarm_enabled": False, "update_strategy": "None", "ric": "12345", "keyword_format": "code"}
    result = await plugin.send_alarm(config, TOKEN, _message(kind="follow_up", priority=3, latitude=None))
    assert result.ok and "ohne Alarm" in result.detail
    request = endpoint.requests[0]
    body = json.loads(request.content)
    assert request.url.params["updateStrategy"] == "None"
    assert body["AlarmEnabled"] is False and body["Ric"] == "12345" and body["Keyword"] == "B2"
    assert body["Status"] == 1 and body["Priority"] == 1  # follow-up = Update; ILS 3 = Low
    assert "Position" not in body


@pytest.mark.parametrize(
    ("status", "retryable", "text"),
    [
        (400, False, "Validierung"),
        (401, False, "Token ungültig"),
        (403, False, "Berechtigung"),
        (429, True, "Rate-Limit"),
        (503, True, "HTTP 503"),
    ],
)
async def test_error_responses(monkeypatch, status, retryable, text):
    monkeypatch.setattr(
        feuersoftware, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(status, text="nope"))
    )
    result = await FeuersoftwareConnectPlugin().send_alarm({}, TOKEN, _message())
    assert not result.ok and result.retryable is retryable and text in result.detail


async def test_connection_test_only_reads(monkeypatch):
    recorder = Recorder(200, [{"Id": 1, "SiteName": "FF Demostadt", "Keyword": "x"}])
    monkeypatch.setattr(feuersoftware, "TRANSPORT", httpx.MockTransport(recorder))
    result = await FeuersoftwareConnectPlugin().test({}, TOKEN)
    assert result.ok and "FF Demostadt" in result.detail
    assert [r.method for r in recorder.requests] == ["GET"]  # never creates an operation
    assert recorder.requests[0].url.params["onlyLatest"] == "true"


async def test_core_stops_retrying_on_permanent_errors():
    calls: list[int] = []

    class Plugin:
        meta = PluginMeta(key="x", name="x", description="", is_real=True, config_schema={})

        async def test(self, config, secret):  # pragma: no cover - unused
            return DeliveryResult(True, "")

        async def send_alarm(self, config, secret, message):
            calls.append(1)
            return DeliveryResult(False, "HTTP 401: API-Token ungültig", retryable=False)

    result = await deliver(Plugin(), {}, None, _message(), enabled=True, mode=OperationMode.REAL)
    assert result.status == "failed" and len(calls) == 1 and "nach 1 Versuch)" in result.detail


async def test_simulation_mode_never_calls_feuersoftware(endpoint):
    result = await deliver(
        FeuersoftwareConnectPlugin(),
        {},
        TOKEN,
        _message(mode="simulation"),
        enabled=True,
        mode=OperationMode.SIMULATION,
    )
    assert result.status == "simulated" and endpoint.requests == []


# ------------------------------------------------------------------------- through the API
async def test_feuersoftware_interface_end_to_end(client, ctx, endpoint):  # noqa: F811
    c = ctx
    plugins = {p["key"]: p for p in (await client.get("/plugins", headers=c["admin"])).json()}
    meta = plugins["feuersoftware_connect"]
    assert meta["is_real"] is True and meta["secret_required"] is True

    bad = await client.post(
        "/interfaces",
        headers=c["admin"],
        json={
            "plugin_key": "feuersoftware_connect",
            "name": "FS",
            "scope": "control_center",
            "control_center_id": c["cc"]["id"],
            "config": {"ric": "1000101"},
            "secret": TOKEN,
        },
    )
    assert bad.status_code == 422  # RIC longer than Connect accepts

    iface = await _interface(
        client, c, plugin="feuersoftware_connect", secret=TOKEN, config={"alarm_enabled": False}
    )
    assert iface["enabled"] is False  # never active on creation
    assert TOKEN not in json.dumps(iface)

    # Simulation mode: cannot be switched on, alarms are not transmitted.
    r = await client.post(
        f"/interfaces/{iface['id']}/enabled",
        headers=c["admin"],
        json={"enabled": True, "expected_version": iface["version"], "reason": "Test"},
    )
    assert r.status_code == 409
    await _ok_alarm(client, c, await _incident(client, c), {"vehicle_ids": [c["vehicles"]["hlf"]["id"]]})
    assert endpoint.requests == []

    # Real mode, enabled by an administrator: one operation per confirmed alarm, no alarm push.
    await _set_mode(client, c, "real")
    try:
        current = (await client.get(f"/interfaces/{iface['id']}", headers=c["admin"])).json()
        r = await client.post(
            f"/interfaces/{iface['id']}/enabled",
            headers=c["admin"],
            json={"enabled": True, "expected_version": current["version"], "reason": "Test mit Connect"},
        )
        assert r.status_code == 200, r.text
        incident = await _incident(client, c)
        alarm = await _ok_alarm(client, c, incident, {"vehicle_ids": [c["vehicles"]["dlk"]["id"]]})
        stored = (await client.get(f"/alarms/{alarm['id']}", headers=c["dispo"])).json()
        target = next(t for t in stored["targets"] if t["target_type"] == "interface")
        assert target["delivery_status"] == "sent" and "ohne Alarm" in target["detail"]
        assert len(endpoint.requests) == 1
        body = json.loads(endpoint.requests[0].content)
        assert body["Number"] == incident["number"] and body["AlarmEnabled"] is False
        assert endpoint.requests[0].headers["authorization"] == f"Bearer {TOKEN}"
    finally:
        await _set_mode(client, c, "simulation")
    after = (await client.get(f"/interfaces/{iface['id']}", headers=c["admin"])).json()
    assert after["enabled"] is False  # leaving real operation switches real interfaces off
