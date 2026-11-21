"""Einsatzmittelvorschlag: loads data, runs the engine, stores and accepts proposals.

A proposal never alarms. Accepting it only assigns the vehicles to the incident; the alarm
is a separate, confirmed step (alarm preview → ``alarm.trigger``).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.models import (
    AlarmRule,
    ControlCenter,
    ControlCenterLink,
    Incident,
    Proposal,
    ProposalSettings,
    Vehicle,
    VehicleType,
)
from app.proposal.engine import Demand, EngineResult, InIncident, Option, Pick, Unit, allocate, fmt_duration
from app.proposal.settings import ProposalSettingsData
from app.proposal.travel import Point, RoutingProvider, Travel, estimate, travel_times
from app.services.aao import active_assignments, free_vehicles, next_stage, rule_for
from app.services.incident_service import IncidentService
from app.services.uow import UnitOfWork, check_version


def origin_of(vehicle: Vehicle) -> tuple[Point | None, str]:
    """Current vehicle position if it is tracked, otherwise the station."""
    has_own = vehicle.latitude is not None and vehicle.longitude is not None
    if has_own and vehicle.position_source != "station":
        return (vehicle.latitude, vehicle.longitude), "Fahrzeugposition"  # type: ignore[return-value]
    st = vehicle.station
    if st.latitude is not None and st.longitude is not None:
        return (st.latitude, st.longitude), "Wache"
    if has_own:
        return (vehicle.latitude, vehicle.longitude), "Fahrzeugposition"  # type: ignore[return-value]
    return None, "unbekannt"


def unit_of(vehicle: Vehicle, position: str = "Wache") -> Unit:
    return Unit(
        id=vehicle.id,
        call_sign=vehicle.call_sign,
        type_id=vehicle.vehicle_type_id,
        type_code=vehicle.vehicle_type.code,
        station_id=vehicle.station_id,
        station_name=vehicle.station.name,
        status_code=vehicle.status_code,
        position=position,
    )


def speed_of(vehicle: Vehicle) -> float:
    return float(vehicle.sim_speed_kmh or vehicle.vehicle_type.default_speed_kmh or 60)


@dataclass(slots=True)
class Computation:
    incident: Incident
    rule: AlarmRule | None
    area_name: str | None
    stage: int | None
    max_stage: int
    next_kind: str
    demands: list[Demand]
    result: EngineResult
    travel_source: str
    warnings: list[str]
    duration_ms: int
    settings: ProposalSettingsData
    candidates: int
    extra: list[dict[str, Any]] = field(default_factory=list)


class ProposalService:
    def __init__(
        self,
        uow: UnitOfWork,
        visible: set[uuid.UUID] | None,
        routing: RoutingProvider | None = None,
        timezone: str = "Europe/Berlin",
    ) -> None:
        self.uow = uow
        self.s = uow.session
        self.visible = visible
        self.routing = routing
        self.incidents = IncidentService(uow, visible, timezone)

    # ------------------------------------------------------------------------ settings
    async def settings_row(self, cc_id: uuid.UUID) -> ProposalSettings | None:
        return await self.s.scalar(
            select(ProposalSettings).where(ProposalSettings.control_center_id == cc_id)
        )

    async def settings_for(self, cc_id: uuid.UUID) -> ProposalSettingsData:
        row = await self.settings_row(cc_id)
        if row is None:
            return ProposalSettingsData()
        try:
            return ProposalSettingsData.model_validate(row.settings)
        except ValidationError:  # stored data from an older version – fall back to defaults
            return ProposalSettingsData()

    async def put_settings(
        self, cc_id: uuid.UUID, data: ProposalSettingsData, expected_version: int | None
    ) -> ProposalSettings:
        self.incidents._check_cc(cc_id)
        if await self.s.get(ControlCenter, cc_id) is None:
            raise NotFoundError("Leitstelle nicht gefunden")
        known = set((await self.s.scalars(select(VehicleType.code))).all())
        unknown = sorted({c for k, subs in data.substitutes.items() for c in [k, *subs]} - known)
        if unknown:
            raise ValidationFailedError(f"Unbekannte Fahrzeugtypen: {', '.join(unknown)}")
        row = await self.settings_row(cc_id)
        new = data.model_dump()
        if row is None:
            if expected_version is not None:
                raise ConflictError(
                    "Die Einstellungen wurden zwischenzeitlich zurückgesetzt – bitte neu laden"
                )
            row = ProposalSettings(control_center_id=cc_id, settings=new)
            self.s.add(row)
            old: dict[str, Any] = ProposalSettingsData().model_dump()
        else:
            if expected_version is None:
                raise ConflictError(
                    "Für diese Leitstelle gibt es bereits Einstellungen – bitte neu laden",
                    details={"current_version": row.version},
                )
            check_version(row, expected_version, "Die Vorschlagsregeln")
            old = dict(row.settings)
            row.settings = new
        row.updated_by_name = self.uow.actor.name
        changes = {k: {"old": old.get(k), "new": v} for k, v in new.items() if old.get(k) != v}
        await self.s.flush()
        self.uow.audit(
            "update",
            "proposal_settings",
            cc_id,
            "Regeln des Einsatzmittelvorschlags geändert",
            changes=changes,
            control_center_id=cc_id,
        )
        self.uow.emit(
            "master_data.changed",
            {"collection": "proposal-settings", "id": str(cc_id), "action": "updated"},
            channels=[f"cc:{cc_id}"],
        )
        await self.uow.commit()
        await self.s.refresh(row)
        return row

    # ------------------------------------------------------------------------- compute
    async def _demands(
        self, rule: AlarmRule | None, stage: int | None, extra: list[dict[str, Any]]
    ) -> tuple[list[Demand], set[uuid.UUID]]:
        items = [i for i in rule.items if stage and i.stage <= stage] if rule else []
        type_ids = {i.vehicle_type_id for i in items if i.vehicle_type_id} | {
            e["vehicle_type_id"] for e in extra
        }
        types = (
            {
                t.id: t
                for t in (await self.s.scalars(select(VehicleType).where(VehicleType.id.in_(type_ids)))).all()
            }
            if type_ids
            else {}
        )
        demands: list[Demand] = []
        preferred: set[uuid.UUID] = set()
        code = rule.keyword.code if rule else ""
        for item in items:
            source = f"AAO {code}, Stufe {item.stage}"
            if item.kind == "vehicle_type" and item.vehicle_type_id in types:
                t = types[item.vehicle_type_id]
                demands.append(Demand(f"aao:{item.id}", item.count, source, item.stage, t.id, t.code))
            elif item.kind == "vehicle" and item.vehicle_id:
                vehicle = await self.s.get(Vehicle, item.vehicle_id)
                label = vehicle.call_sign if vehicle else "Fahrzeug"
                demands.append(
                    Demand(
                        f"aao:{item.id}",
                        1,
                        source,
                        item.stage,
                        vehicle_id=item.vehicle_id,
                        vehicle_label=label,
                    )
                )
            elif item.kind == "station" and item.station_id:
                preferred.add(item.station_id)
        for i, e in enumerate(extra):
            t = types.get(e["vehicle_type_id"])
            if t is None:
                raise ValidationFailedError("Unbekannter Fahrzeugtyp im Zusatzbedarf")
            demands.append(Demand(f"extra:{i}", e["count"], "Zusatzbedarf", None, t.id, t.code))
        return demands, preferred

    async def compute(
        self, incident: Incident, stage: int | None, extra: list[dict[str, Any]] | None = None
    ) -> Computation:
        started = time.perf_counter()
        extra = extra or []
        settings = await self.settings_for(incident.control_center_id)
        rule, area_name = await rule_for(self.s, incident)
        max_stage = max((i.stage for i in rule.items), default=0) if rule else 0
        stage, kind, exhausted = await next_stage(self.s, incident, max_stage, stage)
        warnings: list[str] = []
        if exhausted:
            warnings.append("Alle Stufen der AAO wurden bereits alarmiert")
        if rule is None:
            if incident.keyword_id is None:
                warnings.append("Kein Stichwort gesetzt – Einsatzmittel bitte manuell auswählen")
            else:
                code = incident.keyword.code if incident.keyword else ""
                warnings.append(f"Keine AAO für {code} hinterlegt – Einsatzmittel bitte manuell auswählen")
        demands, preferred = await self._demands(rule, stage, extra)
        dest: Point | None = (
            (incident.latitude, incident.longitude)
            if incident.latitude is not None and incident.longitude is not None
            else None
        )
        if dest is None and demands:
            warnings.append("Einsatzort ohne Koordinaten – keine Fahrzeitberechnung möglich")

        active = await active_assignments(self.s, incident)
        in_incident = [
            InIncident(unit_of(a.vehicle, origin_of(a.vehicle)[1]), a.alarmed_at is not None) for a in active
        ]
        vehicles = await free_vehicles(self.s, incident.control_center_id) if demands else []
        # Pre-filter by straight line: n × demand nearest eligible candidates per demand line.
        subs = settings.substitutes
        origins = {v.id: origin_of(v) for v in vehicles}
        straight = {
            v.id: estimate(origins[v.id][0], dest, 60, 1.0, 1.0).straight_m if dest else None
            for v in vehicles
        }

        def eligible_for(d: Demand, v: Vehicle) -> bool:
            if d.vehicle_id:
                return v.id == d.vehicle_id
            return v.vehicle_type_id == d.type_id or v.vehicle_type.code in subs.get(d.type_code or "", [])

        chosen: dict[uuid.UUID, Vehicle] = {}
        for d in demands:
            eligible = [v for v in vehicles if eligible_for(d, v)]
            eligible.sort(key=lambda v: (straight[v.id] is None, straight[v.id] or 0, v.call_sign))
            limit = settings.candidates_per_demand * d.count if dest else len(eligible)
            for v in eligible[:limit]:
                chosen[v.id] = v
        units = [unit_of(v, origins[v.id][1]) for v in chosen.values()]
        routing = self.routing if settings.use_routing else None
        travel_list, routing_warning = await travel_times(
            [origins[v.id][0] for v in chosen.values()],
            [speed_of(v) for v in chosen.values()],
            dest,
            detour=settings.detour_factor,
            factor=settings.emergency_speed_factor,
            routing=routing,
        )
        if routing_warning:
            warnings.append(routing_warning)
        travel: dict[uuid.UUID, Travel] = {v_id: t for v_id, t in zip(chosen, travel_list, strict=True)}
        result = allocate(demands, in_incident, units, travel, settings, preferred)
        if result.too_far:
            warnings.append(
                f"{result.too_far} Fahrzeug(e) mit mehr als {settings.max_travel_minutes} min Fahrzeit "
                "nicht berücksichtigt"
            )
        await self._neighbour_hints(incident, result)
        sources = {t.source for t in travel_list if t.seconds is not None}
        travel_source = "none" if not sources else sources.pop() if len(sources) == 1 else "mixed"
        return Computation(
            incident=incident,
            rule=rule,
            area_name=area_name,
            stage=stage,
            max_stage=max_stage,
            next_kind=kind,
            demands=demands,
            result=result,
            travel_source=travel_source,
            warnings=warnings,
            duration_ms=round((time.perf_counter() - started) * 1000),
            settings=settings,
            candidates=len(units),
            extra=extra,
        )

    async def _neighbour_hints(self, incident: Incident, result: EngineResult) -> None:
        """Unmet demand: point to linked control centres with free vehicles (information only)."""
        if not result.shortfalls:
            return
        links = (
            await self.s.scalars(
                select(ControlCenterLink).where(
                    ControlCenterLink.from_control_center_id == incident.control_center_id
                )
            )
        ).all()
        neighbours = [link.to_control_center for link in links]
        for shortfall in result.shortfalls:
            hints = []
            for cc in neighbours:
                free = await free_vehicles(self.s, cc.id)
                d = shortfall.demand
                n = sum(
                    1
                    for v in free
                    if (v.id == d.vehicle_id if d.vehicle_id else v.vehicle_type_id == d.type_id)
                )
                if n:
                    hints.append(f"{cc.name}: {n} frei")
            shortfall.message += (
                f" – Unterstützung anfragen ({'; '.join(hints)})"
                if hints
                else " – Nachbarleitstelle anfragen"
            )

    # ---------------------------------------------------------------------- serialise
    @staticmethod
    def _pick_dict(p: Pick) -> dict[str, Any]:
        t = p.travel
        return {
            "demand_key": p.demand.key,
            "vehicle_id": str(p.unit.id),
            "call_sign": p.unit.call_sign,
            "vehicle_type": p.unit.type_code,
            "station_id": str(p.unit.station_id),
            "station": p.unit.station_name,
            "status_code": p.unit.status_code,
            "slot": p.slot,
            "match": p.match,
            "score_seconds": round(p.score) if p.score is not None else None,
            "travel_seconds": round(t.seconds) if t and t.seconds is not None else None,
            "distance_m": round(t.meters) if t and t.meters is not None else None,
            "travel_source": t.source if t else "none",
            "in_incident": p.in_incident,
            "alarmed": p.alarmed,
            "reasons": p.reasons,
        }

    @staticmethod
    def _option_dict(o: Option) -> dict[str, Any]:
        t = o.travel
        match = "Ersatztyp" if o.match == "substitute" else "passender Typ"
        return {
            "vehicle_id": str(o.unit.id),
            "call_sign": o.unit.call_sign,
            "vehicle_type": o.unit.type_code,
            "station": o.unit.station_name,
            "status_code": o.unit.status_code,
            "match": o.match,
            "score_seconds": round(o.score),
            "travel_seconds": round(t.seconds) if t.seconds is not None else None,
            "reason": f"{match}, Fahrzeit {fmt_duration(t.seconds)}, Status {o.unit.status_code}",
        }

    def serialise(self, c: Computation) -> dict[str, Any]:
        picks = c.result.picks
        return {
            "rule": {"id": str(c.rule.id), "name": c.rule.name, "area": c.area_name} if c.rule else None,
            "stage": c.stage,
            "max_stage": c.max_stage,
            "next_kind": c.next_kind,
            "travel_source": c.travel_source,
            "demands": [
                {
                    "key": d.key,
                    "label": d.label,
                    "source": d.source,
                    "count": d.count,
                    "stage": d.stage,
                    "covered": sum(1 for p in picks if p.demand.key == d.key),
                }
                for d in c.demands
            ],
            "picks": [self._pick_dict(p) for p in picks],
            "alternatives": {k: [self._option_dict(o) for o in v] for k, v in c.result.alternatives.items()},
            "shortfalls": [
                {
                    "demand_key": s.demand.key,
                    "label": s.demand.label,
                    "missing": s.missing,
                    "message": s.message,
                }
                for s in c.result.shortfalls
            ],
            "warnings": c.warnings,
            "duration_ms": c.duration_ms,
            "candidates": c.candidates,
        }

    # ------------------------------------------------------------------ persist/accept
    async def create(
        self, incident_id: uuid.UUID, stage: int | None, extra: list[dict[str, Any]]
    ) -> Proposal:
        incident = await self.incidents.get(incident_id)
        if incident.status in ("finished", "closed"):
            raise ConflictError("Für beendete Einsätze wird kein Vorschlag berechnet")
        c = await self.compute(incident, stage, extra)
        proposal = Proposal(
            id=uuid.uuid4(),
            incident_id=incident.id,
            control_center_id=incident.control_center_id,
            computed_by=self.uow.actor.user_id,
            computed_by_name=self.uow.actor.name,
            stage=c.stage,
            duration_ms=c.duration_ms,
            inputs={
                "stage": c.stage,
                "extra": [{"vehicle_type_id": str(e["vehicle_type_id"]), "count": e["count"]} for e in extra],
                "keyword": incident.keyword.code if incident.keyword else None,
                "location": [incident.latitude, incident.longitude],
                "routing": self.routing.name if self.routing and c.settings.use_routing else "estimate",
                "settings": c.settings.model_dump(),
            },
            result=self.serialise(c),
        )
        self.s.add(proposal)
        await self.uow.commit()  # a proposal is a record, not a change of the incident
        return proposal

    async def get(self, proposal_id: uuid.UUID) -> Proposal:
        proposal = await self.s.get(Proposal, proposal_id)
        if proposal is None:
            raise NotFoundError("Vorschlag nicht gefunden")
        if self.visible is not None and proposal.control_center_id not in self.visible:
            raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")
        return proposal

    async def history(self, incident_id: uuid.UUID, limit: int = 50) -> list[Proposal]:
        await self.incidents.get(incident_id)
        stmt = (
            select(Proposal)
            .where(Proposal.incident_id == incident_id)
            .order_by(Proposal.computed_at.desc())
            .limit(limit)
        )
        return list((await self.s.scalars(stmt)).all())

    async def accept(self, proposal_id: uuid.UUID, vehicle_ids: list[uuid.UUID], reassign: bool) -> Proposal:
        proposal = await self.s.scalar(select(Proposal).where(Proposal.id == proposal_id).with_for_update())
        if proposal is None:
            raise NotFoundError("Vorschlag nicht gefunden")
        if self.visible is not None and proposal.control_center_id not in self.visible:
            raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")
        if proposal.accepted_at is not None:
            raise ConflictError(f"Dieser Vorschlag wurde bereits von {proposal.accepted_by_name} übernommen")
        incident = await self.incidents.get(proposal.incident_id, lock=True)
        ids = list(dict.fromkeys(vehicle_ids))
        proposed = {p["vehicle_id"] for p in proposal.result.get("picks", [])}
        added = await self.incidents.assign_vehicles(incident, ids, reassign) if ids else []
        alternatives = {
            o["vehicle_id"]: o["call_sign"]
            for opts in proposal.result.get("alternatives", {}).values()
            for o in opts
        }
        chosen = {str(i) for i in ids}
        manual = [i for i in chosen if i not in proposed and i not in alternatives]
        swapped = [alternatives[i] for i in chosen if i not in proposed and i in alternatives]
        dropped = [
            p["call_sign"]
            for p in proposal.result.get("picks", [])
            if not p["in_incident"] and p["vehicle_id"] not in chosen
        ]
        proposal.accepted_vehicle_ids = [str(i) for i in ids]
        proposal.accepted_at = datetime.now(UTC)
        proposal.accepted_by_name = self.uow.actor.name
        text = "Einsatzmittelvorschlag übernommen – zugeordnet, nicht alarmiert: " + (
            ", ".join(added) or "keine neuen Fahrzeuge"
        )
        if dropped:
            text += f"; abgewählt: {', '.join(dropped)}"
        if swapped:
            text += f"; Alternative gewählt: {', '.join(sorted(swapped))}"
        if manual:
            text += f"; {len(manual)} manuell ergänzt"
        self.incidents.event(
            incident,
            "proposal_accepted",
            text,
            {"proposal_id": str(proposal.id), "vehicles": proposal.accepted_vehicle_ids},
        )
        self.uow.audit(
            "accept",
            "proposal",
            proposal.id,
            f"Einsatz {incident.number}: {text}",
            control_center_id=incident.control_center_id,
        )
        self.incidents.emit(incident, "proposal")
        await self.incidents.commit_assignments()
        await self.s.refresh(proposal)
        return proposal
