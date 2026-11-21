"""Phase 2: Excel/CSV import (milestone M2)."""

from __future__ import annotations

import io

from openpyxl import Workbook
from sqlalchemy import func, select

from app.models import AuditLog, Vehicle
from app.services.import_files import normalise_header, parse_bool, parse_number
from app.services.import_service import suggest_mapping
from tests.conftest import USER_PASSWORD, bearer, login

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def xlsx(rows: list[list[object]], sheet: str = "Fahrzeuge") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def csv_bytes(lines: list[str], encoding: str = "cp1252") -> bytes:
    return ("\r\n".join(lines) + "\r\n").encode(encoding)


async def _setup(client, headers):
    cc = (
        await client.post("/control-centers", headers=headers, json={"code": "ILS-IMP", "name": "Import"})
    ).json()
    orgs = {o["key"]: o for o in (await client.get("/organizations", headers=headers)).json()}
    stations = {}
    for name, short, org in (("Feuerwache Nord", "FW N", "feuerwehr"), ("Rettungswache Süd", "RW S", "drk")):
        r = await client.post(
            "/stations",
            headers=headers,
            json={
                "control_center_id": cc["id"],
                "organization_id": orgs[org]["id"],
                "name": name,
                "short_name": short,
                "latitude": 53.5,
                "longitude": 10.48,
            },
        )
        stations[name] = r.json()
    await client.post(
        "/rics",
        headers=headers,
        json={"control_center_id": cc["id"], "code": "1000001", "sub_address": "A", "label": "Zug Nord"},
    )
    await client.post(
        "/radio-groups",
        headers=headers,
        json={"control_center_id": cc["id"], "name": "TBZ Nord", "talkgroup": "4711"},
    )
    return cc, stations


async def _upload(client, headers, cc, name, content, kind="vehicles", mime=XLSX):
    return await client.post(
        "/imports",
        headers=headers,
        files={"file": (name, content, mime)},
        data={"kind": kind, "control_center_id": cc["id"]},
    )


