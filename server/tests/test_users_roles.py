from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog
from tests.conftest import USER_PASSWORD, bearer, login


async def _user(client, headers, username):
    items = (await client.get("/users", headers=headers, params={"q": username})).json()["items"]
    return next(u for u in items if u["username"] == username)


async def test_dispatcher_cannot_manage_users(client, dispo_headers):
    r = await client.get("/users", headers=dispo_headers)
    assert r.status_code == 403
    assert r.json()["error"]["details"]["missing_permissions"] == ["users.read"]


async def test_create_user_is_audited(client, admin_headers, db):
    r = await client.post(
        "/users",
        headers=admin_headers,
        json={
            "username": "m.mustermann",
            "display_name": "Max Mustermann",
            "roles": ["call_taker"],
            "password": "Sicheres-Passwort-1",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["initial_password"] is None
    assert body["user"]["roles"] == ["call_taker"]
    assert body["user"]["must_change_password"] is True
    async with db.sessionmaker() as s:
        entry = await s.scalar(select(AuditLog).where(AuditLog.entity_id == body["user"]["id"]))
    assert entry.action == "create"
    assert entry.actor_name.startswith("Test Admin")
    assert entry.changes["roles"]["new"] == ["call_taker"]


async def test_duplicate_username_conflict(client, admin_headers):
    r = await client.post(
        "/users", headers=admin_headers, json={"username": "dispo", "display_name": "Doppelt"}
    )
    assert r.status_code == 409


async def test_invalid_username_rejected(client, admin_headers):
    r = await client.post(
        "/users", headers=admin_headers, json={"username": "Ä B", "display_name": "Ungültig"}
    )
    assert r.status_code == 422


async def test_optimistic_locking_conflict(client, admin_headers):
    target = await _user(client, admin_headers, "dispo")
    v = target["version"]
    r1 = await client.patch(
        f"/users/{target['id']}",
        headers=admin_headers,
        json={"display_name": "Erste Änderung", "expected_version": v},
    )
    assert r1.status_code == 200
    assert r1.json()["version"] == v + 1
    # A second dispatcher still holds the old version -> must not overwrite silently.
    r2 = await client.patch(
        f"/users/{target['id']}",
        headers=admin_headers,
        json={"display_name": "Zweite Änderung", "expected_version": v},
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["details"]["current_version"] == v + 1


async def test_relationship_change_increments_version(client, admin_headers):
    target = await _user(client, admin_headers, "dispo")
    r = await client.patch(
        f"/users/{target['id']}",
        headers=admin_headers,
        json={"roles": ["observer"], "expected_version": target["version"]},
    )
    assert r.status_code == 200
    assert r.json()["version"] == target["version"] + 1
    assert r.json()["effective_permissions"] == ["control_centers.read", "incidents.read", "master_data.read"]


async def test_permission_overrides(client, admin_headers):
    target = await _user(client, admin_headers, "dispo")
    r = await client.patch(
        f"/users/{target['id']}",
        headers=admin_headers,
        json={
            "expected_version": target["version"],
            "permission_overrides": [
                {"permission_code": "alarm.trigger", "effect": "deny"},
                {"permission_code": "audit.read", "effect": "grant"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    perms = r.json()["effective_permissions"]
    assert "alarm.trigger" not in perms and "audit.read" in perms
    me = await login(client, "dispo", USER_PASSWORD)
    assert "audit.read" in me["user"]["permissions"]


async def test_unknown_permission_rejected(client, admin_headers):
    target = await _user(client, admin_headers, "dispo")
    r = await client.patch(
        f"/users/{target['id']}",
        headers=admin_headers,
        json={
            "expected_version": target["version"],
            "permission_overrides": [{"permission_code": "nuclear.launch", "effect": "grant"}],
        },
    )
    assert r.status_code == 422


async def test_cannot_deactivate_self_or_last_admin(client, admin_headers):
    me = await _user(client, admin_headers, "admin")
    r = await client.put(
        f"/users/{me['id']}/active",
        headers=admin_headers,
        json={"is_active": False, "expected_version": me["version"]},
    )
    assert r.status_code == 422
    r = await client.patch(
        f"/users/{me['id']}",
        headers=admin_headers,
        json={"roles": ["dispatcher"], "expected_version": me["version"]},
    )
    assert r.status_code == 422
    assert "Administrator" in r.json()["error"]["message"]


async def test_admin_password_reset_generates_password(client, admin_headers):
    old = await login(client, "dispo", USER_PASSWORD)
    target = await _user(client, admin_headers, "dispo")
    r = await client.post(
        f"/users/{target['id']}/reset-password",
        headers=admin_headers,
        json={"expected_version": target["version"]},
    )
    assert r.status_code == 200
    new_password = r.json()["initial_password"]
    assert (await client.get("/auth/me", headers=bearer(old))).status_code == 401
    fresh = await login(client, "dispo", new_password)
    assert fresh["user"]["must_change_password"] is True


async def test_role_management(client, admin_headers):
    roles = (await client.get("/roles", headers=admin_headers)).json()
    assert {r["key"] for r in roles} == {
        "admin",
        "lead",
        "dispatcher",
        "instructor",
        "call_taker",
        "observer",
    }
    r = await client.post(
        "/roles",
        headers=admin_headers,
        json={"key": "funk", "name": "Funkplatz", "permissions": ["radio.handle", "incidents.read"]},
    )
    assert r.status_code == 201
    role = r.json()
    r = await client.patch(
        f"/roles/{role['id']}",
        headers=admin_headers,
        json={"permissions": ["radio.handle"], "expected_version": role["version"]},
    )
    assert r.status_code == 200 and r.json()["permissions"] == ["radio.handle"]
    assert (await client.delete(f"/roles/{role['id']}", headers=admin_headers)).status_code == 204

    admin_role = next(r for r in roles if r["key"] == "admin")
    assert (await client.delete(f"/roles/{admin_role['id']}", headers=admin_headers)).status_code == 422
    r = await client.patch(
        f"/roles/{admin_role['id']}",
        headers=admin_headers,
        json={"permissions": ["users.read"], "expected_version": admin_role["version"]},
    )
    assert r.status_code == 422


async def test_permission_catalogue(client, admin_headers):
    perms = (await client.get("/permissions", headers=admin_headers)).json()
    codes = {p["code"] for p in perms}
    assert {"interfaces.activate_real", "system.mode.change", "alarm.trigger"} <= codes


async def test_login_log_requires_permission(client, admin_headers, dispo_headers):
    assert (await client.get("/login-events", headers=dispo_headers)).status_code == 403
    events = (await client.get("/login-events", headers=admin_headers)).json()
    assert {e["username"] for e in events} >= {"admin", "dispo"}
