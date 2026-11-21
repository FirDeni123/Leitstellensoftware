"""Phase 3: emergency calls, incidents, vehicle assignment, history (milestone M3)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.security import hash_password
from app.models import Role, User
from tests.conftest import ADMIN_PASSWORD, USER_PASSWORD, bearer, login


@pytest.fixture
async def setup(client, admin_headers, db):
    """Control centre with stations/vehicles and two dispatchers assigned to it."""
    cc = (
        await client.post("/control-centers", headers=admin_headers, json={"code": "ILS-OPS", "name": "Ops"})
    ).json()
    other = (
        await client.post(
            "/control-centers", headers=admin_headers, json={"code": "ILS-FREMD", "name": "Fremd"}
        )
    ).json()
    async with db.sessionmaker() as s:
        roles = {r.key: r for r in (await s.scalars(select(Role))).all()}
        s.add_all(
            [
                User(
                    username="dispo2",
                    display_name="Zweite Disponentin",
                    password_hash=hash_password(USER_PASSWORD),
                    must_change_password=False,
                    roles=[roles["dispatcher"]],
                ),
                User(
                    username="annahme",
                    display_name="Annahme Kraft",
                    password_hash=hash_password(USER_PASSWORD),
                    must_change_password=False,
                    roles=[roles["call_taker"]],
                ),
            ]
        )
        await s.commit()
    users = {u["username"]: u for u in (await client.get("/users", headers=admin_headers)).json()["items"]}
    for name in ("dispo", "dispo2", "annahme"):
        await client.patch(
            f"/users/{users[name]['id']}",
            headers=admin_headers,
            json={"control_center_ids": [cc["id"]], "expected_version": users[name]["version"]},
        )
    await client.patch(
        f"/users/{users['admin']['id']}",
        headers=admin_headers,
        json={"control_center_ids": [cc["id"]], "expected_version": users["admin"]["version"]},
    )
    orgs = {o["key"]: o for o in (await client.get("/organizations", headers=admin_headers)).json()}
    types = {t["code"]: t for t in (await client.get("/vehicle-types", headers=admin_headers)).json()}

    async def station(cc_id, name):
        return (
            await client.post(
                "/stations",
                headers=admin_headers,
                json={
                    "control_center_id": cc_id,
                    "organization_id": orgs["feuerwehr"]["id"],
                    "name": name,
                    "latitude": 53.5,
                    "longitude": 10.48,
                },
            )
        ).json()

    async def vehicle(cc_id, st, call_sign, code="HLF20", **extra):
        return (
            await client.post(
                "/vehicles",
                headers=admin_headers,
                json={
                    "control_center_id": cc_id,
                    "station_id": st["id"],
                    "vehicle_type_id": types[code]["id"],
                    "call_sign": call_sign,
                    **extra,
                },
            )
        ).json()

    st = await station(cc["id"], "Feuerwache Ops")
    vehicles = {
        "hlf": await vehicle(cc["id"], st, "Florian Ops 1/46-1"),
        "dlk": await vehicle(cc["id"], st, "Florian Ops 1/33-1", "DLK23"),
        "rtw": await vehicle(cc["id"], st, "Rettung Ops 1/83-1", "RTW"),
        "off": await vehicle(cc["id"], st, "Florian Ops 1/19-1", "MTW", available=False),
    }
    foreign = await vehicle(other["id"], await station(other["id"], "Fremdwache"), "Florian Fremd 1")
    kw_response = await client.get("/keywords", headers=admin_headers)
    assert kw_response.status_code == 200, kw_response.text
    keywords = {k["code"]: k for k in kw_response.json()}
    return {
        "cc": cc,
        "other": other,
        "vehicles": vehicles,
        "foreign": foreign,
        "keywords": keywords,
        "dispo": bearer(await login(client, "dispo", USER_PASSWORD)),
        "dispo2": bearer(await login(client, "dispo2", USER_PASSWORD)),
        "annahme": bearer(await login(client, "annahme", USER_PASSWORD)),
        "admin": bearer(await login(client, "admin", ADMIN_PASSWORD)),
    }


async def _sim_call(client, ctx, scenario="pkw_brand"):
    r = await client.post(
        "/simulation/calls",
        headers=ctx["admin"],
        json={"control_center_id": ctx["cc"]["id"], "scenario": scenario},
    )
    assert r.status_code == 201, r.text
    return r.json()[0]


async def _incident(client, ctx, headers=None, **fields):
    body = {
        "control_center_id": ctx["cc"]["id"],
        "keyword_id": ctx["keywords"]["B2"]["id"],
        "address": "Am Markt 1, Demostadt",
        **fields,
    }
    r = await client.post("/incidents", headers=headers or ctx["dispo"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_keyword_catalogue(client, setup):
    ctx = setup
    assert {"B1", "B2", "H-KLEMM", "RD2", "MANV"} <= set(ctx["keywords"])
    assert ctx["keywords"]["RD2"]["category"] == "ems" and ctx["keywords"]["RD2"]["default_priority"] == 1
    r = await client.post(
        "/keywords", headers=ctx["dispo"], json={"code": "X1", "name": "Test", "category": "other"}
    )
    assert r.status_code == 403
    r = await client.post(
        "/keywords",
        headers=ctx["admin"],
        json={"code": "th-tier", "name": "Tierrettung", "category": "technical"},
    )
    assert r.status_code == 201 and r.json()["code"] == "TH-TIER"


async def test_m3_two_dispatchers_call_to_new_and_existing_incident(client, setup):
    """M3: two dispatchers in parallel, second call is linked to the existing incident."""
    ctx = setup
    first, second = await _sim_call(client, ctx), await _sim_call(client, ctx)
    assert first["status"] == "ringing" and first["source"] == "sim"
    assert "Auf Nachfrage „Wo genau?“" in first["sim_transcript"]

    queue = (
        await client.get("/calls", headers=ctx["dispo2"], params={"control_center_id": ctx["cc"]["id"]})
    ).json()
    assert {c["id"] for c in queue} == {first["id"], second["id"]}

    # dispatcher 1 takes call 1, captures the location and asks follow-up questions
    a = (
        await client.post(
            f"/calls/{first['id']}/answer", headers=ctx["dispo"], json={"expected_version": first["version"]}
        )
    ).json()
    a = (
        await client.patch(
            f"/calls/{first['id']}",
            headers=ctx["dispo"],
            json={
                "expected_version": a["version"],
                "address": "Bahnhofstraße 12, Demostadt",
                "latitude": 53.5035,
                "longitude": 10.4795,
                "reason": "Pkw-Brand auf Parkplatz",
                "priority": 2,
                "caller_name": "Anna Muster",
            },
        )
    ).json()
    a = (
        await client.post(
            f"/calls/{first['id']}/notes",
            headers=ctx["dispo"],
            json={
                "kind": "question",
                "question": "Sind Personen im Fahrzeug?",
                "text": "Nein, Fahrer ist draußen",
            },
        )
    ).json()
    assert a["notes"][0]["question"] == "Sind Personen im Fahrzeug?"

    incident = await _incident(client, ctx, call_id=first["id"], address=None)
    assert incident["number"].endswith("-000001")
    assert incident["address"] == "Bahnhofstraße 12, Demostadt" and incident["caller_name"] == "Anna Muster"
    assert incident["source"] == "sim" and incident["priority"] == 2
    assert [c["id"] for c in incident["calls"]] == [first["id"]]

    # dispatcher 2 takes the second call (same fire) and links it to the existing incident
    b = (
        await client.post(
            f"/calls/{second['id']}/answer",
            headers=ctx["dispo2"],
            json={"expected_version": second["version"]},
        )
    ).json()
    r = await client.post(
        f"/calls/{second['id']}/link",
        headers=ctx["dispo2"],
        json={"incident_id": incident["id"], "expected_version": b["version"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["incident"]["number"] == incident["number"]

    # in parallel dispatcher 1 assigns vehicles; both calls end
    await client.post(
        f"/incidents/{incident['id']}/vehicles",
        headers=ctx["dispo"],
        json={"vehicle_ids": [ctx["vehicles"]["hlf"]["id"]]},
    )
    for call, headers in ((a, ctx["dispo"]), (r.json(), ctx["dispo2"])):
        assert (
            await client.post(
                f"/calls/{call['id']}/end", headers=headers, json={"expected_version": call["version"]}
            )
        ).status_code == 200

    detail = (await client.get(f"/incidents/{incident['id']}", headers=ctx["dispo2"])).json()
    assert len(detail["calls"]) == 2 and detail["vehicles"] == ["Florian Ops 1/46-1"]
    assert detail["status"] == "in_progress"
    events = (await client.get(f"/incidents/{incident['id']}/events", headers=ctx["dispo"])).json()
    kinds = [e["kind"] for e in events]
    assert kinds == ["created", "call_linked", "call_linked", "vehicle_assigned", "status"]
    actors = {e["kind"]: e["actor_name"] for e in events}
    assert actors["created"].startswith("Test Disponent") and events[2]["actor_name"].startswith("Zweite")
    assert "[Simulation]" in events[1]["text"]
    assert (
        await client.get("/calls", headers=ctx["dispo"], params={"control_center_id": ctx["cc"]["id"]})
    ).json() == []


async def test_answer_race_and_call_lifecycle(client, setup):
    ctx = setup
    call = await _sim_call(client, ctx)
    results = await asyncio.gather(
        *(
            client.post(f"/calls/{call['id']}/answer", headers=h, json={"expected_version": call["version"]})
            for h in (ctx["dispo"], ctx["dispo2"])
        )
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert "bereits von" in loser.json()["error"]["message"]
    winner = next(r for r in results if r.status_code == 200).json()
    winner_headers = ctx["dispo"] if winner["handled_by_name"] == "Test Disponent" else ctx["dispo2"]
    other_headers = ctx["dispo2"] if winner_headers is ctx["dispo"] else ctx["dispo"]

    # only the handler may hold/end; a held call can be taken over by a colleague
    assert (
        await client.post(
            f"/calls/{call['id']}/end", headers=other_headers, json={"expected_version": winner["version"]}
        )
    ).status_code == 409
    held = (
        await client.post(
            f"/calls/{call['id']}/hold", headers=winner_headers, json={"expected_version": winner["version"]}
        )
    ).json()
    assert held["status"] == "on_hold"
    taken = (
        await client.post(
            f"/calls/{call['id']}/resume", headers=other_headers, json={"expected_version": held["version"]}
        )
    ).json()
    assert taken["status"] == "active" and taken["handled_by_name"] != winner["handled_by_name"]
    ended = (
        await client.post(
            f"/calls/{call['id']}/end", headers=other_headers, json={"expected_version": taken["version"]}
        )
    ).json()
    assert ended["status"] == "ended" and ended["ended_at"]
    r = await client.patch(
        f"/calls/{call['id']}",
        headers=other_headers,
        json={"expected_version": ended["version"], "reason": "zu spät"},
    )
    assert r.status_code == 409


async def test_manual_call_and_permissions(client, setup, admin_headers):
    ctx = setup
    r = await client.post(
        "/calls",
        headers=ctx["annahme"],
        json={"control_center_id": ctx["cc"]["id"], "caller_phone": "04151 0000 11", "reason": "Ölspur"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "active" and r.json()["source"] == "manual"
    # call takers (no simulation.control) cannot inject simulated calls
    r = await client.post(
        "/simulation/calls", headers=ctx["annahme"], json={"control_center_id": ctx["cc"]["id"]}
    )
    assert r.status_code == 403
    observer = await client.post(
        "/users",
        headers=admin_headers,
        json={
            "username": "beob",
            "display_name": "Beobachter",
            "roles": ["observer"],
            "password": "Sicher-Lesen-77",
            "control_center_ids": [ctx["cc"]["id"]],
        },
    )
    assert observer.status_code == 201


async def test_incident_numbers_are_gapless_under_concurrency(client, setup):
    ctx = setup
    results = await asyncio.gather(
        *(_incident(client, ctx, headers=h) for h in [ctx["dispo"], ctx["dispo2"]] * 5)
    )
    sequences = sorted(int(i["number"].split("-")[1]) for i in results)
    assert sequences == list(range(1, 11))
    other = (
        await client.post(
            "/incidents",
            headers=ctx["admin"],
            json={"control_center_id": ctx["other"]["id"], "address": "Fremd"},
        )
    ).json()
    assert other["number"].endswith("-000001")  # numbering per control centre


async def test_vehicle_assignment_rules(client, setup):
    ctx = setup
    v = ctx["vehicles"]
    a = await _incident(client, ctx)
    b = await _incident(client, ctx, keyword_id=ctx["keywords"]["RD2"]["id"])
    assert b["priority"] == 1 and b["incident_type"] == "ems"

    r = await client.post(
        f"/incidents/{a['id']}/vehicles",
        headers=ctx["dispo"],
        json={"vehicle_ids": [v["hlf"]["id"], v["dlk"]["id"]]},
    )
    assert r.status_code == 200 and r.json()["vehicles"] == ["Florian Ops 1/46-1", "Florian Ops 1/33-1"]
    assert r.json()["stations"][0]["name"] == "Feuerwache Ops"

    blocked = await client.post(
        f"/incidents/{b['id']}/vehicles", headers=ctx["dispo2"], json={"vehicle_ids": [v["hlf"]["id"]]}
    )
    assert blocked.status_code == 409 and a["number"] in blocked.json()["error"]["message"]
    moved = await client.post(
        f"/incidents/{b['id']}/vehicles",
        headers=ctx["dispo2"],
        json={"vehicle_ids": [v["hlf"]["id"]], "reassign": True},
    )
    assert moved.status_code == 200 and moved.json()["vehicles"] == ["Florian Ops 1/46-1"]
    a_now = (await client.get(f"/incidents/{a['id']}", headers=ctx["dispo"])).json()
    assert a_now["vehicles"] == ["Florian Ops 1/33-1"]
    assert any(x["released_reason"] == "reassigned" for x in a_now["assignments"])
    a_events = (await client.get(f"/incidents/{a['id']}/events", headers=ctx["dispo"])).json()
    assert "umgesetzt" in a_events[-1]["text"]

    assert (
        await client.post(
            f"/incidents/{a['id']}/vehicles", headers=ctx["dispo"], json={"vehicle_ids": [v["off"]["id"]]}
        )
    ).status_code == 422
    released = await client.delete(f"/incidents/{a['id']}/vehicles/{v['dlk']['id']}", headers=ctx["dispo"])
    assert released.status_code == 200 and released.json()["vehicles"] == []
    active = (
        await client.get(
            "/incidents/active-assignments",
            headers=ctx["dispo"],
            params={"control_center_id": ctx["cc"]["id"]},
        )
    ).json()
    assert [(x["vehicle_id"], x["incident_number"]) for x in active] == [(v["hlf"]["id"], b["number"])]


async def test_foreign_vehicle_is_rejected(client, setup):
    ctx = setup
    a = await _incident(client, ctx, headers=ctx["admin"])
    r = await client.post(
        f"/incidents/{a['id']}/vehicles", headers=ctx["admin"], json={"vehicle_ids": [ctx["foreign"]["id"]]}
    )
    assert r.status_code == 422 and "anderen Leitstelle" in r.json()["error"]["message"]


async def test_concurrent_assignment_of_same_vehicle(client, setup):
    ctx = setup
    a, b = await _incident(client, ctx), await _incident(client, ctx)
    vid = ctx["vehicles"]["rtw"]["id"]
    results = await asyncio.gather(
        client.post(f"/incidents/{a['id']}/vehicles", headers=ctx["dispo"], json={"vehicle_ids": [vid]}),
        client.post(f"/incidents/{b['id']}/vehicles", headers=ctx["dispo2"], json={"vehicle_ids": [vid]}),
    )
    assert sorted(r.status_code for r in results) == [200, 409]


async def test_status_rules_and_closing(client, setup):
    ctx = setup
    inc = await _incident(client, ctx)
    await client.post(
        f"/incidents/{inc['id']}/vehicles",
        headers=ctx["dispo"],
        json={"vehicle_ids": [ctx["vehicles"]["hlf"]["id"]]},
    )
    inc = (await client.get(f"/incidents/{inc['id']}", headers=ctx["dispo"])).json()

    async def status(target, version, headers=None):
        return await client.post(
            f"/incidents/{inc['id']}/status",
            headers=headers or ctx["dispo"],
            json={"status": target, "expected_version": version},
        )

    assert (await status("closed", inc["version"])).status_code == 409  # not finished yet
    r = await status("on_scene", inc["version"])
    assert r.status_code == 200 and r.json()["status"] == "on_scene"
    assert (await status("finished", inc["version"])).status_code == 409  # stale version
    r = await status("finished", r.json()["version"])
    assert r.json()["finished_at"]
    blocked = await status("closed", r.json()["version"])
    assert blocked.status_code == 409 and "Florian Ops 1/46-1" in blocked.json()["error"]["message"]
    assert (
        await client.post(
            f"/incidents/{inc['id']}/vehicles",
            headers=ctx["dispo"],
            json={"vehicle_ids": [ctx["vehicles"]["dlk"]["id"]]},
        )
    ).status_code == 409
    await client.delete(
        f"/incidents/{inc['id']}/vehicles/{ctx['vehicles']['hlf']['id']}", headers=ctx["dispo"]
    )
    version = (await client.get(f"/incidents/{inc['id']}", headers=ctx["dispo"])).json()["version"]
    assert (
        await status("closed", version, ctx["annahme"])
    ).status_code == 403  # call taker lacks incidents.close
    closed = await status("closed", version)
    assert closed.status_code == 200 and closed.json()["closed_at"]

    v = closed.json()["version"]
    assert (
        await client.patch(
            f"/incidents/{inc['id']}", headers=ctx["dispo"], json={"address": "X", "expected_version": v}
        )
    ).status_code == 409
    assert (
        await client.post(f"/incidents/{inc['id']}/notes", headers=ctx["dispo"], json={"text": "Nachtrag"})
    ).status_code == 409
    assert (await status("on_scene", v)).status_code == 409  # reopen only to "finished"
    reopened = await status("finished", v)
    assert reopened.status_code == 200
    kinds = [
        e["kind"] for e in (await client.get(f"/incidents/{inc['id']}/events", headers=ctx["dispo"])).json()
    ]
    assert kinds[-1] == "reopened"
    listed = (await client.get("/incidents", headers=ctx["dispo"], params={"scope": "open"})).json()
    assert inc["id"] in [i["id"] for i in listed]


async def test_update_history_and_optimistic_locking(client, setup):
    ctx = setup
    inc = await _incident(client, ctx)
    r = await client.patch(
        f"/incidents/{inc['id']}",
        headers=ctx["dispo"],
        json={
            "expected_version": inc["version"],
            "keyword_id": ctx["keywords"]["B3"]["id"],
            "priority": 1,
            "description": "Vollbrand Lagerhalle",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["keyword"]["code"] == "B3"
    stale = await client.patch(
        f"/incidents/{inc['id']}",
        headers=ctx["dispo2"],
        json={"expected_version": inc["version"], "priority": 3},
    )
    assert stale.status_code == 409
    events = (await client.get(f"/incidents/{inc['id']}/events", headers=ctx["dispo"])).json()
    assert events[-1]["kind"] == "updated" and "Stichwort B2 → B3" in events[-1]["text"]
    assert events[-1]["data"]["changes"]["priority"] == {"old": 2, "new": 1}
    note = await client.post(
        f"/incidents/{inc['id']}/notes", headers=ctx["dispo2"], json={"text": "Lage: starke Rauchentwicklung"}
    )
    assert note.status_code == 201 and note.json()["actor_name"].startswith("Zweite")


async def test_incident_history_is_immutable(client, setup, db):
    ctx = setup
    await _incident(client, ctx)
    for sql in ("UPDATE incident_events SET text = 'manipuliert'", "DELETE FROM incident_events"):
        with pytest.raises(DBAPIError, match="unveränderbar"):
            async with db.engine.begin() as conn:
                await conn.execute(text(sql))


async def test_simulated_calls_are_refused_in_real_mode(client, setup):
    ctx = setup
    mode = (await client.get("/system/operation-mode", headers=ctx["admin"])).json()
    await client.put(
        "/system/operation-mode",
        headers=ctx["admin"],
        json={
            "mode": "real",
            "reason": "Test Trennung",
            "confirmation": "ECHTBETRIEB",
            "expected_version": mode["version"],
        },
    )
    r = await client.post(
        "/simulation/calls", headers=ctx["admin"], json={"control_center_id": ctx["cc"]["id"]}
    )
    assert r.status_code == 409 and "Echtbetrieb" in r.json()["error"]["message"]


async def test_tenant_scoping_of_calls_and_incidents(client, setup):
    ctx = setup
    foreign = (
        await client.post(
            "/incidents",
            headers=ctx["admin"],
            json={"control_center_id": ctx["other"]["id"], "address": "Fremd"},
        )
    ).json()
    assert (await client.get(f"/incidents/{foreign['id']}", headers=ctx["dispo"])).status_code == 403
    assert foreign["id"] not in [
        i["id"] for i in (await client.get("/incidents", headers=ctx["dispo"])).json()
    ]
    assert (
        await client.get("/calls", headers=ctx["dispo"], params={"control_center_id": ctx["other"]["id"]})
    ).status_code == 403
    call = await _sim_call(client, ctx)
    answered = (
        await client.post(
            f"/calls/{call['id']}/answer", headers=ctx["dispo"], json={"expected_version": call["version"]}
        )
    ).json()
    r = await client.post(
        f"/calls/{call['id']}/link",
        headers=ctx["dispo"],
        json={"incident_id": foreign["id"], "expected_version": answered["version"]},
    )
    assert r.status_code == 403
