"""Specifications of all master data types (fields, references, business rules)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationFailedError
from app.core.geo import normalise_geometry
from app.models import (
    AlarmGroup,
    ControlCenterArea,
    Keyword,
    Organization,
    RadioGroup,
    Ric,
    Station,
    Vehicle,
    VehicleStatusDefinition,
    VehicleType,
)
from app.schemas.master_data import Position, VehicleOut
from app.services.crud import CrudSpec, Ref, Relation


def _geometry_digest(geometry: dict[str, Any] | None) -> str | None:
    """Audit-friendly fingerprint instead of thousands of coordinates."""
    if not geometry:
        return None
    raw = json.dumps(geometry, sort_keys=True).encode()
    points = sum(len(ring) for poly in geometry.get("coordinates", []) for ring in poly)
    return f"Geometrie ({points} Punkte, {hashlib.sha256(raw).hexdigest()[:10]})"


def ric_title(r: Ric) -> str:
    return f"{r.code}{r.sub_address}"


# ------------------------------------------------------------------------------ business rules
async def _validate_organization(
    s: AsyncSession, org: Organization, data: dict[str, Any], is_create: bool
) -> None:
    if org.kind == "police" and org.alarmable:
        raise ValidationFailedError(
            "Die Polizei ist nicht alarmierbar – sie erhält nur einen Informationshinweis"
        )
    if org.kind == "police" and not is_create:
        has_vehicles = await s.scalar(select(exists().where(Vehicle.organization_id == org.id)))
        if has_vehicles:
            raise ConflictError("Organisation hat Fahrzeuge – Polizeifahrzeuge werden nicht disponiert")


async def _prepare_vehicle(s: AsyncSession, v: Vehicle, data: dict[str, Any], is_create: bool) -> None:
    if is_create and data.get("organization_id") is None and data.get("station_id"):
        station = await s.get(Station, data["station_id"])
        if station is not None:
            data["organization_id"] = station.organization_id
    if is_create:
        v.status_changed_at = datetime.now(UTC)


async def _validate_vehicle(s: AsyncSession, v: Vehicle, data: dict[str, Any], is_create: bool) -> None:
    org = await s.get(Organization, v.organization_id)
    if org is not None and not org.alarmable:
        raise ValidationFailedError(
            f"Fahrzeuge der Organisation „{org.name}“ werden nicht disponiert (nicht alarmierbar)"
        )
    if "vehicle_type_id" in data:
        vt = await s.get(VehicleType, v.vehicle_type_id)
        if vt is not None and not vt.is_active:
            raise ValidationFailedError(f"Fahrzeugtyp {vt.code} ist deaktiviert")


async def _validate_area(
    s: AsyncSession, area: ControlCenterArea, data: dict[str, Any], is_create: bool
) -> None:
    if data.get("geometry") is not None:
        area.geometry = normalise_geometry(data["geometry"])
    if area.geometry is None and not area.municipality_key:
        raise ValidationFailedError("Geometrie oder Gemeindeschlüssel angeben")


# ------------------------------------------------------------------------------------- specs
ORGANIZATIONS = CrudSpec(
    model=Organization,
    entity_type="organization",
    collection="organizations",
    label="Organisation",
    title=lambda o: o.name,
    fields=("name", "kind", "alarmable", "color", "description", "is_active"),
    create_only=("key",),
    scoped=False,
    search=("name", "key"),
    unique_message="mit diesem Schlüssel existiert bereits",
    in_use_message="wird noch von Wachen, Fahrzeugen oder Funkrufgruppen verwendet",
    validate=_validate_organization,
)

VEHICLE_TYPES = CrudSpec(
    model=VehicleType,
    entity_type="vehicle_type",
    collection="vehicle-types",
    label="Fahrzeugtyp",
    title=lambda t: t.code,
    fields=(
        "name",
        "category",
        "default_speed_kmh",
        "default_crew",
        "capabilities",
        "description",
        "is_active",
    ),
    create_only=("code",),
    scoped=False,
    search=("code", "name"),
    order_by=("code",),
    unique_message="mit diesem Kürzel existiert bereits",
    in_use_message="wird noch von Fahrzeugen verwendet",
)

STATUS_DEFINITIONS = CrudSpec(
    model=VehicleStatusDefinition,
    entity_type="vehicle_status_definition",
    collection="vehicle-status",
    label="Fahrzeugstatus",
    title=lambda d: f"{d.code} ({d.label})",
    fields=("label", "short_label", "color", "counts_as_available", "description"),
    scoped=False,
    order_by=("code",),
)

RIC_RELATION = Relation("rics", "ric_ids", Ric, "RICs", ric_title)

STATIONS = CrudSpec(
    model=Station,
    entity_type="station",
    collection="stations",
    label="Wache",
    title=lambda s: s.name,
    fields=(
        "name",
        "short_name",
        "address",
        "latitude",
        "longitude",
        "phone",
        "availability",
        "description",
        "osm_ref",
        "is_active",
    ),
    refs=(Ref("organization_id", Organization, "Organisation", scoped=False),),
    relations=(RIC_RELATION,),
    search=("name", "short_name", "address"),
    unique_message="mit diesem Namen existiert in dieser Leitstelle bereits",
    in_use_message="hat noch Fahrzeuge oder Zuordnungen und kann nicht gelöscht werden",
)

VEHICLES = CrudSpec(
    model=Vehicle,
    entity_type="vehicle",
    collection="vehicles",
    label="Fahrzeug",
    title=lambda v: v.call_sign,
    fields=(
        "call_sign",
        "license_plate",
        "available",
        "availability_note",
        "crew_size",
        "description",
        "sim_speed_kmh",
    ),
    create_only=("status_code",),
    refs=(
        Ref("station_id", Station, "Wache"),
        Ref("vehicle_type_id", VehicleType, "Fahrzeugtyp", scoped=False),
        Ref("organization_id", Organization, "Organisation", scoped=False),
        Ref("radio_group_id", RadioGroup, "Funkrufgruppe"),
    ),
    relations=(RIC_RELATION,),
    search=("call_sign", "license_plate", "description"),
    order_by=("call_sign",),
    unique_message="mit diesem Funkrufnamen existiert in dieser Leitstelle bereits",
    prepare=_prepare_vehicle,
    validate=_validate_vehicle,
)

RICS = CrudSpec(
    model=Ric,
    entity_type="ric",
    collection="rics",
    label="RIC",
    title=lambda r: f"{ric_title(r)} {r.label}",
    fields=("code", "sub_address", "label", "description", "is_active"),
    relations=(
        Relation("stations", "station_ids", Station, "Wachen", lambda s: s.name),
        Relation("vehicles", "vehicle_ids", Vehicle, "Fahrzeuge", lambda v: v.call_sign),
    ),
    search=("code", "label"),
    order_by=("code", "sub_address"),
    unique_message="mit dieser Kennung und Subadresse existiert bereits",
)

ALARM_GROUPS = CrudSpec(
    model=AlarmGroup,
    entity_type="alarm_group",
    collection="alarm-groups",
    label="Alarmierungsgruppe",
    title=lambda g: g.name,
    fields=("name", "description"),
    relations=(RIC_RELATION,),
    search=("name",),
    unique_message="mit diesem Namen existiert bereits",
)

RADIO_GROUPS = CrudSpec(
    model=RadioGroup,
    entity_type="radio_group",
    collection="radio-groups",
    label="Funkrufgruppe",
    title=lambda g: g.name,
    fields=("name", "talkgroup", "description"),
    relations=(
        Relation("stations", "station_ids", Station, "Wachen", lambda s: s.name),
        Relation(
            "organizations",
            "organization_ids",
            Organization,
            "Organisationen",
            lambda o: o.name,
            scoped=False,
        ),
    ),
    search=("name", "talkgroup"),
    unique_message="mit diesem Namen existiert bereits",
    in_use_message="ist noch Fahrzeugen zugeordnet",
)

KEYWORDS = CrudSpec(
    model=Keyword,
    entity_type="keyword",
    collection="keywords",
    label="Einsatzstichwort",
    title=lambda k: k.code,
    fields=("name", "category", "default_priority", "description", "is_active"),
    create_only=("code",),
    scoped=False,
    search=("code", "name"),
    order_by=("code",),
    unique_message="mit diesem Kürzel existiert bereits",
    in_use_message="wird noch von Einsätzen verwendet – stattdessen deaktivieren",
)

AREAS = CrudSpec(
    model=ControlCenterArea,
    entity_type="control_center_area",
    collection="control-center-areas",
    label="Zuständigkeitsbereich",
    title=lambda a: a.name,
    fields=("name", "municipality_key", "geometry", "priority", "description"),
    search=("name", "municipality_key"),
    order_by=("priority", "name"),
    validate=_validate_area,
    snapshot_extra=lambda a: {"geometry": _geometry_digest(a.geometry)},
)


def vehicle_out(v: Vehicle) -> VehicleOut:
    """Effective position: own coordinates when moved (simulation/GPS), else the station's."""
    if v.position_source != "station" and v.latitude is not None:
        position = Position(latitude=v.latitude, longitude=v.longitude, source=v.position_source)
    else:
        position = Position(latitude=v.station.latitude, longitude=v.station.longitude, source="station")
    data = {name: getattr(v, name) for name in VehicleOut.model_fields if hasattr(v, name)}
    data.update(position=position, effective_speed_kmh=v.sim_speed_kmh or v.vehicle_type.default_speed_kmh)
    return VehicleOut.model_validate(data, from_attributes=True)
