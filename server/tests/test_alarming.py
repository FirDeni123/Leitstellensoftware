"""Phase 4: AAO, alarm preview, confirmed alarms, police notices, interfaces (milestone M4)."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text, update

from app.core.crypto import SecretBox
from app.models import Alarm, AlarmTarget, AuditLog, Interface, InterfaceEvent, Vehicle
from app.plugins.builtin import webhook
from app.realtime.bus import InMemoryEventBus
from app.services import interface_service
from app.services.alarm_delivery import recover_interrupted_deliveries
from app.services.uow import UnitOfWork
from tests.test_operations import setup  # noqa: F401 – shared fixture (control centre, vehicles, users)

SECRET = "sehr-geheimer-token-4711"


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    monkeypatch.setattr(interface_service, "RETRY_DELAYS", (0.0, 0.0))


@pytest.fixture
async def ctx(client, setup, db):  # noqa: F811
    """Adds RICs, a second fire station, a police station/vehicle and an AAO for B2."""
    c = dict(setup)
    admin, cc_id = c["admin"], c["cc"]["id"]
    orgs = {o["key"]: o for o in (await client.get("/organizations", headers=admin)).json()}
    types = {t["code"]: t for t in (await client.get("/vehicle-types", headers=admin)).json()}
    c["types"] = types
    stations = (await client.get("/stations", headers=admin, params={"control_center_id": cc_id})).json()
    c["station"] = stations[0] if isinstance(stations, list) else stations["items"][0]
    ric_hlf = (
        await client.post(
            "/rics",
            headers=admin,
            json={
                "control_center_id": cc_id,
                "code": "1234501",
                "label": "LZ Ops Vollalarm",
                "vehicle_ids": [c["vehicles"]["hlf"]["id"]],
            },
        )
    ).json()
    c["ric_hlf"] = ric_hlf
    second = (
        await client.post(
            "/stations",
            headers=admin,
            json={
                "control_center_id": cc_id,
                "organization_id": orgs["feuerwehr"]["id"],
                "name": "FF Nachbarort",
                "latitude": 53.6,
                "longitude": 10.6,
            },
        )
    ).json()
    c["second_station"] = second
    c["second_hlf"] = (
        await client.post(
            "/vehicles",
            headers=admin,
            json={
                "control_center_id": cc_id,
                "station_id": second["id"],
                "vehicle_type_id": types["HLF20"]["id"],
                "call_sign": "Florian Nachbar 1/46-1",
            },
        )
    ).json()
    police_station = (
        await client.post(
            "/stations",
            headers=admin,
            json={
                "control_center_id": cc_id,
                "organization_id": orgs["polizei"]["id"],
                "name": "Polizeirevier",
            },
        )
    ).json()
    c["police_station"] = police_station
    # Master data already refuse police vehicles; insert one directly to test the alarm-level guard.
    async with db.sessionmaker() as session:
        police_vehicle = Vehicle(
            control_center_id=uuid.UUID(cc_id),
            station_id=uuid.UUID(police_station["id"]),
            organization_id=uuid.UUID(orgs["polizei"]["id"]),
            vehicle_type_id=uuid.UUID(types["MTW"]["id"]),
            call_sign="Funkstreife 11",
            status_code=2,
        )
        session.add(police_vehicle)
        await session.commit()
        c["police_vehicle"] = {"id": str(police_vehicle.id)}
    rule = await client.post(
        "/alarm-rules",
        headers=admin,
        json={
            "control_center_id": cc_id,
            "keyword_id": c["keywords"]["B2"]["id"],
            "name": "B2 Standard",
            "items": [
                {"stage": 1, "kind": "vehicle_type", "target_id": types["HLF20"]["id"], "count": 1},
                {"stage": 1, "kind": "vehicle_type", "target_id": types["DLK23"]["id"], "count": 1},
                {"stage": 2, "kind": "vehicle_type", "target_id": types["RTW"]["id"], "count": 1},
            ],
        },
    )
    assert rule.status_code == 201, rule.text
    c["rule"] = rule.json()
    return c


async def _incident(client, c, keyword="B2", **extra):
    body = {
        "control_center_id": c["cc"]["id"],
        "keyword_id": c["keywords"][keyword]["id"],
        "address": "Demostraße 1, Demostadt",
        "latitude": 53.501,
        "longitude": 10.481,
        **extra,
    }
    r = await client.post("/incidents", headers=c["dispo"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _preview(client, c, incident, **body):
    r = await client.post(f"/incidents/{incident['id']}/alarm-preview", headers=c["dispo"], json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def _alarm(client, c, incident, selection, key=None, headers=None, **extra):
    body = {**selection, "confirmed": True, **extra}
    return await client.post(
        f"/incidents/{incident['id']}/alarms",
        headers={**(headers or c["dispo"]), "Idempotency-Key": key or uuid.uuid4().hex},
        json=body,
    )


async def _ok_alarm(client, c, incident, selection, **extra):
    r = await _alarm(client, c, incident, selection, **extra)
    assert r.status_code == 201, r.text
    return r.json()


async def _set_mode(client, c, mode):
    current = (await client.get("/system/operation-mode", headers=c["admin"])).json()
    r = await client.put(
        "/system/operation-mode",
        headers=c["admin"],
        json={
            "mode": mode,
            "reason": "Test der Betriebsarten",
            "confirmation": "ECHTBETRIEB",
            "expected_version": current["version"],
        },
    )
    assert r.status_code == 200, r.text


async def _interface(client, c, plugin="webhook", scope="control_center", **extra):
    body = {
        "plugin_key": plugin,
        "name": f"{plugin} Test",
        "scope": scope,
        "control_center_id": c["cc"]["id"] if scope != "global" else None,
        "config": {"url": "https://alarm.example.invalid/hook"} if plugin == "webhook" else {},
        **extra,
    }
    r = await client.post("/interfaces", headers=c["admin"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------------------------- AAO
async def test_alarm_rule_validation_and_permissions(client, ctx):
    c = ctx
    base = {"control_center_id": c["cc"]["id"], "keyword_id": c["keywords"]["B2"]["id"]}
    duplicate = await client.post("/alarm-rules", headers=c["admin"], json=base)
    assert duplicate.status_code == 409
    foreign = await client.post(
        "/alarm-rules",
        headers=c["admin"],
        json={
            "control_center_id": c["cc"]["id"],
            "keyword_id": c["keywords"]["B1"]["id"],
            "items": [{"kind": "vehicle", "target_id": c["foreign"]["id"]}],
        },
    )
    assert foreign.status_code == 422
    police = await client.post(
        "/alarm-rules",
        headers=c["admin"],
        json={
            "control_center_id": c["cc"]["id"],
            "keyword_id": c["keywords"]["B1"]["id"],
            "items": [{"kind": "station", "target_id": c["police_station"]["id"]}],
        },
    )
    assert police.status_code == 422 and "Polizei" in police.json()["error"]["message"]
    # Dispatchers may read but not change the AAO.
    assert (await client.get("/alarm-rules", headers=c["dispo"])).status_code == 200
    forbidden = await client.patch(
        f"/alarm-rules/{c['rule']['id']}", headers=c["dispo"], json={"expected_version": 1, "name": "x"}
    )
    assert forbidden.status_code == 403
    # Replace the items; a stale version is rejected.
    rule = c["rule"]
    assert [i["target_label"].split(" ")[0] for i in rule["items"]] == ["HLF20", "DLK23", "RTW"]
    assert rule["max_stage"] == 2
    r = await client.patch(
        f"/alarm-rules/{rule['id']}",
        headers=c["admin"],
        json={
            "expected_version": rule["version"],
            "items": [{"stage": 1, "kind": "ric", "target_id": c["ric_hlf"]["id"]}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["version"] > rule["version"] and len(r.json()["items"]) == 1
    stale = await client.patch(
        f"/alarm-rules/{rule['id']}",
        headers=c["admin"],
        json={"expected_version": rule["version"], "name": "x"},
    )
    assert stale.status_code == 409


# ----------------------------------------------------------------------------- preview / M4
async def test_m4_preview_for_b2_is_correct_and_triggers_nothing(client, ctx, db):
    c = ctx
    incident = await _incident(client, c)
    preview = await _preview(client, c, incident)
    assert preview["rule"]["name"] == "B2 Standard"
    assert preview["stage"] == 1 and preview["max_stage"] == 2 and preview["next_kind"] == "initial"
    assert preview["mode"] == "simulation"
    calls = {v["call_sign"]: v for v in preview["vehicles"]}
    # Nearest HLF (own station, ~0.1 km) instead of the neighbouring station; DLK; no RTW in stage 1.
    assert set(calls) == {"Florian Ops 1/46-1", "Florian Ops 1/33-1"}
    assert calls["Florian Ops 1/46-1"]["distance_km"] < 1
    assert calls["Florian Ops 1/46-1"]["reason"].startswith("AAO Stufe 1")
    assert [r["label"] for r in preview["rics"]] == ["1234501 LZ Ops Vollalarm"]
    assert preview["police_notice"] is None and preview["warnings"] == []
    assert set(preview["selection"]["vehicle_ids"]) == {
        c["vehicles"]["hlf"]["id"],
        c["vehicles"]["dlk"]["id"],
    }
    # A preview changes nothing.
    detail = (await client.get(f"/incidents/{incident['id']}", headers=c["dispo"])).json()
    assert detail["status"] == "new" and detail["assignments"] == []
    async with db.sessionmaker() as s:
        assert (await s.scalar(select(Alarm.id))) is None

    # Stage 2 at once: everything of stages 1 and 2.
    stage2 = await _preview(client, c, incident, stage=2)
    assert {v["vehicle_type"] for v in stage2["vehicles"]} == {"HLF20", "DLK23", "RTW"}


async def test_preview_warns_about_missing_units_and_missing_aao(client, ctx):
    c = ctx
    await client.patch(
        f"/vehicles/{c['vehicles']['dlk']['id']}",
        headers=c["admin"],
        json={"available": False, "expected_version": c["vehicles"]["dlk"]["version"]},
    )
    preview = await _preview(client, c, await _incident(client, c))
    assert any("DLK23: 1 von 1 nicht verfügbar" in w for w in preview["warnings"])
    no_rule = await _preview(client, c, await _incident(client, c, keyword="B1"))
    assert no_rule["rule"] is None and no_rule["vehicles"] == []
    assert any("Keine AAO für B1" in w for w in no_rule["warnings"])


async def test_area_specific_rule_wins_inside_the_area(client, ctx):
    c = ctx
    area = await client.post(
        "/control-center-areas",
        headers=c["admin"],
        json={
            "control_center_id": c["cc"]["id"],
            "name": "Altstadt",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[10.47, 53.49], [10.49, 53.49], [10.49, 53.51], [10.47, 53.51]]],
            },
        },
    )
    assert area.status_code == 201, area.text
    r = await client.post(
        "/alarm-rules",
        headers=c["admin"],
        json={
            "control_center_id": c["cc"]["id"],
            "keyword_id": c["keywords"]["B2"]["id"],
            "area_id": area.json()["id"],
            "name": "B2 Altstadt",
            "items": [{"kind": "vehicle_type", "target_id": c["types"]["HLF20"]["id"], "count": 2}],
        },
    )
    assert r.status_code == 201, r.text
    inside = await _preview(client, c, await _incident(client, c))
    assert inside["rule"]["name"] == "B2 Altstadt" and inside["rule"]["area"] == "Altstadt"
    assert sorted(v["call_sign"] for v in inside["vehicles"]) == [
        "Florian Nachbar 1/46-1",
        "Florian Ops 1/46-1",
    ]
    outside = await _preview(client, c, await _incident(client, c, latitude=53.7, longitude=10.7))
    assert outside["rule"]["name"] == "B2 Standard"


# ------------------------------------------------------------------------- alarm / M4
async def test_m4_alarm_only_after_confirmation_and_idempotent(client, ctx, db):
    c = ctx
    incident = await _incident(client, c)
    selection = (await _preview(client, c, incident))["selection"]
    url = f"/incidents/{incident['id']}/alarms"
    no_confirm = await client.post(url, headers={**c["dispo"], "Idempotency-Key": "k" * 16}, json=selection)
    assert no_confirm.status_code == 422
    not_true = await client.post(
        url, headers={**c["dispo"], "Idempotency-Key": "k" * 16}, json={**selection, "confirmed": False}
    )
    assert not_true.status_code == 422
    no_key = await client.post(url, headers=c["dispo"], json={**selection, "confirmed": True})
    assert no_key.status_code == 422
    async with db.sessionmaker() as s:
        assert (await s.scalar(select(Alarm.id))) is None

    key = uuid.uuid4().hex
    first = await _alarm(client, c, incident, selection, key=key)
    assert first.status_code == 201, first.text
    alarm = first.json()
    assert alarm["kind"] == "initial" and alarm["stage"] == 1 and alarm["mode"] == "simulation"
    assert alarm["status"] == "completed" and alarm["triggered_by_name"].startswith("Test Disponent")
    statuses = {(t["target_type"], t["label"].split(" (")[0]): t["delivery_status"] for t in alarm["targets"]}
    assert statuses == {
        ("vehicle", "Florian Ops 1/46-1"): "simulated",
        ("vehicle", "Florian Ops 1/33-1"): "simulated",
        ("ric", "1234501 LZ Ops Vollalarm"): "simulated",
    }
    # Repeating the request (e.g. after a network error) does not alarm twice.
    again = await _alarm(client, c, incident, selection, key=key)
    assert again.status_code == 200 and again.json()["id"] == alarm["id"] and again.json()["replayed"] is True
    misuse = await _alarm(client, c, incident, {"vehicle_ids": [c["vehicles"]["rtw"]["id"]]}, key=key)
    assert misuse.status_code == 409
    async with db.sessionmaker() as s:
        assert len((await s.scalars(select(Alarm))).all()) == 1

    detail = (await client.get(f"/incidents/{incident['id']}", headers=c["dispo2"])).json()
    assert detail["status"] == "alarmed"
    assert all(a["alarmed_at"] for a in detail["assignments"]) and len(detail["assignments"]) == 2
    events = (await client.get(f"/incidents/{incident['id']}/events", headers=c["dispo"])).json()
    alarm_events = [e for e in events if e["kind"] == "alarm"]
    assert len(alarm_events) == 1 and "Erstalarm (Stufe 1, AAO B2) [Simulation]" in alarm_events[0]["text"]
    assert alarm_events[0]["actor_name"].startswith("Test Disponent")
    assert any(e["kind"] == "status" and "Alarmiert" in e["text"] for e in events)

    # Follow-up: the next stage proposes only what is still missing.
    follow = await _preview(client, c, incident)
    assert follow["stage"] == 2 and follow["next_kind"] == "follow_up"
    assert [v["vehicle_type"] for v in follow["vehicles"]] == ["RTW"]
    assert sorted(follow["already_alarmed"]) == ["Florian Ops 1/33-1", "Florian Ops 1/46-1"]
    second = await _alarm(client, c, incident, follow["selection"], stage=2)
    assert second.status_code == 201 and second.json()["kind"] == "follow_up"
    listed = (await client.get(f"/incidents/{incident['id']}/alarms", headers=c["dispo"])).json()
    assert [a["kind"] for a in listed] == ["follow_up", "initial"]
    overview = (
        await client.get("/alarms", headers=c["dispo"], params={"control_center_id": c["cc"]["id"]})
    ).json()
    assert len(overview) == 2 and overview[0]["incident_number"] == incident["number"]


async def test_concurrent_requests_with_same_key_alarm_once(client, ctx, db):
    c = ctx
    incident = await _incident(client, c)
    selection = (await _preview(client, c, incident))["selection"]
    key = uuid.uuid4().hex
    results = await asyncio.gather(*(_alarm(client, c, incident, selection, key=key) for _ in range(4)))
    assert sorted(r.status_code for r in results) == [200, 200, 200, 201]
    assert len({r.json()["id"] for r in results}) == 1
    async with db.sessionmaker() as s:
        assert len((await s.scalars(select(Alarm))).all()) == 1


async def test_alarm_permissions_and_rules(client, ctx):
    c = ctx
    incident = await _incident(client, c)
    selection = {"vehicle_ids": [c["vehicles"]["hlf"]["id"]]}
    assert (await _alarm(client, c, incident, selection, headers=c["annahme"])).status_code == 403
    foreign = await _alarm(client, c, incident, {"vehicle_ids": [c["foreign"]["id"]]})
    assert foreign.status_code == 422
    unavailable = await _alarm(client, c, incident, {"vehicle_ids": [c["vehicles"]["off"]["id"]]})
    assert unavailable.status_code == 422
    empty = await _alarm(client, c, incident, {"vehicle_ids": []})
    assert empty.status_code == 422
    # A vehicle bound to another incident needs an explicit reassignment.
    other = await _incident(client, c)
    assert (await _alarm(client, c, other, selection)).status_code == 201
    busy = await _alarm(client, c, incident, selection)
    assert busy.status_code == 409
    moved = await _alarm(client, c, incident, selection, reassign=True)
    assert moved.status_code == 201, moved.text


# --------------------------------------------------------------------------- police / M4
async def test_police_is_never_alarmed(client, ctx):
    c = ctx
    incident = await _incident(client, c)
    for selection in (
        {"vehicle_ids": [c["police_vehicle"]["id"]]},
        {"station_ids": [c["police_station"]["id"]]},
    ):
        r = await _alarm(client, c, incident, selection)
        assert r.status_code == 422 and "Polizei nur als Informationshinweis" in r.json()["error"]["message"]
    proposal = await _preview(client, c, incident, stage=2)
    assert "Funkstreife 11" not in [v["call_sign"] for v in proposal["vehicles"]]
    with pytest.raises(AssertionError):
        await _interface(
            client, c, plugin="simulation_receiver", scope="station", station_id=c["police_station"]["id"]
        )


async def test_m4_police_notice_popup_is_logged_and_nothing_is_sent(client, ctx):
    c = ctx
    h2 = c["keywords"]["H2"]
    assert h2["police_notice"] is True and "Polizei informieren" in h2["police_notice_text"]
    incident = await _incident(client, c, keyword="H2")
    preview = await _preview(client, c, incident, selection={"vehicle_ids": [c["vehicles"]["hlf"]["id"]]})
    assert "Polizei informieren" in preview["police_notice"]
    alarm = await _ok_alarm(client, c, incident, preview["selection"])
    notice = alarm["police_notice"]
    assert notice["keyword_code"] == "H2" and notice["acknowledged_at"] is None
    # No target of any kind points to the police.
    assert all("Polizei" not in t["label"] for t in alarm["targets"])
    open_notices = (await client.get("/police-notices", headers=c["dispo2"])).json()
    assert [n["id"] for n in open_notices] == [notice["id"]]
    # A second alarm in the same incident does not create a second notice.
    await _alarm(client, c, incident, {"vehicle_ids": [c["vehicles"]["rtw"]["id"]]})
    assert len((await client.get("/police-notices", headers=c["dispo"])).json()) == 1

    ack = await client.post(
        f"/police-notices/{notice['id']}/acknowledge",
        headers=c["dispo"],
        json={"note": "Polizei telefonisch informiert"},
    )
    assert ack.status_code == 200 and ack.json()["acknowledged_by_name"].startswith("Test Disponent")
    twice = await client.post(f"/police-notices/{notice['id']}/acknowledge", headers=c["dispo2"], json={})
    assert twice.status_code == 409 and "Test Disponent" in twice.json()["error"]["message"]
    assert (await client.get("/police-notices", headers=c["dispo"])).json() == []
    events = (await client.get(f"/incidents/{incident['id']}/events", headers=c["dispo"])).json()
    kinds = [e["kind"] for e in events]
    assert "police_notice" in kinds and "police_ack" in kinds
    ack_event = next(e for e in events if e["kind"] == "police_ack")
    assert "Polizei telefonisch informiert" in ack_event["text"]
    assert "Keine Übermittlung durch das System" in ack_event["text"]


# ------------------------------------------------------------------------------ interfaces
async def test_plugins_listed_and_config_validated(client, ctx):
    c = ctx
    plugins = {p["key"]: p for p in (await client.get("/plugins", headers=c["admin"])).json()}
    assert plugins["webhook"]["is_real"] is True and plugins["simulation_receiver"]["is_real"] is False
    assert "url" in plugins["webhook"]["config_schema"]["properties"]
    bad = [
        {"plugin_key": "webhook", "config": {"url": "http://unverschluesselt.example"}},
        {"plugin_key": "webhook", "config": {"url": "https://x.example", "unbekannt": 1}},
        {"plugin_key": "webhook", "config": {}},
        {"plugin_key": "gibt_es_nicht", "config": {}},
    ]
    for body in bad:
        r = await client.post(
            "/interfaces",
            headers=c["admin"],
            json={"name": "Falsch", "scope": "control_center", "control_center_id": c["cc"]["id"], **body},
        )
        assert r.status_code == 422, body
    assert (await client.get("/interfaces", headers=c["dispo"])).status_code == 403  # no interfaces.read


async def test_interface_secret_is_encrypted_and_never_returned(client, ctx, db, settings):
    c = ctx
    created = await _interface(client, c, secret=SECRET)
    assert created["enabled"] is False and created["effective"] is False
    assert created["has_secret"] is True and created["secret_hint"] == "••••4711"
    assert SECRET not in json.dumps(created)
    listed = (await client.get("/interfaces", headers=c["admin"])).text
    assert SECRET not in listed
    async with db.sessionmaker() as s:
        row = await s.get(Interface, uuid.UUID(created["id"]))
        assert row.secret_encrypted and SECRET not in row.secret_encrypted
        assert SecretBox.from_config(settings.encryption_keys).decrypt(row.secret_encrypted) == SECRET
        audit = (await s.scalars(select(AuditLog).where(AuditLog.entity_type == "interface"))).all()
        assert audit and all(SECRET not in json.dumps(a.changes or {}) + a.summary for a in audit)
        raw = (await s.execute(text("SELECT config::text FROM interfaces"))).scalar_one()
        assert SECRET not in raw
    # Rotate and remove the secret.
    r = await client.patch(
        f"/interfaces/{created['id']}",
        headers=c["admin"],
        json={"expected_version": created["version"], "secret": "neuer-token-0815"},
    )
    assert r.json()["secret_hint"] == "••••0815"
    r = await client.patch(
        f"/interfaces/{created['id']}",
        headers=c["admin"],
        json={"expected_version": r.json()["version"], "clear_secret": True},
    )
    assert r.json()["has_secret"] is False and r.json()["secret_hint"] is None


async def test_real_interface_activation_rules(client, ctx, db):
    c = ctx
    real = await _interface(client, c)
    toggle = f"/interfaces/{real['id']}/enabled"
    body = {"enabled": True, "expected_version": real["version"], "reason": "Inbetriebnahme Test"}
    in_sim = await client.post(toggle, headers=c["admin"], json=body)
    assert in_sim.status_code == 409 and "Echtbetrieb" in in_sim.json()["error"]["message"]
    test_in_sim = await client.post(f"/interfaces/{real['id']}/test", headers=c["admin"])
    assert test_in_sim.status_code == 409

    await _set_mode(client, c, "real")
    # interfaces.write alone is not enough for real interfaces.
    users = {u["username"]: u for u in (await client.get("/users", headers=c["admin"])).json()["items"]}
    dispo = users["dispo"]
    await client.patch(
        f"/users/{dispo['id']}",
        headers=c["admin"],
        json={
            "expected_version": dispo["version"],
            "permission_overrides": [
                {"permission_code": "interfaces.read", "effect": "grant"},
                {"permission_code": "interfaces.write", "effect": "grant"},
            ],
        },
    )
    from tests.conftest import USER_PASSWORD, bearer, login

    dispo_headers = bearer(await login(client, "dispo", USER_PASSWORD))
    denied = await client.post(toggle, headers=dispo_headers, json=body)
    assert denied.status_code == 403 and "interfaces.activate_real" in denied.text
    no_reason = await client.post(toggle, headers=c["admin"], json={**body, "reason": None})
    assert no_reason.status_code == 422
    enabled = await client.post(toggle, headers=c["admin"], json=body)
    assert enabled.status_code == 200 and enabled.json()["enabled"] and enabled.json()["effective"]
    # Changing an active real interface is as powerful as activating it.
    retarget = await client.patch(
        f"/interfaces/{real['id']}",
        headers=dispo_headers,
        json={
            "expected_version": enabled.json()["version"],
            "config": {"url": "https://andere.example/hook"},
        },
    )
    assert retarget.status_code == 403

    # Back to simulation: every real interface is switched off automatically.
    await _set_mode(client, c, "simulation")
    after = (await client.get(f"/interfaces/{real['id']}", headers=c["admin"])).json()
    assert after["enabled"] is False
    async with db.sessionmaker() as s:
        audit = (await s.scalars(select(AuditLog).where(AuditLog.action == "disable"))).all()
        assert any("automatisch deaktiviert" in a.summary for a in audit)


async def test_m4_real_plugin_is_never_called_in_simulation_mode(client, ctx, db, monkeypatch):
    """Defence in depth: even if a real interface is (wrongly) enabled while the system runs in
    simulation mode, the core redirects the delivery and the plugin never sends anything."""
    c = ctx
    sent: list[httpx.Request] = []
    monkeypatch.setattr(
        webhook, "TRANSPORT", httpx.MockTransport(lambda req: sent.append(req) or httpx.Response(200))
    )
    real = await _interface(client, c, secret=SECRET)
    async with db.sessionmaker() as s:
        await s.execute(update(Interface).where(Interface.id == uuid.UUID(real["id"])).values(enabled=True))
        await s.commit()
    incident = await _incident(client, c)
    preview = await _preview(client, c, incident)
    iface = next(i for i in preview["interfaces"] if i["id"] == real["id"])
    assert iface["effect"] == "redirect"
    alarm = await _ok_alarm(client, c, incident, preview["selection"])
    stored = (await client.get(f"/alarms/{alarm['id']}", headers=c["dispo"])).json()
    target = next(t for t in stored["targets"] if t["target_type"] == "interface")
    assert target["delivery_status"] == "simulated"
    assert target["detail"] == interface_service.REDIRECT_TEXT
    assert stored["status"] == "completed"
    assert sent == []
    events = (await client.get(f"/interfaces/{real['id']}/events", headers=c["admin"])).json()
    assert events[0]["kind"] == "redirected"


async def test_simulation_receiver_delivers_in_simulation(client, ctx):
    c = ctx
    sim = await _interface(client, c, plugin="simulation_receiver", config={"receiver_label": "Übungs-App"})
    tested = await client.post(f"/interfaces/{sim['id']}/test", headers=c["admin"])
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] and tested.json()["interface"]["status"] == "ok", tested.text
    await client.post(
        f"/interfaces/{sim['id']}/enabled",
        headers=c["admin"],
        json={"enabled": True, "expected_version": tested.json()["interface"]["version"]},
    )
    incident = await _incident(client, c)
    preview = await _preview(client, c, incident)
    assert next(i for i in preview["interfaces"] if i["id"] == sim["id"])["effect"] == "simulate"
    alarm = await _ok_alarm(client, c, incident, preview["selection"])
    stored = (await client.get(f"/alarms/{alarm['id']}", headers=c["dispo"])).json()
    target = next(t for t in stored["targets"] if t["target_type"] == "interface")
    assert target["delivery_status"] == "simulated" and "Übungs-App" in target["detail"]
    events = (await client.get(f"/incidents/{incident['id']}/events", headers=c["dispo"])).json()
    assert any(e["kind"] == "alarm_delivery" for e in events)
    # Disabling a configured interface keeps the alarm working without it.
    current = (await client.get(f"/interfaces/{sim['id']}", headers=c["admin"])).json()
    await client.post(
        f"/interfaces/{sim['id']}/enabled",
        headers=c["admin"],
        json={"enabled": False, "expected_version": current["version"]},
    )
    later = await _preview(client, c, await _incident(client, c))
    assert all(i["id"] != sim["id"] for i in later["interfaces"])


async def test_real_mode_delivery_retries_and_station_data_minimisation(client, ctx, monkeypatch):
    c = ctx
    responses = {"count": 0}
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        responses["count"] += 1
        payloads.append(json.loads(request.content))
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        return httpx.Response(500 if responses["count"] < 3 else 200)

    monkeypatch.setattr(webhook, "TRANSPORT", httpx.MockTransport(handler))
    await _set_mode(client, c, "real")
    station_iface = await _interface(client, c, scope="station", station_id=c["station"]["id"], secret=SECRET)
    await client.post(
        f"/interfaces/{station_iface['id']}/enabled",
        headers=c["admin"],
        json={"enabled": True, "expected_version": station_iface["version"], "reason": "Test im Echtbetrieb"},
    )
    incident = await _incident(client, c)
    selection = {"vehicle_ids": [c["vehicles"]["hlf"]["id"], c["second_hlf"]["id"]]}
    preview = await _preview(client, c, incident, selection=selection)
    assert any("Funkalarmierung" in w for w in preview["warnings"])
    alarm = await _ok_alarm(client, c, incident, selection)
    stored = (await client.get(f"/alarms/{alarm['id']}", headers=c["dispo"])).json()
    assert stored["mode"] == "real"
    target = next(t for t in stored["targets"] if t["target_type"] == "interface")
    assert target["delivery_status"] == "sent" and responses["count"] == 3
    ric = next(t for t in stored["targets"] if t["target_type"] == "ric")
    assert ric["delivery_status"] == "not_delivered" and stored["status"] == "partial"
    # The station interface only receives its own station's vehicle.
    assert payloads[-1]["vehicles"] == ["Florian Ops 1/46-1"] and payloads[-1]["mode"] == "real"
    assert (await client.get(f"/interfaces/{station_iface['id']}", headers=c["admin"])).json()[
        "status"
    ] == "ok"

    # Permanent failure: reported as failed, interface status error.
    monkeypatch.setattr(webhook, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(503)))
    failed = await _ok_alarm(
        client, c, await _incident(client, c), {"vehicle_ids": [c["vehicles"]["dlk"]["id"]]}
    )
    stored = (await client.get(f"/alarms/{failed['id']}", headers=c["dispo"])).json()
    target = next(t for t in stored["targets"] if t["target_type"] == "interface")
    assert target["delivery_status"] == "failed" and "nach 3 Versuchen" in target["detail"]
    after = (await client.get(f"/interfaces/{station_iface['id']}", headers=c["admin"])).json()
    assert after["status"] == "error" and "HTTP 503" in after["last_error"]


async def test_interrupted_deliveries_are_marked_failed_not_resent(client, ctx, db):
    c = ctx
    sim = await _interface(client, c, plugin="simulation_receiver")
    incident = await _incident(client, c)
    async with db.sessionmaker() as s:
        alarm = Alarm(
            incident_id=uuid.UUID(incident["id"]),
            control_center_id=uuid.UUID(c["cc"]["id"]),
            idempotency_key="restart-test",
            request_hash="x",
            kind="initial",
            mode="simulation",
            status="pending",
            triggered_by_name="Test",
            created_at=datetime.now(UTC) - timedelta(minutes=10),
            targets=[
                AlarmTarget(
                    target_type="interface", target_id=sim["id"], label="Sim", delivery_status="pending"
                )
            ],
        )
        s.add(alarm)
        await s.commit()
        assert await recover_interrupted_deliveries(UnitOfWork(s, InMemoryEventBus())) == 1
    async with db.sessionmaker() as s:
        stored = await s.get(Alarm, alarm.id)
        assert stored.status == "partial" and stored.targets[0].delivery_status == "failed"
        assert (await s.scalar(select(InterfaceEvent.id).where(InterfaceEvent.kind == "delivery"))) is None
