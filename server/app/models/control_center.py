from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin, utcnow


class ControlCenter(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """A control centre (Leitstelle) – the tenant boundary for operational data."""

    __tablename__ = "control_centers"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(String(300))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ControlCenterLink(UUIDPrimaryKeyMixin, Base):
    """Directed relation between two control centres (neighbour, backup, cooperation)."""

    __tablename__ = "control_center_links"
    __table_args__ = (
        UniqueConstraint("from_control_center_id", "to_control_center_id", name="uq_cc_links_pair"),
        CheckConstraint("from_control_center_id <> to_control_center_id", name="no_self_link"),
    )

    from_control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="CASCADE"), index=True
    )
    to_control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # neighbor | backup | cooperation
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    from_control_center: Mapped[ControlCenter] = relationship(
        foreign_keys=[from_control_center_id], lazy="selectin"
    )
    to_control_center: Mapped[ControlCenter] = relationship(
        foreign_keys=[to_control_center_id], lazy="selectin"
    )


class ControlCenterArea(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """Area of responsibility (Zuständigkeitsbereich): GeoJSON polygon and/or municipality key."""

    __tablename__ = "control_center_areas"
    __table_args__ = (
        CheckConstraint("geometry IS NOT NULL OR municipality_key IS NOT NULL", name="geometry_or_key"),
    )

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    municipality_key: Mapped[str | None] = mapped_column(String(12))  # Amtlicher Gemeindeschlüssel
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # GeoJSON Polygon/MultiPolygon
    # Lower value wins when areas overlap (primary vs. secondary responsibility).
    priority: Mapped[int] = mapped_column(Integer, default=100)
    description: Mapped[str | None] = mapped_column(Text)

    control_center: Mapped[ControlCenter] = relationship(lazy="selectin")
