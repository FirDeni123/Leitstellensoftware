"""FastAPI dependencies: database session, unit of work, authentication, permissions."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.permissions import P
from app.core.security import decode_access_token
from app.models import AuthSession, User
from app.realtime.bus import EventBus
from app.services.uow import Actor, UnitOfWork

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.sessionmaker() as session:
        yield session


def get_bus(request: Request) -> EventBus:
    return request.app.state.bus


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def client_ip(request: Request, settings: Settings) -> str | None:
    """Client IP, honouring X-Forwarded-For only for the configured number of proxies."""
    if settings.trusted_proxy_count > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = [h.strip() for h in forwarded.split(",") if h.strip()]
            if len(hops) >= settings.trusted_proxy_count:
                return hops[-settings.trusted_proxy_count]
    return request.client.host if request.client else None


@dataclass(slots=True)
class AuthContext:
    user: User
    session_id: uuid.UUID
    permissions: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return P.SYSTEM_ADMIN.value in self.permissions

    def has(self, permission: P | str) -> bool:
        return str(permission) in self.permissions

    def control_center_ids(self) -> set[uuid.UUID]:
        return {cc.id for cc in self.user.control_centers}

    def can_access_control_center(self, cc_id: uuid.UUID) -> bool:
        return self.is_admin or cc_id in self.control_center_ids()


async def authenticate_token(session: AsyncSession, settings: Settings, token: str) -> AuthContext:
    """Shared by HTTP and WebSocket authentication."""
    claims = decode_access_token(settings, token)
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Benutzerkonto ist deaktiviert")
    if user.token_version != claims.token_version:
        raise AuthenticationError(
            "Sitzung ungültig – bitte neu anmelden", details={"reason": "token_revoked"}
        )
    auth_session = await session.get(AuthSession, claims.session_id)
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= datetime.now(UTC)
    ):
        raise AuthenticationError(
            "Sitzung beendet – bitte neu anmelden", details={"reason": "session_revoked"}
        )
    return AuthContext(
        user=user, session_id=claims.session_id, permissions=frozenset(user.effective_permissions())
    )


async def get_auth_allow_password_change(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthContext:
    """Authenticated user – also allowed while a password change is pending."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError()
    return await authenticate_token(session, settings, credentials.credentials)


async def get_auth(
    auth: Annotated[AuthContext, Depends(get_auth_allow_password_change)],
) -> AuthContext:
    if auth.user.must_change_password:
        raise PermissionDeniedError(
            "Bitte zuerst das Passwort ändern", details={"reason": "password_change_required"}
        )
    return auth


AuthDep = Annotated[AuthContext, Depends(get_auth)]


def require(*permissions: P) -> Callable[..., Coroutine[Any, Any, AuthContext]]:
    """Dependency factory: the user must hold *all* given permissions."""

    async def _dep(auth: AuthDep) -> AuthContext:
        missing = [p.value for p in permissions if p.value not in auth.permissions]
        if missing:
            raise PermissionDeniedError(details={"missing_permissions": missing})
        return auth

    return _dep


async def get_uow(session: SessionDep, request: Request) -> UnitOfWork:
    return UnitOfWork(session, request.app.state.bus)


def uow_for(auth: AuthContext, uow: UnitOfWork) -> UnitOfWork:
    uow.actor = Actor.of(auth.user)
    return uow


UowDep = Annotated[UnitOfWork, Depends(get_uow)]
