"""Vehicle status (FMS) and talk requests (Sprechwünsche).

Status effects
* 3 (Einsatz übernommen) / 4 (am Einsatzort): times on the assignment, incident status
  „Anfahrt“ / „Am Einsatzort“, entries in the incident history.
* 1 / 2 (frei) while bound to an incident: the vehicle reports free → assignment released.
* 6 (außer Dienst) while bound: assignment released with a warning entry.
* 0 / 5 are no status changes in FMS – they create a talk request (0 = priorisiert/Notruf).
* 7 / 8 / 9: recorded, mentioned in the incident history.

In simulation mode a ``Fleet`` (simulated drives) may be passed in; it is informed about
dispatcher actions (manual status 3/4/1/2/6) so that the simulated vehicle follows.
Every status change is written to the append-only ``vehicle_status_history``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.models import (
    Incident,
    IncidentVehicle,
    TalkRequest,
    Vehicle,
    VehicleStatusDefinition,
    VehicleStatusHistory,
)
from app.services.incident_service import IncidentService
from app.services.uow import UnitOfWork

if TYPE_CHECKING:
    from app.simulation.fleet import Fleet

TALK_CODES = (0, 5)
FREE_CODES = (1, 2)
SOURCE_LABEL = {"dispatcher": "", "simulation": " [Simulation]", "fms": " [FMS]", "system": " [System]"}
TALK_ACTIONS = {
    "accept": ("accepted", ("open", "deferred"), "Sprechaufforderung erteilt"),
    "defer": ("deferred", ("open",), "zurückgestellt"),
    "reject": ("rejected", ("open", "deferred"), "abgelehnt"),
    "done": ("done", ("accepted", "open", "deferred"), "erledigt"),
}


@dataclass(slots=True)
class StatusResult:
    vehicle: Vehicle
    talk_request: TalkRequest | None = None
    changed: bool = False


class VehicleStatusService:
    def __init__(
        self,
        uow: UnitOfWork,
        visible: set[uuid.UUID] | None,
        *,
        fleet: Fleet | None = None,
        timezone: str = "Europe/Berlin",
    ) -> None:
        self.uow = uow
        self.s = uow.session
        self.visible = visible
        self.fleet = fleet
        self.incidents = IncidentService(uow, visible, timezone)

    def _check_cc(self, cc_id: uuid.UUID) -> None:
        if self.visible is not None and cc_id not in self.visible:
            raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")

    async def vehicle(self, vehicle_id: uuid.UUID, *, lock: bool = False) -> Vehicle:
        stmt = select(Vehicle).where(Vehicle.id == vehicle_id)
        if lock:
            stmt = stmt.with_for_update()
        vehicle = await self.s.scalar(stmt)
        if vehicle is None:
            raise NotFoundError("Fahrzeug nicht gefunden")
        self._check_cc(vehicle.control_center_id)
        return vehicle

    async def active_assignment(self, vehicle_id: uuid.UUID) -> IncidentVehicle | None:
        return await self.s.scalar(
            select(IncidentVehicle).where(
                IncidentVehicle.vehicle_id == vehicle_id, IncidentVehicle.released_at.is_(None)
            )
        )

    async def _label(self, code: int) -> str:
        definition = await self.s.get(VehicleStatusDefinition, code)
        if definition is None:
            raise ValidationFailedError(f"Unbekannter Status {code}")
        return definition.short_label

    def _emit_vehicle(
        self, vehicle: Vehicle, previous: int | None, incident_id: uuid.UUID | None, source: str
    ) -> None:
        self.uow.emit(
            "vehicle.status_changed",
            {
                "id": str(vehicle.id),
                "status_code": vehicle.status_code,
                "previous": previous,
                "incident_id": str(incident_id) if incident_id else None,
                "source": source,
            },
            channels=[f"cc:{vehicle.control_center_id}"],
            required_permission="incidents.read",
        )

    # --------------------------------------------------------------------------- status
    async def set_status(
        self, vehicle_id: uuid.UUID, code: int, *, source: str = "dispatcher", note: str | None = None
    ) -> StatusResult:
        vehicle = await self.vehicle(vehicle_id, lock=True)
        label = await self._label(code)
        if code in TALK_CODES:
            request = await self._talk_request(vehicle, code, source, note)
            return StatusResult(vehicle, request, False)
        previous = vehicle.status_code
        if previous == code:
            return StatusResult(vehicle)
        assignment = await self.active_assignment(vehicle.id)
        incident = await self.incidents.get(assignment.incident_id, lock=True) if assignment else None
        now = datetime.now(UTC)
        vehicle.status_code = code
        vehicle.status_changed_at = now
        suffix = SOURCE_LABEL.get(source, "")
        self.s.add(
            VehicleStatusHistory(
                control_center_id=vehicle.control_center_id,
                vehicle_id=vehicle.id,
                status_code=code,
                previous_code=previous,
                source=source,
                incident_id=incident.id if incident else None,
                actor_user_id=self.uow.actor.user_id,
                actor_name=self.uow.actor.name,
                note=note,
                ts=now,
            )
        )
        if incident is not None and assignment is not None:
            await self._incident_effects(vehicle, assignment, incident, code, label, suffix, now)
        if self.fleet is not None and source != "simulation":
            await self._simulation_follow(vehicle, code, incident)
        self._emit_vehicle(vehicle, previous, incident.id if incident else None, source)
        await self.s.flush()
        return StatusResult(vehicle, None, True)

    async def _incident_effects(
        self,
        vehicle: Vehicle,
        assignment: IncidentVehicle,
        incident: Incident,
        code: int,
        label: str,
        suffix: str,
        now: datetime,
    ) -> None:
        sign = vehicle.call_sign
        data = {"vehicle_id": str(vehicle.id), "status": code}
        if code == 3:
            assignment.s3_at = assignment.s3_at or now
            self.incidents.event(incident, "vehicle_status", f"{sign}: Status 3 – {label}{suffix}", data)
            await self._advance(
                incident, ("new", "in_progress", "alarmed"), "en_route", f"{sign} Status 3", now
            )
        elif code == 4:
            assignment.s4_at = assignment.s4_at or now
            self.incidents.event(
                incident, "vehicle_arrived", f"{sign}: Ankunft am Einsatzort (Status 4){suffix}", data
            )
            await self._advance(
                incident, ("new", "in_progress", "alarmed", "en_route"), "on_scene", f"Ankunft {sign}", now
            )
        elif code in FREE_CODES or code == 6:
            assignment.released_at = now
            assignment.released_reason = "out_of_service" if code == 6 else "status_free"
            text = (
                f"{sign} außer Dienst (Status 6){suffix} – aus dem Einsatz gelöst"
                if code == 6
                else f"{sign} meldet frei (Status {code}){suffix} – Fahrzeug freigegeben"
            )
            self.incidents.event(incident, "vehicle_released", text, data)
        else:
            self.incidents.event(incident, "vehicle_status", f"{sign}: Status {code} – {label}{suffix}", data)
        incident.updated_at = now
        self.incidents.emit(incident, "vehicle_status")

    async def _advance(
        self, incident: Incident, from_states: tuple[str, ...], to: str, why: str, now: datetime
    ) -> None:
        if incident.status not in from_states:
            return
        from app.services.incident_service import STATUS_LABEL

        old = incident.status
        incident.status = to
        incident.status_changed_at = now
        self.incidents.event(
            incident,
            "status",
            f"Status: {STATUS_LABEL[old]} → {STATUS_LABEL[to]} ({why})",
            {"from": old, "to": to},
        )

    async def _simulation_follow(self, vehicle: Vehicle, code: int, incident: Incident | None) -> None:
        """Keep the simulated vehicle consistent with a status set by a dispatcher."""
        fleet = self.fleet
        assert fleet is not None
        if code == 3 and incident is not None:
            await fleet.depart_now(vehicle, incident)
        elif code == 4:
            await fleet.arrive_now(vehicle)
        elif code == 2:
            await fleet.to_station_now(vehicle)
        elif code == 1:
            await fleet.plan_return(vehicle)
        elif code == 6:
            await fleet.stop(vehicle, "Fahrzeug außer Dienst (Status 6)")

    async def history(self, vehicle_id: uuid.UUID, limit: int) -> list[VehicleStatusHistory]:
        await self.vehicle(vehicle_id)
        stmt = (
            select(VehicleStatusHistory)
            .where(VehicleStatusHistory.vehicle_id == vehicle_id)
            .order_by(VehicleStatusHistory.id.desc())
            .limit(limit)
        )
        return list((await self.s.scalars(stmt)).all())

    # --------------------------------------------------------------------- talk requests
    async def _talk_request(self, vehicle: Vehicle, code: int, source: str, note: str | None) -> TalkRequest:
        existing = await self.s.scalar(
            select(TalkRequest)
            .where(TalkRequest.vehicle_id == vehicle.id, TalkRequest.status.in_(("open", "deferred")))
            .with_for_update()
        )
        assignment = await self.active_assignment(vehicle.id)
        if existing is not None:
            if code == 0 and existing.priority != 0:  # escalation to a priority request
                existing.priority = 0
                existing.status = "open"
                self._emit_talk(existing, "escalated")
            return existing
        request = TalkRequest(
            id=uuid.uuid4(),
            control_center_id=vehicle.control_center_id,
            vehicle_id=vehicle.id,
            priority=code,
            status="open",
            source=source,
            incident_id=assignment.incident_id if assignment else None,
            note=note,
        )
        self.s.add(request)
        await self.s.flush()
        if assignment is not None:
            incident = await self.incidents.get(assignment.incident_id)
            kind = "Priorisierter Sprechwunsch (Status 0)" if code == 0 else "Sprechwunsch (Status 5)"
            self.incidents.event(
                incident,
                "talk_request",
                f"{vehicle.call_sign}: {kind}{SOURCE_LABEL.get(source, '')}",
                {"talk_request_id": str(request.id)},
            )
            self.incidents.emit(incident, "talk_request")
        self._emit_talk(request, "created")
        return request

    def _emit_talk(self, request: TalkRequest, action: str) -> None:
        self.uow.emit(
            "talk_request.changed",
            {"id": str(request.id), "priority": request.priority, "status": request.status, "action": action},
            channels=[f"cc:{request.control_center_id}"],
            required_permission="radio.handle",
        )

    async def talk_requests(
        self, control_center_id: uuid.UUID | None, only_open: bool, limit: int
    ) -> list[TalkRequest]:
        stmt = select(TalkRequest)
        if control_center_id is not None:
            self._check_cc(control_center_id)
            stmt = stmt.where(TalkRequest.control_center_id == control_center_id)
        elif self.visible is not None:
            stmt = stmt.where(TalkRequest.control_center_id.in_(self.visible or {uuid.uuid4()}))
        if only_open:
            stmt = stmt.where(TalkRequest.status.in_(("open", "deferred", "accepted")))
        stmt = stmt.order_by(TalkRequest.priority, TalkRequest.created_at).limit(limit)
        return list((await self.s.scalars(stmt)).all())

    async def handle_talk_request(self, request_id: uuid.UUID, action: str, note: str | None) -> TalkRequest:
        if action not in TALK_ACTIONS:
            raise ValidationFailedError("Unbekannte Aktion")
        request = await self.s.scalar(
            select(TalkRequest).where(TalkRequest.id == request_id).with_for_update()
        )
        if request is None:
            raise NotFoundError("Sprechwunsch nicht gefunden")
        self._check_cc(request.control_center_id)
        new_state, allowed, text = TALK_ACTIONS[action]
        if request.status not in allowed:
            who = f" von {request.handled_by_name}" if request.handled_by_name else ""
            raise ConflictError(f"Der Sprechwunsch ist bereits {request.status}{who}")
        request.status = new_state
        request.handled_at = datetime.now(UTC)
        request.handled_by = self.uow.actor.user_id
        request.handled_by_name = self.uow.actor.name
        if note:
            request.note = note.strip()[:500]
        if request.incident_id and action in ("accept", "done"):
            incident = await self.s.get(Incident, request.incident_id)
            if incident is not None and incident.status != "closed":
                extra = f" – {request.note}" if action == "done" and request.note else ""
                self.incidents.event(
                    incident,
                    "talk_request",
                    f"Sprechwunsch {request.vehicle.call_sign}: {text}{extra}",
                    {"talk_request_id": str(request.id)},
                )
                self.incidents.emit(incident, "talk_request")
        self.uow.audit(
            action,
            "talk_request",
            request.id,
            f"Sprechwunsch {request.vehicle.call_sign}: {text}",
            control_center_id=request.control_center_id,
        )
        self._emit_talk(request, action)
        await self.uow.commit()
        await self.s.refresh(request)
        return request
