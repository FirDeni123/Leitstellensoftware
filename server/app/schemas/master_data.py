"""API contracts for master data (Phase 2)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.auth import ControlCenterRef
from app.schemas.common import ApiModel, VersionedUpdate

OrganizationKind = Literal["fire", "ems", "civil_protection", "technical_relief", "aid", "police", "other"]
SubAddress = Literal["", "A", "B", "C", "D"]
LinkKind = Literal["neighbor", "backup", "cooperation"]

HEX_COLOR = r"^#[0-9a-fA-F]{6}$"
TIME = r"^([01]\d|2[0-3]):[0-5]\d$"


def _strip(v: Any) -> Any:
    return v.strip() if isinstance(v, str) else v


def _norm_code(v: str) -> str:
    v = v.strip().upper()
    if not re.match(r"^[A-Z0-9][A-Z0-9/ ._-]{0,31}$", v):
        raise ValueError("Kürzel: Großbuchstaben, Ziffern, / . _ - und Leerzeichen")
    return v


def _norm_caps(v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    for c in v:
        if not re.match(r"^[a-z][a-z_]{1,39}$", c):
            raise ValueError(f"Ungültige Fähigkeit: {c}")
    return sorted(set(v))


def _norm_plate(v: str | None) -> str | None:
    return " ".join(v.upper().split()) if v else v


def _check_coords(obj: Any) -> Any:
    lat, lon = getattr(obj, "latitude", None), getattr(obj, "longitude", None)
    fields = getattr(obj, "model_fields_set", set())
    if ("latitude" in fields or "longitude" in fields) and (lat is None) != (lon is None):
        raise ValueError("Breiten- und Längengrad nur gemeinsam angeben")
    return obj


# ------------------------------------------------------------------------------- references
class OrganizationRef(ApiModel):
    id: uuid.UUID
    key: str
    name: str
    kind: str
    color: str | None
    alarmable: bool


class VehicleTypeRef(ApiModel):
    id: uuid.UUID
    code: str
    name: str
    category: str


class StationRef(ApiModel):
    id: uuid.UUID
    name: str
    short_name: str | None


class RadioGroupRef(ApiModel):
    id: uuid.UUID
    name: str
    talkgroup: str | None


class RicRef(ApiModel):
    id: uuid.UUID
    code: str
    sub_address: str
    label: str


class VehicleRef(ApiModel):
    id: uuid.UUID
    call_sign: str


# ---------------------------------------------------------------------------- organisations
class OrganizationCreate(ApiModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,47}$")
    name: str = Field(min_length=2, max_length=200)
    kind: OrganizationKind
    alarmable: bool = True
    color: str | None = Field(default=None, pattern=HEX_COLOR)
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool = True


class OrganizationUpdate(VersionedUpdate):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    kind: OrganizationKind | None = None
    alarmable: bool | None = None
    color: str | None = Field(default=None, pattern=HEX_COLOR)
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None


class OrganizationOut(OrganizationRef):
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    version: int


# ---------------------------------------------------------------------------- vehicle types
class VehicleTypeCreate(ApiModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=2, max_length=200)
    category: OrganizationKind
    default_speed_kmh: int = Field(default=60, ge=5, le=300)
    default_crew: int | None = Field(default=None, ge=0, le=99)
    capabilities: list[str] = Field(default_factory=list, max_length=30)
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool = True

    _code = field_validator("code")(_norm_code)
    _caps = field_validator("capabilities")(_norm_caps)


class VehicleTypeUpdate(VersionedUpdate):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    category: OrganizationKind | None = None
    default_speed_kmh: int | None = Field(default=None, ge=5, le=300)
    default_crew: int | None = Field(default=None, ge=0, le=99)
    capabilities: list[str] | None = Field(default=None, max_length=30)
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None

    _caps = field_validator("capabilities")(_norm_caps)


class VehicleTypeOut(VehicleTypeRef):
    default_speed_kmh: int
    default_crew: int | None
    capabilities: list[str]
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    version: int


# ------------------------------------------------------------------------ status definitions
class StatusDefinitionOut(ApiModel):
    code: int
    label: str
    short_label: str
    color: str
    counts_as_available: bool
    description: str | None
    version: int


class StatusDefinitionUpdate(VersionedUpdate):
    label: str | None = Field(default=None, min_length=2, max_length=120)
    short_label: str | None = Field(default=None, min_length=1, max_length=32)
    color: str | None = Field(default=None, pattern=HEX_COLOR)
    counts_as_available: bool | None = None
    description: str | None = Field(default=None, max_length=2000)


# -------------------------------------------------------------------------------- stations
class ScheduleEntry(ApiModel):
    days: list[int] = Field(min_length=1, max_length=7, description="1 = Montag … 7 = Sonntag")
    start: str = Field(pattern=TIME)
    end: str = Field(pattern=TIME)

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("Wochentage 1–7")
        return sorted(set(v))


class Availability(ApiModel):
    mode: Literal["always", "schedule", "unavailable"] = "always"
    schedule: list[ScheduleEntry] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _schedule_needed(self) -> Availability:
        if self.mode == "schedule" and not self.schedule:
            raise ValueError("Bei Verfügbarkeit nach Zeitplan mindestens einen Zeitraum angeben")
        return self


class StationCreate(ApiModel):
    control_center_id: uuid.UUID
    organization_id: uuid.UUID
    name: str = Field(min_length=2, max_length=200)
    short_name: str | None = Field(default=None, max_length=48)
    address: str | None = Field(default=None, max_length=300)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    phone: str | None = Field(default=None, max_length=64)
    availability: Availability = Field(default_factory=Availability)
    description: str | None = Field(default=None, max_length=4000)
    osm_ref: str | None = Field(default=None, max_length=64)
    is_active: bool = True
    ric_ids: list[uuid.UUID] = Field(default_factory=list)

    _strip = field_validator("name", "short_name")(_strip)
    _coords = model_validator(mode="after")(_check_coords)


class StationUpdate(VersionedUpdate):
    organization_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=2, max_length=200)
    short_name: str | None = Field(default=None, max_length=48)
    address: str | None = Field(default=None, max_length=300)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    phone: str | None = Field(default=None, max_length=64)
    availability: Availability | None = None
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None
    ric_ids: list[uuid.UUID] | None = None

    _coords = model_validator(mode="after")(_check_coords)


class StationOut(ApiModel):
    id: uuid.UUID
    control_center_id: uuid.UUID
    organization: OrganizationRef
    name: str
    short_name: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    phone: str | None
    availability: dict[str, Any]
    description: str | None
    osm_ref: str | None
    is_active: bool
    rics: list[RicRef]
    created_at: datetime
    updated_at: datetime
    version: int


# -------------------------------------------------------------------------------- vehicles
class VehicleCreate(ApiModel):
    control_center_id: uuid.UUID
    station_id: uuid.UUID
    vehicle_type_id: uuid.UUID
    organization_id: uuid.UUID | None = Field(default=None, description="Leer = Organisation der Wache")
    radio_group_id: uuid.UUID | None = None
    call_sign: str = Field(min_length=2, max_length=80, description="Funkrufname")
    license_plate: str | None = Field(default=None, max_length=20)
    status_code: int = Field(default=2, ge=0, le=9, description="Anfangsstatus")
    available: bool = True
    availability_note: str | None = Field(default=None, max_length=300)
    crew_size: int | None = Field(default=None, ge=0, le=99)
    description: str | None = Field(default=None, max_length=4000)
    sim_speed_kmh: int | None = Field(default=None, ge=5, le=300)
    ric_ids: list[uuid.UUID] = Field(default_factory=list)

    _strip = field_validator("call_sign")(_strip)
    _plate = field_validator("license_plate")(_norm_plate)


class VehicleUpdate(VersionedUpdate):
    station_id: uuid.UUID | None = None
    vehicle_type_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    radio_group_id: uuid.UUID | None = None
    call_sign: str | None = Field(default=None, min_length=2, max_length=80)
    license_plate: str | None = Field(default=None, max_length=20)
    available: bool | None = None
    availability_note: str | None = Field(default=None, max_length=300)
    crew_size: int | None = Field(default=None, ge=0, le=99)
    description: str | None = Field(default=None, max_length=4000)
    sim_speed_kmh: int | None = Field(default=None, ge=5, le=300)
    ric_ids: list[uuid.UUID] | None = None

    _strip = field_validator("call_sign")(_strip)
    _plate = field_validator("license_plate")(_norm_plate)


class Position(ApiModel):
    latitude: float | None
    longitude: float | None
    source: str


class VehicleOut(ApiModel):
    id: uuid.UUID
    control_center_id: uuid.UUID
    call_sign: str
    license_plate: str | None
    station: StationRef
    vehicle_type: VehicleTypeRef
    organization: OrganizationRef
    radio_group: RadioGroupRef | None
    rics: list[RicRef]
    status_code: int
    status_changed_at: datetime | None
    position: Position
    available: bool
    availability_note: str | None
    crew_size: int | None
    description: str | None
    sim_speed_kmh: int | None
    effective_speed_kmh: int
    import_job_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    version: int


# ------------------------------------------------------------------------------------ RICs
class RicCreate(ApiModel):
    control_center_id: uuid.UUID
    code: str = Field(pattern=r"^\d{1,10}$")
    sub_address: SubAddress = ""
    label: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool = True
    station_ids: list[uuid.UUID] = Field(default_factory=list)
    vehicle_ids: list[uuid.UUID] = Field(default_factory=list)


class RicUpdate(VersionedUpdate):
    code: str | None = Field(default=None, pattern=r"^\d{1,10}$")
    sub_address: SubAddress | None = None
    label: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None
    station_ids: list[uuid.UUID] | None = None
    vehicle_ids: list[uuid.UUID] | None = None


class RicOut(RicRef):
    control_center_id: uuid.UUID
    description: str | None
    is_active: bool
    stations: list[StationRef]
    vehicles: list[VehicleRef]
    created_at: datetime
    updated_at: datetime
    version: int


class AlarmGroupCreate(ApiModel):
    control_center_id: uuid.UUID
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    ric_ids: list[uuid.UUID] = Field(default_factory=list)


class AlarmGroupUpdate(VersionedUpdate):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    ric_ids: list[uuid.UUID] | None = None


class AlarmGroupOut(ApiModel):
    id: uuid.UUID
    control_center_id: uuid.UUID
    name: str
    description: str | None
    rics: list[RicRef]
    created_at: datetime
    updated_at: datetime
    version: int


# ---------------------------------------------------------------------------- radio groups
class RadioGroupCreate(ApiModel):
    control_center_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    talkgroup: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    station_ids: list[uuid.UUID] = Field(default_factory=list)
    organization_ids: list[uuid.UUID] = Field(default_factory=list)


class RadioGroupUpdate(VersionedUpdate):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    talkgroup: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    station_ids: list[uuid.UUID] | None = None
    organization_ids: list[uuid.UUID] | None = None


class RadioGroupOut(RadioGroupRef):
    control_center_id: uuid.UUID
    description: str | None
    stations: list[StationRef]
    organizations: list[OrganizationRef]
    vehicles: list[VehicleRef]
    created_at: datetime
    updated_at: datetime
    version: int


# ------------------------------------------------------------- control centre links / areas
class LinkCreate(ApiModel):
    from_control_center_id: uuid.UUID
    to_control_center_id: uuid.UUID
    kind: LinkKind
    note: str | None = Field(default=None, max_length=500)


class LinkOut(ApiModel):
    id: uuid.UUID
    from_control_center: ControlCenterRef
    to_control_center: ControlCenterRef
    kind: LinkKind
    note: str | None
    created_at: datetime


class AreaCreate(ApiModel):
    control_center_id: uuid.UUID
    name: str = Field(min_length=2, max_length=200)
    municipality_key: str | None = Field(
        default=None,
        pattern=r"^(\d{8}|\d{12})$",
        description="Amtlicher Gemeindeschlüssel (8) oder Regionalschlüssel (12)",
    )
    geometry: dict[str, Any] | None = Field(default=None, description="GeoJSON Polygon/MultiPolygon")
    priority: int = Field(default=100, ge=0, le=1000)
    description: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _one_of(self) -> AreaCreate:
        if self.geometry is None and not self.municipality_key:
            raise ValueError("Geometrie oder Gemeindeschlüssel angeben")
        return self


class AreaUpdate(VersionedUpdate):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    municipality_key: str | None = Field(default=None, pattern=r"^(\d{8}|\d{12})$")
    geometry: dict[str, Any] | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    description: str | None = Field(default=None, max_length=4000)


class AreaOut(ApiModel):
    id: uuid.UUID
    control_center_id: uuid.UUID
    name: str
    municipality_key: str | None
    geometry: dict[str, Any] | None
    priority: int
    description: str | None
    created_at: datetime
    updated_at: datetime
    version: int


class ResponsibilityOut(ApiModel):
    area_id: uuid.UUID
    area_name: str
    priority: int
    control_center: ControlCenterRef
