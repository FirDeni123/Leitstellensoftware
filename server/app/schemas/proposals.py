"""API contracts for the Einsatzmittelvorschlag (Phase 5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.proposal.settings import ProposalSettingsData
from app.schemas.common import ApiModel


class ExtraDemand(ApiModel):
    vehicle_type_id: uuid.UUID
    count: int = Field(default=1, ge=1, le=20)


class ProposalRequest(ApiModel):
    stage: int | None = Field(default=None, ge=1, le=9, description="Leer = nächste Stufe laut AAO")
    extra: list[ExtraDemand] = Field(default_factory=list, max_length=20, description="Zusatzbedarf")


class ProposalPick(ApiModel):
    demand_key: str
    vehicle_id: uuid.UUID
    call_sign: str
    vehicle_type: str
    station_id: uuid.UUID
    station: str
    status_code: int
    slot: int
    match: Literal["exact", "substitute", "vehicle", "covered"]
    score_seconds: int | None
    travel_seconds: int | None
    distance_m: int | None
    travel_source: Literal["osrm", "estimate", "none"]
    in_incident: bool
    alarmed: bool
    reasons: list[str]


class ProposalOption(ApiModel):
    vehicle_id: uuid.UUID
    call_sign: str
    vehicle_type: str
    station: str
    status_code: int
    match: str
    score_seconds: int
    travel_seconds: int | None
    reason: str


class ProposalDemand(ApiModel):
    key: str
    label: str
    source: str
    count: int
    stage: int | None
    covered: int


class ProposalShortfall(ApiModel):
    demand_key: str
    label: str
    missing: int
    message: str


class ProposalOut(ApiModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    control_center_id: uuid.UUID
    computed_at: datetime
    computed_by_name: str
    duration_ms: int
    rule: dict[str, Any] | None
    stage: int | None
    max_stage: int
    next_kind: Literal["initial", "follow_up"]
    travel_source: Literal["osrm", "estimate", "mixed", "none"]
    demands: list[ProposalDemand]
    picks: list[ProposalPick]
    alternatives: dict[str, list[ProposalOption]]
    shortfalls: list[ProposalShortfall]
    warnings: list[str]
    candidates: int
    accepted_vehicle_ids: list[uuid.UUID] | None
    accepted_at: datetime | None
    accepted_by_name: str | None


class ProposalAccept(ApiModel):
    vehicle_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    reassign: bool = False


class ProposalSettingsOut(ApiModel):
    control_center_id: uuid.UUID
    settings: ProposalSettingsData
    defaults: ProposalSettingsData
    is_default: bool
    version: int | None
    updated_at: datetime | None
    updated_by_name: str | None
    routing_configured: bool


class ProposalSettingsUpdate(ApiModel):
    control_center_id: uuid.UUID
    settings: ProposalSettingsData
    expected_version: int | None = Field(default=None, ge=1, description="Leer beim ersten Speichern")
