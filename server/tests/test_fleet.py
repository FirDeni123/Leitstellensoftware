"""Phase 6: vehicle status, talk requests, simulated drives (milestone M6)."""

from __future__ import annotations

import time
import uuid

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import Vehicle, VehicleMovement, VehicleStatusHistory
from app.proposal import travel as travel_module
from app.proposal.travel import OsrmProvider
from app.simulation import clock as clock_module
from app.simulation.clock import ClockState
from app.simulation.route import bearing, position_at, straight_route
from app.simulation.runner import SimulationRunner, tick_once
from tests.test_alarming import _incident, ctx  # noqa: F401 – shared fixtures
from tests.test_operations import setup  # noqa: F401

FAR = {"latitude": 53.53, "longitude": 10.53}  # ≈ 4.5 km from the test station


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1_800_000_000.0}
    monkeypatch.setattr(clock_module, "real_time", lambda: now["t"])
    return now


@pytest.fixture
def published(app, monkeypatch):
    messages = []
    original = app.state.bus.publish

    async def record(msg):
        messages.append(msg)
        await original(msg)

    monkeypatch.setattr(app.state.bus, "publish", record)
    return messages


async def _status(client, c, vehicle_id, code, headers=None, **extra):
    return await client.post(
        f"/vehicles/{vehicle_id}/status", headers=headers or c["dispo"], json={"status_code": code, **extra}
    )


async def _fleet(client, c, headers=None):
    r = await client.get("/fleet", headers=headers or c["dispo"], params={"control_center_id": c["cc"]["id"]})
    assert r.status_code == 200, r.text
    return {v["call_sign"]: v for v in r.json()}


async def _alarm(client, c, incident, vehicle_ids):
    r = await client.post(
        f"/incidents/{incident['id']}/alarms",
        headers={**c["dispo"], "Idempotency-Key": uuid.uuid4().hex},
        json={"vehicle_ids": vehicle_ids, "confirmed": True},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------------- pure functions
def test_route_math_and_clock():
    route = straight_route((53.50, 10.48), (53.52, 10.48), speed_kmh=60, detour=1.3, factor=1.0)
    assert route.source == "straight" and route.duration_s == pytest.approx(route.distance_m / (60 / 3.6))
    lat, lon, heading = position_at(route.geometry, route.profile, route.duration_s / 2)
    assert (
        lat == pytest.approx(53.51) and lon == pytest.approx(10.48) and heading == pytest.approx(0, abs=0.5)
    )
    assert position_at(route.geometry, route.profile, 10**9)[:2] == (53.52, 10.48)
    # different speeds per segment: the first half takes 10 s, the second 30 s
    geometry, profile = [[10.0, 53.0], [10.0, 53.1], [10.0, 53.2]], [0.0, 10.0, 40.0]
    assert position_at(geometry, profile, 25)[0] == pytest.approx(53.15)
    assert bearing([10.0, 53.0], [10.1, 53.0]) == pytest.approx(90, abs=0.1)
    state = ClockState(base_real=1000.0, base_sim=5000.0, factor=10.0)
    assert state.now(1002.0) == 5020.0
    assert ClockState(base_real=1000.0, base_sim=5000.0, paused=True).now(9999.0) == 5000.0


# ------------------------------------------------------------------------------- status
async def test_status_effects_history_and_permissions(client, ctx, db):  # noqa: F811
    c = ctx
    incident = await _incident(client, c)
    hlf = c["vehicles"]["hlf"]["id"]
    await client.post(
        f"/incidents/{incident['id']}/vehicles", headers=c["dispo"], json={"vehicle_ids": [hlf]}
    )
    assert (await _status(client, c, hlf, 3, headers=c["annahme"])).status_code == 403
    assert (await _status(client, c, hlf, 3)).json()["status_code"] == 3
    detail = (await client.get(f"/incidents/{incident['id']}", headers=c["dispo"])).json()
    assert detail["status"] == "en_route" and detail["assignments"][0]["s3_at"] is not None
    await _status(client, c, hlf, 4)
    detail = (await client.get(f"/incidents/{incident['id']}", headers=c["dispo"])).json()
    assert detail["status"] == "on_scene" and detail["assignments"][0]["s4_at"] is not None
    # status 1 = vehicle reports free -> released from the incident
    vehicle = (await _status(client, c, hlf, 1)).json()
    assert vehicle["incident"] is None
    events = [
        e["text"]
        for e in (await client.get(f"/incidents/{incident['id']}/events", headers=c["dispo"])).json()
    ]
    assert any("Florian Ops 1/46-1: Status 3" in t for t in events)
    assert any("Ankunft am Einsatzort (Status 4)" in t for t in events)
    assert any("meldet frei (Status 1)" in t for t in events)
    assert any("Status: Alarmiert" in t or "Anfahrt" in t for t in events)
    history = (await client.get(f"/vehicles/{hlf}/status-history", headers=c["dispo"])).json()
    assert [(h["status_code"], h["previous_code"]) for h in history] == [(1, 4), (4, 3), (3, 2)]
    assert history[0]["actor_name"].startswith("Test Disponent") and history[0]["source"] == "dispatcher"
    unknown = await _status(client, c, hlf, 9)
    assert unknown.status_code == 200  # status 9 exists (Fremdanmeldung)
    # the history is append-only
    async with db.engine.begin() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("UPDATE vehicle_status_history SET status_code = 2"))


