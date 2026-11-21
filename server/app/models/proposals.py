"""Einsatzmittelvorschlag (Phase 5): per-control-centre settings and stored proposals.

A proposal is a decision aid. Storing it (inputs + result + reasons) makes later reviews
possible ("why was this vehicle proposed?"). Accepting a proposal only assigns vehicles –
it never alarms.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin, utcnow


class ProposalSettings(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """Weights and rules of the proposal per control centre (validated by ``ProposalSettingsData``)."""

    __tablename__ = "proposal_settings"

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="CASCADE"), unique=True
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_by_name: Mapped[str | None] = mapped_column(String(200))


class Proposal(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "proposals"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="RESTRICT"), index=True
    )
    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    computed_at: Mapped[datetime] = mapped_column(default=utcnow)
    computed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    computed_by_name: Mapped[str] = mapped_column(String(200))
    stage: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    accepted_vehicle_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    accepted_at: Mapped[datetime | None] = mapped_column()
    accepted_by_name: Mapped[str | None] = mapped_column(String(200))
