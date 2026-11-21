from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.models.settings import OperationMode
from app.schemas.common import ApiModel


class ModuleStatus(ApiModel):
    key: str
    name: str
    phase: int
    status: Literal["available", "partial", "planned"]
    note: str | None = None


class SystemInfo(ApiModel):
    product: str
    version: str
    environment: str
    server_time: datetime
    operation_mode: OperationMode
    realtime_backend: Literal["memory", "redis"]
    modules: list[ModuleStatus]


class OperationModeUpdate(ApiModel):
    mode: OperationMode
    reason: str = Field(min_length=5, max_length=500)
    confirmation: str = Field(description="Muss beim Wechsel in den Echtbetrieb 'ECHTBETRIEB' lauten")
    expected_version: int = Field(ge=1)


class OperationModeOut(ApiModel):
    mode: OperationMode
    version: int
    updated_at: datetime


class AuditEntryOut(ApiModel):
    id: int
    ts: datetime
    actor_user_id: uuid.UUID | None
    actor_name: str
    action: str
    entity_type: str
    entity_id: str | None
    control_center_id: uuid.UUID | None
    summary: str
    changes: dict[str, Any] | None
    request_id: str | None


class AuditPage(ApiModel):
    items: list[AuditEntryOut]
    next_before_id: int | None


class LayoutOut(ApiModel):
    workstation: str
    layout: dict[str, Any]
    version: int
    updated_at: datetime


class LayoutPut(ApiModel):
    layout: dict[str, Any]
    expected_version: int | None = Field(default=None, description="None beim ersten Speichern")