async def test_m2_import_200_vehicles_from_xlsx(client, admin_headers, db):
    cc, _ = await _setup(client, admin_headers)
    rows: list[list[object]] = [
        ["Rufname", "Fzg.-Typ", "Standort", "Amtl. Kennzeichen", "RIC", "Bemerkung", "Interne Nummer"]
    ]
    for i in range(200):
        rows.append(
            [
                f"Florian Import {i:03d}",
                "HLF 20" if i % 2 else "Rettungswagen",
                "FW N" if i % 2 else "Rettungswache Süd",
                f"RZ-FW {i}",
                "1000001A" if i % 10 == 0 else None,
                None,
                9000 + i,
            ]
        )
    r = await _upload(client, admin_headers, cc, "fahrzeuge.xlsx", xlsx(rows))
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["row_count"] == 200 and job["sheets"] == ["Fahrzeuge"]
    assert job["column_mapping"] == {
        "call_sign": 0,
        "vehicle_type": 1,
        "station": 2,
        "license_plate": 3,
        "rics": 4,
        "description": 5,
        "organization": None,
        "radio_group": None,
        "crew_size": None,
        "sim_speed_kmh": None,
        "available": None,
    }
    assert len(job["sample_rows"]) == 20

    # the administrator adjusts the mapping (no description column) and validates
    mapping = {**job["column_mapping"], "description": None}
    r = await client.put(
        f"/imports/{job['id']}/mapping",
        headers=admin_headers,
        json={"mapping": mapping, "expected_version": job["version"]},
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "validated"
    assert job["summary"]["create"] == 200 and job["summary"]["error"] == 0
    async with db.sessionmaker() as s:
        assert await s.scalar(select(func.count(Vehicle.id))) == 0  # nothing written before commit

    r = await client.post(
        f"/imports/{job['id']}/commit", headers=admin_headers, json={"expected_version": job["version"]}
    )
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "committed" and done["sample_rows"] == []  # raw rows removed after commit

    vehicles = (
        await client.get("/vehicles", headers=admin_headers, params={"control_center_id": cc["id"]})
    ).json()
    assert len(vehicles) == 200
    rtw = next(v for v in vehicles if v["call_sign"] == "Florian Import 000")
    assert rtw["vehicle_type"]["code"] == "RTW" and rtw["organization"]["key"] == "drk"
    assert [x["code"] + x["sub_address"] for x in rtw["rics"]] == ["1000001A"]
    assert rtw["import_job_id"] == job["id"]
    async with db.sessionmaker() as s:
        audited = await s.scalar(select(func.count(AuditLog.id)).where(AuditLog.entity_type == "vehicle"))
        assert audited == 200
        summary = await s.scalar(select(AuditLog.summary).where(AuditLog.action == "commit"))
        assert "200 neu" in summary


async def test_row_errors_are_reported_and_block_commit(client, admin_headers):
    cc, stations = await _setup(client, admin_headers)
    lines = [
        "Funkrufname;Fahrzeugtyp;Wache;Organisation;Besatzung;RICs;Geschwindigkeit",
        "Florian Gut 1;HLF20;Feuerwache Nord;;9;1000001A;60",
        "Florian Typ;Raumschiff;Feuerwache Nord;;;;",
        "Florian Wache;HLF20;Gibt es nicht;;;;",
        "Florian Gut 1;LF20;Feuerwache Nord;;;;",
        "Polizei 1;RTW;Rettungswache Süd;Polizei;;;",
        "Florian Zahl;HLF20;FW N;;viele;;55,5",
        "Florian RIC;HLF20;FW N;;;9999999;",
        "Florian Ümlaut;RTW;RW S;DRK;2;1000001;80 km/h",
    ]
    r = await _upload(client, admin_headers, cc, "fahrzeuge.csv", csv_bytes(lines), mime="text/csv")
    assert r.status_code == 201, r.text
    job = r.json()
    r = await client.put(
        f"/imports/{job['id']}/mapping",
        headers=admin_headers,
        json={"mapping": job["column_mapping"], "expected_version": job["version"]},
    )
    job = r.json()
    by_row = {x["row"]: x for x in job["validation"]}
    assert by_row[2]["action"] == "create"
    assert by_row[3]["errors"] == ["Fahrzeugtyp „Raumschiff“ unbekannt"]
    assert "Wache „Gibt es nicht“ unbekannt" in by_row[4]["errors"][0]
    assert by_row[5]["errors"] == ["Doppelt in der Datei (bereits in Zeile 2)"]
    assert "nicht disponiert" in by_row[6]["errors"][0]
    assert any("Besatzung" in e for e in by_row[7]["errors"]) and any(
        "Geschwindigkeit" in e for e in by_row[7]["errors"]
    )
    assert by_row[8]["errors"] == ["RIC 9999999 ist nicht angelegt"]
    assert (
        by_row[9]["action"] == "create" and by_row[9]["values"]["call_sign"] == "Florian Ümlaut"
    )  # cp1252 decoded
    assert job["summary"] == {"create": 2, "update": 0, "unchanged": 0, "error": 6, "skip": 0, "total": 8}

    blocked = await client.post(
        f"/imports/{job['id']}/commit", headers=admin_headers, json={"expected_version": job["version"]}
    )
    assert blocked.status_code == 422
    assert (await client.get("/vehicles", headers=admin_headers)).json() == []

    job = (await client.get(f"/imports/{job['id']}", headers=admin_headers)).json()
    r = await client.post(
        f"/imports/{job['id']}/commit",
        headers=admin_headers,
        json={"expected_version": job["version"], "skip_invalid": True},
    )
    assert r.status_code == 200, r.text
    names = sorted(v["call_sign"] for v in (await client.get("/vehicles", headers=admin_headers)).json())
    assert names == ["Florian Gut 1", "Florian Ümlaut"]
    umlaut = next(
        v
        for v in (await client.get("/vehicles", headers=admin_headers)).json()
        if v["call_sign"] == "Florian Ümlaut"
    )
    assert umlaut["sim_speed_kmh"] == 80 and umlaut["crew_size"] == 2


async def test_update_existing_vehicles(client, admin_headers):
    cc, stations = await _setup(client, admin_headers)
    types = {t["code"]: t for t in (await client.get("/vehicle-types", headers=admin_headers)).json()}
    existing = (
        await client.post(
            "/vehicles",
            headers=admin_headers,
            json={
                "control_center_id": cc["id"],
                "station_id": stations["Feuerwache Nord"]["id"],
                "vehicle_type_id": types["HLF20"]["id"],
                "call_sign": "Florian Alt 1",
                "license_plate": "RZ-A 1",
                "description": "bleibt erhalten",
            },
        )
    ).json()
    rows = [
        ["Funkrufname", "Typ", "Wache", "Kennzeichen", "Beschreibung"],
        ["florian alt 1", "HLF20", "Feuerwache Nord", "RZ-NEU 1", None],
        ["Florian Neu 2", "LF20", "Feuerwache Nord", None, None],
    ]
    job = (await _upload(client, admin_headers, cc, "update.xlsx", xlsx(rows))).json()

    without = (
        await client.put(
            f"/imports/{job['id']}/mapping",
            headers=admin_headers,
            json={"mapping": job["column_mapping"], "expected_version": job["version"]},
        )
    ).json()
    assert "Existiert bereits" in without["validation"][0]["errors"][0]

    job = (
        await client.put(
            f"/imports/{job['id']}/mapping",
            headers=admin_headers,
            json={
                "mapping": job["column_mapping"],
                "update_existing": True,
                "expected_version": without["version"],
            },
        )
    ).json()
    first = job["validation"][0]
    assert first["action"] == "update" and first["changes"] == ["Kennzeichen"]
    r = await client.post(
        f"/imports/{job['id']}/commit", headers=admin_headers, json={"expected_version": job["version"]}
    )
    assert r.status_code == 200
    updated = (await client.get(f"/vehicles/{existing['id']}", headers=admin_headers)).json()
    assert updated["license_plate"] == "RZ-NEU 1"
    assert updated["description"] == "bleibt erhalten"  # empty cell does not overwrite
    assert updated["version"] == existing["version"] + 1


async def test_station_import_with_german_coordinates(client, admin_headers):
    cc, _ = await _setup(client, admin_headers)
    lines = [
        "Name;Organisation;Kürzel;Breitengrad;Längengrad;Anschrift",
        "Feuerwache Ost;Feuerwehr;FW O;53,4981;10,5102;Hauptstr. 1",
        "Wache Vertauscht;feuerwehr;;10,48;53,50;",
        "Wache Halb;feuerwehr;;53,5;;",
    ]
    job = (
        await _upload(
            client,
            admin_headers,
            cc,
            "wachen.csv",
            csv_bytes(lines, "utf-8"),
            kind="stations",
            mime="text/csv",
        )
    ).json()
    assert job["column_mapping"]["short_name"] == 2 and job["column_mapping"]["latitude"] == 3
    job = (
        await client.put(
            f"/imports/{job['id']}/mapping",
            headers=admin_headers,
            json={"mapping": job["column_mapping"], "expected_version": job["version"]},
        )
    ).json()
    rows = job["validation"]
    assert rows[0]["action"] == "create"
    assert "vertauscht" in rows[1]["warnings"][0]
    assert rows[2]["errors"] == ["Breiten- und Längengrad nur gemeinsam angeben"]
    r = await client.post(
        f"/imports/{job['id']}/commit",
        headers=admin_headers,
        json={"expected_version": job["version"], "skip_invalid": True},
    )
    assert r.status_code == 200
    ost = next(
        s
        for s in (await client.get("/stations", headers=admin_headers)).json()
        if s["name"] == "Feuerwache Ost"
    )
    assert (ost["latitude"], ost["longitude"], ost["short_name"]) == (53.4981, 10.5102, "FW O")


async def test_mapping_and_file_validation(client, admin_headers):
    cc, _ = await _setup(client, admin_headers)
    job = (
        await _upload(client, admin_headers, cc, "f.xlsx", xlsx([["A", "B", "C"], ["x", "y", "z"]]))
    ).json()
    assert job["column_mapping"]["call_sign"] is None
    r = await client.put(
        f"/imports/{job['id']}/mapping",
        headers=admin_headers,
        json={"mapping": {"call_sign": 0}, "expected_version": job["version"]},
    )
    assert r.status_code == 422 and "Pflichtfelder" in r.json()["error"]["message"]
    r = await client.put(
        f"/imports/{job['id']}/mapping",
        headers=admin_headers,
        json={
            "mapping": {"call_sign": 0, "vehicle_type": 0, "station": 1},
            "expected_version": job["version"],
        },
    )
    assert r.status_code == 422 and "mehrfach" in r.json()["error"]["message"]

    assert (await _upload(client, admin_headers, cc, "alt.xls", b"\xd0\xcf\x11\xe0")).status_code == 422
    assert (await _upload(client, admin_headers, cc, "kaputt.xlsx", b"kein zip")).status_code == 422
    assert (await _upload(client, admin_headers, cc, "leer.csv", b"", mime="text/csv")).status_code == 422
    assert (
        await _upload(client, admin_headers, cc, "nur-kopf.csv", b"a;b\n", mime="text/csv")
    ).status_code == 422
    assert (await _upload(client, admin_headers, cc, "bild.png", b"\x89PNG")).status_code == 422


async def test_discard_and_permissions(client, admin_headers, dispo_headers):
    cc, _ = await _setup(client, admin_headers)
    content = xlsx([["Funkrufname", "Typ", "Wache"], ["Florian X", "HLF20", "FW N"]])
    assert (await _upload(client, dispo_headers, cc, "x.xlsx", content)).status_code == 403

    job = (await _upload(client, admin_headers, cc, "x.xlsx", content)).json()
    assert (await client.delete(f"/imports/{job['id']}", headers=admin_headers)).status_code == 204
    discarded = (await client.get(f"/imports/{job['id']}", headers=admin_headers)).json()
    assert discarded["status"] == "discarded" and discarded["sample_rows"] == []
    r = await client.post(
        f"/imports/{job['id']}/commit", headers=admin_headers, json={"expected_version": discarded["version"]}
    )
    assert r.status_code == 409

    # data.import alone is not enough – the target permission is required as well
    users = (await client.get("/users", headers=admin_headers)).json()["items"]
    dispo = next(u for u in users if u["username"] == "dispo")
    await client.patch(
        f"/users/{dispo['id']}",
        headers=admin_headers,
        json={
            "expected_version": dispo["version"],
            "control_center_ids": [cc["id"]],
            "permission_overrides": [{"permission_code": "data.import", "effect": "grant"}],
        },
    )
    fresh = bearer(await login(client, "dispo", USER_PASSWORD))
    r = await _upload(client, fresh, cc, "x.xlsx", content)
    assert r.status_code == 403 and r.json()["error"]["details"]["missing_permissions"] == ["vehicles.write"]


def test_header_mapping_suggestions():
    headers = ["Fahrzeug-Typ", "Funkrufname", "Wache/Standort", "Amtl. Kennzeichen", "Bemerkungen", "km/h"]
    m = suggest_mapping("vehicles", headers)
    assert (
        m["vehicle_type"],
        m["call_sign"],
        m["station"],
        m["license_plate"],
        m["description"],
        m["sim_speed_kmh"],
    ) == (0, 1, 2, 3, 4, 5)
    assert normalise_header("Längengrad (WGS84)") == "laengengrad wgs84"


def test_value_parsing():
    assert parse_number("53,5036") == 53.5036
    assert parse_number("1.234,5") == 1234.5
    assert parse_number("1,234.5") == 1234.5
    assert parse_number("80 km/h") == 80
    assert parse_bool("X") is True and parse_bool("nein") is False
