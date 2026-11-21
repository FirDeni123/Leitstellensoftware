"""Fleet operations (Phase 6): status history, talk requests (Sprechwünsche), simulated movements.

* ``vehicle_status_history`` is append-only (database trigger, migration 0006).
* Movements store the route and a cumulative time profile in **simulation seconds** (see
  ``app.simulation.clock``). Positions are never written per tick: they are a function of the
  simulation time and can therefore be reconstructed after a restart.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin, utcnow
from app.models.master_data import Vehicle

STATUS_SOURCES = ("dispatcher", "simulation", "fms", "system")
TALK_REQUEST_STATES = ("open", "accepted", "deferred", "rejected", "done")
MOVEMENT_STATES = ("pending", "active", "arrived", "cancelled")


class VehicleStatusHistory(Base):
    __tablename__ = "vehicle_status_history"
    __table_args__ = (Index("ix_vehicle_status_history_vehicle_ts", "vehicle_id", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="RESTRICT"))
    status_code: Mapped[int] = mapped_column(Integer)
    previous_code: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16))  # dispatcher | simulation | fms | system
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id", ondelete="RESTRICT"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column()
    actor_name: Mapped[str] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(String(500))
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class TalkRequest(UUIDPrimaryKeyMixin, Base):
    """Sprechwunsch: FMS status 5 (normal) or 0 (priorisierter Sprechwunsch / Notruf)."""

    __tablename__ = "talk_requests"
    __table_args__ = (
        Index(
            "uq_talk_requests_open_vehicle",
            "vehicle_id",
            unique=True,
            postgresql_where=text("status IN ('open', 'deferred')"),
        ),
    )

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="RESTRICT"))
    priority: Mapped[int] = mapped_column(Integer)  # 0 = priorisiert (Notruf), 5 = normal
    status: Mapped[str] = mapped_column(String(16), default="open")
    source: Mapped[str] = mapped_column(String(16))
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    handled_at: Mapped[datetime | None] = mapped_column()
    handled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    handled_by_name: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(String(500))

    vehicle: Mapped[Vehicle] = relationship(lazy="selectin")


class VehicleMovement(UUIDPrimaryKeyMixin, Base):
    """A (simulated) drive. ``geometry`` is ``[[lon, lat], …]``; ``profile`` holds the
    cumulative seconds at each vertex (same length), so speeds may differ per segment."""

    __tablename__ = "vehicle_movements"
    __table_args__ = (
        Index(
            "uq_vehicle_movements_open_vehicle",
            "vehicle_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'active')"),
        ),
        Index(
            "ix_vehicle_movements_open",
            "control_center_id",
            postgresql_where=text("status IN ('pending', 'active')"),
        ),
    )

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT")
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="RESTRICT"))
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))  # to_incident | to_station
    status: Mapped[str] = mapped_column(String(16), default="pending")
    emergency: Mapped[bool] = mapped_column(default=True)  # Sonderrechte (to incidents)
    dest_lat: Mapped[float] = mapped_column(Float)
    dest_lon: Mapped[float] = mapped_column(Float)
    # The route is computed at departure (from the position at that moment).
    route_source: Mapped[str] = mapped_column(String(16), default="pending")  # pending | osrm | straight
    depart_sim: Mapped[float] = mapped_column(Float)  # simulation seconds
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    distance_m: Mapped[float] = mapped_column(Float, default=0.0)
    geometry: Mapped[list[list[float]]] = mapped_column(JSONB, default=list)
    profile: Mapped[list[float]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)

    vehicle: Mapped[Vehicle] = relationship(lazy="selectin")

    @property
    def arrive_sim(self) -> float:
        return self.depart_sim + self.duration_s

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "vehicle_id": str(self.vehicle_id),
            "kind": self.kind,
            "status": self.status,
        }
