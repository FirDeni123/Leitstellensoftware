from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel


class ClientInfo(ApiModel):
    client_name: str | None = Field(default=None, max_length=120)
    client_version: str | None = Field(default=None, max_length=40)
    workstation: str | None = Field(default=None, max_length=120, description="Rechner-/Platzname")


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    client: ClientInfo = Field(default_factory=ClientInfo)


class RefreshRequest(ApiModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class ChangePasswordRequest(ApiModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class ControlCenterRef(ApiModel):
    id: uuid.UUID
    code: str
    name: str


class MeResponse(ApiModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    must_change_password: bool
    roles: list[str]
    permissions: list[str]
    control_centers: list[ControlCenterRef]
    all_control_centers: bool = Field(description="True bei system.admin: Zugriff auf alle Leitstellen")
    session_id: uuid.UUID


class TokenResponse(ApiModel):
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 (OAuth token type, not a secret)
    user: MeResponse
