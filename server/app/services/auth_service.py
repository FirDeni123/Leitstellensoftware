"""Login, token refresh (with rotation + reuse detection), logout, password change."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.errors import AccountLockedError, AuthenticationError
from app.core.logging import log_ctx
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    validate_password_policy,
    verify_password,
)
from app.models import AuthSession, LoginEvent, RefreshToken, User
from app.schemas.auth import ClientInfo
from app.services.uow import Actor, UnitOfWork

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS = "Benutzername oder Passwort falsch"


@dataclass(slots=True)
class IssuedTokens:
    user: User
    session: AuthSession
    access_token: str
    access_expires_at: datetime
    refresh_token: str


class AuthService:
    def __init__(self, uow: UnitOfWork, settings: Settings) -> None:
        self.uow = uow
        self.s = uow.session
        self.settings = settings

    # ------------------------------------------------------------------------------ login
    async def login(self, username: str, password: str, client: ClientInfo, ip: str | None) -> IssuedTokens:
        username = username.strip().lower()
        now = datetime.now(UTC)
        user = await self.s.scalar(select(User).where(User.username == username))

        def log(success: bool, event: str, reason: str | None = None) -> None:
            self.s.add(
                LoginEvent(
                    username=username[:64],
                    user_id=user.id if user else None,
                    success=success,
                    event=event,
                    reason=reason,
                    ip_address=ip,
                    client_name=client.client_name,
                    workstation=client.workstation,
                )
            )

        if user is None:
            verify_password(password, None)  # equalise timing
            log(False, "login", "unknown_user")
            await self.uow.commit()
            raise AuthenticationError(INVALID_CREDENTIALS)

        if user.locked_until and user.locked_until > now:
            log(False, "login", "locked")
            await self.uow.commit()
            raise AccountLockedError(
                "Konto nach mehreren Fehlversuchen vorübergehend gesperrt",
                details={"locked_until": user.locked_until.isoformat()},
            )

        if not verify_password(password, user.password_hash):
            user.failed_login_count += 1
            reason = "wrong_password"
            if user.failed_login_count >= self.settings.max_failed_logins:
                user.locked_until = now + timedelta(minutes=self.settings.lockout_minutes)
                user.failed_login_count = 0
                reason = "wrong_password_locked"
                logger.warning("Konto gesperrt", extra=log_ctx(username=username, ip=ip))
            log(False, "login", reason)
            await self.uow.commit()
            raise AuthenticationError(INVALID_CREDENTIALS)

        if not user.is_active:
            log(False, "login", "inactive")
            await self.uow.commit()
            raise AuthenticationError("Benutzerkonto ist deaktiviert")

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        session = AuthSession(
            user_id=user.id,
            expires_at=now + timedelta(days=self.settings.refresh_token_days),
            client_name=client.client_name,
            client_version=client.client_version,
            workstation=client.workstation,
            ip_address=ip,
        )
        self.s.add(session)
        await self.s.flush()
        tokens = self._issue(user, session)
        log(True, "login")
        await self.uow.commit()
        logger.info("Anmeldung erfolgreich", extra=log_ctx(user=username, ip=ip, sid=str(session.id)))
        return tokens

    def _issue(self, user: User, session: AuthSession) -> IssuedTokens:
        refresh = generate_refresh_token()
        self.s.add(RefreshToken(session_id=session.id, token_hash=hash_token(refresh)))
        access, expires = create_access_token(
            self.settings, user_id=user.id, session_id=session.id, token_version=user.token_version
        )
        return IssuedTokens(user, session, access, expires, refresh)

    # ---------------------------------------------------------------------------- refresh
    async def refresh(self, refresh_token: str, ip: str | None) -> IssuedTokens:
        now = datetime.now(UTC)
        token = await self.s.scalar(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(refresh_token))
            .options(selectinload(RefreshToken.session))
            .with_for_update()
        )
        if token is None:
            raise AuthenticationError("Sitzung ungültig – bitte neu anmelden")
        session = token.session
        user = await self.s.get(User, session.user_id)

        if token.used_at is not None:
            # A consumed token was presented again: token theft or a replay. Kill the session.
            if session.revoked_at is None:
                session.revoked_at = now
                session.revoke_reason = "refresh_token_reuse"
            self.s.add(
                LoginEvent(
                    username=user.username if user else "?",
                    user_id=session.user_id,
                    success=False,
                    event="refresh_reuse",
                    reason="Wiederverwendung eines Refresh-Tokens – Sitzung beendet",
                    ip_address=ip,
                    client_name=session.client_name,
                    workstation=session.workstation,
                )
            )
            self.uow.control("disconnect_session", {"session_id": str(session.id)})
            await self.uow.commit()
            logger.warning("Refresh-Token wiederverwendet", extra=log_ctx(sid=str(session.id), ip=ip))
            raise AuthenticationError("Sitzung ungültig – bitte neu anmelden")

        if session.revoked_at is not None or session.expires_at <= now:
            raise AuthenticationError("Sitzung abgelaufen – bitte neu anmelden")
        if user is None or not user.is_active:
            raise AuthenticationError("Benutzerkonto ist deaktiviert")

        token.used_at = now
        session.last_used_at = now
        session.ip_address = ip or session.ip_address
        tokens = self._issue(user, session)
        await self.uow.commit()
        return tokens

    # ----------------------------------------------------------------------------- logout
    async def logout(self, user: User, session_id: uuid.UUID, ip: str | None) -> None:
        session = await self.s.get(AuthSession, session_id)
        if session and session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            session.revoke_reason = "logout"
        self.s.add(
            LoginEvent(
                username=user.username,
                user_id=user.id,
                success=True,
                event="logout",
                ip_address=ip,
                client_name=session.client_name if session else None,
                workstation=session.workstation if session else None,
            )
        )
        self.uow.control("disconnect_session", {"session_id": str(session_id)})
        await self.uow.commit()

    # -------------------------------------------------------------------- password change
    async def change_password(
        self, user: User, session_id: uuid.UUID, current_password: str, new_password: str
    ) -> IssuedTokens:
        if not verify_password(current_password, user.password_hash):
            raise AuthenticationError("Aktuelles Passwort ist falsch")
        if verify_password(new_password, user.password_hash):
            from app.core.errors import ValidationFailedError

            raise ValidationFailedError("Das neue Passwort muss sich vom bisherigen unterscheiden")
        validate_password_policy(new_password, self.settings, username=user.username)

        now = datetime.now(UTC)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = now
        user.must_change_password = False
        user.token_version += 1
        # End every other session of this user; the current one continues with new tokens.
        await self.s.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.id != session_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoke_reason="password_changed")
        )
        session = await self.s.get(AuthSession, session_id)
        if session is None or session.revoked_at is not None:
            raise AuthenticationError("Sitzung ungültig – bitte neu anmelden")
        uow = self.uow
        uow.actor = Actor.of(user)
        uow.audit("password_change", "user", user.id, f"Passwort von {user.username} geändert")
        uow.control("disconnect_user", {"user_id": str(user.id), "code": 4001, "reason": "password changed"})
        tokens = self._issue(user, session)
        await uow.commit()
        return tokens
