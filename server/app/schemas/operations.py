"""API contracts for emergency calls, incidents and keywords (Phase 3)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import ApiModel, VersionedUpdate
from app.schemas.master_data import StationRef, _check_coords, _norm_code

IncidentStatus = Literal["new", "in_progress", "alarmed", "en_route", "on_scene", "finished", "closed"]
IncidentType = Literal["fire", "technical", "ems", "hazmat", "water", "other"]
CallStatus = Literal["ringing", "active", "on_hold", "ended"]
Priority = int


# ------------------------------------------------------------------------------- keywords
class KeywordRef(ApiModel):
    id: uuid.UUID
    code: str
    name: str
    category: IncidentType


class KeywordCreate(ApiModel):
    code: str = Field(min_length=1, max_length=24)
    name: str = Field(min_length=2, max_length=200)
    category: IncidentType
    default_priority: int = Field(default=2, ge=1, le=3)
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool = True

    @model_validator(mode="after")
    def _code(self) -> KeywordCreate:
        self.code = _norm_code(self.code)
        return self


class KeywordUpdate(VersionedUpdate):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    category: IncidentType | None = None
    default_priority: int | None = Field(default=None, ge=1, le=3)
    description: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None


class KeywordOut(KeywordRef):
    default_priority: int
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    version: int


# --------------------------------------------------------------------------------- calls
class CallNoteOut(ApiModel):
    id: int
    kind: Literal["note", "question"]
    question: str | None
    text: str
    author_name: str
    ts: datetime


class IncidentRef(ApiModel):
    id: uuid.UUID
    number: str
    status: IncidentStatus


class CallOut(ApiModel):
    id: uuid.UUID
    control_center_id: uuid.UUID
    status: CallStatus
    priority: int
    source: str
    line: str | None
    caller_name: str | None
    caller_phone: str | None
    caller_location: str | None
    caller_latitude: float | None
    caller_longitude: float | None
    address: str | None
    latitude: float | None
    longitude: float | None
    reason: str | None
    sim_transcript: str | None
    incident: IncidentRef | None
    handled_by: uuid.UUID | None
    handled_by_name: str | None
    received_at: datetime
    answered_at: datetime | None
    ended_at: datetime | None
    notes: list[CallNoteOut]
    version: int


class CallCreate(ApiModel):
    """Manually captured call (e.g. received on a phone without integration)."""

    control_center_id: uuid.UUID
    priority: int = Field(default=3, ge=1, le=3)
    line: str | None = Field(default=None, max_length=32)
    caller_name: str | None = Field(default=None, max_length=200)
    caller_phone: str | None = Field(default=None, max_length=64)
    caller_location: str | None = Field(default=None, max_length=300)
    reason: str | None = Field(default=None, max_length=4000)


class CallUpdate(VersionedUpdate):
    priority: int | None = Field(default=None, ge=1, le=3)
    caller_name: str | None = Field(default=None, max_length=200)
    caller_phone: str | None = Field(default=None, max_length=64)
    caller_location: str | None = Field(default=None, max_length=300)
    address: str | None = Field(default=None, max_length=300)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    reason: str | None = Field(default=None, max_length=4000)

    _coords = model_validator(mode="after")(_check_coords)


class CallAction(ApiModel):
    """Lifecycle actions are guarded by the call state; the version is informational only."""

    expected_version: int | None = Field(default=None, ge=1)


class CallNoteCreate(ApiModel):
    kind: Literal["note", "question"] = "note"
    question: str | None = Field(default=None, max_length=300)
    text: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def _question(self) -> CallNoteCreate:
        if self.kind == "question" and not self.question:
            raise ValueError("Bei einer Rückfrage muss die Frage angegeben werden")
        return self


class CallLink(ApiModel):
    incident_id: uuid.UUID
    expected_version: int | None = Field(default=None, ge=1)


# ----------------------------------------------------------------------------- incidents
class AssignedVehicle(ApiModel):
    id: uuid.UUID
    call_sign: str
    vehicle_type: str
    station: str


class AssignmentOut(ApiModel):
    id: int
    vehicle: AssignedVehicle
    assigned_at: datetime
    alarmed_at: datetime | None
    s3_at: datetime | None
    s4_at: datetime | None
    released_at: datetime | None
    released_reason: str | None


class CallRef(ApiModel):
    id: uuid.UUID
    status: CallStatus
    caller_name: str | None
    caller_phone: str | None
    received_at: datetime


class IncidentSummary(ApiModel):
    id: uuid.UUID
    control_center_id: uuid.UUID
    number: str
    keyword: KeywordRef | None
    incident_type: IncidentType
    status: IncidentStatus
    priority: int
    address: str | None
    created_at: datetime
    status_changed_at: datetime
    vehicles: list[str] = Field(description="Funkrufnamen der aktuell zugeordneten Fahrzeuge")
    version: int


class IncidentOut(IncidentSummary):
    year: int
    sequence: int
    location_note: str | None
    latitude: float | None
    longitude: float | None
    caller_name: str | None
    caller_phone: str | None
    description: str | None
    source: str
    updated_at: datetime
    finished_at: datetime | None
    closed_at: datetime | None
    assignments: list[AssignmentOut]
    stations: list[StationRef]
    calls: list[CallRef]


class IncidentFields(ApiModel):
    keyword_id: uuid.UUID | None = None
    incident_type: IncidentType | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    address: str | None = Field(default=None, max_length=300)
    location_note: str | None = Field(default=None, max_length=300)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    caller_name: str | None = Field(default=None, max_length=200)
    caller_phone: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=8000)

    _coords = model_validator(mode="after")(_check_coords)


class IncidentCreate(IncidentFields):
    control_center_id: uuid.UUID
    call_id: uuid.UUID | None = Field(default=None, description="Notruf, aus dem der Einsatz entsteht")


class IncidentUpdate(IncidentFields):
    expected_version: int = Field(ge=1)


class StatusChange(VersionedUpdate):
    status: IncidentStatus
    note: str | None = Field(default=None, max_length=2000)


class NoteCreate(ApiModel):
    text: str = Field(min_length=1, max_length=8000)


class AssignVehicles(ApiModel):
    vehicle_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    reassign: bool = Field(default=False, description="Fahrzeuge aus anderen Einsätzen umsetzen")


class IncidentEventOut(ApiModel):
    id: int
    ts: datetime
    kind: str
    text: str
    data: dict[str, Any] | None
    actor_name: str


class ActiveAssignment(ApiModel):
    vehicle_id: uuid.UUID
    incident_id: uuid.UUID
    incident_number: str
    assigned_at: datetime


# ---------------------------------------------------------------------------- simulation
class SimulatedCallRequest(ApiModel):
    control_center_id: uuid.UUID
    scenario: str | None = Field(default=None, description="Schlüssel eines Szenarios; leer = zufällig")
    count: int = Field(default=1, ge=1, le=5)


class ScenarioOut(ApiModel):
    key: str
    title: str
    expected_keyword: str
