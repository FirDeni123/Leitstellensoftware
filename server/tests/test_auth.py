from __future__ import annotations

from sqlalchemy import select

from app.models import LoginEvent
from tests.conftest import ADMIN_PASSWORD, USER_PASSWORD, bearer, login


async def test_login_returns_tokens_and_permissions(client):
    data = await login(client, "Dispo", USER_PASSWORD)  # username is case-insensitive
    assert data["access_token"] and data["refresh_token"]
    assert data["user"]["username"] == "dispo"
    assert "alarm.trigger" in data["user"]["permissions"]
    assert "users.read" not in data["user"]["permissions"]
    assert data["user"]["all_control_centers"] is False


async def test_wrong_password_is_rejected_and_logged(client, db):
    r = await client.post("/auth/login", json={"username": "dispo", "password": "falsch"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"
    r = await client.post("/auth/login", json={"username": "gibtsnicht", "password": "x"})
    assert r.status_code == 401
    async with db.sessionmaker() as s:
        reasons = [e.reason for e in (await s.scalars(select(LoginEvent).order_by(LoginEvent.id))).all()]
    assert reasons == ["wrong_password", "unknown_user"]


async def test_account_lockout_after_repeated_failures(client):
    for _ in range(3):  # max_failed_logins=3 in test settings
        assert (
            await client.post("/auth/login", json={"username": "dispo", "password": "x"})
        ).status_code == 401
    r = await client.post("/auth/login", json={"username": "dispo", "password": USER_PASSWORD})
    assert r.status_code == 423
    assert r.json()["error"]["code"] == "account_locked"


async def test_refresh_rotation_and_reuse_detection(client):
    first = await login(client, "dispo", USER_PASSWORD)
    r = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]

    # Re-using the consumed token kills the whole session ...
    r = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401
    # ... so the newer token and the access token are dead too.
    r = await client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r.status_code == 401
    r = await client.get("/auth/me", headers=bearer(second))
    assert r.status_code == 401


async def test_logout_revokes_session(client):
    tokens = await login(client, "dispo", USER_PASSWORD)
    assert (await client.post("/auth/logout", headers=bearer(tokens))).status_code == 204
    assert (await client.get("/auth/me", headers=bearer(tokens))).status_code == 401
    assert (
        await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 401


async def test_invalid_and_missing_tokens(client):
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/auth/me", headers={"Authorization": "Bearer abc.def.ghi"})).status_code == 401


async def test_must_change_password_flow(client, admin_headers):
    r = await client.post(
        "/users",
        headers=admin_headers,
        json={"username": "neu", "display_name": "Neue Person", "roles": ["dispatcher"]},
    )
    assert r.status_code == 201
    initial = r.json()["initial_password"]
    assert initial

    tokens = await login(client, "neu", initial)
    assert tokens["user"]["must_change_password"] is True
    # Everything except /auth/* is blocked until the password has been changed.
    r = await client.get("/system/info", headers=bearer(tokens))
    assert r.status_code == 403
    assert r.json()["error"]["details"]["reason"] == "password_change_required"

    weak = await client.post(
        "/auth/change-password",
        headers=bearer(tokens),
        json={"current_password": initial, "new_password": "kurz"},
    )
    assert weak.status_code == 422

    r = await client.post(
        "/auth/change-password",
        headers=bearer(tokens),
        json={"current_password": initial, "new_password": "Sicher-Wechsel-42"},
    )
    assert r.status_code == 200, r.text
    new_tokens = r.json()
    # Old access token is invalid (token version bumped), new one works.
    assert (await client.get("/system/info", headers=bearer(tokens))).status_code == 401
    assert (await client.get("/system/info", headers=bearer(new_tokens))).status_code == 200


async def test_deactivation_invalidates_tokens_immediately(client, admin_headers):
    dispo = await login(client, "dispo", USER_PASSWORD)
    users = (await client.get("/users", headers=admin_headers, params={"q": "dispo"})).json()["items"]
    target = users[0]
    r = await client.put(
        f"/users/{target['id']}/active",
        headers=admin_headers,
        json={"is_active": False, "expected_version": target["version"]},
    )
    assert r.status_code == 200
    assert (await client.get("/auth/me", headers=bearer(dispo))).status_code == 401
    r = await client.post("/auth/login", json={"username": "dispo", "password": USER_PASSWORD})
    assert r.status_code == 401


async def test_admin_login_has_all_control_centers(client):
    data = await login(client, "admin", ADMIN_PASSWORD)
    assert data["user"]["all_control_centers"] is True
    assert "system.admin" in data["user"]["permissions"]
