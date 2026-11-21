"""Plugin contract for external interfaces (Schnittstellen).

A plugin describes itself (``PluginMeta``: name, whether it reaches *real* systems, its
configuration as JSON Schema, the label of its secret) and implements ``test`` and
``send_alarm``. Plugins never decide whether they may run: the core (``interface_service``)
enforces the simulation/real separation, retries and logging for every plugin.

External plugins are Python packages exposing an entry point in the group
``ils_sim.plugins`` that returns an object implementing :class:`InterfacePlugin`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PluginMeta:
    key: str
    name: str
    description: str
    is_real: bool  # True = contacts real external systems (only allowed in real operation)
    config_schema: dict[str, Any]
    scopes: tuple[str, ...] = ("global", "control_center", "station")
    secret_label: str | None = None
    secret_required: bool = False
    capabilities: tuple[str, ...] = ("alarm",)


@dataclass(frozen=True, slots=True)
class AlarmMessage:
    alarm_id: str
    control_center: str
    incident_number: str
    keyword: str | None
    keyword_name: str | None
    incident_type: str
    priority: int
    address: str | None
    location_note: str | None
    latitude: float | None
    longitude: float | None
    description: str | None
    stage: int | None
    mode: str  # simulation | real
    created_at: datetime
    vehicles: list[str] = field(default_factory=list)
    stations: list[str] = field(default_factory=list)
    rics: list[str] = field(default_factory=list)
    kind: str = "initial"  # initial | follow_up | manual

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    ok: bool
    detail: str
    external_id: str | None = None
    # False: repeating the same request cannot succeed (e.g. invalid token, validation error) –
    # the core then stops retrying instead of burning the receiver's rate limit.
    retryable: bool = True


@runtime_checkable
class InterfacePlugin(Protocol):
    meta: PluginMeta

    async def test(self, config: dict[str, Any], secret: str | None) -> DeliveryResult: ...

    async def send_alarm(
        self, config: dict[str, Any], secret: str | None, message: AlarmMessage
    ) -> DeliveryResult: ...