async def test_out_of_service_releases_with_warning(client, ctx):  # noqa: F811
    c = ctx
    incident = await _incident(client, c)
    dlk = c["vehicles"]["dlk"]["id"]
    await client.post(
        f"/incidents/{incident['id']}/vehicles", headers=c["dispo"], json={"vehicle_ids": [dlk]}
    )
    assert (await _status(client, c, dlk, 6, note="Pumpe defekt")).json()["incident"] is None
    events = [
        e["text"]
        for e in (await client.get(f"/incidents/{incident['id']}/events", headers=c["dispo"])).json()
    ]
    assert any("außer Dienst (Status 6)" in t for t in events)


async def test_talk_requests_workflow(client, ctx):  # noqa: F811
    c = ctx
    incident = await _incident(client, c)
    rtw, hlf = c["vehicles"]["rtw"]["id"], c["vehicles"]["hlf"]["id"]
    await client.post(
        f"/incidents/{incident['id']}/vehicles", headers=c["dispo"], json={"vehicle_ids": [rtw]}
    )
    response = (await _status(client, c, rtw, 5)).json()
    assert response["status_code"] == 2  # 5 is a request, not a status
    assert response["talk_request"]["priority"] == 5
    await _status(client, c, hlf, 5)
    await _status(client, c, rtw, 0)  # escalation of the open request
    queue = (
        await client.get("/talk-requests", headers=c["dispo"], params={"control_center_id": c["cc"]["id"]})
    ).json()
    assert [(q["call_sign"], q["priority"]) for q in queue] == [
        ("Rettung Ops 1/83-1", 0),
        ("Florian Ops 1/46-1", 5),
    ]
    assert queue[0]["incident_number"] == incident["number"]
    assert (await client.get("/talk-requests", headers=c["annahme"])).status_code == 403
    first = queue[0]["id"]
    accepted = await client.post(f"/talk-requests/{first}/accept", headers=c["dispo"], json={})
    assert accepted.status_code == 200 and accepted.json()["handled_by_name"].startswith("Test Disponent")
    again = await client.post(f"/talk-requests/{first}/accept", headers=c["dispo2"], json={})
    assert again.status_code == 409
    done = await client.post(
        f"/talk-requests/{first}/done", headers=c["dispo"], json={"note": "Nachforderung NEF"}
    )
    assert done.json()["status"] == "done"
    events = [
        e["text"]
        for e in (await client.get(f"/incidents/{incident['id']}/events", headers=c["dispo"])).json()
    ]
    assert any("Priorisierter Sprechwunsch" in t or "Sprechwunsch (Status 5)" in t for t in events)
    assert any("erledigt – Nachforderung NEF" in t for t in events)
    remaining = (await client.get("/talk-requests", headers=c["dispo"])).json()
    assert [q["call_sign"] for q in remaining] == ["Florian Ops 1/46-1"]


