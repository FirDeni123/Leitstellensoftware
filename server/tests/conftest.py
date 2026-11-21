"""Test fixtures.

Tests run against a real PostgreSQL database (``ILS_TEST_DATABASE_URL``, default
``ils_test`` on localhost). The schema is created through the Alembic migrations, so the
migrations themselves are tested as well. Between tests all data tables are truncated.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.config import Environment, Settings
from app.core.security import hash_password
from app.db.session import Database
from app.main import create_app
from app.models import Role, User
from app.realtime.bus import InMemoryEventBus
from app.services.reference_data import ensure_reference_data
from app.services.role_service import sync_catalogue
from app.services.uow import UnitOfWork

TEST_DB_URL = os.environ.get(
    "ILS_TEST_DATABASE_URL", "postgresql+asyncpg://ils:ils_dev@localhost:5432/ils_test"
)
ADMIN_PASSWORD = "Test-Admin-Pass-1!"
USER_PASSWORD = "Test-User-Pass-1!"

DATA_TABLES = (
    "vehicle_movements, talk_requests, vehicle_status_history, "
    "proposals, proposal_settings, "
    "interface_events, alarm_targets, alarms, police_notices, alarm_rule_items, alarm_rules, interfaces, "
    "call_notes, emergency_calls, incident_events, incident_vehicles, incidents, incident_number_sequences, "
    "keywords, audit_log, login_events, refresh_tokens, auth_sessions, user_layouts, system_settings, "
    "user_permission_overrides, user_roles, user_control_centers, users, "
    "vehicle_rics, station_rics, alarm_group_rics, radio_group_stations, radio_group_organizations, "
    "vehicles, import_jobs, stations, rics, alarm_groups, radio_groups, control_center_links, "
    "control_center_areas, organizations, vehicle_types, vehicle_status_definitions, control_centers"
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_url=TEST_DB_URL,
        redis_url=None,
        log_level="WARNING",
        log_json=False,
        max_failed_logins=3,
        ws_heartbeat_seconds=0.5,
        simulation_tick_seconds=0,  # tests drive the simulation explicitly
    )


@pytest.fixture(scope="session", autouse=True)
async def _schema(settings: Settings) -> AsyncIterator[None]:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = settings.database_url
    await asyncio.to_thread(command.upgrade, cfg, "head")
    db = Database(settings)
    async with db.sessionmaker() as session:
        await sync_catalogue(UnitOfWork(session, InMemoryEventBus()))
    await db.dispose()
    yield


@pytest.fixture(scope="session")
async def db(settings: Settings) -> AsyncIterator[Database]:
    database = Database(settings)
    yield database
    await database.dispose()


@pytest.fixture(autouse=True)
async def _clean(db: Database) -> AsyncIterator[None]:
    """Reset data and create the standard test users: admin + dispatcher."""
    async with db.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {DATA_TABLES} RESTART IDENTITY CASCADE"))
    async with db.sessionmaker() as session:
        roles = {r.key: r for r in (await session.scalars(select(Role))).all()}
        session.add_all(
            [
                User(
                    username="admin",
                    display_name="Test Admin",
                    password_hash=hash_password(ADMIN_PASSWORD),
                    must_change_password=False,
                    roles=[roles["admin"]],
                ),
                User(
                    username="dispo",
                    display_name="Test Disponent",
                    password_hash=hash_password(USER_PASSWORD),
                    must_change_password=False,
                    roles=[roles["dispatcher"]],
                ),
            ]
        )
        await session.commit()
        await ensure_reference_data(UnitOfWork(session, InMemoryEventBus()))
    yield


@pytest.fixture(scope="session")
async def app(settings: Settings, _schema: None):  # type: ignore[no-untyped-def]
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        yield c


async def login(client: httpx.AsyncClient, username: str, password: str) -> dict:
    r = await client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def bearer(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
async def admin_headers(client: httpx.AsyncClient) -> dict[str, str]:
    return bearer(await login(client, "admin", ADMIN_PASSWORD))


@pytest.fixture
async def dispo_headers(client: httpx.AsyncClient) -> dict[str, str]:
    return bearer(await login(client, "dispo", USER_PASSWORD))
