"""Phase 5: Einsatzmittelvorschlag via API (milestone M5)."""

from __future__ import annotations

import time
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models import Alarm, Role, User, Vehicle
from app.proposal import travel as travel_module
from app.proposal.travel import OsrmProvider
from tests.conftest import USER_PASSWORD, bearer, login
from tests.test_alarming import _incident, ctx  # noqa: F401 – shared fixtures (AAO B2 etc.)
from tests.test_operations import setup  # noqa: F401


async def _proposal(client, c, incident, headers=None, **body):
    r = await client.post(f"/incidents/{incident['id']}/proposal", headers=headers or c["dispo"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_m5_b2_proposal_fast_with_reasons_and_no_alarm(client, ctx, db):  # noqa: F811
    c = ctx
    incident = await _incident(client, c)
    started = time.perf_counter()
    proposal = await _proposal(client, c, incident)
    wall_ms = (time.perf_counter() - started) * 1000
    assert proposal["duration_ms"] < 1000 and wall_ms < 1000
    assert proposal["rule"]["name"] == "B2 Standard" and proposal["stage"] == 1
    assert proposal["travel_source"] == "estimate"
    picks = {p["call_sign"]: p for p in proposal["picks"]}
    assert set(picks) == {"Florian Ops 1/46-1", "Florian Ops 1/33-1"}
    hlf = picks["Florian Ops 1/46-1"]
    assert hlf["reasons"][0] == "AAO B2, Stufe 1: HLF20 (Bedarf 1/1)"
    assert any(r.startswith("Fahrzeit ca.") and "Schätzung" in r for r in hlf["reasons"])
    assert any(r.startswith("Status 2 auf Wache") for r in hlf["reasons"])
    assert hlf["travel_seconds"] is not None and hlf["score_seconds"] >= hlf["travel_seconds"]
    # the second HLF (neighbouring station) is the alternative
    hlf_demand = next(d for d in proposal["demands"] if d["label"] == "HLF20")
    assert [a["call_sign"] for a in proposal["alternatives"][hlf_demand["key"]]] == ["Florian Nachbar 1/46-1"]
    assert proposal["shortfalls"] == [] and proposal["accepted_at"] is None

    # A proposal changes nothing: no alarm, no assignment – but it is stored.
    detail = (await client.get(f"/incidents/{incident['id']}", headers=c["dispo"])).json()
    assert detail["status"] == "new" and detail["assignments"] == []
    async with db.sessionmaker() as s:
        assert (await s.scalar(select(Alarm.id))) is None
    history = (await client.get(f"/incidents/{incident['id']}/proposals", headers=c["dispo2"])).json()
    assert [h["id"] for h in history] == [proposal["id"]]


async def test_accept_assigns_only_and_documents(client, ctx, db):  # noqa: F811
    c = ctx
    incident = await _incident(client, c)
    proposal = await _proposal(client, c, incident)
    hlf = next(p for p in proposal["picks"] if p["vehicle_type"] == "HLF20")
    # take the HLF, drop the DLK, add the RTW manually
    r = await client.post(
        f"/proposals/{proposal['id']}/accept",
        headers=c["dispo"],
        json={"vehicle_ids": [hlf["vehicle_id"], c["vehicles"]["rtw"]["id"]]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["accepted_by_name"].startswith("Test Disponent")
    detail = (await client.get(f"/incidents/{incident['id']}", headers=c["dispo"])).json()
    assert detail["status"] == "in_progress"
    assert sorted(a["vehicle"]["call_sign"] for a in detail["assignments"]) == [
        "Florian Ops 1/46-1",
        "Rettung Ops 1/83-1",
    ]
    assert all(a["alarmed_at"] is None for a in detail["assignments"])
    async with db.sessionmaker() as s:
        assert (await s.scalar(select(Alarm.id))) is None
    events = (await client.get(f"/incidents/{incident['id']}/events", headers=c["dispo"])).json()
    accepted = next(e for e in events if e["kind"] == "proposal_accepted")
    assert "zugeordnet, nicht alarmiert" in accepted["text"]
    assert "abgewählt: Florian Ops 1/33-1" in accepted["text"] and "1 manuell ergänzt" in accepted["text"]
    again = await client.post(
        f"/proposals/{proposal['id']}/accept", headers=c["dispo2"], json={"vehicle_ids": []}
    )
    assert again.status_code == 409 and "Test Disponent" in again.json()["error"]["message"]

    # The next proposal counts the assigned HLF towards the demand and proposes only the DLK.
    follow = await _proposal(client, c, incident)
    by_sign = {p["call_sign"]: p for p in follow["picks"]}
    assert by_sign["Florian Ops 1/46-1"]["in_incident"] is True
    assert "bereits dem Einsatz zugeordnet" in by_sign["Florian Ops 1/46-1"]["reasons"]
    assert by_sign["Florian Ops 1/33-1"]["in_incident"] is False


async def test_extra_demand_shortfall_and_neighbour_hint(client, ctx):  # noqa: F811
    c = ctx
    link = await client.post(
        "/control-center-links",
        headers=c["admin"],
        json={
            "from_control_center_id": c["cc"]["id"],
            "to_control_center_id": c["other"]["id"],
            "kind": "neighbor",
        },
    )
    assert link.status_code == 201, link.text
    incident = await _incident(client, c)
    proposal = await _proposal(
        client,
        c,
        incident,
        extra=[
            {"vehicle_type_id": c["types"]["HLF20"]["id"], "count": 2},
            {"vehicle_type_id": c["types"]["RTW"]["id"]},
        ],
    )
    extra = [d for d in proposal["demands"] if d["source"] == "Zusatzbedarf"]
    assert [(d["label"], d["count"], d["covered"]) for d in extra] == [("HLF20", 2, 1), ("RTW", 1, 1)]
    shortfall = proposal["shortfalls"][0]
    assert shortfall["message"] == "HLF20: 1 von 2 nicht verfügbar – Unterstützung anfragen (Fremd: 1 frei)"


async def test_routing_service_is_used_and_failure_falls_back(client, ctx, app, monkeypatch):  # noqa: F811
    c = ctx
    calls: list[httpx.Request] = []

    def osrm(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        n = len(request.url.params["sources"].split(";"))
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "durations": [[420.0 + 60 * i] for i in range(n)],
                "distances": [[5200.0 + 100 * i] for i in range(n)],
            },
        )

    monkeypatch.setattr(travel_module, "TRANSPORT", httpx.MockTransport(osrm))
    # State attributes are not restored correctly by monkeypatch.setattr – patch the dict instead
    monkeypatch.setitem(app.state._state, "routing", OsrmProvider("http://osrm.test"))
    incident = await _incident(client, c)
    proposal = await _proposal(client, c, incident)
    assert calls and calls[0].url.path.startswith("/table/v1/driving/")
    assert proposal["travel_source"] == "osrm"
    hlf = next(p for p in proposal["picks"] if p["vehicle_type"] == "HLF20")
    assert hlf["travel_source"] == "osrm" and any("(Route, " in r for r in hlf["reasons"])

    monkeypatch.setattr(travel_module, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(503)))
    fallback = await _proposal(client, c, incident)
    assert fallback["travel_source"] == "estimate"
    assert any("Routing-Dienst nicht erreichbar" in w for w in fallback["warnings"])
    # disabled per control centre: the routing service is not asked at all
    calls.clear()
    monkeypatch.setattr(travel_module, "TRANSPORT", httpx.MockTransport(osrm))
    settings = (
        await client.get(
            "/proposal-settings", headers=c["admin"], params={"control_center_id": c["cc"]["id"]}
        )
    ).json()
    assert settings["routing_configured"] is True
    await client.put(
        "/proposal-settings",
        headers=c["admin"],
        json={"control_center_id": c["cc"]["id"], "settings": {**settings["settings"], "use_routing": False}},
    )
    assert (await _proposal(client, c, incident))["travel_source"] == "estimate" and calls == []


async def test_settings_permissions_versioning_and_effect(client, ctx):  # noqa: F811
    c = ctx
    params = {"control_center_id": c["cc"]["id"]}
    current = (await client.get("/proposal-settings", headers=c["dispo"], params=params)).json()
    assert current["is_default"] is True and current["version"] is None
    assert current["settings"]["substitutes"]["HLF20"] == ["LF20", "LF10"]
    body = {
        "control_center_id": c["cc"]["id"],
        "settings": {**current["settings"], "turnout_seconds_on_station": 300},
    }
    assert (await client.put("/proposal-settings", headers=c["dispo"], json=body)).status_code == 403
    saved = await client.put("/proposal-settings", headers=c["admin"], json=body)
    assert saved.status_code == 200 and saved.json()["version"] == 1
    stale = await client.put("/proposal-settings", headers=c["admin"], json=body)
    assert stale.status_code == 409
    bad = {
        **body,
        "expected_version": 1,
        "settings": {**body["settings"], "substitutes": {"HLF20": ["XYZ99"]}},
    }
    r = await client.put("/proposal-settings", headers=c["admin"], json=bad)
    assert r.status_code == 422 and "XYZ99" in r.json()["error"]["message"]
    # the new turnout time shows up in the reasons
    proposal = await _proposal(client, c, await _incident(client, c))
    hlf = next(p for p in proposal["picks"] if p["vehicle_type"] == "HLF20")
    assert "Status 2 auf Wache (+5:00 min Ausrücken)" in hlf["reasons"]


async def test_observer_cannot_compute_and_closed_incidents_are_refused(client, ctx, db):  # noqa: F811
    c = ctx
    async with db.sessionmaker() as s:
        observer = (await s.scalars(select(Role).where(Role.key == "observer"))).one()
        s.add(
            User(
                username="beob",
                display_name="Beobachter",
                password_hash=hash_password(USER_PASSWORD),
                must_change_password=False,
                roles=[observer],
            )
        )
        await s.commit()
    users = {u["username"]: u for u in (await client.get("/users", headers=c["admin"])).json()["items"]}
    await client.patch(
        f"/users/{users['beob']['id']}",
        headers=c["admin"],
        json={"control_center_ids": [c["cc"]["id"]], "expected_version": users["beob"]["version"]},
    )
    observer_headers = bearer(await login(client, "beob", USER_PASSWORD))
    incident = await _incident(client, c)
    r = await client.post(f"/incidents/{incident['id']}/proposal", headers=observer_headers, json={})
    assert r.status_code == 403
    assert (
        await client.get(f"/incidents/{incident['id']}/proposals", headers=observer_headers)
    ).status_code == 200
    await client.post(
        f"/incidents/{incident['id']}/status",
        headers=c["dispo"],
        json={"status": "finished", "expected_version": incident["version"]},
    )
    r = await client.post(f"/incidents/{incident['id']}/proposal", headers=c["dispo"], json={})
    assert r.status_code == 409


@pytest.mark.parametrize("vehicle_count", [300])
async def test_m5_performance_with_many_vehicles(client, ctx, db, vehicle_count):  # noqa: F811
    c = ctx
    station_id = uuid.UUID(c["station"]["id"])
    async with db.sessionmaker() as s:
        org_id = (await s.get(Vehicle, uuid.UUID(c["vehicles"]["hlf"]["id"]))).organization_id
        for i in range(vehicle_count):
            code = ("HLF20", "LF20", "DLK23", "RTW", "ELW1")[i % 5]
            s.add(
                Vehicle(
                    control_center_id=uuid.UUID(c["cc"]["id"]),
                    station_id=station_id,
                    organization_id=org_id,
                    vehicle_type_id=uuid.UUID(c["types"][code]["id"]),
                    call_sign=f"Last {i:03d}",
                    status_code=1 + i % 2,
                    latitude=53.3 + (i % 40) * 0.01,
                    longitude=10.2 + (i // 40) * 0.02,
                    position_source="sim",
                )
            )
        await s.commit()
    incident = await _incident(client, c)
    started = time.perf_counter()
    proposal = await _proposal(
        client, c, incident, stage=2, extra=[{"vehicle_type_id": c["types"]["HLF20"]["id"], "count": 5}]
    )
    wall_ms = (time.perf_counter() - started) * 1000
    assert len(proposal["picks"]) == 8 and proposal["shortfalls"] == []
    assert proposal["duration_ms"] < 1000 and wall_ms < 1000, (proposal["duration_ms"], wall_ms)
