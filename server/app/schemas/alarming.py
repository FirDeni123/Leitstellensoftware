"""API contracts for alarm rules (AAO), alarms, police notices and interfaces (Phase 4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import ApiModel, VersionedUpdate
from app.schemas.operations import KeywordRef

RuleItemKind = Literal["vehicle_type", "vehicle", "station", "ric", "alarm_group", "interface"]
InterfaceScope = Literal["global", "control_center", "station"]
DeliveryStatus = Literal["simulated", "sent", "failed", "skipped", "not_delivered", "pending"]


# ------------------------------------------------------------------------------ AAO
class AlarmRuleItemIn(ApiModel):
    stage: int = Field(default=1, ge=1, le=9, description="Alarmierungsstufe (1 = Erstalarm)")
    kind: RuleItemKind
    count: int = Field(default=1, ge=1, le=20, description="Anzahl (nur für Fahrzeugtypen relevant)")
    target_id: uuid.UUID
    note: str | None = Field(default=None, max_length=300)


class AlarmRuleItemOut(ApiModel):
    id: int
    stage: int
    position: int
    kind: RuleItemKind
    count: int
    target_id: uuid.UUID
    target_label: str
    note: str | None


class AreaRef(ApiModel):
    id: uuid.UUID
    name: str


class AlarmRuleCreate(ApiModel):
    control_center_id: uuid.UUID
    keyword_id: uuid.UUID
    area_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=200)
    is_active: bool = True
    items: list[AlarmRuleItemIn] = Field(default_factory=list, max_length=100)


class AlarmRuleUpdate(VersionedUpdate):
    name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    items: list[AlarmRuleItemIn] | None = Field(default=None, max_length=100)


class AlarmRuleOut(ApiModel):
    id: uuid.UUID
    control_center_id: uuid.UUID
    keyword: KeywordRef
    area: AreaRef | None
    name: str | None
    is_active: bool
    items: list[AlarmRuleItemOut]
    max_stage: int
    created_at: datetime
    updated_at: datetime
    version: int


# ---------------------------------------------------------------------------- alarms
class AlarmSelection(ApiModel):
    """Explicitly chosen targets. RICs of the chosen vehicles/stations and the interfaces
    responsible for them are always added by the server."""

    vehicle_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    station_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    ric_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    interface_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class PreviewRequest(ApiModel):
    stage: int | None = Field(default=None, ge=1, le=9, description="Leer = nächste Stufe laut AAO")
    selection: AlarmSelection | None = Field(
        default=None, description="Leer = Vorschlag aus der AAO; sonst genau diese Auswahl prüfen"
    )


class PreviewVehicle(ApiModel):
    id: uuid.UUID
    call_sign: str
    vehicle_type: str
    station_id: uuid.UUID
    station: str
    status_code: int
    distance_km: float | None
    travel_seconds: int | None = None
    travel_source: Literal["osrm", "estimate", "none"] | None = None
    reason: str
    assigned: bool


class PreviewTarget(ApiModel):
    id: uuid.UUID
    label: str
    reason: str


class PreviewInterface(ApiModel):
    id: uuid.UUID
    name: str
    plugin_name: str
    is_real: bool
    effect: Literal["deliver", "simulate", "redirect", "skip"]
    reason: str


class RuleRef(ApiModel):
    id: uuid.UUID
    name: str | None
    area: str | None


class AlarmPreview(ApiModel):
    incident_id: uuid.UUID
    incident_number: str
    incident_version: int
    keyword: KeywordRef | None
    rule: RuleRef | None
    stage: int | None
    max_stage: int
    next_kind: Literal["initial", "follow_up"]
    mode: Literal["simulation", "real"]
    vehicles: list[PreviewVehicle]
    stations: list[PreviewTarget]
    rics: list[PreviewTarget]
    interfaces: list[PreviewInterface]
    already_alarmed: list[str]
    police_notice: str | None
    warnings: list[str]
    selection: AlarmSelection


class AlarmCreate(AlarmSelection):
    stage: int | None = Field(default=None, ge=1, le=9)
    note: str | None = Field(default=None, max_length=1000)
    reassign: bool = Field(default=False, description="Fahrzeuge aus anderen Einsätzen umsetzen")
    confirmed: Literal[True] = Field(description="Bestätigung durch den Disponenten (Pflicht)")

    @model_validator(mode="after")
    def _not_empty(self) -> AlarmCreate:
        if not (self.vehicle_ids or self.station_ids or self.ric_ids or self.interface_ids):
            raise ValueError("Keine Alarmierungsziele ausgewählt")
        return self


class AlarmTargetOut(ApiModel):
    id: int
    target_type: Literal["vehicle", "station", "ric", "interface"]
    target_id: str
    label: str
    reason: str | None
    delivery_status: DeliveryStatus
    detail: str | None
    delivered_at: datetime | None


class PoliceNoticeOut(ApiModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    incident_number: str
    control_center_id: uuid.UUID
    keyword_code: str
    text: str
    created_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by_name: str | None
    note: str | None


class AlarmOut(ApiModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    incident_number: str
    control_center_id: uuid.UUID
    kind: Literal["initial", "follow_up", "manual"]
    stage: int | None
    mode: Literal["simulation", "real"]
    status: Literal["pending", "completed", "partial"]
    note: str | None
    triggered_by_name: str
    created_at: datetime
    targets: list[AlarmTargetOut]
    replayed: bool = False
    police_notice: PoliceNoticeOut | None = None


class PoliceAcknowledge(ApiModel):
    note: str | None = Field(default=None, max_length=1000)


# ------------------------------------------------------------------------ interfaces
class PluginOut(ApiModel):
    key: str
    name: str
    description: str
    is_real: bool
    scopes: list[InterfaceScope]
    config_schema: dict[str, Any]
    secret_label: str | None
    secret_required: bool
    capabilities: list[str]


class InterfaceCreate(ApiModel):
    plugin_key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=2, max_length=200)
    scope: InterfaceScope
    control_center_id: uuid.UUID | None = None
    station_id: uuid.UUID | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    secret: str | None = Field(
        default=None, min_length=1, max_length=4000, description="wird verschlüsselt gespeichert"
    )


class InterfaceUpdate(VersionedUpdate):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    config: dict[str, Any] | None = None
    secret: str | None = Field(default=None, min_length=1, max_length=4000)
    clear_secret: bool = False


class InterfaceToggle(VersionedUpdate):
    enabled: bool
    reason: str | None = Field(default=None, max_length=500)


class InterfaceOut(ApiModel):
    id: uuid.UUID
    plugin_key: str
    plugin_name: str
    is_real: bool
    name: str
    scope: InterfaceScope
    control_center_id: uuid.UUID | None
    station_id: uuid.UUID | None
    station_name: str | None
    enabled: bool
    effective: bool
    config: dict[str, Any]
    has_secret: bool
    secret_hint: str | None
    status: Literal["unknown", "ok", "error"]
    last_ok_at: datetime | None
    last_error: str | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class InterfaceEventOut(ApiModel):
    id: int
    ts: datetime
    level: Literal["info", "warning", "error"]
    kind: str
    message: str


class InterfaceTestResult(ApiModel):
    ok: bool
    detail: str
    interface: InterfaceOut