# --------------------------------------------------------------------------- simulation
async def test_m6_fifty_vehicles_drive_and_arrive(client, ctx, db, app, clock, published):  # noqa: F811
    c = ctx
    async with db.sessionmaker() as s:
        template = await s.get(Vehicle, uuid.UUID(c["vehicles"]["hlf"]["id"]))
        for i in range(50):
            s.add(
                Vehicle(
                    control_center_id=template.control_center_id,
                    station_id=template.station_id,
                    organization_id=template.organization_id,
                    vehicle_type_id=template.vehicle_type_id,
                    call_sign=f"Sim {i:02d}",
                    status_code=2,
                )
            )
        await s.commit()
        ids = [
            str(v.id) for v in (await s.scalars(select(Vehicle).where(Vehicle.call_sign.like("Sim %")))).all()
        ]
    incident = await _incident(client, c, **FAR)
    await _alarm(client, c, incident, ids)
    movements = (
        await client.get("/movements", headers=c["dispo"], params={"control_center_id": c["cc"]["id"]})
    ).json()
    assert len(movements) == 50 and all(
        m["status"] == "pending" and m["depart_in_s"] == 90 for m in movements
    )
    assert (await _fleet(client, c))["Sim 00"]["planned_departure_s"] == 90

    clock["t"] += 91  # turnout time (status 2: 90 s) elapsed
    started = time.perf_counter()
    assert await tick_once(app.state) == 50
    departures_s = time.perf_counter() - started
    print(f"Takt mit 50 Abfahrten: {departures_s * 1000:.0f} ms")
    fleet = await _fleet(client, c)
    assert fleet["Sim 00"]["status_code"] == 3 and fleet["Sim 00"]["position"]["moving"] is True
    detail = (await client.get(f"/incidents/{incident['id']}", headers=c["dispo"])).json()
    assert detail["status"] == "en_route"

    published.clear()
    clock["t"] += 60
    started = time.perf_counter()
    await tick_once(app.state)
    tick_s = time.perf_counter() - started
    print(f"Positions-Takt mit 50 fahrenden Fahrzeugen: {tick_s * 1000:.0f} ms")
    assert tick_s < 0.5, "1-Hz-Takt muss deutlich unter einer Sekunde bleiben"
    assert departures_s < 2.0
    positions = [m for m in published if m.topic == "vehicle.positions"]
    assert len(positions) == 1 and positions[0].channels == [f"cc:{c['cc']['id']}"]
    items = positions[0].data["positions"]
    assert len(items) == 50 and all(0 < p["eta_s"] < 600 for p in items)
    eta = items[0]["eta_s"]
    # positions are a function of simulation time: a fresh read gives the same result
    snapshot = await _fleet(client, c)
    first = next(p for p in items if p["id"] == snapshot["Sim 00"]["id"])
    assert snapshot["Sim 00"]["position"]["lat"] == pytest.approx(first["lat"], abs=1e-6)

    clock["t"] += eta + 5
    assert await tick_once(app.state) == 0  # everybody arrived
    fleet = await _fleet(client, c)
    assert all(fleet[f"Sim {i:02d}"]["status_code"] == 4 for i in range(50))
    assert fleet["Sim 07"]["position"] == {
        "lat": 53.53,
        "lon": 10.53,
        "source": "sim",
        "moving": False,
        "heading": None,
        "eta_s": None,
        "kind": None,
    }
    events = (await client.get(f"/incidents/{incident['id']}/events", headers=c["dispo"])).json()
    arrivals = [e for e in events if e["kind"] == "vehicle_arrived"]
    assert len(arrivals) == 50 and "[Simulation]" in arrivals[0]["text"]
    assert (await client.get(f"/incidents/{incident['id']}", headers=c["dispo"])).json()[
        "status"
    ] == "on_scene"
    async with db.sessionmaker() as s:
        sources = set((await s.scalars(select(VehicleStatusHistory.source))).all())
        assert sources == {"simulation"}


