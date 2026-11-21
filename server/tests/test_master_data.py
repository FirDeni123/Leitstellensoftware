"""Phase 2: master data (organisations, vehicle types, stations, vehicles, RICs, groups, areas)."""

from __future__ import annotations

import pytest

from tests.conftest import USER_PASSWORD, bearer, login

SQUARE = {  # roughly the Schwarzenbek area, with a hole in the north-east
    "type": "Polygon",
    "coordinates": [
        [[10.40, 53.45], [10.56, 53.45], [10.56, 53.56], [10.40, 53.56], [10.40, 53.45]],
        [[10.50, 53.52], [10.55, 53.52], [10.55, 53.55], [10.50, 53.55], [10.50, 53.52]],
    ],
}


async def _cc(client, headers, code="ILS-A"):
    r = await client.post(
        "/control-centers", headers=headers, json={"code": code, "name": f"Leitstelle {code}"}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _by(client, headers, path, key):
    return {item[key]: item for item in (await client.get(path, headers=headers)).json()}


async def _station(client, headers, cc, name="Feuerwache Nord", org="feuerwehr", **extra):
    orgs = await _by(client, headers, "/organizations", "key")
    body = {
        "control_center_id": cc["id"],
        "organization_id": orgs[org]["id"],
        "name": name,
        "latitude": 53.50,
        "longitude": 10.48,
        **extra,
    }
    r = await client.post("/stations", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _vehicle(client, headers, cc, station, call_sign="Florian Demo 1/46-1", code="HLF20", **extra):
    types = await _by(client, headers, "/vehicle-types", "code")
    body = {
        "control_center_id": cc["id"],
        "station_id": station["id"],
        "vehicle_type_id": types[code]["id"],
        "call_sign": call_sign,
        **extra,
    }
    return await client.post("/vehicles", headers=headers, json=body)


async def test_reference_data_is_seeded(client, admin_headers):
    orgs = await _by(client, admin_headers, "/organizations", "key")
    assert orgs["polizei"]["alarmable"] is False and orgs["polizei"]["kind"] == "police"
    assert orgs["feuerwehr"]["alarmable"] is True
    types = await _by(client, admin_headers, "/vehicle-types", "code")
    assert {"HLF20", "RTW", "NEF", "DLK23"} <= set(types)
    statuses = (await client.get("/vehicle-status-definitions", headers=admin_headers)).json()
    assert [s["code"] for s in statuses] == list(range(10))
    assert {s["code"] for s in statuses if s["counts_as_available"]} == {1, 2}


async def test_police_can_never_be_alarmable(client, admin_headers):
    r = await client.post(
        "/organizations",
        headers=admin_headers,
        json={"key": "bupo", "name": "Bundespolizei", "kind": "police", "alarmable": True},
    )
    assert r.status_code == 422
    police = (await _by(client, admin_headers, "/organizations", "key"))["polizei"]
    r = await client.patch(
        f"/organizations/{police['id']}",
        headers=admin_headers,
        json={"alarmable": True, "expected_version": police["version"]},
    )
    assert r.status_code == 422
    assert "Informationshinweis" in r.json()["error"]["message"]


async def test_station_crud_uniqueness_and_validation(client, admin_headers):
    cc = await _cc(client, admin_headers)
    station = await _station(
        client,
        admin_headers,
        cc,
        availability={
            "mode": "schedule",
            "schedule": [{"days": [1, 2, 3, 4, 5], "start": "06:00", "end": "18:00"}],
        },
    )
    assert station["organization"]["key"] == "feuerwehr"
    assert station["availability"]["mode"] == "schedule"

    orgs = await _by(client, admin_headers, "/organizations", "key")
    dup = await client.post(
        "/stations",
        headers=admin_headers,
        json={
            "control_center_id": cc["id"],
            "organization_id": orgs["feuerwehr"]["id"],
            "name": "FEUERWACHE NORD",
        },
    )
    assert dup.status_code == 409 and "existiert" in dup.json()["error"]["message"]

    bad = await client.post(
        "/stations",
        headers=admin_headers,
        json={
            "control_center_id": cc["id"],
            "organization_id": orgs["feuerwehr"]["id"],
            "name": "Ohne Länge",
            "latitude": 53.5,
        },
    )
    assert bad.status_code == 422
    bad = await client.post(
        "/stations",
        headers=admin_headers,
        json={
            "control_center_id": cc["id"],
            "organization_id": orgs["feuerwehr"]["id"],
            "name": "Plan",
            "availability": {"mode": "schedule"},
        },
    )
    assert bad.status_code == 422

    r = await client.patch(
        f"/stations/{station['id']}",
        headers=admin_headers,
        json={"name": None, "expected_version": station["version"]},
    )
    assert r.status_code == 422
    r = await client.patch(
        f"/stations/{station['id']}",
        headers=admin_headers,
        json={"short_name": "FW N", "expected_version": station["version"]},
    )
    assert r.status_code == 200 and r.json()["version"] == station["version"] + 1
    stale = await client.patch(
        f"/stations/{station['id']}",
        headers=admin_headers,
        json={"short_name": "X", "expected_version": station["version"]},
    )
    assert stale.status_code == 409


async def test_vehicle_rules(client, admin_headers):
    cc = await _cc(client, admin_headers)
    other_cc = await _cc(client, admin_headers, "ILS-B")
    station = await _station(client, admin_headers, cc)
    r = await _vehicle(client, admin_headers, cc, station, license_plate="rz-fw 112")
    assert r.status_code == 201, r.text
    v = r.json()
    # organisation defaults to the station's, position to the station's coordinates
    assert v["organization"]["key"] == "feuerwehr"
    assert v["position"] == {"latitude": 53.5, "longitude": 10.48, "source": "station"}
    assert v["effective_speed_kmh"] == 60 and v["status_code"] == 2 and v["license_plate"] == "RZ-FW 112"

    assert (
        await _vehicle(client, admin_headers, cc, station, call_sign="florian demo 1/46-1")
    ).status_code == 409

    orgs = await _by(client, admin_headers, "/organizations", "key")
    police = await _vehicle(
        client, admin_headers, cc, station, call_sign="Polizei 1", organization_id=orgs["polizei"]["id"]
    )
    assert police.status_code == 422 and "nicht disponiert" in police.json()["error"]["message"]

    foreign_station = await _station(client, admin_headers, other_cc, name="Fremdwache")
    cross = await _vehicle(client, admin_headers, cc, foreign_station, call_sign="Florian Fremd")
    assert cross.status_code == 422 and "anderen Leitstelle" in cross.json()["error"]["message"]

    second = await _station(client, admin_headers, cc, name="Feuerwache Süd", latitude=53.45, longitude=10.50)
    moved = await client.patch(
        f"/vehicles/{v['id']}",
        headers=admin_headers,
        json={"station_id": second["id"], "sim_speed_kmh": 75, "expected_version": v["version"]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["station"]["name"] == "Feuerwache Süd"
    assert moved.json()["position"]["latitude"] == 53.45 and moved.json()["effective_speed_kmh"] == 75

    # station with vehicles cannot be deleted; vehicles can
    assert (await client.delete(f"/stations/{second['id']}", headers=admin_headers)).status_code == 409
    assert (await client.delete(f"/vehicles/{v['id']}", headers=admin_headers)).status_code == 204
    assert (await client.delete(f"/stations/{second['id']}", headers=admin_headers)).status_code == 204


async def test_ric_assignment_from_both_sides(client, admin_headers):
    cc = await _cc(client, admin_headers)
    station = await _station(client, admin_headers, cc)
    vehicle = (await _vehicle(client, admin_headers, cc, station)).json()
    r = await client.post(
        "/rics",
        headers=admin_headers,
        json={
            "control_center_id": cc["id"],
            "code": "1234567",
            "sub_address": "A",
            "label": "Vollalarm Nord",
            "station_ids": [station["id"]],
            "vehicle_ids": [vehicle["id"]],
        },
    )
    assert r.status_code == 201, r.text
    ric = r.json()
    assert [s["name"] for s in ric["stations"]] == ["Feuerwache Nord"]
    st = (await client.get(f"/stations/{station['id']}", headers=admin_headers)).json()
    assert [x["code"] + x["sub_address"] for x in st["rics"]] == ["1234567A"]

    same = await client.post(
        "/rics",
        headers=admin_headers,
        json={"control_center_id": cc["id"], "code": "1234567", "sub_address": "A", "label": "Doppelt"},
    )
    assert same.status_code == 409
    other_sub = await client.post(
        "/rics",
        headers=admin_headers,
        json={"control_center_id": cc["id"], "code": "1234567", "sub_address": "B", "label": "Info"},
    )
    assert other_sub.status_code == 201

    other_cc = await _cc(client, admin_headers, "ILS-B")
    foreign = (
        await client.post(
            "/rics",
            headers=admin_headers,
            json={"control_center_id": other_cc["id"], "code": "7654321", "label": "Fremd"},
        )
    ).json()
    r = await client.patch(
        f"/vehicles/{vehicle['id']}",
        headers=admin_headers,
        json={"ric_ids": [foreign["id"]], "expected_version": vehicle["version"]},
    )
    assert r.status_code == 422

    group = await client.post(
        "/alarm-groups",
        headers=admin_headers,
        json={
            "control_center_id": cc["id"],
            "name": "Zug Nord",
            "ric_ids": [ric["id"], other_sub.json()["id"]],
        },
    )
    assert group.status_code == 201 and len(group.json()["rics"]) == 2

    # deleting a RIC removes its assignments (and is audited)
    assert (await client.delete(f"/rics/{ric['id']}", headers=admin_headers)).status_code == 204
    st = (await client.get(f"/stations/{station['id']}", headers=admin_headers)).json()
    assert st["rics"] == []


async def test_radio_groups(client, admin_headers):
    cc = await _cc(client, admin_headers)
    station = await _station(client, admin_headers, cc)
    orgs = await _by(client, admin_headers, "/organizations", "key")
    r = await client.post(
        "/radio-groups",
        headers=admin_headers,
        json={
            "control_center_id": cc["id"],
            "name": "TBZ Feuerwehr Süd",
            "talkgroup": "4711",
            "station_ids": [station["id"]],
            "organization_ids": [orgs["feuerwehr"]["id"]],
        },
    )
    assert r.status_code == 201, r.text
    group = r.json()
    vehicle = (await _vehicle(client, admin_headers, cc, station, radio_group_id=group["id"])).json()
    assert vehicle["radio_group"]["name"] == "TBZ Feuerwehr Süd"
    group = (await client.get(f"/radio-groups/{group['id']}", headers=admin_headers)).json()
    assert [v["call_sign"] for v in group["vehicles"]] == [vehicle["call_sign"]]
    assert (await client.delete(f"/radio-groups/{group['id']}", headers=admin_headers)).status_code == 409
    listed = (
        await client.get("/vehicles", headers=admin_headers, params={"radio_group_id": group["id"]})
    ).json()
    assert len(listed) == 1


async def test_status_definitions_are_administrable(client, admin_headers):
    s3 = next(
        s
        for s in (await client.get("/vehicle-status-definitions", headers=admin_headers)).json()
        if s["code"] == 3
    )
    r = await client.patch(
        "/vehicle-status-definitions/3",
        headers=admin_headers,
        json={"label": "Auftrag übernommen / Anfahrt", "expected_version": s3["version"]},
    )
    assert r.status_code == 200 and r.json()["label"] == "Auftrag übernommen / Anfahrt"
    assert (
        await client.post("/vehicle-status-definitions", headers=admin_headers, json={})
    ).status_code == 405
    audit = (
        await client.get("/audit", headers=admin_headers, params={"entity_type": "vehicle_status_definition"})
    ).json()["items"]
    assert audit[0]["changes"]["label"]["old"] == "Einsatzauftrag übernommen"


async def test_areas_and_responsibility(client, admin_headers):
    cc = await _cc(client, admin_headers)
    r = await client.post(
        "/control-center-areas",
        headers=admin_headers,
        json={
            "control_center_id": cc["id"],
            "name": "Amt Schwarzenbek-Land",
            "geometry": SQUARE,
            "priority": 10,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["geometry"]["type"] == "MultiPolygon"
    inside = (
        await client.get(
            "/responsibility", headers=admin_headers, params={"latitude": 53.50, "longitude": 10.48}
        )
    ).json()
    assert [x["control_center"]["code"] for x in inside] == ["ILS-A"]
    in_hole = (
        await client.get(
            "/responsibility", headers=admin_headers, params={"latitude": 53.53, "longitude": 10.52}
        )
    ).json()
    assert in_hole == []
    outside = (
        await client.get(
            "/responsibility", headers=admin_headers, params={"latitude": 53.60, "longitude": 10.48}
        )
    ).json()
    assert outside == []

    bad = await client.post(
        "/control-center-areas",
        headers=admin_headers,
        json={
            "control_center_id": cc["id"],
            "name": "Kaputt",
            "geometry": {"type": "Point", "coordinates": [10, 53]},
        },
    )
    assert bad.status_code == 422
    swapped = await client.post(
        "/control-center-areas",
        headers=admin_headers,
        json={
            "control_center_id": cc["id"],
            "name": "Vertauscht",
            "geometry": {"type": "Polygon", "coordinates": [[[53.4, 10.4], [53.6, 10.4], [53.6, 100.0]]]},
        },
    )
    assert swapped.status_code == 422
    by_key = await client.post(
        "/control-center-areas",
        headers=admin_headers,
        json={"control_center_id": cc["id"], "name": "Gemeinde", "municipality_key": "01053112"},
    )
    assert by_key.status_code == 201
    neither = await client.post(
        "/control-center-areas", headers=admin_headers, json={"control_center_id": cc["id"], "name": "Leer"}
    )
    assert neither.status_code == 422
    # a control centre with areas cannot be deleted silently
    assert (await client.delete(f"/control-centers/{cc['id']}", headers=admin_headers)).status_code == 409


async def test_control_center_links(client, admin_headers):
    a, b = await _cc(client, admin_headers), await _cc(client, admin_headers, "ILS-B")
    r = await client.post(
        "/control-center-links",
        headers=admin_headers,
        json={
            "from_control_center_id": a["id"],
            "to_control_center_id": b["id"],
            "kind": "backup",
            "note": "Ausfall",
        },
    )
    assert r.status_code == 201, r.text
    link = r.json()
    assert link["to_control_center"]["code"] == "ILS-B"
    assert (
        await client.post(
            "/control-center-links",
            headers=admin_headers,
            json={"from_control_center_id": a["id"], "to_control_center_id": b["id"], "kind": "neighbor"},
        )
    ).status_code == 409
    assert (
        await client.post(
            "/control-center-links",
            headers=admin_headers,
            json={"from_control_center_id": a["id"], "to_control_center_id": a["id"], "kind": "neighbor"},
        )
    ).status_code == 409
    listed = (
        await client.get(
            "/control-center-links", headers=admin_headers, params={"control_center_id": b["id"]}
        )
    ).json()
    assert [x["id"] for x in listed] == [link["id"]]
    assert (
        await client.delete(f"/control-center-links/{link['id']}", headers=admin_headers)
    ).status_code == 204


async def test_tenant_scoping_and_read_permissions(client, admin_headers, dispo_headers):
    cc = await _cc(client, admin_headers)
    await _station(client, admin_headers, cc)
    # dispatcher may read master data but only of assigned control centres
    assert (await client.get("/stations", headers=dispo_headers)).json() == []
    assert (
        await client.get("/stations", headers=dispo_headers, params={"control_center_id": cc["id"]})
    ).status_code == 403
    dispo = next(
        u
        for u in (await client.get("/users", headers=admin_headers)).json()["items"]
        if u["username"] == "dispo"
    )
    await client.patch(
        f"/users/{dispo['id']}",
        headers=admin_headers,
        json={"control_center_ids": [cc["id"]], "expected_version": dispo["version"]},
    )
    fresh = bearer(await login(client, "dispo", USER_PASSWORD))
    assert [s["name"] for s in (await client.get("/stations", headers=fresh)).json()] == ["Feuerwache Nord"]
    orgs = await _by(client, fresh, "/organizations", "key")
    r = await client.post(
        "/stations",
        headers=fresh,
        json={
            "control_center_id": cc["id"],
            "organization_id": orgs["feuerwehr"]["id"],
            "name": "Nicht erlaubt",
        },
    )
    assert r.status_code == 403


@pytest.mark.parametrize("q,expected", [("nord", ["Feuerwache Nord"]), ("xyz", [])])
async def test_search(client, admin_headers, q, expected):
    cc = await _cc(client, admin_headers)
    await _station(client, admin_headers, cc)
    await _station(client, admin_headers, cc, name="Rettungswache Mitte", org="rettungsdienst")
    names = [
        s["name"] for s in (await client.get("/stations", headers=admin_headers, params={"q": q})).json()
    ]
    assert names == expected


async def test_vehicle_changes_are_audited_with_fields(client, admin_headers):
    cc = await _cc(client, admin_headers)
    station = await _station(client, admin_headers, cc)
    v = (await _vehicle(client, admin_headers, cc, station)).json()
    await client.patch(
        f"/vehicles/{v['id']}", headers=admin_headers, json={"crew_size": 6, "expected_version": v["version"]}
    )
    entries = (
        await client.get(
            "/audit", headers=admin_headers, params={"entity_type": "vehicle", "entity_id": v["id"]}
        )
    ).json()["items"]
    assert [e["action"] for e in entries] == ["update", "create"]
    assert entries[0]["changes"] == {"crew_size": {"old": None, "new": 6}}
    assert entries[0]["control_center_id"] == cc["id"]
