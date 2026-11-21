from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel, VersionedUpdate


class ControlCenterBase(ApiModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    address: str | None = Field(default=None, max_length=300)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_active: bool = True


class ControlCenterCreate(ControlCenterBase):
    code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{1,31}$", description="Kurzkennung, z. B. ILS-NORD")


class ControlCenterUpdate(VersionedUpdate):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    address: str | None = Field(default=None, max_length=300)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    is_active: bool | None = None


class ControlCenterOut(ControlCenterBase):
    id: uuid.UUID
    code: str
    created_at: datetime
    updated_at: datetime
    version: int
