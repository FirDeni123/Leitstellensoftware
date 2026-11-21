from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.models.user import PermissionEffect
from app.schemas.auth import ControlCenterRef
from app.schemas.common import ApiModel, VersionedUpdate

_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


def _normalise_username(value: str) -> str:
    value = value.strip().lower()
    if not _USERNAME_RE.match(value):
        raise ValueError("Benutzername: 2–64 Zeichen, nur a–z, 0–9, Punkt, Bindestrich, Unterstrich")
    return value


class PermissionOut(ApiModel):
    code: str
    area: str
    description: str


class RoleOut(ApiModel):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    is_system: bool
    permissions: list[str]
    version: int


class RoleCreate(ApiModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(VersionedUpdate):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    permissions: list[str] | None = None


class PermissionOverrideIn(ApiModel):
    permission_code: str
    effect: PermissionEffect


class UserOut(ApiModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    is_active: bool
    must_change_password: bool
    locked_until: datetime | None
    last_login_at: datetime | None
    roles: list[str] = Field(description="Rollen-Schlüssel")
    control_centers: list[ControlCenterRef]
    permission_overrides: list[PermissionOverrideIn]
    effective_permissions: list[str]
    created_at: datetime
    updated_at: datetime
    version: int


class UserCreate(ApiModel):
    username: str
    display_name: str = Field(min_length=2, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    password: str | None = Field(
        default=None, description="Leer lassen, um ein Initialpasswort generieren zu lassen"
    )
    roles: list[str] = Field(default_factory=list)
    control_center_ids: list[uuid.UUID] = Field(default_factory=list)
    permission_overrides: list[PermissionOverrideIn] = Field(default_factory=list)

    _norm = field_validator("username")(_normalise_username)


class UserUpdate(VersionedUpdate):
    display_name: str | None = Field(default=None, min_length=2, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    roles: list[str] | None = None
    control_center_ids: list[uuid.UUID] | None = None
    permission_overrides: list[PermissionOverrideIn] | None = None


class UserActiveUpdate(VersionedUpdate):
    is_active: bool


class PasswordResetRequest(VersionedUpdate):
    new_password: str | None = Field(default=None, description="Leer = Passwort generieren")


class UserCreatedResponse(ApiModel):
    user: UserOut
    initial_password: str | None = Field(
        default=None, description="Nur einmalig sichtbar, wenn das Passwort generiert wurde"
    )


class LoginEventOut(ApiModel):
    id: int
    ts: datetime
    username: str
    user_id: uuid.UUID | None
    success: bool
    event: str
    reason: str | None
    ip_address: str | None
    client_name: str | None
    workstation: str | None