async def test_release_drives_back_and_reports_status_2(client, ctx, app, clock):  # noqa: F811
    c = ctx
    hlf = c["vehicles"]["hlf"]["id"]
    incident = await _incident(client, c, **FAR)
    await _alarm(client, c, incident, [hlf])
    clock["t"] += 91
    await tick_once(app.state)
    clock["t"] += 3600
    await tick_once(app.state)
    assert (await _fleet(client, c))["Florian Ops 1/46-1"]["status_code"] == 4
    await client.delete(f"/incidents/{incident['id']}/vehicles/{hlf}", headers=c["dispo"])
    vehicle = (await _fleet(client, c))["Florian Ops 1/46-1"]
    assert vehicle["status_code"] == 1 and vehicle["incident"] is None
    movements = (
        await client.get("/movements", headers=c["dispo"], params={"control_center_id": c["cc"]["id"]})
    ).json()
    assert [(m["kind"], m["emergency"]) for m in movements] == [("to_station", False)]
    await tick_once(app.state)
    clock["t"] += 3600
    await tick_once(app.state)
    vehicle = (await _fleet(client, c))["Florian Ops 1/46-1"]
    assert vehicle["status_code"] == 2 and vehicle["position"]["source"] == "station"


async def test_clock_pause_factor_and_real_mode(client, ctx, app, clock):  # noqa: F811
    c = ctx
    incident = await _incident(client, c, **FAR)
    await _alarm(client, c, incident, [c["vehicles"]["hlf"]["id"]])
    assert (await client.put("/simulation/clock", headers=c["dispo"], json={"factor": 10})).status_code == 403
    r = await client.put("/simulation/clock", headers=c["admin"], json={"factor": 10})
    assert r.status_code == 200 and r.json()["factor"] == 10
    assert (await client.put("/simulation/clock", headers=c["admin"], json={"factor": 7})).status_code == 422
    clock["t"] += 9.2  # 92 simulated seconds
    await tick_once(app.state)
    assert (await _fleet(client, c))["Florian Ops 1/46-1"]["status_code"] == 3
    await client.put("/simulation/clock", headers=c["admin"], json={"paused": True})
    before = (await _fleet(client, c))["Florian Ops 1/46-1"]["position"]
    clock["t"] += 600
    await tick_once(app.state)
    assert (await _fleet(client, c))["Florian Ops 1/46-1"]["position"] == before
    # switching to real operation stops all simulated drives; the runner does nothing there
    mode = (await client.get("/system/operation-mode", headers=c["admin"])).json()
    await client.put(
        "/system/operation-mode",
        headers=c["admin"],
        json={
            "mode": "real",
            "reason": "Test Echtbetrieb",
            "confirmation": "ECHTBETRIEB",
            "expected_version": mode["version"],
        },
    )
    assert (
        await client.get("/movements", headers=c["dispo"], params={"control_center_id": c["cc"]["id"]})
    ).json() == []
    assert await tick_once(app.state) == 0
    assert (
        await client.put("/simulation/clock", headers=c["admin"], json={"paused": False})
    ).status_code == 409


async def test_breakdown_and_manual_move(client, ctx, app, clock):  # noqa: F811
    c = ctx
    hlf = c["vehicles"]["hlf"]["id"]
    incident = await _incident(client, c, **FAR)
    await _alarm(client, c, incident, [hlf])
    clock["t"] += 91
    await tick_once(app.state)
    clock["t"] += 30
    assert (
        await client.post(f"/simulation/vehicles/{hlf}/breakdown", headers=c["dispo"], json={})
    ).status_code == 403
    r = await client.post(
        f"/simulation/vehicles/{hlf}/breakdown", headers=c["admin"], json={"note": "Reifenschaden"}
    )
    vehicle = r.json()
    assert vehicle["status_code"] == 6 and vehicle["incident"] is None
    assert vehicle["position"]["moving"] is False and vehicle["position"]["source"] == "sim"
    assert 53.5 < vehicle["position"]["lat"] < 53.53  # stopped on the way
    moved = await client.post(
        f"/simulation/vehicles/{hlf}/position", headers=c["admin"], json={"lat": 53.4, "lon": 10.4}
    )
    assert moved.json()["position"]["lat"] == 53.4


