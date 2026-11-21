from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import USER_PASSWORD, bearer, login

CC = {"code": "ILS-TEST", "name": "Leitstelle Test", "latitude": 53.5, "longitude": 10.48}


async def test_control_center_crud_and_scoping(client, admin_headers, dispo_headers):
    r = await client.post("/control-centers", headers=admin_headers, json=CC)
    assert r.status_code == 201, r.text
    cc = r.json()
    assert (await client.post("/control-centers", headers=admin_headers, json=CC)).status_code == 409

    # Dispatcher is not assigned yet -> sees nothing, cannot open it.
    assert (await client.get("/control-centers", headers=dispo_headers)).json() == []
    assert (await client.get(f"/control-centers/{cc['id']}", headers=dispo_headers)).status_code == 403

    dispo = next(
        u
        for u in (await client.get("/users", headers=admin_headers)).json()["items"]
        if u["username"] == "dispo"
    )
    r = await client.patch(
        f"/users/{dispo['id']}",
        headers=admin_headers,
        json={"control_center_ids": [cc["id"]], "expected_version": dispo["version"]},
    )
    assert r.status_code == 200
    fresh = bearer(await login(client, "dispo", USER_PASSWORD))
    assert [c["code"] for c in (await client.get("/control-centers", headers=fresh)).json()] == ["ILS-TEST"]

    # Dispatcher cannot modify, admin can – with version check.
    assert (
        await client.patch(
            f"/control-centers/{cc['id']}", headers=fresh, json={"name": "X", "expected_version": 1}
        )
    ).status_code == 403
    r = await client.patch(
        f"/control-centers/{cc['id']}",
        headers=admin_headers,
        json={"name": "Leitstelle Test Nord", "expected_version": cc["version"]},
    )
    assert r.status_code == 200 and r.json()["version"] == cc["version"] + 1
    r = await client.patch(
        f"/control-centers/{cc['id']}",
        headers=admin_headers,
        json={"name": "Veraltet", "expected_version": cc["version"]},
    )
    assert r.status_code == 409

    assert (await client.delete(f"/control-centers/{cc['id']}", headers=admin_headers)).status_code == 204
    assert (await client.get(f"/control-centers/{cc['id']}", headers=admin_headers)).status_code == 404


async def test_invalid_coordinates_rejected(client, admin_headers):
    r = await client.post("/control-centers", headers=admin_headers, json={**CC, "latitude": 123})
    assert r.status_code == 422


async def test_system_info_and_default_simulation_mode(client, dispo_headers):
    info = (await client.get("/system/info", headers=dispo_headers)).json()
    assert info["operation_mode"] == "simulation"
    assert info["realtime_backend"] == "memory"
    statuses = {m["key"]: m["status"] for m in info["modules"]}
    assert statuses["auth"] == "available" and statuses["ai_caller"] == "planned"


async def test_operation_mode_switch_requires_permission_and_confirmation(
    client, admin_headers, dispo_headers
):
    mode = (await client.get("/system/operation-mode", headers=admin_headers)).json()
    body = {
        "mode": "real",
        "reason": "Test des Echtbetriebs",
        "confirmation": "ja",
        "expected_version": mode["version"],
    }
    assert (await client.put("/system/operation-mode", headers=dispo_headers, json=body)).status_code == 403
    assert (await client.put("/system/operation-mode", headers=admin_headers, json=body)).status_code == 422
    body["confirmation"] = "ECHTBETRIEB"
    r = await client.put("/system/operation-mode", headers=admin_headers, json=body)
    assert r.status_code == 200 and r.json()["mode"] == "real"
    audit = (await client.get("/audit", headers=admin_headers, params={"entity_type": "system"})).json()
    assert audit["items"][0]["action"] == "mode_change"


async def test_layout_persistence_with_conflict_detection(client, dispo_headers):
    assert (await client.get("/me/layouts/dispatch", headers=dispo_headers)).status_code == 404
    r = await client.put("/me/layouts/dispatch", headers=dispo_headers, json={"layout": {"grid": 1}})
    assert r.status_code == 200
    v = r.json()["version"]
    r = await client.put(
        "/me/layouts/dispatch", headers=dispo_headers, json={"layout": {"grid": 2}, "expected_version": v}
    )
    assert r.status_code == 200
    stale = await client.put(
        "/me/layouts/dispatch", headers=dispo_headers, json={"layout": {"grid": 3}, "expected_version": v}
    )
    assert stale.status_code == 409
    assert (await client.get("/me/layouts/dispatch", headers=dispo_headers)).json()["layout"] == {"grid": 2}
    assert (
        await client.put("/me/layouts/unbekannt", headers=dispo_headers, json={"layout": {}})
    ).status_code == 422
    assert (await client.delete("/me/layouts/dispatch", headers=dispo_headers)).status_code == 204


async def test_audit_pagination(client, admin_headers):
    for i in range(5):
        await client.post("/control-centers", headers=admin_headers, json={**CC, "code": f"ILS-{i}"})
    page1 = (await client.get("/audit", headers=admin_headers, params={"limit": 3})).json()
    assert len(page1["items"]) == 3 and page1["next_before_id"]
    page2 = (
        await client.get(
            "/audit", headers=admin_headers, params={"limit": 3, "before_id": page1["next_before_id"]}
        )
    ).json()
    ids = [e["id"] for e in page1["items"] + page2["items"]]
    assert ids == sorted(ids, reverse=True) and len(set(ids)) == len(ids)


async def test_audit_log_is_immutable_in_database(db, client, admin_headers):
    await client.post("/control-centers", headers=admin_headers, json=CC)
    with pytest.raises(DBAPIError, match="unveränderbar"):
        async with db.engine.begin() as conn:
            await conn.execute(text("UPDATE audit_log SET summary = 'manipuliert'"))
    with pytest.raises(DBAPIError, match="unveränderbar"):
        async with db.engine.begin() as conn:
            await conn.execute(text("DELETE FROM audit_log"))


async def test_health(app):
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/health")
    assert r.status_code == 200 and r.json()["checks"]["database"] == "ok"
    assert r.headers["x-request-id"]
