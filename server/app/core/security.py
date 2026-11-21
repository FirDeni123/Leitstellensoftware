"""Password hashing, JWT access tokens and opaque refresh tokens.

* Passwords: Argon2id (argon2-cffi defaults, RFC 9106 low-memory profile).
* Access tokens: short-lived signed JWT (HS256). They carry the user id, the session
  (refresh-token family) id and the user's ``token_version`` so that deactivation or a
  password change invalidates all outstanding tokens immediately.
* Refresh tokens: random 256-bit opaque strings. Only their SHA-256 hash is stored.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings
from app.core.errors import AuthenticationError, ValidationFailedError

_hasher = PasswordHasher()
# Pre-computed hash used to equalise timing when the username does not exist.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def validate_password_policy(password: str, settings: Settings, *, username: str | None = None) -> None:
    problems: list[str] = []
    if len(password) < settings.password_min_length:
        problems.append(f"mindestens {settings.password_min_length} Zeichen")
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        problems.append("mindestens drei Zeichenarten (Klein-, Großbuchstaben, Ziffern, Sonderzeichen)")
    if username and len(username) >= 3 and username.lower() in password.lower():
        problems.append("darf den Benutzernamen nicht enthalten")
    if problems:
        raise ValidationFailedError("Passwort erfüllt die Richtlinie nicht: " + ", ".join(problems))


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    token_version: int
    expires_at: datetime


def create_access_token(
    settings: Settings, *, user_id: uuid.UUID, session_id: uuid.UUID, token_version: int
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_minutes)
    payload = {
        "iss": settings.jwt_issuer,
        "sub": str(user_id),
        "sid": str(session_id),
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256"), expires


def decode_access_token(settings: Settings, token: str) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "sub", "sid", "tv", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Sitzung abgelaufen", details={"reason": "token_expired"}) from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Ungültiges Token") from exc
    if payload.get("typ") != "access":
        raise AuthenticationError("Ungültiges Token")
    try:
        return AccessTokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            session_id=uuid.UUID(payload["sid"]),
            token_version=int(payload["tv"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (ValueError, TypeError) as exc:
        raise AuthenticationError("Ungültiges Token") from exc


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_initial_password(length: int = 16, *, username: str | None = None) -> str:
    """Random password satisfying the policy (used for bootstrap and admin resets)."""
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        candidate = (
            "".join(secrets.choice(alphabet) for _ in range(length - 2)) + "-" + secrets.choice("!#%+")
        )
        if (
            any(c.islower() for c in candidate)
            and any(c.isupper() for c in candidate)
            and any(c.isdigit() for c in candidate)
            and not (username and username.lower() in candidate.lower())
        ):
            return candidate
