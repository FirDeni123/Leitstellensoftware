"""Operational data (Phase 3): keywords, emergency calls and incidents.

Design notes
* Incident numbers are gapless per control centre and year: a counter row is locked
  (``SELECT … FOR UPDATE``) inside the creating transaction – a rollback releases the number.
* ``incident_events`` is the incident history (Einsatzverlauf). It is append-only; a database
  trigger (migration 0003) rejects UPDATE and DELETE.
* A vehicle can be bound to at most one incident at a time – enforced by a partial unique
  index on ``incident_vehicles(vehicle_id) WHERE released_at IS NULL`` in addition to the
  service-level check.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin, utcnow
from app.models.master_data import Vehicle

# Incident lifecycle (order matters for the client's status bar)
INCIDENT_STATUSES = ("new", "in_progress", "alarmed", "en_route", "on_scene", "finished", "closed")
INCIDENT_TYPES = ("fire", "technical", "ems", "hazmat", "water", "other")
CALL_STATUSES = ("ringing", "active", "on_hold", "ended")


class Keyword(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """Einsatzstichwort (global catalogue). Alarm rules (AAO) are per control centre."""

    __tablename__ = "keywords"
    __table_args__ = (CheckConstraint("default_priority BETWEEN 1 AND 3", name="priority_range"),)

    code: Mapped[str] = mapped_column(String(24), unique=True)  # B1, H2, RD2 …
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(16))  # one of INCIDENT_TYPES
    default_priority: Mapped[int] = mapped_column(Integer, default=2)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Police are never alarmed by the system – the dispatcher only gets a notice to confirm.
    police_notice: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    police_notice_text: Mapped[str | None] = mapped_column(Text)


class EmergencyCall(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "emergency_calls"
    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 3", name="priority_range"),
        Index(
            "ix_emergency_calls_open",
            "control_center_id",
            "status",
            postgresql_where=text("status <> 'ended'"),
        ),
    )

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="ringing")
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1 kritisch, 2 dringend, 3 normal
    source: Mapped[str] = mapped_column(String(16))  # sim | manual | voip | training
    line: Mapped[str | None] = mapped_column(String(32))  # e.g. "112"
    caller_name: Mapped[str | None] = mapped_column(String(200))
    caller_phone: Mapped[str | None] = mapped_column(String(64))
    # Location of the caller as transmitted (e.g. AML) – may differ from the incident location
    caller_location: Mapped[str | None] = mapped_column(String(300))
    caller_latitude: Mapped[float | None] = mapped_column(Float)
    caller_longitude: Mapped[float | None] = mapped_column(Float)
    address: Mapped[str | None] = mapped_column(String(300))  # incident location as captured
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)  # Einsatzgrund
    # Simulation only: what the simulated caller reports (clearly marked in the UI)
    sim_transcript: Mapped[str | None] = mapped_column(Text)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"), index=True
    )
    handled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    received_at: Mapped[datetime] = mapped_column(default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column()
    ended_at: Mapped[datetime | None] = mapped_column()

    notes: Mapped[list[CallNote]] = relationship(
        lazy="selectin", order_by="CallNote.id", cascade="all, delete-orphan"
    )


class CallNote(Base):
    """Conversation note or documented follow-up question (Rückfrage) of a call."""

    __tablename__ = "call_notes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emergency_calls.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # note | question
    question: Mapped[str | None] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    author_name: Mapped[str] = mapped_column(String(200))
    ts: Mapped[datetime] = mapped_column(default=utcnow)


class IncidentNumberSequence(Base):
    __tablename__ = "incident_number_sequences"

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="CASCADE"), primary_key=True
    )
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, default=0)


class Incident(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 3", name="priority_range"),
        Index("uq_incidents_cc_year_seq", "control_center_id", "year", "sequence", unique=True),
        Index(
            "ix_incidents_open", "control_center_id", "status", postgresql_where=text("status <> 'closed'")
        ),
    )

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    year: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(String(32))  # e.g. ILS-DEMO 2026-000123
    keyword_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("keywords.id", ondelete="RESTRICT"))
    incident_type: Mapped[str] = mapped_column(String(16), default="other")
    status: Mapped[str] = mapped_column(String(16), default="new")
    priority: Mapped[int] = mapped_column(Integer, default=2)
    address: Mapped[str | None] = mapped_column(String(300))
    location_note: Mapped[str | None] = mapped_column(String(300))  # e.g. "Parkplatz hinter dem Bahnhof"
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    caller_name: Mapped[str | None] = mapped_column(String(200))
    caller_phone: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | call | sim | training
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status_changed_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column()
    closed_at: Mapped[datetime | None] = mapped_column()

    keyword: Mapped[Keyword | None] = relationship(lazy="selectin")
    assignments: Mapped[list[IncidentVehicle]] = relationship(
        lazy="selectin", order_by="IncidentVehicle.assigned_at", back_populates="incident"
    )
    calls: Mapped[list[EmergencyCall]] = relationship(
        lazy="selectin", order_by="EmergencyCall.received_at", viewonly=True
    )


class IncidentVehicle(Base):
    """Assignment of a vehicle to an incident (history kept: released rows stay)."""

    __tablename__ = "incident_vehicles"
    __table_args__ = (
        Index(
            "uq_incident_vehicles_active",
            "vehicle_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="RESTRICT"), index=True
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="RESTRICT"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(default=utcnow)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # set by the alarm (phase 4) and the vehicle status (phase 6)
    alarmed_at: Mapped[datetime | None] = mapped_column()
    s3_at: Mapped[datetime | None] = mapped_column()
    s4_at: Mapped[datetime | None] = mapped_column()
    released_at: Mapped[datetime | None] = mapped_column()
    released_reason: Mapped[str | None] = mapped_column(String(32))  # released | reassigned | closed

    incident: Mapped[Incident] = relationship(back_populates="assignments")
    vehicle: Mapped[Vehicle] = relationship(lazy="selectin")


class IncidentEvent(Base):
    """Einsatzverlauf – append-only (trigger)."""

    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="RESTRICT"), index=True
    )
    ts: Mapped[datetime] = mapped_column(default=utcnow)
    kind: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column()
    actor_name: Mapped[str] = mapped_column(String(200))
