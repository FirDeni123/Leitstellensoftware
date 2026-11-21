"""Administrative command line (``ils-admin``).

Commands::

    ils-admin bootstrap           Permission catalogue + default roles + first administrator
    ils-admin seed-demo           Sample control centre and users for development/training
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
from app.realtime.bus import InMemoryEventBus
from app.services.reference_data import ensure_reference_data
from app.services.role_service import sync_catalogue
from app.services.uow import UnitOfWork

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
            if await s.scalar(select(User).where(User.username == username)):
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
        if get_settings().is_production:
            sys.exit("seed-demo ist in der Produktionsumgebung deaktiviert")
        asyncio.run(seed_demo(args.password))
    elif args.cmd == "create-user":
        asyncio.run(create_user(args.username, args.display_name, args.role, args.password))


if __name__ == "__main__":
    main()
