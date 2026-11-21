from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin, utcnow


class OperationMode(StrEnum):
    """System-wide operation mode. Real interfaces only work in ``REAL`` mode."""

    SIMULATION = "simulation"
    REAL = "real"


class SystemSetting(VersionedMixin, Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class UserLayout(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """Per-user, per-workstation window layout of the Windows client."""

    __tablename__ = "user_layouts"
    __table_args__ = (UniqueConstraint("user_id", "workstation"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    workstation: Mapped[str] = mapped_column(String(32))
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB)
