"""User administration: CRUD, roles, permission overrides, control centre assignment."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.permissions import ALL_PERMISSIONS, P
from app.core.security import generate_initial_password, hash_password, validate_password_policy
from app.models import AuthSession, ControlCenter, Role, User, UserPermissionOverride
from app.schemas.auth import ControlCenterRef
from app.schemas.users import (
    PermissionOverrideIn,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services.uow import UnitOfWork, check_version, diff

USERS_CHANNEL_PERMISSION = P.USERS_READ.value


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        locked_until=user.locked_until,
        last_login_at=user.last_login_at,
        roles=sorted(r.key for r in user.roles),
        control_centers=[ControlCenterRef.model_validate(cc) for cc in user.control_centers],
        permission_overrides=[
            PermissionOverrideIn(permission_code=o.permission_code, effect=o.effect)
            for o in sorted(user.permission_overrides, key=lambda o: o.permission_code)
        ],
        effective_permissions=sorted(user.effective_permissions()),
        created_at=user.created_at,
        updated_at=user.updated_at,
        version=user.version,
    )


def _snapshot(user: User) -> dict[str, Any]:
    return {
        "display_name": user.display_name,
        "email": user.email,
        "is_active": user.is_active,
        "roles": sorted(r.key for r in user.roles),
        "control_centers": sorted(cc.code for cc in user.control_centers),
        "overrides": sorted(f"{o.effect.value}:{o.permission_code}" for o in user.permission_overrides),
    }


class UserService:
    def __init__(self, uow: UnitOfWork, settings: Settings) -> None:
        self.uow = uow
        self.s = uow.session
        self.settings = settings

    async def list(
        self,
        *,
        q: str | None,
        active: bool | None,
        control_center_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        stmt = select(User)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(func.lower(User.username).like(like), func.lower(User.display_name).like(like))
            )
        if active is not None:
            stmt = stmt.where(User.is_active.is_(active))
        if control_center_id:
            stmt = stmt.where(User.control_centers.any(ControlCenter.id == control_center_id))
        total = await self.s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await self.s.scalars(stmt.order_by(User.username).limit(limit).offset(offset))).all()
        return list(rows), total

    async def get(self, user_id: uuid.UUID) -> User:
        user = await self.s.get(User, user_id)
        if user is None:
            raise NotFoundError("Benutzer nicht gefunden")
        return user

    async def _roles(self, keys: list[str]) -> list[Role]:
        if not keys:
            return []
        roles = list((await self.s.scalars(select(Role).where(Role.key.in_(keys)))).all())
        unknown = set(keys) - {r.key for r in roles}
        if unknown:
            raise ValidationFailedError("Unbekannte Rolle(n)", details={"roles": sorted(unknown)})
        return roles

    async def _control_centers(self, ids: list[uuid.UUID]) -> list[ControlCenter]:
        if not ids:
            return []
        ccs = list((await self.s.scalars(select(ControlCenter).where(ControlCenter.id.in_(ids)))).all())
        if len(ccs) != len(set(ids)):
            raise ValidationFailedError("Unbekannte Leitstelle(n)")
        return ccs

    @staticmethod
    def _overrides(items: list[PermissionOverrideIn]) -> list[UserPermissionOverride]:
        codes = [o.permission_code for o in items]
        unknown = set(codes) - ALL_PERMISSIONS
        if unknown:
            raise ValidationFailedError(
                "Unbekannte Berechtigung(en)", details={"permissions": sorted(unknown)}
            )
        if len(codes) != len(set(codes)):
            raise ValidationFailedError("Berechtigung mehrfach angegeben")
        return [UserPermissionOverride(permission_code=o.permission_code, effect=o.effect) for o in items]

    async def create(self, data: UserCreate) -> tuple[User, str | None]:
        generated = None
        password = data.password
        if not password:
            password = generated = generate_initial_password(username=data.username)
        validate_password_policy(password, self.settings, username=data.username)
        user = User(
            username=data.username,
            display_name=data.display_name,
            email=data.email,
            password_hash=hash_password(password),
            must_change_password=True,
            roles=await self._roles(data.roles),
            control_centers=await self._control_centers(data.control_center_ids),
            permission_overrides=self._overrides(data.permission_overrides),
        )
        self.s.add(user)
        try:
            await self.s.flush()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError(f"Benutzername '{data.username}' ist bereits vergeben") from exc
        self.uow.audit(
            "create", "user", user.id, f"Benutzer {user.username} angelegt", changes=diff({}, _snapshot(user))
        )
        self._emit_changed(user, "created")
        await self.uow.commit()
        return user, generated

    async def update(self, user_id: uuid.UUID, data: UserUpdate) -> User:
        user = await self.get(user_id)
        check_version(user, data.expected_version, "Der Benutzer")
        before = _snapshot(user)
        if data.display_name is not None:
            user.display_name = data.display_name
        if "email" in data.model_fields_set:
            user.email = data.email
        security_relevant = False
        if data.roles is not None:
            user.roles = await self._roles(data.roles)
            security_relevant = True
        if data.control_center_ids is not None:
            user.control_centers = await self._control_centers(data.control_center_ids)
            security_relevant = True
        if data.permission_overrides is not None:
            user.permission_overrides = self._overrides(data.permission_overrides)
            security_relevant = True
        changes = diff(before, _snapshot(user))
        if not changes:
            return user
        # Touch the row so the version also increments for relationship-only changes.
        user.updated_at = datetime.now(UTC)
        await self.s.flush()
        await self._ensure_admin_remains()
        self.uow.audit("update", "user", user.id, f"Benutzer {user.username} geändert", changes=changes)
        self._emit_changed(user, "updated")
        if security_relevant:
            # Open WebSocket connections reconnect and pick up the new permissions.
            self.uow.control("disconnect_user", {"user_id": str(user.id), "code": 4002})
        await self.uow.commit()
        return user

    async def set_active(
        self, user_id: uuid.UUID, is_active: bool, expected_version: int, actor_id: uuid.UUID
    ) -> User:
        user = await self.get(user_id)
        check_version(user, expected_version, "Der Benutzer")
        if user.id == actor_id and not is_active:
            raise ValidationFailedError("Das eigene Konto kann nicht deaktiviert werden")
        if user.is_active == is_active:
            return user
        user.is_active = is_active
        if not is_active:
            user.token_version += 1
            await self._revoke_sessions(user.id, "deactivated")
            self.uow.control(
                "disconnect_user", {"user_id": str(user.id), "code": 4001, "reason": "deactivated"}
            )
        else:
            user.locked_until = None
            user.failed_login_count = 0
        await self.s.flush()
        await self._ensure_admin_remains()
        verb = "aktiviert" if is_active else "deaktiviert"
        self.uow.audit(
            "activate" if is_active else "deactivate", "user", user.id, f"Benutzer {user.username} {verb}"
        )
        self._emit_changed(user, "updated")
        await self.uow.commit()
        return user

    async def reset_password(
        self, user_id: uuid.UUID, new_password: str | None, expected_version: int
    ) -> tuple[User, str | None]:
        user = await self.get(user_id)
        check_version(user, expected_version, "Der Benutzer")
        generated = None
        if not new_password:
            new_password = generated = generate_initial_password(username=user.username)
        validate_password_policy(new_password, self.settings, username=user.username)
        user.password_hash = hash_password(new_password)
        user.must_change_password = True
        user.password_changed_at = datetime.now(UTC)
        user.locked_until = None
        user.failed_login_count = 0
        user.token_version += 1
        await self._revoke_sessions(user.id, "password_reset")
        self.uow.control(
            "disconnect_user", {"user_id": str(user.id), "code": 4001, "reason": "password reset"}
        )
        self.uow.audit("password_reset", "user", user.id, f"Passwort von {user.username} zurückgesetzt")
        self._emit_changed(user, "updated")
        await self.uow.commit()
        return user, generated

    async def unlock(self, user_id: uuid.UUID) -> User:
        user = await self.get(user_id)
        user.locked_until = None
        user.failed_login_count = 0
        self.uow.audit("unlock", "user", user.id, f"Sperre von {user.username} aufgehoben")
        self._emit_changed(user, "updated")
        await self.uow.commit()
        return user

    async def _revoke_sessions(self, user_id: uuid.UUID, reason: str) -> None:
        await self.s.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoke_reason=reason)
        )

    async def _ensure_admin_remains(self) -> None:
        """Safety net: the system must always keep at least one active administrator."""
        users = (await self.s.scalars(select(User).where(User.is_active.is_(True)))).all()
        if not any(P.SYSTEM_ADMIN.value in u.effective_permissions() for u in users):
            await self.uow.rollback()
            raise ValidationFailedError("Es muss mindestens ein aktiver Administrator verbleiben")

    def _emit_changed(self, user: User, action: str) -> None:
        self.uow.emit(
            f"user.{action}",
            {"id": str(user.id), "username": user.username},
            required_permission=USERS_CHANNEL_PERMISSION,
        )
        self.uow.emit("me.changed", {"id": str(user.id)}, channels=[f"user:{user.id}"])