async def test_routing_service_route_and_fallback(client, ctx, app, clock, monkeypatch):  # noqa: F811
    c = ctx

    def osrm(request: httpx.Request) -> httpx.Response:
        assert request.url.path.startswith("/route/v1/driving/")
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 5100.0,
                        "duration": 360.0,
                        "geometry": {"coordinates": [[10.48, 53.5], [10.50, 53.51], [10.53, 53.53]]},
                        "legs": [{"annotation": {"duration": [120.0, 240.0]}}],
                    }
                ],
            },
        )

    monkeypatch.setattr(travel_module, "TRANSPORT", httpx.MockTransport(osrm))
    monkeypatch.setitem(app.state._state, "routing", OsrmProvider("http://osrm.test"))
    incident = await _incident(client, c, **FAR)
    await _alarm(client, c, incident, [c["vehicles"]["hlf"]["id"]])
    clock["t"] += 91
    await tick_once(app.state)
    movement = (
        await client.get("/movements", headers=c["dispo"], params={"control_center_id": c["cc"]["id"]})
    ).json()[0]
    assert movement["route_source"] == "osrm" and len(movement["geometry"]) == 3
    assert movement["eta_s"] == pytest.approx(360 / 1.15, abs=0.5)  # Sonderrechte factor

    monkeypatch.setattr(travel_module, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(502)))
    other = await _incident(client, c, latitude=53.52, longitude=10.52)
    await _alarm(client, c, other, [c["vehicles"]["dlk"]["id"]])
    clock["t"] += 91
    await tick_once(app.state)
    movements = (
        await client.get("/movements", headers=c["dispo"], params={"control_center_id": c["cc"]["id"]})
    ).json()
    dlk = next(m for m in movements if m["call_sign"] == "Florian Ops 1/33-1")
    assert dlk["route_source"] == "straight" and "Luftlinie" in dlk["note"]


async def test_reassigned_vehicle_does_not_report_arrival_at_old_incident(client, ctx, app, clock):  # noqa: F811
    c = ctx
    hlf = c["vehicles"]["hlf"]["id"]
    first = await _incident(client, c, **FAR)
    await _alarm(client, c, first, [hlf])
    clock["t"] += 91
    await tick_once(app.state)
    second = await _incident(client, c)  # without alarm: only assigned (umsetzen)
    await client.post(
        f"/incidents/{second['id']}/vehicles",
        headers=c["dispo"],
        json={"vehicle_ids": [hlf], "reassign": True},
    )
    clock["t"] += 3600
    await tick_once(app.state)
    detail = (await client.get(f"/incidents/{first['id']}", headers=c["dispo"])).json()
    assert detail["status"] != "on_scene"
    assert (await _fleet(client, c))["Florian Ops 1/46-1"]["status_code"] == 3


async def test_single_simulation_leader(app):
    first, second = SimulationRunner(app.state), SimulationRunner(app.state)
    try:
        assert await first._is_leader() is True
        assert await second._is_leader() is False
        await first._release()
        assert await second._is_leader() is True
    finally:
        await first._release()
        await second._release()


async def test_map_config(client, ctx):  # noqa: F811
    c = ctx
    cfg = (
        await client.get("/map/config", headers=c["dispo"], params={"control_center_id": c["cc"]["id"]})
    ).json()
    assert "{z}" in cfg["tile_url"] and "OpenStreetMap" in cfg["attribution"]
    assert cfg["center"] is not None and cfg["routing"] is False


async def test_movements_survive_a_restart(client, ctx, db, app, clock):  # noqa: F811
    """Positions are derived from the stored route + simulation clock (no in-memory state)."""
    c = ctx
    incident = await _incident(client, c, **FAR)
    await _alarm(client, c, incident, [c["vehicles"]["hlf"]["id"]])
    clock["t"] += 91
    await tick_once(app.state)
    clock["t"] += 45
    before = (await _fleet(client, c))["Florian Ops 1/46-1"]["position"]
    async with db.sessionmaker() as s:  # "restart": everything comes from the database again
        movement = (await s.scalars(select(VehicleMovement))).one()
        lat, lon, _ = position_at(movement.geometry, movement.profile, 45)
    assert (before["lat"], before["lon"]) == pytest.approx((lat, lon), abs=1e-9)
