"""Administrative command line (``ils-admin``).

Commands::

    ils-admin bootstrap           Permission catalogue + default roles + first administrator
    ils-admin seed-demo           Sample control centre and users for development/training
    ils-admin reset-data          Delete all data except users, roles and settings
    ils-admin set-mode [MODE]     Show or switch the operation mode (simulation | real)
    ils-admin create-user ...     Create a user from the shell
    ils-admin generate-key        New Fernet key for ILS_ENCRYPTION_KEYS
    ils-admin generate-jwt-secret New value for ILS_JWT_SECRET
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.crypto import SecretBox
from app.core.errors import AppError
from app.core.security import generate_initial_password, hash_password, validate_password_policy
from app.db.session import Database
from app.demo_data import seed_master_data
from app.models import ControlCenter, Role, User
from app.realtime.bus import InMemoryEventBus, create_bus
from app.services.reference_data import ensure_reference_data
from app.services.role_service import sync_catalogue
from app.services.uow import Actor, UnitOfWork

DEMO_CONTROL_CENTER = {
    "code": "ILS-DEMO",
    "name": "Integrierte Leitstelle Demo (Beispieldaten)",
    "description": "Beispiel-Leitstelle für Entwicklung und Training. Alle Daten sind fiktiv.",
    "address": "Schwarzenbek (Beispielstandort)",
    "latitude": 53.5036,
    "longitude": 10.4806,
}

DEMO_USERS = (
    ("admin.demo", "Administrator Demo", "admin"),
    ("lead.demo", "Leitstellenleitung Demo", "lead"),
    ("dispo.demo", "Disponent Demo", "dispatcher"),
    ("ausbilder.demo", "Ausbilder Demo", "instructor"),
    ("annahme.demo", "Einsatzbearbeiter Demo", "call_taker"),
    ("beobachter.demo", "Beobachter Demo", "observer"),
)


async def _with_uow(fn):  # type: ignore[no-untyped-def]
    db = Database(get_settings())
    try:
        async with db.sessionmaker() as session:
            return await fn(UnitOfWork(session, InMemoryEventBus()))
    finally:
        await db.dispose()


async def bootstrap(admin_username: str, admin_password: str | None) -> None:
    async def run(uow: UnitOfWork) -> None:
        result = await sync_catalogue(uow)
        ref = await ensure_reference_data(uow)
        print(
            f"Referenzdaten: {ref['statuses']} Status, {ref['organizations']} Organisationen, "
            f"{ref['vehicle_types']} Fahrzeugtypen, {ref['keywords']} Stichworte angelegt"
        )
        print(
            f"Berechtigungskatalog: {result['permissions_added']} neu, "
            f"Rollen angelegt: {result['roles_created']}"
        )
        existing_admin = await uow.session.scalar(select(User).where(User.roles.any(Role.key == "admin")))
        if existing_admin:
            print(f"Administrator vorhanden ({existing_admin.username}) – kein neuer angelegt.")
            return
        password = admin_password or generate_initial_password(username=admin_username)
        validate_password_policy(password, get_settings(), username=admin_username)
        admin_role = await uow.session.scalar(select(Role).where(Role.key == "admin"))
        user = User(
            username=admin_username,
            display_name="Administrator",
            password_hash=hash_password(password),
            must_change_password=True,
            roles=[admin_role],
        )
        uow.session.add(user)
        await uow.session.flush()
        uow.audit("create", "user", user.id, f"Erster Administrator {admin_username} angelegt (Bootstrap)")
        await uow.commit()
        print(f"Administrator angelegt: {admin_username}")
        if not admin_password:
            print(f"Initialpasswort (muss bei erster Anmeldung geändert werden): {password}")

    await _with_uow(run)


async def seed_demo(password: str) -> None:
    async def run(uow: UnitOfWork) -> None:
        s = uow.session
        await sync_catalogue(uow)  # roles introduced by newer versions (e.g. "instructor")
        cc = await s.scalar(select(ControlCenter).where(ControlCenter.code == DEMO_CONTROL_CENTER["code"]))
        if cc is None:
            cc = ControlCenter(**DEMO_CONTROL_CENTER)
            s.add(cc)
            await s.flush()
            uow.audit(
                "create",
                "control_center",
                cc.id,
                f"Demo-Leitstelle {cc.name} angelegt (Seed)",
                control_center_id=cc.id,
            )
            print(f"Leitstelle angelegt: {cc.code}")
        roles = {r.key: r for r in (await s.scalars(select(Role))).all()}
        if not roles:
            raise SystemExit("Bitte zuerst 'ils-admin bootstrap' ausführen")
        for username, name, role_key in DEMO_USERS:
            existing = await s.scalar(select(User).where(User.username == username))
            if existing is not None:
                if cc not in existing.control_centers:  # e.g. after reset-data
                    existing.control_centers = [*existing.control_centers, cc]
                continue
            user = User(
                username=username,
                display_name=name,
                password_hash=hash_password(password),
                must_change_password=False,
                roles=[roles[role_key]],
                control_centers=[cc],
            )
            s.add(user)
            await s.flush()
            uow.audit("create", "user", user.id, f"Demo-Benutzer {username} angelegt (Seed)")
            print(f"Benutzer angelegt: {username} ({role_key})")
        counts = await seed_master_data(uow, cc)
        print(f"Demo-Stammdaten: {counts}")
        # Assign every administrator to the demo centre so it shows up as default.
        for admin in (await s.scalars(select(User).where(User.roles.any(Role.key == "admin")))).all():
            if cc not in admin.control_centers:
                admin.control_centers = [*admin.control_centers, cc]
        await uow.commit()

    await _with_uow(run)


async def reset_data_command(confirm: str | None, dry_run: bool, include_audit: bool) -> None:
    from app.services.data_reset import CONFIRMATION, reset_data

    if not dry_run and confirm != CONFIRMATION:
        raise SystemExit(
            "Löscht alle Daten außer Benutzern, Rollen und Einstellungen – unwiderruflich.\n"
            "Erst ansehen:  ils-admin reset-data --dry-run\n"
            f"Ausführen:     ils-admin reset-data --confirm {CONFIRMATION}\n"
            "Vorher eine Sicherung anlegen (deploy/scripts/backup.sh)."
        )

    async def run(uow: UnitOfWork) -> None:
        result = await reset_data(uow, include_audit=include_audit, dry_run=dry_run)
        filled = {k: v for k, v in result["tables"].items() if v}
        print(("Würde löschen" if dry_run else "Gelöscht") + f": {result['rows']} Datensätze")
        for table, count in sorted(filled.items(), key=lambda kv: -kv[1]):
            print(f"  {table:<28} {count:>8}")
        print(
            f"Behalten: {result['users_kept']} Benutzer mit Rollen, Rechten und Layouts, Systemeinstellungen"
            + ("" if include_audit else ", Änderungsprotokoll")
        )
        if not dry_run:
            print(f"Grundkataloge neu angelegt: {result['reference_data']}")
            print("Bitte die API neu starten: docker compose restart api")

    await _with_uow(run)


CONSOLE_ACTOR = Actor(None, "Server-Konsole (ils-admin)")
MODE_LABEL = {"simulation": "Simulationsbetrieb", "real": "ECHTBETRIEB"}


async def change_mode(uow: UnitOfWork, mode: str | None, reason: str | None, confirm: str | None) -> str:
    """Show (mode None) or switch the operation mode – same rules and effects as in the API."""
    from app.models import OperationMode
    from app.services.system_service import REAL_MODE_CONFIRMATION, SystemService

    service = SystemService(uow)
    current = await service.mode_setting()
    if mode is None:
        return f"Aktueller Betriebsmodus: {MODE_LABEL.get(current.value, current.value)}"
    target = OperationMode(mode)
    if target.value == current.value:
        return f"Bereits im {MODE_LABEL[target.value]} – nichts geändert"
    if not reason or len(reason.strip()) < 5:
        raise SystemExit('Bitte eine Begründung angeben (mind. 5 Zeichen): --reason "…"')
    if target == OperationMode.REAL and confirm != REAL_MODE_CONFIRMATION:
        raise SystemExit(
            "Wechsel in den ECHTBETRIEB: Reale Schnittstellen können danach eingeschaltet werden und "
            "übertragen jede bestätigte Alarmierung; Übungen, simulierte Notrufe und Fahrten werden "
            f"beendet.\nZur Bestätigung zusätzlich: --confirm {REAL_MODE_CONFIRMATION}"
        )
    await service.set_operation_mode(target, reason.strip(), confirm or "", current.version)
    after = await service.mode_setting()
    note = (
        "Reale Schnittstellen sind weiterhin aus – einschalten im Fenster „Schnittstellen“."
        if target == OperationMode.REAL
        else "Alle realen Schnittstellen wurden automatisch ausgeschaltet."
    )
    return f"Betriebsmodus jetzt: {MODE_LABEL[after.value]}. {note}"


async def set_mode_command(mode: str | None, reason: str | None, confirm: str | None) -> None:
    settings = get_settings()
    db = Database(settings)
    bus = create_bus(settings.redis_url)  # with Redis every connected client sees the change live
    try:
        async with db.sessionmaker() as session:
            print(await change_mode(UnitOfWork(session, bus, CONSOLE_ACTOR), mode, reason, confirm))
    finally:
        await bus.stop()
        await db.dispose()


async def create_user(username: str, display_name: str, role: str, password: str | None) -> None:
    async def run(uow: UnitOfWork) -> None:
        s = uow.session
        role_obj = await s.scalar(select(Role).where(Role.key == role))
        if role_obj is None:
            raise SystemExit(f"Unbekannte Rolle: {role}")
        pw = password or generate_initial_password(username=username)
        validate_password_policy(pw, get_settings(), username=username)
        user = User(
            username=username.lower(),
            display_name=display_name,
            password_hash=hash_password(pw),
            must_change_password=True,
            roles=[role_obj],
        )
        s.add(user)
        await s.flush()
        uow.audit("create", "user", user.id, f"Benutzer {username} per CLI angelegt")
        await uow.commit()
        print(f"Benutzer {username} angelegt." + ("" if password else f" Initialpasswort: {pw}"))

    await _with_uow(run)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ils-admin", description="ILS-Sim Server-Verwaltung")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap", help="Katalog, Rollen und ersten Administrator anlegen")
    b.add_argument("--admin-username", default="admin")
    b.add_argument("--admin-password", default=os.environ.get("ILS_BOOTSTRAP_ADMIN_PASSWORD"))
    d = sub.add_parser("seed-demo", help="Demo-Leitstelle und Demo-Benutzer anlegen")
    d.add_argument("--password", default=os.environ.get("ILS_DEMO_PASSWORD", "Demo-Passwort-2026!"))
    d.add_argument(
        "--allow-production",
        action="store_true",
        help="auch bei ILS_ENVIRONMENT=production (nur reine Test- und Schulungsserver)",
    )
    r = sub.add_parser("reset-data", help="Alle Daten außer Benutzern, Rollen und Einstellungen löschen")
    r.add_argument("--confirm", help="Bestätigungswort ALLES-LOESCHEN")
    r.add_argument("--dry-run", action="store_true", help="nur anzeigen, was gelöscht würde")
    r.add_argument("--include-audit-log", action="store_true", help="auch das Änderungsprotokoll leeren")
    m = sub.add_parser("set-mode", help="Betriebsmodus anzeigen oder umschalten (simulation | real)")
    m.add_argument("mode", nargs="?", choices=["simulation", "real"])
    m.add_argument("--reason", help="Begründung (wird protokolliert)")
    m.add_argument("--confirm", help="beim Wechsel in den Echtbetrieb: ECHTBETRIEB")
    c = sub.add_parser("create-user", help="Benutzer anlegen")
    c.add_argument("username")
    c.add_argument("display_name")
    c.add_argument("--role", default="dispatcher")
    c.add_argument("--password")
    sub.add_parser("generate-key", help="Neuen Verschlüsselungsschlüssel erzeugen")
    sub.add_parser("generate-jwt-secret", help="Neues JWT-Secret erzeugen")
    args = parser.parse_args(argv)
    try:
        _dispatch(args)
    except AppError as exc:
        sys.exit(f"Fehler: {exc.message}")


def _dispatch(args: argparse.Namespace) -> None:
    if args.cmd == "generate-key":
        print(SecretBox.generate_key())
    elif args.cmd == "generate-jwt-secret":
        print(secrets.token_urlsafe(48))
    elif args.cmd == "bootstrap":
        asyncio.run(bootstrap(args.admin_username, args.admin_password))
    elif args.cmd == "seed-demo":
        if get_settings().is_production and not args.allow_production:
            sys.exit(
                "seed-demo ist in der Produktionsumgebung deaktiviert. Nur auf einem reinen Test- "
                "oder Schulungsserver: ils-admin seed-demo --allow-production"
            )
        if get_settings().is_production:
            print("WARNUNG: Demodaten werden auf einem Server im Produktionsmodus angelegt.")
        asyncio.run(seed_demo(args.password))
    elif args.cmd == "reset-data":
        asyncio.run(reset_data_command(args.confirm, args.dry_run, args.include_audit_log))
    elif args.cmd == "set-mode":
        asyncio.run(set_mode_command(args.mode, args.reason, args.confirm))
    elif args.cmd == "create-user":
        asyncio.run(create_user(args.username, args.display_name, args.role, args.password))


if __name__ == "__main__":
    main()
