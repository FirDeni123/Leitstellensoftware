"""Incidents (Einsätze): numbering, lifecycle, vehicle assignment, history.

Every change writes an entry into the incident history (``incident_events``, append-only)
in the same transaction; data changes are additionally recorded in the audit log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.models import (
    EmergencyCall,
    Incident,
    IncidentEvent,
    IncidentNumberSequence,
    IncidentVehicle,
    Keyword,
    Vehicle,
)
from app.models.operations import INCIDENT_STATUSES
from app.services.uow import UnitOfWork, check_version

STATUS_LABEL = {
    "new": "Neu",
    "in_progress": "In Bearbeitung",
    "alarmed": "Alarmiert",
    "en_route": "Fahrzeuge auf Anfahrt",
    "on_scene": "Am Einsatzort",
    "finished": "Einsatz beendet",
    "closed": "Abgeschlossen",
}
FIELD_LABEL = {
    "keyword_id": "Stichwort",
    "incident_type": "Einsatzart",
    "priority": "Priorität",
    "address": "Einsatzort",
    "location_note": "Ortshinweis",
    "latitude": "Breitengrad",
    "longitude": "Längengrad",
    "caller_name": "Meldender",
    "caller_phone": "Rückrufnummer",
    "description": "Beschreibung",
}
EDITABLE = tuple(FIELD_LABEL)
NO_ASSIGNMENT_STATUSES = ("finished", "closed")


def incident_channel(incident: Incident) -> list[str]:
    return [f"cc:{incident.control_center_id}"]


class IncidentService:
    def __init__(
        self, uow: UnitOfWork, visible: set[uuid.UUID] | None, timezone: str = "Europe/Berlin"
    ) -> None:
        self.uow = uow
        self.s = uow.session
        self.visible = visible
        self.tz = ZoneInfo(timezone)

    # -------------------------------------------------------------------------- helpers
    def _check_cc(self, cc_id: uuid.UUID) -> None:
        if self.visible is not None and cc_id not in self.visible:
            raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")

    def event(self, incident: Incident, kind: str, text: str, data: dict[str, Any] | None = None) -> None:
        self.s.add(
            IncidentEvent(
                incident_id=incident.id,
                kind=kind,
                text=text,
                data=data,
                actor_user_id=self.uow.actor.user_id,
                actor_name=self.uow.actor.name,
            )
        )

    def emit(self, incident: Incident, action: str) -> None:
        self.uow.emit(
            "incident.changed",
            {"id": str(incident.id), "number": incident.number, "action": action, "status": incident.status},
            channels=incident_channel(incident),
            required_permission="incidents.read",
        )

    async def get(self, incident_id: uuid.UUID, *, lock: bool = False) -> Incident:
        stmt = select(Incident).where(Incident.id == incident_id)
        if lock:
            stmt = stmt.with_for_update()
        incident = await self.s.scalar(stmt)
        if incident is None:
            raise NotFoundError("Einsatz nicht gefunden")
        self._check_cc(incident.control_center_id)
        return incident

    async def list(
        self, control_center_id: uuid.UUID | None, scope: str, q: str | None, limit: int
    ) -> list[Incident]:
        stmt = select(Incident)
        if control_center_id:
            self._check_cc(control_center_id)
            stmt = stmt.where(Incident.control_center_id == control_center_id)
        elif self.visible is not None:
            stmt = stmt.where(Incident.control_center_id.in_(self.visible or {uuid.uuid4()}))
        if scope == "open":
            stmt = stmt.where(Incident.status != "closed")
        elif scope == "closed":
            stmt = stmt.where(Incident.status == "closed")
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    Incident.number.ilike(like),
                    Incident.address.ilike(like),
                    Incident.description.ilike(like),
                    Incident.caller_name.ilike(like),
                )
            )
        stmt = stmt.order_by(Incident.priority, Incident.created_at.desc()).limit(limit)
        return list((await self.s.scalars(stmt)).all())

    async def _next_number(self, cc_id: uuid.UUID) -> tuple[int, int, str]:
        """Gapless per control centre and year: the counter row is locked until commit."""
        year = datetime.now(self.tz).year
        seq_row = await self.s.scalar(
            select(IncidentNumberSequence)
            .where(IncidentNumberSequence.control_center_id == cc_id, IncidentNumberSequence.year == year)
            .with_for_update()
        )
        if seq_row is None:
            # INSERT … ON CONFLICT DO NOTHING keeps concurrent first incidents of a year safe.
            from sqlalchemy.dialects.postgresql import insert

            await self.s.execute(
                insert(IncidentNumberSequence)
                .values(control_center_id=cc_id, year=year, last_value=0)
                .on_conflict_do_nothing()
            )
            seq_row = await self.s.scalar(
                select(IncidentNumberSequence)
                .where(IncidentNumberSequence.control_center_id == cc_id, IncidentNumberSequence.year == year)
                .with_for_update()
            )
        assert seq_row is not None
        seq_row.last_value += 1
        return year, seq_row.last_value, f"{year}-{seq_row.last_value:06d}"

    async def _keyword(self, keyword_id: uuid.UUID | None) -> Keyword | None:
        if keyword_id is None:
            return None
        kw = await self.s.get(Keyword, keyword_id)
        if kw is None:
            raise ValidationFailedError("Stichwort nicht gefunden")
        return kw

    # ---------------------------------------------------------------------------- create
    async def create(self, data: dict[str, Any]) -> Incident:
        cc_id = data["control_center_id"]
        self._check_cc(cc_id)
        call: EmergencyCall | None = None
        if data.get("call_id"):
            call = await self.s.scalar(
                select(EmergencyCall).where(EmergencyCall.id == data["call_id"]).with_for_update()
            )
            if call is None or call.control_center_id != cc_id:
                raise ValidationFailedError("Notruf nicht gefunden oder aus anderer Leitstelle")
            if call.incident_id is not None:
                raise ConflictError("Dieser Notruf ist bereits einem Einsatz zugeordnet")
        kw = await self._keyword(data.get("keyword_id"))
        year, seq, number = await self._next_number(cc_id)
        incident = Incident(
            id=uuid.uuid4(),
            control_center_id=cc_id,
            year=year,
            sequence=seq,
            number=number,
            keyword_id=kw.id if kw else None,
            incident_type=data.get("incident_type") or (kw.category if kw else "other"),
            priority=data.get("priority") or (kw.default_priority if kw else 2),
            created_by=self.uow.actor.user_id,
            status="new",
            source=("sim" if call and call.source in ("sim", "training") else "call") if call else "manual",
        )
        for field in EDITABLE:
            if field in ("keyword_id", "incident_type", "priority"):
                continue
            value = data.get(field)
            if value is None and call is not None:  # take over what the call taker captured
                value = {
                    "caller_name": call.caller_name,
                    "caller_phone": call.caller_phone,
                    "address": call.address,
                    "latitude": call.latitude,
                    "longitude": call.longitude,
                    "description": call.reason,
                }.get(field)
            setattr(incident, field, value)
        self.s.add(incident)
        await self.s.flush()
        kw_text = f" mit Stichwort {kw.code}" if kw else ""
        self.event(
            incident,
            "created",
            f"Einsatz {number} angelegt{kw_text}",
            {"keyword": kw.code if kw else None, "address": incident.address, "priority": incident.priority},
        )
        if call is not None:
            call.incident_id = incident.id
            self.event(incident, "call_linked", _call_text(call), {"call_id": str(call.id)})
            self.uow.emit(
                "call.changed",
                {"id": str(call.id), "status": call.status, "action": "linked"},
                channels=[f"cc:{cc_id}"],
                required_permission="calls.handle",
            )
        self.uow.audit(
            "create", "incident", incident.id, f"Einsatz {number} angelegt{kw_text}", control_center_id=cc_id
        )
        self.emit(incident, "created")
        await self.uow.commit()
        await self.s.refresh(incident)
        return incident

    # ---------------------------------------------------------------------------- update
    async def update(self, incident_id: uuid.UUID, data: dict[str, Any], expected_version: int) -> Incident:
        incident = await self.get(incident_id)
        check_version(incident, expected_version, f"Einsatz {incident.number}")
        if incident.status == "closed":
            raise ConflictError("Abgeschlossene Einsätze können nicht mehr geändert werden")
        changes: dict[str, dict[str, Any]] = {}
        if "keyword_id" in data:
            kw = await self._keyword(data["keyword_id"])
            old = incident.keyword.code if incident.keyword else None
            new = kw.code if kw else None
            if old != new:
                changes["keyword_id"] = {"old": old, "new": new}
                incident.keyword_id = kw.id if kw else None
        for field in EDITABLE:
            if field == "keyword_id" or field not in data:
                continue
            value = data[field]
            if field in ("incident_type", "priority") and value is None:
                continue
            if getattr(incident, field) != value:
                changes[field] = {"old": getattr(incident, field), "new": value}
                setattr(incident, field, value)
        if not changes:
            return incident
        incident.updated_at = datetime.now(UTC)
        text = "Geändert: " + ", ".join(
            f"{FIELD_LABEL[k]} {_fmt(v['old'])} → {_fmt(v['new'])}"
            if k not in ("description",)
            else f"{FIELD_LABEL[k]}"
            for k, v in changes.items()
        )
        self.event(incident, "updated", text, {"changes": changes})
        self.uow.audit(
            "update",
            "incident",
            incident.id,
            f"Einsatz {incident.number} geändert",
            changes=changes,
            control_center_id=incident.control_center_id,
        )
        self.emit(incident, "updated")
        await self.uow.commit()
        await self.s.refresh(incident)
        return incident

    # ---------------------------------------------------------------------------- status
    async def change_status(
        self, incident_id: uuid.UUID, status: str, expected_version: int, note: str | None, can_close: bool
    ) -> Incident:
        if status not in INCIDENT_STATUSES:
            raise ValidationFailedError("Unbekannter Status")
        incident = await self.get(incident_id, lock=True)
        check_version(incident, expected_version, f"Einsatz {incident.number}")
        current = incident.status
        if status == current:
            return incident
        if status == "closed" or current == "closed":
            if not can_close:
                raise PermissionDeniedError(
                    "Abschließen/Wiedereröffnen erfordert 'incidents.close'",
                    details={"missing_permissions": ["incidents.close"]},
                )
        if status == "closed":
            if current != "finished":
                raise ConflictError("Nur beendete Einsätze können abgeschlossen werden")
            active = [a for a in incident.assignments if a.released_at is None]
            if active:
                names = ", ".join(a.vehicle.call_sign for a in active)
                raise ConflictError(f"Noch zugeordnete Fahrzeuge: {names} – zuerst freigeben")
        if current == "closed" and status != "finished":
            raise ConflictError(
                "Ein abgeschlossener Einsatz kann nur in „Einsatz beendet“ zurückgesetzt werden"
            )
        now = datetime.now(UTC)
        incident.status = status
        incident.status_changed_at = now
        if status == "finished":
            incident.finished_at = now
        if status == "closed":
            incident.closed_at = now
        if current == "closed":
            incident.closed_at = None
        kind = "reopened" if current == "closed" else "status"
        text = f"Status: {STATUS_LABEL[current]} → {STATUS_LABEL[status]}" + (f" – {note}" if note else "")
        self.event(incident, kind, text, {"from": current, "to": status, "note": note})
        self.uow.audit(
            "status",
            "incident",
            incident.id,
            f"Einsatz {incident.number}: {text}",
            changes={"status": {"old": current, "new": status}},
            control_center_id=incident.control_center_id,
        )
        self.emit(incident, "status")
        await self.uow.commit()
        await self.s.refresh(incident)
        return incident

    # ----------------------------------------------------------------------- documentation
    async def add_note(self, incident_id: uuid.UUID, text: str) -> IncidentEvent:
        incident = await self.get(incident_id)
        if incident.status == "closed":
            raise ConflictError("Abgeschlossene Einsätze können nicht mehr ergänzt werden")
        entry = IncidentEvent(
            incident_id=incident.id,
            kind="note",
            text=text.strip(),
            data=None,
            actor_user_id=self.uow.actor.user_id,
            actor_name=self.uow.actor.name,
        )
        self.s.add(entry)
        self.emit(incident, "note")
        await self.uow.commit()
        return entry

    async def events(self, incident_id: uuid.UUID) -> list[IncidentEvent]:
        await self.get(incident_id)
        stmt = (
            select(IncidentEvent).where(IncidentEvent.incident_id == incident_id).order_by(IncidentEvent.id)
        )
        return list((await self.s.scalars(stmt)).all())

    # --------------------------------------------------------------------------- vehicles
    async def assign(self, incident_id: uuid.UUID, vehicle_ids: list[uuid.UUID], reassign: bool) -> Incident:
        incident = await self.get(incident_id, lock=True)
        added = await self.assign_vehicles(incident, vehicle_ids, reassign)
        if not added:
            return incident
        self.uow.audit(
            "assign",
            "incident",
            incident.id,
            f"Einsatz {incident.number}: Fahrzeuge zugeordnet ({', '.join(added)})",
            control_center_id=incident.control_center_id,
        )
        await self.commit_assignments()
        await self.s.refresh(incident)
        return incident

    async def commit_assignments(self) -> None:
        try:
            await self.uow.commit()
        except IntegrityError as exc:  # partial unique index as last line of defence
            await self.uow.rollback()
            raise ConflictError(
                "Fahrzeug wurde gleichzeitig einem anderen Einsatz zugeordnet – bitte neu laden"
            ) from exc

    async def assign_vehicles(
        self, incident: Incident, vehicle_ids: list[uuid.UUID], reassign: bool
    ) -> list[str]:
        """Assign vehicles to a locked incident (history + events, no commit). Returns the call signs
        that were newly assigned. Used by manual assignment and by the alarm."""
        if incident.status in NO_ASSIGNMENT_STATUSES:
            raise ConflictError(
                "Einem beendeten oder abgeschlossenen Einsatz können keine Fahrzeuge zugeordnet werden"
            )
        now = datetime.now(UTC)
        touched: dict[uuid.UUID, Incident] = {}
        added: list[str] = []
        # Lock the vehicles in a stable order: concurrent assignments are serialised, no deadlocks.
        vehicles = list(
            (
                await self.s.scalars(
                    select(Vehicle).where(Vehicle.id.in_(vehicle_ids)).order_by(Vehicle.id).with_for_update()
                )
            ).all()
        )
        if len(vehicles) != len(set(vehicle_ids)):
            raise ValidationFailedError("Unbekannte Fahrzeuge")
        for vehicle in sorted(vehicles, key=lambda v: vehicle_ids.index(v.id)):
            if vehicle.control_center_id != incident.control_center_id:
                raise ValidationFailedError(f"{vehicle.call_sign} gehört zu einer anderen Leitstelle")
            if not vehicle.available:
                raise ValidationFailedError(f"{vehicle.call_sign} ist nicht verfügbar (außer Dienst)")
            current = await self.s.scalar(
                select(IncidentVehicle).where(
                    IncidentVehicle.vehicle_id == vehicle.id, IncidentVehicle.released_at.is_(None)
                )
            )
            if current is not None and current.incident_id == incident.id:
                continue  # already assigned here
            if current is not None:
                other = await self.s.get(Incident, current.incident_id)
                assert other is not None
                if not reassign:
                    raise ConflictError(
                        f"{vehicle.call_sign} ist bereits Einsatz {other.number} zugeordnet",
                        details={
                            "vehicle_id": str(vehicle.id),
                            "incident_id": str(other.id),
                            "incident_number": other.number,
                        },
                    )
                current.released_at = now
                current.released_reason = "reassigned"
                self.event(
                    other,
                    "vehicle_reassigned",
                    f"{vehicle.call_sign} abgezogen und in Einsatz {incident.number} umgesetzt",
                    {"vehicle_id": str(vehicle.id), "to_incident": str(incident.id)},
                )
                touched[other.id] = other
                await self.s.flush()
            self.s.add(
                IncidentVehicle(
                    incident_id=incident.id,
                    vehicle_id=vehicle.id,
                    assigned_at=now,
                    assigned_by=self.uow.actor.user_id,
                )
            )
            source = f" (aus Einsatz {touched[current.incident_id].number})" if current is not None else ""
            self.event(
                incident,
                "vehicle_assigned",
                f"{vehicle.call_sign} ({vehicle.vehicle_type.code}, {vehicle.station.name}) "
                f"zugeordnet{source}",
                {"vehicle_id": str(vehicle.id)},
            )
            added.append(vehicle.call_sign)
        if not added:
            return added
        if incident.status == "new":
            incident.status = "in_progress"
            incident.status_changed_at = now
            self.event(
                incident,
                "status",
                "Status: Neu → In Bearbeitung (Fahrzeugzuordnung)",
                {"from": "new", "to": "in_progress"},
            )
        incident.updated_at = now
        self.emit(incident, "vehicles")
        for other in touched.values():
            self.emit(other, "vehicles")
        await self.s.flush()
        return added

    async def release(self, incident_id: uuid.UUID, vehicle_id: uuid.UUID) -> Incident:
        incident = await self.get(incident_id, lock=True)
        assignment = await self.s.scalar(
            select(IncidentVehicle).where(
                IncidentVehicle.incident_id == incident.id,
                IncidentVehicle.vehicle_id == vehicle_id,
                IncidentVehicle.released_at.is_(None),
            )
        )
        if assignment is None:
            raise NotFoundError("Fahrzeug ist diesem Einsatz nicht zugeordnet")
        assignment.released_at = datetime.now(UTC)
        assignment.released_reason = "released"
        incident.updated_at = assignment.released_at
        call_sign = assignment.vehicle.call_sign
        self.event(incident, "vehicle_released", f"{call_sign} freigegeben", {"vehicle_id": str(vehicle_id)})
        self.uow.audit(
            "release",
            "incident",
            incident.id,
            f"Einsatz {incident.number}: {call_sign} freigegeben",
            control_center_id=incident.control_center_id,
        )
        self.emit(incident, "vehicles")
        await self.uow.commit()
        await self.s.refresh(incident)
        return incident

    async def active_assignments(
        self, control_center_id: uuid.UUID
    ) -> list[tuple[IncidentVehicle, Incident]]:
        self._check_cc(control_center_id)
        rows = (
            await self.s.execute(
                select(IncidentVehicle, Incident)
                .join(Incident, Incident.id == IncidentVehicle.incident_id)
                .where(IncidentVehicle.released_at.is_(None), Incident.control_center_id == control_center_id)
            )
        ).all()
        return [(a, i) for a, i in rows]


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "–"
    if isinstance(value, float):
        return f"{value:.5f}"
    return str(value)


def _call_text(call: EmergencyCall) -> str:
    who = call.caller_name or "unbekannt"
    phone = f", {call.caller_phone}" if call.caller_phone else ""
    sim = " [Simulation]" if call.source in ("sim", "training") else ""
    return f"Notruf von {who}{phone} zugeordnet{sim}"
