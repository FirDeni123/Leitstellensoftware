"""ils-admin: demo data are refused on production servers unless explicitly allowed."""

from __future__ import annotations

import pytest

from app import cli
from tests.test_operations import setup  # noqa: F401 – shared fixture


def test_seed_demo_refused_in_production_without_flag(monkeypatch):
    calls: list[str] = []

    async def fake_seed(password: str) -> None:
        calls.append(password)

    monkeypatch.setattr(cli, "seed_demo", fake_seed)
    monkeypatch.setattr(cli, "get_settings", lambda: type("S", (), {"is_production": True})())
    with pytest.raises(SystemExit, match="--allow-production"):
        cli.main(["seed-demo"])
    assert calls == []
    cli.main(["seed-demo", "--allow-production", "--password", "Test-Pass-2026!"])
    assert calls == ["Test-Pass-2026!"]


async def test_reset_data_keeps_users_and_empties_everything_else(client, setup, db):  # noqa: F811
    from sqlalchemy import func, select, text

    from app.core.errors import ConflictError
    from app.models import AuditLog, Keyword, Role, User
    from app.realtime.bus import InMemoryEventBus
    from app.services.data_reset import reset_data, tables_to_empty
    from app.services.uow import UnitOfWork

    c = setup
    r = await client.post(
        "/incidents",
        headers=c["dispo"],
        json={
            "control_center_id": c["cc"]["id"],
            "keyword_id": c["keywords"]["B2"]["id"],
            "address": "Weg 1",
        },
    )
    assert r.status_code == 201, r.text
    users_before = len((await client.get("/users", headers=c["admin"])).json()["items"])

    async with db.sessionmaker() as s:
        before = await reset_data(UnitOfWork(s, InMemoryEventBus()), dry_run=True)
    assert before["tables"]["incidents"] == 1 and before["tables"]["control_centers"] == 2
    assert "audit_log" not in before["tables"] and "users" not in before["tables"]
    assert "audit_log" in tables_to_empty(include_audit=True)

    async with db.sessionmaker() as s:
        result = await reset_data(UnitOfWork(s, InMemoryEventBus()))
    assert result["rows"] >= 2 and result["users_kept"] == users_before
    async with db.sessionmaker() as s:
        for table in tables_to_empty(include_audit=False):
            if table in ("keywords", "organizations", "vehicle_types", "vehicle_status_definitions"):
                continue  # recreated with defaults
            count = (await s.execute(text(f'SELECT count(*) FROM "{table}"'))).scalar_one()  # noqa: S608
            assert count == 0, table
        assert await s.scalar(select(func.count()).select_from(User)) == users_before
        assert await s.scalar(select(func.count()).select_from(Role)) >= 5
        assert await s.scalar(select(func.count()).select_from(Keyword)) > 10  # catalogue recreated
        summaries = (await s.scalars(select(AuditLog.summary).where(AuditLog.action == "reset"))).all()
        assert summaries and "Benutzer" in summaries[0]
    # users can still log in
    assert (await client.get("/auth/me", headers=c["dispo"])).status_code == 200

    # never in real operation
    async with db.sessionmaker() as s:
        await s.execute(text("UPDATE system_settings SET value = '\"real\"' WHERE key = 'operation_mode'"))
        await s.commit()
    async with db.sessionmaker() as s:
        with pytest.raises(ConflictError):
            await reset_data(UnitOfWork(s, InMemoryEventBus()))


def test_reset_data_requires_confirmation(monkeypatch):
    with pytest.raises(SystemExit, match="ALLES-LOESCHEN"):
        cli.main(["reset-data"])


async def test_set_mode_from_the_server_console(db):
    from sqlalchemy import select

    from app.models import AuditLog
    from app.realtime.bus import InMemoryEventBus
    from app.services.uow import UnitOfWork

    async def run(*args):
        async with db.sessionmaker() as s:
            return await cli.change_mode(UnitOfWork(s, InMemoryEventBus(), cli.CONSOLE_ACTOR), *args)

    assert "Simulationsbetrieb" in await run(None, None, None)
    with pytest.raises(SystemExit, match="ECHTBETRIEB"):
        await run("real", "Test der Anbindung", None)  # confirmation missing
    with pytest.raises(SystemExit, match="Begründung"):
        await run("real", None, "ECHTBETRIEB")
    assert "jetzt: ECHTBETRIEB" in await run("real", "Test der Anbindung", "ECHTBETRIEB")
    assert "Bereits" in await run("real", "nochmal", "ECHTBETRIEB")
    assert "jetzt: Simulationsbetrieb" in await run("simulation", "Test beendet", None)
    async with db.sessionmaker() as s:
        entries = (await s.scalars(select(AuditLog).where(AuditLog.action == "mode_change"))).all()
    assert len(entries) == 2 and all(e.actor_name == "Server-Konsole (ils-admin)" for e in entries)
    assert "Test der Anbindung" in entries[0].summary
