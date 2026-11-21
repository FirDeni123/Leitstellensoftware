"""Master data (Stammdaten): organisations, vehicle types, status definitions, stations,
vehicles, RICs, alarm groups and radio groups.

Global catalogues (organisations, vehicle types, status definitions) are shared by all
control centres. Everything else belongs to exactly one control centre (tenant).
Foreign keys use RESTRICT so that data still referenced elsewhere cannot vanish silently;
the API turns such violations into a readable 409 conflict.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionedMixin


def _assoc(name: str, left: str, left_table: str, right: str, right_table: str) -> Table:
    return Table(
        name,
        Base.metadata,
        Column(
            left, UUID(as_uuid=True), ForeignKey(f"{left_table}.id", ondelete="CASCADE"), primary_key=True
        ),
        Column(
            right, UUID(as_uuid=True), ForeignKey(f"{right_table}.id", ondelete="CASCADE"), primary_key=True
        ),
    )


station_rics = _assoc("station_rics", "station_id", "stations", "ric_id", "rics")
vehicle_rics = _assoc("vehicle_rics", "vehicle_id", "vehicles", "ric_id", "rics")
alarm_group_rics = _assoc("alarm_group_rics", "alarm_group_id", "alarm_groups", "ric_id", "rics")
radio_group_stations = _assoc(
    "radio_group_stations", "radio_group_id", "radio_groups", "station_id", "stations"
)
radio_group_organizations = _assoc(
    "radio_group_organizations", "radio_group_id", "radio_groups", "organization_id", "organizations"
)


# --------------------------------------------------------------------------- global catalogues
class Organization(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """Feuerwehr, Rettungsdienst, THW, Hilfsorganisationen … and the police (information only)."""

    __tablename__ = "organizations"
    __table_args__ = (
        # The police may never be alarmed by the control centre (only an information notice).
        CheckConstraint("kind <> 'police' OR alarmable = false", name="police_not_alarmable"),
    )

    key: Mapped[str] = mapped_column(String(48), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    alarmable: Mapped[bool] = mapped_column(Boolean, default=True)
    color: Mapped[str | None] = mapped_column(String(9))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class VehicleType(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "vehicle_types"

    code: Mapped[str] = mapped_column(String(32), unique=True)  # HLF20, RTW, NEF …
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32))  # same values as Organization.kind
    default_speed_kmh: Mapped[int] = mapped_column(Integer, default=60)
    default_crew: Mapped[int | None] = mapped_column(Integer)
    capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class VehicleStatusDefinition(VersionedMixin, Base):
    """Administrable labels of the FMS status codes 0–9."""

    __tablename__ = "vehicle_status_definitions"
    __table_args__ = (CheckConstraint("code BETWEEN 0 AND 9", name="code_range"),)

    code: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    label: Mapped[str] = mapped_column(String(120))
    short_label: Mapped[str] = mapped_column(String(32))
    color: Mapped[str] = mapped_column(String(9))
    counts_as_available: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)


# ----------------------------------------------------------------------- per control centre
class Station(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """Wache / Standort."""

    __tablename__ = "stations"
    __table_args__ = (Index("uq_stations_cc_name", "control_center_id", text("lower(name)"), unique=True),)

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str | None] = mapped_column(String(48))
    address: Mapped[str | None] = mapped_column(String(300))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    phone: Mapped[str | None] = mapped_column(String(64))
    # {"mode": "always" | "schedule" | "unavailable", "schedule": [...], "note": "..."}
    availability: Mapped[dict[str, Any]] = mapped_column(JSONB, default=lambda: {"mode": "always"})
    description: Mapped[str | None] = mapped_column(Text)
    osm_ref: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    organization: Mapped[Organization] = relationship(lazy="selectin")
    rics: Mapped[list[Ric]] = relationship(secondary=station_rics, lazy="selectin", back_populates="stations")


class Vehicle(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        Index("uq_vehicles_cc_call_sign", "control_center_id", text("lower(call_sign)"), unique=True),
        CheckConstraint("sim_speed_kmh IS NULL OR sim_speed_kmh BETWEEN 5 AND 300", name="sim_speed_range"),
    )

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    station_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stations.id", ondelete="RESTRICT"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"))
    vehicle_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicle_types.id", ondelete="RESTRICT"))
    radio_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("radio_groups.id", ondelete="RESTRICT")
    )
    call_sign: Mapped[str] = mapped_column(String(80))  # Funkrufname
    license_plate: Mapped[str | None] = mapped_column(String(20))
    status_code: Mapped[int] = mapped_column(
        ForeignKey("vehicle_status_definitions.code", ondelete="RESTRICT"), default=2
    )
    status_changed_at: Mapped[datetime | None] = mapped_column()
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    # station = at its station's coordinates, sim = simulation service, gps = real feed (plugin)
    position_source: Mapped[str] = mapped_column(String(16), default="station")
    position_updated_at: Mapped[datetime | None] = mapped_column()
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    availability_note: Mapped[str | None] = mapped_column(String(300))
    crew_size: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    sim_speed_kmh: Mapped[int | None] = mapped_column(Integer)
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_jobs.id", ondelete="SET NULL"))

    station: Mapped[Station] = relationship(lazy="selectin")
    organization: Mapped[Organization] = relationship(lazy="selectin")
    vehicle_type: Mapped[VehicleType] = relationship(lazy="selectin")
    radio_group: Mapped[RadioGroup | None] = relationship(lazy="selectin")
    rics: Mapped[list[Ric]] = relationship(secondary=vehicle_rics, lazy="selectin", back_populates="vehicles")


class Ric(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """Radio Identification Code of the paging network (POCSAG/digital alerting)."""

    __tablename__ = "rics"
    __table_args__ = (
        UniqueConstraint("control_center_id", "code", "sub_address", name="uq_rics_cc_code_sub"),
    )

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(16))
    sub_address: Mapped[str] = mapped_column(String(1), default="")  # "" or A–D
    label: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    stations: Mapped[list[Station]] = relationship(
        secondary=station_rics, lazy="selectin", back_populates="rics"
    )
    vehicles: Mapped[list[Vehicle]] = relationship(
        secondary=vehicle_rics, lazy="selectin", back_populates="rics"
    )


class AlarmGroup(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """Bundle of RICs that are alerted together (Alarmierungsgruppe)."""

    __tablename__ = "alarm_groups"
    __table_args__ = (UniqueConstraint("control_center_id", "name", name="uq_alarm_groups_cc_name"),)

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)

    rics: Mapped[list[Ric]] = relationship(secondary=alarm_group_rics, lazy="selectin")


class RadioGroup(UUIDPrimaryKeyMixin, TimestampMixin, VersionedMixin, Base):
    """Funkrufgruppe (talk group). Vehicles reference one group; stations/organisations n:m."""

    __tablename__ = "radio_groups"
    __table_args__ = (UniqueConstraint("control_center_id", "name", name="uq_radio_groups_cc_name"),)

    control_center_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("control_centers.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    talkgroup: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)

    stations: Mapped[list[Station]] = relationship(secondary=radio_group_stations, lazy="selectin")
    organizations: Mapped[list[Organization]] = relationship(
        secondary=radio_group_organizations, lazy="selectin"
    )
    # Vehicles reference their radio group (one per vehicle); read-only view from the group side.
    vehicles: Mapped[list[Vehicle]] = relationship(
        viewonly=True, lazy="selectin", order_by="Vehicle.call_sign"
    )
