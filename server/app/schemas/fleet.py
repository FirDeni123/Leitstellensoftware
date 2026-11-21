"""API contracts for vehicle status, fleet view, talk requests, movements and simulation (Phase 6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel

TalkAction = Literal["accept", "defer", "reject", "done"]


class FleetPosition(ApiModel):
    lat: float
    lon: float
    source: str  # station | sim | gps
    moving: bool
    heading: float | None
    eta_s: float | None
    kind: str | None


class FleetIncident(ApiModel):
    id: uuid.UUID
    number: str
    status: str
    alarmed: bool


class FleetTalkRequest(ApiModel):
    id: uuid.UUID
    priority: int
    status: str


class FleetVehicle(ApiModel):
    id: uuid.UUID
    call_sign: str
    vehicle_type: str
    station_id: uuid.UUID
    station: str
    organization: str
    radio_group_id: uuid.UUID | None
    radio_group: str | None
    status_code: int
    status_changed_at: datetime | None
    available: bool
    position: FleetPosition | None
    incident: FleetIncident | None
    talk_request: FleetTalkRequest | None
    planned_departure_s: float | None = Field(
        default=None, description="Sekunden bis zur simulierten Abfahrt"
    )


class StatusSet(ApiModel):
    status_code: int = Field(ge=0, le=9)
    note: str | None = Field(default=None, max_length=500)
    simulate: bool = Field(
        default=False, description="als Statusmeldung des Fahrzeugs simulieren (Ausbilder)"
    )


class StatusHistoryOut(ApiModel):
    id: int
    status_code: int
    previous_code: int | None
    source: str
    incident_id: uuid.UUID | None
    actor_name: str
    note: str | None
    ts: datetime


class TalkRequestOut(ApiModel):
    id: uuid.UUID
    control_center_id: uuid.UUID
    vehicle_id: uuid.UUID
    call_sign: str
    vehicle_type: str
    station: str
    priority: int
    status: Literal["open", "accepted", "deferred", "rejected", "done"]
    source: str
    incident_id: uuid.UUID | None
    incident_number: str | None
    created_at: datetime
    handled_at: datetime | None
    handled_by_name: str | None
    note: str | None


class TalkRequestAction(ApiModel):
    note: str | None = Field(default=None, max_length=500)


class MovementOut(ApiModel):
    id: uuid.UUID
    vehicle_id: uuid.UUID
    call_sign: str
    incident_id: uuid.UUID | None
    kind: Literal["to_incident", "to_station"]
    status: Literal["pending", "active"]
    route_source: str
    emergency: bool
    geometry: list[list[float]]
    dest: list[float]
    eta_s: float | None
    depart_in_s: float | None
    note: str | None


class MapConfig(ApiModel):
    tile_url: str
    attribution: str
    max_zoom: int
    center: list[float] | None  # [lat, lon]
    routing: bool


class ClockOut(ApiModel):
    sim_time: float
    factor: float
    paused: bool
    factors: list[float]
    simulation_mode: bool


class ClockUpdate(ApiModel):
    factor: float | None = Field(default=None, gt=0, le=60)
    paused: bool | None = None


class MoveVehicle(ApiModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Breakdown(ApiModel):
    note: str | None = Field(default=None, max_length=500)
