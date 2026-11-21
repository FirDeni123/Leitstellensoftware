"""Alarm preview, confirmed alarms (Alarmierung) and police notices.

Principles
* The system never alarms on its own. The preview is only a proposal from the AAO; an alarm
  is created exclusively by an explicit, confirmed request of a dispatcher
  (``confirmed: true`` + ``Idempotency-Key``).
* The police are never alarmed: organisations that are not alarmable (police) are rejected as
  targets. Keywords marked with ``police_notice`` only produce an information notice that the
  dispatcher has to acknowledge – nothing is transmitted.
* Deliveries to interfaces run after the commit (``alarm_delivery``); the alarm record and the
  incident history are written first, so nothing is lost if an interface hangs.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.geo import haversine_m
from app.models import (
    Alarm,
    AlarmGroup,
    AlarmRule,
    AlarmTarget,
    Incident,
    IncidentEvent,
    IncidentVehicle,
    Interface,
    OperationMode,
    PoliceNotice,
    Ric,
    Station,
    Vehicle,
)
from app.plugins.registry import get_plugin
from app.proposal.travel import RoutingProvider
from app.schemas.alarming import AlarmCreate, AlarmSelection
from app.services.aao import active_assignments
from app.services.alarm_rule_service import target_label
from app.services.incident_service import NO_ASSIGNMENT_STATUSES, STATUS_LABEL, IncidentService
from app.services.interface_service import is_effective
from app.services.proposal_service import Computation, ProposalService
from app.services.uow import UnitOfWork

KIND_LABEL = {"initial": "Erstalarm", "follow_up": "Nachalarmierung", "manual": "Alarmierung"}
DELIVERY_LABEL = {
    "simulated": "simuliert",
    "sent": "übertragen",
    "failed": "fehlgeschlagen",
    "skipped": "nicht übertragen",
    "not_delivered": "nicht zugestellt",
    "pending": "ausstehend",
}
DEFAULT_POLICE_TEXT = "Polizei informieren."
POLICE_DISCLAIMER = (
    "Keine Übermittlung durch das System – die Information der Polizei liegt beim Disponenten."
)


def ric_label(ric: Ric) -> str:
    return target_label("ric", ric)


def alarm_status(targets: list[AlarmTarget]) -> str:
    statuses = {t.delivery_status for t in targets}
    if "pending" in statuses:
        return "pending"
    return "partial" if statuses & {"failed", "not_delivered"} else "completed"


def police_text(keyword: Any) -> str:
    return (keyword.police_notice_text or "").strip() or DEFAULT_POLICE_TEXT


@dataclass(slots=True)
class Composition:
    rule: AlarmRule | None = None
    area_name: str | None = None
    stage: int | None = None
    max_stage: int = 0
    next_kind: str = "initial"
    vehicles: list[tuple[Vehicle, str, bool, float | None]] = field(
        default_factory=list
    )  # reason, assigned, km
    stations: list[tuple[Station, str]] = field(default_factory=list)
    rics: dict[uuid.UUID, tuple[Ric, str]] = field(default_factory=dict)
    interfaces: dict[uuid.UUID, tuple[Interface, str]] = field(default_factory=dict)
    explicit_ric_ids: list[uuid.UUID] = field(default_factory=list)
    explicit_interface_ids: list[uuid.UUID] = field(default_factory=list)
    already_alarmed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    travel: dict[uuid.UUID, tuple[int, str]] = field(default_factory=dict)  # seconds, source

    def selection(self) -> AlarmSelection:
        return AlarmSelection(
            vehicle_ids=[v.id for v, *_ in self.vehicles],
            station_ids=[s.id for s, _ in self.stations],
            ric_ids=list(self.explicit_ric_ids),
            interface_ids=list(self.explicit_interface_ids),
        )


class AlarmService:
    def __init__(
        self,
        uow: UnitOfWork,
        visible: set[uuid.UUID] | None,
        timezone: str = "Europe/Berlin",
        routing: RoutingProvider | None = None,
    ) -> None:
        self.uow = uow
        self.s = uow.session
        self.visible = visible
        self.routing = routing
        self.timezone = timezone
        self.incidents = IncidentService(uow, visible, timezone)

    async def _mode(self) -> OperationMode:
        from app.services.system_service import SystemService

        return await SystemService(self.uow).operation_mode()

    # ------------------------------------------------------------------------ lookups
    async def _active_assignments(self, incident: Incident) -> list[IncidentVehicle]:
        return await active_assignments(self.s, incident)

    def _distance_km(self, incident: Incident, vehicle: Vehicle) -> float | None:
        if incident.latitude is None or incident.longitude is None:
            return None
        lat = vehicle.latitude if vehicle.latitude is not None else vehicle.station.latitude
        lon = vehicle.longitude if vehicle.longitude is not None else vehicle.station.longitude
        if lat is None or lon is None:
            return None
        return round(haversine_m(incident.latitude, incident.longitude, lat, lon) / 1000, 1)

    # --------------------------------------------------------------------- composition
    async def compose(
        self, incident: Incident, stage: int | None, selection: AlarmSelection | None, mode: OperationMode
    ) -> Composition:
        comp = Composition()
        # Vehicle demand is computed by the Einsatzmittelvorschlag (same scoring and reasons).
        computation = await ProposalService(self.uow, self.visible, self.routing, self.timezone).compute(
            incident, stage, []
        )
        comp.rule, comp.area_name = computation.rule, computation.area_name
        comp.max_stage, comp.next_kind, comp.stage = (
            computation.max_stage,
            computation.next_kind,
            computation.stage,
        )
        stage = computation.stage

        active = await self._active_assignments(incident)
        alarmed = {a.vehicle_id for a in active if a.alarmed_at is not None}
        comp.already_alarmed = [a.vehicle.call_sign for a in active if a.alarmed_at is not None]
        in_incident = {a.vehicle_id: a.vehicle for a in active}

        proposal = await self._propose(incident, comp, stage, active, computation)
        reasons = {v.id: reason for v, reason in proposal["vehicles"]}
        if selection is None:
            chosen_vehicles = [v for v, _ in proposal["vehicles"]]
            chosen_stations = proposal["stations"]
            comp.explicit_ric_ids = [r.id for r, _ in proposal["rics"]]
            comp.explicit_interface_ids = [i.id for i, _ in proposal["interfaces"]]
            explicit_rics = proposal["rics"]
            explicit_interfaces = proposal["interfaces"]
        else:
            chosen_vehicles = await self._load(Vehicle, selection.vehicle_ids, incident, "Fahrzeuge")
            station_reason = {s.id: r for s, r in proposal["stations"]}
            chosen_stations = [
                (st, station_reason.get(st.id, "manuell gewählt"))
                for st in await self._load(Station, selection.station_ids, incident, "Wachen")
            ]
            ric_reason = {r.id: why for r, why in proposal["rics"]}
            explicit_rics = [
                (r, ric_reason.get(r.id, "manuell gewählt"))
                for r in await self._load(Ric, selection.ric_ids, incident, "RICs")
            ]
            iface_reason = {i.id: why for i, why in proposal["interfaces"]}
            explicit_interfaces = [
                (i, iface_reason.get(i.id, "manuell gewählt"))
                for i in await self._load_interfaces(selection.interface_ids, incident)
            ]
            comp.explicit_ric_ids = [r.id for r, _ in explicit_rics]
            comp.explicit_interface_ids = [i.id for i, _ in explicit_interfaces]
        comp.warnings.extend(proposal["warnings"] if selection is None else [])
        for pick in computation.result.picks:
            if pick.travel is not None and pick.travel.seconds is not None:
                comp.travel[pick.unit.id] = (round(pick.travel.seconds), pick.travel.source)

        for vehicle in chosen_vehicles:
            if vehicle.id in alarmed:
                reason = "bereits alarmiert – erneute Alarmierung"
            else:
                reason = reasons.get(vehicle.id) or (
                    "zugeordnet" if vehicle.id in in_incident else "manuell gewählt"
                )
            comp.vehicles.append(
                (vehicle, reason, vehicle.id in in_incident, self._distance_km(incident, vehicle))
            )
        comp.stations = chosen_stations
        await self._check_targets(comp)

        # Derived RICs: vehicle RICs (or the station's when the vehicle has none) and station RICs.
        for vehicle, *_ in comp.vehicles:
            if vehicle.rics:
                for ric in vehicle.rics:
                    self._add_ric(comp, ric, f"RIC von {vehicle.call_sign}")
            else:
                for ric in vehicle.station.rics:
                    self._add_ric(
                        comp, ric, f"RIC der Wache {vehicle.station.name} (für {vehicle.call_sign})"
                    )
        for station, _ in comp.stations:
            for ric in station.rics:
                self._add_ric(comp, ric, f"RIC der Wache {station.name}")
        for ric, why in explicit_rics:
            self._add_ric(comp, ric, why)

        # Interfaces: explicitly chosen + every enabled interface responsible for the alarm.
        for interface, why in explicit_interfaces:
            comp.interfaces.setdefault(interface.id, (interface, why))
        station_ids = {v.station_id for v, *_ in comp.vehicles} | {s.id for s, _ in comp.stations}
        responsible = (
            await self.s.scalars(
                select(Interface).where(
                    Interface.enabled.is_(True),
                    or_(
                        Interface.scope == "global",
                        (Interface.scope == "control_center")
                        & (Interface.control_center_id == incident.control_center_id),
                        (Interface.scope == "station")
                        & (Interface.station_id.in_(station_ids or {uuid.uuid4()})),
                    ),
                )
            )
        ).all()
        for interface in sorted(responsible, key=lambda i: (i.scope, i.name)):
            reason = {
                "global": "systemweite Schnittstelle",
                "control_center": "Schnittstelle der Leitstelle",
                "station": "Schnittstelle der beteiligten Wache",
            }[interface.scope]
            comp.interfaces.setdefault(interface.id, (interface, reason))

        self._mode_warnings(comp, mode)
        if not (comp.vehicles or comp.stations or comp.rics or comp.interfaces):
            comp.warnings.append("Keine Alarmierungsziele – bitte Fahrzeuge oder Wachen auswählen")
        return comp

    async def _propose(
        self,
        incident: Incident,
        comp: Composition,
        stage: int | None,
        active: list[IncidentVehicle],
        computation: Computation,
    ) -> dict[str, list[Any]]:
        vehicles: list[tuple[Vehicle, str]] = []
        stations: list[tuple[Station, str]] = []
        rics: list[tuple[Ric, str]] = []
        interfaces: list[tuple[Interface, str]] = []
        warnings: list[str] = []
        picked: set[uuid.UUID] = set()
        warnings.extend(computation.warnings)
        warnings.extend(s.message for s in computation.result.shortfalls)
        for pick in computation.result.picks:
            if pick.alarmed:
                continue  # already alarmed – nothing to do
            vehicle = await self.s.get(Vehicle, pick.unit.id)
            if vehicle is not None and vehicle.id not in picked:
                vehicles.append((vehicle, " · ".join(pick.reasons)))
                picked.add(vehicle.id)
        rule = comp.rule
        if rule is not None and stage:
            for item in [i for i in rule.items if i.stage <= stage]:
                why = f"AAO Stufe {item.stage}"
                if item.kind in ("vehicle_type", "vehicle"):
                    continue  # handled by the Einsatzmittelvorschlag above
                if item.kind == "station":
                    station = await self.s.get(Station, item.station_id)
                    if station is not None and station.is_active:
                        if all(s.id != station.id for s, _ in stations):
                            stations.append((station, why))
                    else:
                        warnings.append(f"Wache aus {why} ist nicht aktiv")
                elif item.kind == "ric":
                    ric = await self.s.get(Ric, item.ric_id)
                    if ric is not None:
                        rics.append((ric, why))
                elif item.kind == "alarm_group":
                    group = await self.s.get(AlarmGroup, item.alarm_group_id)
                    if group is not None:
                        rics.extend((ric, f"{why}: Alarmierungsgruppe {group.name}") for ric in group.rics)
                elif item.kind == "interface":
                    interface = await self.s.get(Interface, item.interface_id)
                    if interface is not None:
                        interfaces.append((interface, why))
        # Manually assigned vehicles that are not alarmed yet are part of the proposal as well.
        for assignment in active:
            if assignment.alarmed_at is None and assignment.vehicle_id not in picked:
                vehicles.append((assignment.vehicle, "zugeordnet"))
                picked.add(assignment.vehicle_id)
        return {
            "vehicles": vehicles,
            "stations": stations,
            "rics": rics,
            "interfaces": interfaces,
            "warnings": warnings,
        }

    async def _type_code(self, vehicle_type_id: uuid.UUID | None) -> str:
        from app.models import VehicleType

        vt = await self.s.get(VehicleType, vehicle_type_id) if vehicle_type_id else None
        return vt.code if vt else "Fahrzeugtyp"

    async def _load(self, model: Any, ids: list[uuid.UUID], incident: Incident, label: str) -> list[Any]:
        unique = list(dict.fromkeys(ids))
        if not unique:
            return []
        rows = {r.id: r for r in (await self.s.scalars(select(model).where(model.id.in_(unique)))).all()}
        if len(rows) != len(unique):
            raise ValidationFailedError(f"Unbekannte {label}")
        for row in rows.values():
            if row.control_center_id != incident.control_center_id:
                raise ValidationFailedError(f"{label}: Ziel aus einer anderen Leitstelle")
        return [rows[i] for i in unique]

    async def _load_interfaces(self, ids: list[uuid.UUID], incident: Incident) -> list[Interface]:
        unique = list(dict.fromkeys(ids))
        if not unique:
            return []
        rows = {
            r.id: r for r in (await self.s.scalars(select(Interface).where(Interface.id.in_(unique)))).all()
        }
        if len(rows) != len(unique):
            raise ValidationFailedError("Unbekannte Schnittstellen")
        for row in rows.values():
            if row.control_center_id not in (None, incident.control_center_id):
                raise ValidationFailedError("Schnittstelle aus einer anderen Leitstelle")
        return [rows[i] for i in unique]

    async def _check_targets(self, comp: Composition) -> None:
        for vehicle, *_ in comp.vehicles:
            if not vehicle.organization.alarmable:
                raise ValidationFailedError(
                    f"{vehicle.call_sign}: {vehicle.organization.name} wird nicht alarmiert "
                    "(Polizei nur als Informationshinweis)"
                )
        for station, _ in comp.stations:
            if not station.organization.alarmable:
                raise ValidationFailedError(
                    f"{station.name}: {station.organization.name} wird nicht alarmiert "
                    "(Polizei nur als Informationshinweis)"
                )

    @staticmethod
    def _add_ric(comp: Composition, ric: Ric, reason: str) -> None:
        if ric.is_active and ric.id not in comp.rics:
            comp.rics[ric.id] = (ric, reason)
        elif not ric.is_active:
            message = f"RIC {ric_label(ric)} ist deaktiviert und wird nicht ausgelöst"
            if message not in comp.warnings:
                comp.warnings.append(message)

    @staticmethod
    def _mode_warnings(comp: Composition, mode: OperationMode) -> None:
        if mode != OperationMode.REAL:
            return
        real_effective = [
            i
            for i, _ in comp.interfaces.values()
            if is_effective(i, mode) and get_plugin(i.plugin_key).meta.is_real
        ]
        if not real_effective:
            comp.warnings.append(
                "ECHTBETRIEB: Keine aktive reale Schnittstelle zuständig – "
                "die Alarmierung wird nicht real übertragen"
            )
        if comp.rics:
            comp.warnings.append(
                "ECHTBETRIEB: Funkalarmierung (POCSAG/TETRA) ist nicht angebunden – "
                "RICs werden nur protokolliert"
            )

    @staticmethod
    def interface_effect(interface: Interface, mode: OperationMode) -> str:
        if not interface.enabled:
            return "skip"
        if get_plugin(interface.plugin_key).meta.is_real:
            return "deliver" if mode == OperationMode.REAL else "redirect"
        return "simulate"

    # ------------------------------------------------------------------------ preview
    async def preview(
        self, incident_id: uuid.UUID, stage: int | None, selection: AlarmSelection | None
    ) -> dict[str, Any]:
        mode = await self._mode()
        incident = await self.incidents.get(incident_id)
        comp = await self.compose(incident, stage, selection, mode)
        effect_text = {
            "skip": "deaktiviert – wird nicht übertragen",
            "redirect": "reale Schnittstelle – im Simulationsbetrieb umgeleitet",
            "deliver": "reale Übertragung",
            "simulate": "simuliert",
        }
        keyword = incident.keyword
        return {
            "incident_id": incident.id,
            "incident_number": incident.number,
            "incident_version": incident.version,
            "keyword": keyword,
            "rule": {"id": comp.rule.id, "name": comp.rule.name, "area": comp.area_name}
            if comp.rule
            else None,
            "stage": comp.stage,
            "max_stage": comp.max_stage,
            "next_kind": comp.next_kind,
            "mode": mode.value,
            "vehicles": [
                {
                    "id": v.id,
                    "call_sign": v.call_sign,
                    "vehicle_type": v.vehicle_type.code,
                    "station_id": v.station_id,
                    "station": v.station.name,
                    "status_code": v.status_code,
                    "distance_km": km,
                    "travel_seconds": comp.travel.get(v.id, (None, None))[0],
                    "travel_source": comp.travel.get(v.id, (None, None))[1],
                    "reason": reason,
                    "assigned": assigned,
                }
                for v, reason, assigned, km in comp.vehicles
            ],
            "stations": [{"id": s.id, "label": s.name, "reason": why} for s, why in comp.stations],
            "rics": [{"id": r.id, "label": ric_label(r), "reason": why} for r, why in comp.rics.values()],
            "interfaces": [
                {
                    "id": i.id,
                    "name": i.name,
                    "plugin_name": get_plugin(i.plugin_key).meta.name,
                    "is_real": get_plugin(i.plugin_key).meta.is_real,
                    "effect": (effect := self.interface_effect(i, mode)),
                    "reason": f"{why} · {effect_text[effect]}",
                }
                for i, why in comp.interfaces.values()
            ],
            "already_alarmed": comp.already_alarmed,
            "police_notice": police_text(keyword) if keyword and keyword.police_notice else None,
            "warnings": comp.warnings,
            "selection": comp.selection(),
        }

    # ------------------------------------------------------------------------ trigger
    async def trigger(
        self, incident_id: uuid.UUID, body: AlarmCreate, idempotency_key: str
    ) -> tuple[Alarm, bool]:
        mode = await self._mode()  # read before locking (may initialise the setting)
        payload = body.model_dump(mode="json")
        request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        incident = await self.incidents.get(incident_id, lock=True)
        existing = await self.s.scalar(
            select(Alarm).where(Alarm.incident_id == incident.id, Alarm.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError(
                    "Dieser Idempotency-Key wurde bereits für eine andere Alarmierung verwendet"
                )
            return existing, True
        if incident.status in NO_ASSIGNMENT_STATUSES:
            raise ConflictError("Beendete oder abgeschlossene Einsätze können nicht alarmiert werden")

        comp = await self.compose(incident, body.stage, body, mode)
        new_vehicle_ids = [v.id for v, _, assigned, _ in comp.vehicles if not assigned]
        if new_vehicle_ids:
            await self.incidents.assign_vehicles(incident, new_vehicle_ids, body.reassign)
        now = datetime.now(UTC)
        assignments = {a.vehicle_id: a for a in await self._active_assignments(incident)}
        for vehicle, *_ in comp.vehicles:
            assignment = assignments.get(vehicle.id)
            if assignment is not None and assignment.alarmed_at is None:
                assignment.alarmed_at = now

        alarm = Alarm(
            id=uuid.uuid4(),
            incident_id=incident.id,
            control_center_id=incident.control_center_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            kind=comp.next_kind,
            stage=comp.stage if body.stage is not None or comp.rule is not None else None,
            mode=mode.value,
            note=body.note,
            triggered_by=self.uow.actor.user_id,
            triggered_by_name=self.uow.actor.name,
            created_at=now,
        )
        simulated = mode != OperationMode.REAL
        logical = (
            ("simulated", "Simulierte Alarmierung")
            if simulated
            else (
                "skipped",
                "Logisches Ziel – Übertragung nur über die zuständigen Schnittstellen",
            )
        )
        targets: list[AlarmTarget] = []
        for vehicle, reason, _, _ in comp.vehicles:
            targets.append(
                self._target(
                    "vehicle",
                    vehicle.id,
                    f"{vehicle.call_sign} ({vehicle.vehicle_type.code})",
                    reason,
                    *logical,
                    now,
                )
            )
        for station, reason in comp.stations:
            targets.append(self._target("station", station.id, station.name, reason, *logical, now))
        for ric, reason in comp.rics.values():
            if simulated:
                targets.append(
                    self._target(
                        "ric",
                        ric.id,
                        ric_label(ric),
                        reason,
                        "simulated",
                        "Meldeempfänger simuliert ausgelöst",
                        now,
                    )
                )
            else:
                targets.append(
                    self._target(
                        "ric",
                        ric.id,
                        ric_label(ric),
                        reason,
                        "not_delivered",
                        "Funkalarmierung nicht angebunden (nicht umgesetzt)",
                        None,
                    )
                )
        for interface, reason in comp.interfaces.values():
            if interface.enabled:
                targets.append(
                    self._target("interface", interface.id, interface.name, reason, "pending", None, None)
                )
            else:
                targets.append(
                    self._target(
                        "interface",
                        interface.id,
                        interface.name,
                        reason,
                        "skipped",
                        "Schnittstelle deaktiviert – nicht übertragen",
                        None,
                    )
                )
        alarm.targets = targets
        alarm.status = alarm_status(targets)
        self.s.add(alarm)

        if incident.status in ("new", "in_progress"):
            old = incident.status
            incident.status = "alarmed"
            incident.status_changed_at = now
            self.incidents.event(
                incident,
                "status",
                f"Status: {STATUS_LABEL[old]} → {STATUS_LABEL['alarmed']} (Alarmierung)",
                {"from": old, "to": "alarmed"},
            )
        incident.updated_at = now
        text = self._alarm_text(alarm, comp, mode)
        self.incidents.event(incident, "alarm", text, {"alarm_id": str(alarm.id), "mode": mode.value})
        notice = await self._police_notice(incident)
        self.uow.audit(
            "alarm",
            "incident",
            incident.id,
            f"Einsatz {incident.number}: {text}",
            control_center_id=incident.control_center_id,
        )
        self.incidents.emit(incident, "alarm")
        self.uow.emit(
            "alarm.changed",
            {
                "id": str(alarm.id),
                "incident_id": str(incident.id),
                "status": alarm.status,
                "action": "created",
            },
            channels=[f"cc:{incident.control_center_id}"],
            required_permission="incidents.read",
        )
        if notice is not None:
            self.uow.emit(
                "police_notice.changed",
                {
                    "id": str(notice.id),
                    "incident_id": str(incident.id),
                    "action": "created",
                    "for_user": str(self.uow.actor.user_id) if self.uow.actor.user_id else None,
                },
                channels=[f"cc:{incident.control_center_id}"],
                required_permission="incidents.read",
            )
        try:
            await self.uow.commit()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError(
                "Alarmierung wurde gleichzeitig ausgelöst oder ein Fahrzeug wurde gleichzeitig "
                "einem anderen Einsatz zugeordnet – bitte neu laden"
            ) from exc
        await self.s.refresh(alarm)
        return alarm, False

    @staticmethod
    def _target(
        kind: str,
        target_id: uuid.UUID,
        label: str,
        reason: str | None,
        status: str,
        detail: str | None,
        delivered_at: datetime | None,
    ) -> AlarmTarget:
        return AlarmTarget(
            target_type=kind,
            target_id=str(target_id),
            label=label[:300],
            reason=(reason or "")[:300] or None,
            delivery_status=status,
            detail=detail,
            delivered_at=delivered_at if status in ("simulated", "sent") else None,
        )

    @staticmethod
    def _alarm_text(alarm: Alarm, comp: Composition, mode: OperationMode) -> str:
        head = KIND_LABEL[alarm.kind]
        details = []
        if alarm.stage:
            details.append(f"Stufe {alarm.stage}")
        if comp.rule is not None:
            details.append(
                f"AAO {comp.rule.keyword.code}" + (f" / {comp.area_name}" if comp.area_name else "")
            )
        head += f" ({', '.join(details)})" if details else ""
        head += " [Simulation]" if mode != OperationMode.REAL else " [ECHTBETRIEB]"
        parts = []
        if comp.vehicles:
            parts.append("Fahrzeuge " + ", ".join(v.call_sign for v, *_ in comp.vehicles))
        if comp.stations:
            parts.append("Wachen " + ", ".join(s.name for s, _ in comp.stations))
        if comp.rics:
            parts.append(
                "RIC "
                + ", ".join(
                    r.code + (f"/{r.sub_address}" if r.sub_address else "") for r, _ in comp.rics.values()
                )
            )
        if comp.interfaces:
            parts.append("Schnittstellen " + ", ".join(i.name for i, _ in comp.interfaces.values()))
        return head + ": " + "; ".join(parts)

    async def _police_notice(self, incident: Incident) -> PoliceNotice | None:
        keyword = incident.keyword
        if keyword is None or not keyword.police_notice:
            return None
        exists = await self.s.scalar(
            select(PoliceNotice.id).where(
                PoliceNotice.incident_id == incident.id, PoliceNotice.keyword_code == keyword.code
            )
        )
        if exists is not None:
            return None
        notice = PoliceNotice(
            id=uuid.uuid4(),
            incident_id=incident.id,
            control_center_id=incident.control_center_id,
            keyword_code=keyword.code,
            text=police_text(keyword),
        )
        self.s.add(notice)
        self.incidents.event(
            incident,
            "police_notice",
            f"Hinweis „Polizei informieren“ ({keyword.code}): {notice.text} {POLICE_DISCLAIMER}",
            {"police_notice_id": str(notice.id)},
        )
        return notice

    # ------------------------------------------------------------------------- queries
    async def get(self, alarm_id: uuid.UUID) -> Alarm:
        alarm = await self.s.get(Alarm, alarm_id)
        if alarm is None:
            raise NotFoundError("Alarmierung nicht gefunden")
        self.incidents._check_cc(alarm.control_center_id)
        return alarm

    async def list(
        self, control_center_id: uuid.UUID | None, incident_id: uuid.UUID | None, limit: int
    ) -> list[Alarm]:
        stmt = select(Alarm)
        if incident_id is not None:
            await self.incidents.get(incident_id)
            stmt = stmt.where(Alarm.incident_id == incident_id)
        if control_center_id is not None:
            self.incidents._check_cc(control_center_id)
            stmt = stmt.where(Alarm.control_center_id == control_center_id)
        elif self.visible is not None:
            stmt = stmt.where(Alarm.control_center_id.in_(self.visible or {uuid.uuid4()}))
        stmt = stmt.order_by(Alarm.created_at.desc()).limit(limit)
        return list((await self.s.scalars(stmt)).all())

    async def numbers(self, incident_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not incident_ids:
            return {}
        rows = await self.s.execute(select(Incident.id, Incident.number).where(Incident.id.in_(incident_ids)))
        return dict(rows.tuples().all())

    async def notices_for(self, incident_ids: set[uuid.UUID]) -> list[PoliceNotice]:
        if not incident_ids:
            return []
        stmt = (
            select(PoliceNotice)
            .where(PoliceNotice.incident_id.in_(incident_ids))
            .order_by(PoliceNotice.created_at)
        )
        return list((await self.s.scalars(stmt)).all())

    # ------------------------------------------------------------------ police notices
    async def police_notices(
        self, control_center_id: uuid.UUID | None, only_open: bool, limit: int
    ) -> list[PoliceNotice]:
        stmt = select(PoliceNotice)
        if control_center_id is not None:
            self.incidents._check_cc(control_center_id)
            stmt = stmt.where(PoliceNotice.control_center_id == control_center_id)
        elif self.visible is not None:
            stmt = stmt.where(PoliceNotice.control_center_id.in_(self.visible or {uuid.uuid4()}))
        if only_open:
            stmt = stmt.where(PoliceNotice.acknowledged_at.is_(None))
        return list((await self.s.scalars(stmt.order_by(PoliceNotice.created_at.desc()).limit(limit))).all())

    async def acknowledge(self, notice_id: uuid.UUID, note: str | None) -> PoliceNotice:
        notice = await self.s.scalar(
            select(PoliceNotice).where(PoliceNotice.id == notice_id).with_for_update()
        )
        if notice is None:
            raise NotFoundError("Polizei-Hinweis nicht gefunden")
        self.incidents._check_cc(notice.control_center_id)
        if notice.acknowledged_at is not None:
            raise ConflictError(f"Bereits bestätigt von {notice.acknowledged_by_name}")
        incident = await self.incidents.get(notice.incident_id)
        notice.acknowledged_at = datetime.now(UTC)
        notice.acknowledged_by = self.uow.actor.user_id
        notice.acknowledged_by_name = self.uow.actor.name
        notice.note = (note or "").strip() or None
        extra = f" Vermerk: {notice.note}" if notice.note else ""
        self.s.add(
            IncidentEvent(
                incident_id=incident.id,
                kind="police_ack",
                text=f"Polizei-Hinweis zur Kenntnis genommen ({notice.keyword_code}).{extra} "
                f"{POLICE_DISCLAIMER}",
                data={"police_notice_id": str(notice.id)},
                actor_user_id=self.uow.actor.user_id,
                actor_name=self.uow.actor.name,
            )
        )
        self.uow.audit(
            "acknowledge",
            "police_notice",
            notice.id,
            f"Einsatz {incident.number}: Polizei-Hinweis bestätigt (keine Übermittlung)",
            control_center_id=notice.control_center_id,
        )
        self.uow.emit(
            "police_notice.changed",
            {"id": str(notice.id), "incident_id": str(incident.id), "action": "acknowledged"},
            channels=[f"cc:{notice.control_center_id}"],
            required_permission="incidents.read",
        )
        self.incidents.emit(incident, "police_ack")
        await self.uow.commit()
        return notice
