"""Roles and the permission catalogue."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import exists, select, text
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.permissions import ALL_PERMISSIONS, CATALOGUE, DEFAULT_ROLES, P
from app.models import Permission, Role, User, user_roles
from app.schemas.users import RoleCreate, RoleOut, RoleUpdate
from app.services.uow import UnitOfWork, check_version, diff


def role_out(role: Role) -> RoleOut:
    return RoleOut(
        id=role.id,
        key=role.key,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=sorted(p.code for p in role.permissions),
        version=role.version,
    )


class RoleService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self.s = uow.session

    async def list(self) -> list[Role]:
        return list((await self.s.scalars(select(Role).order_by(Role.name))).all())

    async def permissions(self) -> list[Permission]:
        return list(
            (await self.s.scalars(select(Permission).order_by(Permission.area, Permission.code))).all()
        )

    async def get(self, role_id: uuid.UUID) -> Role:
        role = await self.s.get(Role, role_id)
        if role is None:
            raise NotFoundError("Rolle nicht gefunden")
        return role

    async def _permissions(self, codes: list[str]) -> list[Permission]:
        unknown = set(codes) - ALL_PERMISSIONS
        if unknown:
            raise ValidationFailedError(
                "Unbekannte Berechtigung(en)", details={"permissions": sorted(unknown)}
            )
        if not codes:
            return []
        return list((await self.s.scalars(select(Permission).where(Permission.code.in_(codes)))).all())

    async def create(self, data: RoleCreate) -> Role:
        role = Role(
            key=data.key,
            name=data.name,
            description=data.description,
            is_system=False,
            permissions=await self._permissions(data.permissions),
        )
        self.s.add(role)
        try:
            await self.s.flush()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError(f"Rollen-Schlüssel '{data.key}' existiert bereits") from exc
        self.uow.audit(
            "create",
            "role",
            role.id,
            f"Rolle {role.name} angelegt",
            changes={"permissions": {"old": None, "new": sorted(data.permissions)}},
        )
        self.uow.emit("role.changed", {"id": str(role.id)})
        await self.uow.commit()
        return role

    async def update(self, role_id: uuid.UUID, data: RoleUpdate) -> Role:
        role = await self.get(role_id)
        check_version(role, data.expected_version, "Die Rolle")
        before = {
            "name": role.name,
            "description": role.description,
            "permissions": sorted(p.code for p in role.permissions),
        }
        if data.name is not None:
            role.name = data.name
        if "description" in data.model_fields_set:
            role.description = data.description
        if data.permissions is not None:
            if role.key == "admin" and P.SYSTEM_ADMIN.value not in data.permissions:
                raise ValidationFailedError(
                    "Der Administrator-Rolle kann 'system.admin' nicht entzogen werden"
                )
            role.permissions = await self._permissions(data.permissions)
        after = {
            "name": role.name,
            "description": role.description,
            "permissions": sorted(p.code for p in role.permissions),
        }
        changes = diff(before, after)
        if not changes:
            return role
        role.updated_at = datetime.now(UTC)
        self.uow.audit("update", "role", role.id, f"Rolle {role.name} geändert", changes=changes)
        self.uow.emit("role.changed", {"id": str(role.id)})
        if "permissions" in changes:
            # All holders of the role reconnect their realtime channel with new permissions.
            holders = (
                await self.s.scalars(select(user_roles.c.user_id).where(user_roles.c.role_id == role.id))
            ).all()
            for uid in holders:
                self.uow.control("disconnect_user", {"user_id": str(uid), "code": 4002})
                self.uow.emit("me.changed", {"id": str(uid)}, channels=[f"user:{uid}"])
        await self.uow.commit()
        return role

    async def delete(self, role_id: uuid.UUID) -> None:
        role = await self.get(role_id)
        if role.is_system:
            raise ValidationFailedError("Systemrollen können nicht gelöscht werden")
        in_use = await self.s.scalar(select(exists().where(user_roles.c.role_id == role.id)))
        if in_use:
            raise ConflictError("Rolle ist noch Benutzern zugewiesen")
        self.uow.audit("delete", "role", role.id, f"Rolle {role.name} gelöscht")
        await self.s.delete(role)
        self.uow.emit("role.changed", {"id": str(role.id), "deleted": True})
        await self.uow.commit()


async def sync_catalogue(uow: UnitOfWork) -> dict[str, int]:
    """Synchronise the permission catalogue and create missing default roles (idempotent)."""
    s = uow.session
    # Several API workers may start at the same time: serialise the synchronisation.
    await s.execute(text("SELECT pg_advisory_xact_lock(470011)"))
    existing = {p.code: p for p in (await s.scalars(select(Permission))).all()}
    added = 0
    new_codes: set[str] = set()
    for info in CATALOGUE:
        perm = existing.get(info.code.value)
        if perm is None:
            s.add(Permission(code=info.code.value, area=info.area, description=info.description))
            added += 1
            new_codes.add(info.code.value)
        else:
            perm.area, perm.description = info.area, info.description
    await s.flush()
    all_perms = {p.code: p for p in (await s.scalars(select(Permission))).all()}
    roles_created = 0
    for definition in DEFAULT_ROLES:
        role = await s.scalar(select(Role).where(Role.key == definition.key))
        if role is None:
            s.add(
                Role(
                    key=definition.key,
                    name=definition.name,
                    description=definition.description,
                    is_system=True,
                    permissions=[all_perms[c] for c in sorted(definition.permissions)],
                )
            )
            roles_created += 1
        else:
            # Newly introduced permissions are granted once to the system roles whose default
            # definition contains them (existing, possibly edited assignments stay untouched).
            # The administrator role always holds every permission.
            have = {p.code for p in role.permissions}
            wanted = (
                definition.permissions if definition.key == "admin" else definition.permissions & new_codes
            )
            missing = [all_perms[c] for c in sorted(wanted) if c not in have]
            if missing:
                role.permissions = [*role.permissions, *missing]
    if added or roles_created:
        uow.audit(
            "sync",
            "permission_catalogue",
            None,
            f"Berechtigungskatalog synchronisiert ({added} neu, {roles_created} Rollen angelegt)",
        )
    await uow.commit()
    return {"permissions_added": added, "roles_created": roles_created}


async def user_count(uow: UnitOfWork) -> int:
    from sqlalchemy import func

    return await uow.session.scalar(select(func.count(User.id))) or 0
