"""Reset the data of an installation – keeps users, roles, permissions and system settings.

Used by ``ils-admin reset-data`` (e.g. after a test phase with demo data). Everything else is
emptied in one transaction: control centres, master data, AAO, interfaces, incidents, calls,
alarms, vehicle history, proposals, exercises, imports. The reference catalogues (organisations,
vehicle types, status definitions, keywords) are then recreated with their defaults.

Kept: user accounts with roles, individual rights, sessions, login history and window layouts,
the operation mode, the AI settings and – unless explicitly requested – the audit log. User
assignments to control centres are removed together with the control centres.
Refused in real operation.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text

from app.core.errors import ConflictError
from app.db.base import Base
from app.models import SystemSetting
from app.services.reference_data import (
    KEYWORD_SEED_FLAG,
    POLICE_SEED_FLAG,
    SEED_FLAG,
    ensure_reference_data,
)
from app.services.system_service import SystemService
from app.services.uow import UnitOfWork
from app.simulation.clock import CLOCK_KEY

CONFIRMATION = "ALLES-LOESCHEN"
KEEP_TABLES = frozenset(
    {
        "users",
        "roles",
        "permissions",
        "role_permissions",
        "user_roles",
        "user_permission_overrides",
        "auth_sessions",
        "refresh_tokens",
        "login_events",
        "user_layouts",
        "system_settings",
        "audit_log",
    }
)
# Settings that belong to the deleted data (seed markers are removed so the catalogues are
# recreated; the simulation clock restarts).
RESET_SETTINGS = (SEED_FLAG, KEYWORD_SEED_FLAG, POLICE_SEED_FLAG, CLOCK_KEY)


def tables_to_empty(include_audit: bool) -> list[str]:
    keep = KEEP_TABLES - ({"audit_log"} if include_audit else set())
    return sorted(t.name for t in Base.metadata.sorted_tables if t.name not in keep)


async def row_counts(uow: UnitOfWork, tables: list[str]) -> dict[str, int]:
    counts = {}
    for name in tables:
        # table names come from the model metadata, never from input
        query = text(f'SELECT count(*) FROM "{name}"')  # noqa: S608
        counts[name] = int((await uow.session.execute(query)).scalar_one())
    return counts


async def reset_data(
    uow: UnitOfWork, *, include_audit: bool = False, dry_run: bool = False
) -> dict[str, Any]:
    if await SystemService(uow).operation_mode() != "simulation":
        raise ConflictError("Im Echtbetrieb gesperrt – erst in den Simulationsbetrieb wechseln")
    tables = tables_to_empty(include_audit)
    counts = await row_counts(uow, tables)
    users = int(
        (
            await uow.session.execute(select(func.count()).select_from(Base.metadata.tables["users"]))
        ).scalar_one()
    )
    result: dict[str, Any] = {"tables": counts, "rows": sum(counts.values()), "users_kept": users}
    if dry_run:
        await uow.session.rollback()
        return result
    # One statement, one transaction: either everything is emptied or nothing. TRUNCATE does not
    # fire the row triggers that keep history tables append-only during normal operation.
    quoted = ", ".join(f'"{t}"' for t in tables)
    await uow.session.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY"))
    for key in RESET_SETTINGS:
        row = await uow.session.get(SystemSetting, key)
        if row is not None:
            await uow.session.delete(row)
    await uow.session.flush()
    result["reference_data"] = await ensure_reference_data(uow)  # commits
    uow.audit(
        "reset",
        "system",
        "data",
        f"Datenbestand zurückgesetzt: {result['rows']} Datensätze in {len(tables)} Tabellen gelöscht"
        f"{' (inkl. Änderungsprotokoll)' if include_audit else ''}; {users} Benutzer, Rollen und "
        "Einstellungen behalten",
    )
    uow.emit("system.data_reset", {"rows": result["rows"]})
    await uow.commit()
    return result
