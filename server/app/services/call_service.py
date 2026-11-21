"""Emergency calls (Notrufannahme).

Lifecycle: ringing → active (answered by exactly one dispatcher) ⇄ on_hold → ended.
Concurrent answers are serialised with a row lock: the second dispatcher gets a 409 with
the name of the colleague who already took the call. Lifecycle actions (answer, hold,
resume, end, link) are guarded by the call state, not by the record version – only content
changes (PATCH) use optimistic locking.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.models import CallNote, EmergencyCall, Incident, User
from app.services.incident_service import IncidentService, _call_text
from app.services.uow import UnitOfWork, check_version

CALL_FIELDS = (
    "priority",
    "caller_name",
    "caller_phone",
    "caller_location",
    "address",
    "latitude",
    "longitude",
    "reason",
)
SOURCE_LABEL = {
    "sim": "simulierter",
    "manual": "manuell erfasster",
    "voip": "eingehender",
    "training": "Trainings-",
}


class CallService:
    def __init__(self, uow: UnitOfWork, visible: set[uuid.UUID] | None) -> None:
        self.uow = uow
        self.s = uow.session
        self.visible = visible

    def _check_cc(self, cc_id: uuid.UUID) -> None:
        if self.visible is not None and cc_id not in self.visible:
            raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")

    def _emit(self, call: EmergencyCall, action: str) -> None:
        self.uow.emit(
            "call.changed",
            {
                "id": str(call.id),
                "status": call.status,
                "priority": call.priority,
                "action": action,
                "handled_by": str(call.handled_by) if call.handled_by else None,
            },
            channels=[f"cc:{call.control_center_id}"],
            required_permission="calls.handle",
        )

    async def get(self, call_id: uuid.UUID, *, lock: bool = False) -> EmergencyCall:
        stmt = select(EmergencyCall).where(EmergencyCall.id == call_id)
        if lock:
            stmt = stmt.with_for_update()
        call = await self.s.scalar(stmt)
        if call is None:
            raise NotFoundError("Notruf nicht gefunden")
        self._check_cc(call.control_center_id)
        return call

    async def list(
        self, control_center_id: uuid.UUID | None, include_ended: bool, limit: int
    ) -> list[EmergencyCall]:
        stmt = select(EmergencyCall)
        if control_center_id:
            self._check_cc(control_center_id)
            stmt = stmt.where(EmergencyCall.control_center_id == control_center_id)
        elif self.visible is not None:
            stmt = stmt.where(EmergencyCall.control_center_id.in_(self.visible or {uuid.uuid4()}))
        if not include_ended:
            stmt = stmt.where(EmergencyCall.status != "ended")
        stmt = stmt.order_by(EmergencyCall.priority, EmergencyCall.received_at).limit(limit)
        return list((await self.s.scalars(stmt)).all())

    async def handler_names(self, calls: list[EmergencyCall]) -> dict[uuid.UUID, str]:
        ids = {c.handled_by for c in calls if c.handled_by}
        if not ids:
            return {}
        return {
            u.id: u.display_name for u in (await self.s.scalars(select(User).where(User.id.in_(ids)))).all()
        }

    # ---------------------------------------------------------------------------- inbound
    async def receive(
        self, cc_id: uuid.UUID, *, source: str, priority: int = 3, **fields: Any
    ) -> EmergencyCall:
        """Entry point for every incoming call – simulated, manual or (later) VoIP."""
        self._check_cc(cc_id)
        call = EmergencyCall(
            id=uuid.uuid4(),
            control_center_id=cc_id,
            status="ringing",
            source=source,
            priority=priority,
            received_at=datetime.now(UTC),
            **fields,
        )
        self.s.add(call)
        await self.s.flush()
        who = call.caller_phone or "Rufnummer unterdrückt"
        self.uow.audit(
            "receive",
            "emergency_call",
            call.id,
            f"{SOURCE_LABEL.get(source, '')} Notruf ({who})".strip(),
            control_center_id=cc_id,
        )
        self._emit(call, "ringing")
        await self.uow.commit()
        await self.s.refresh(call)  # load relationships (notes) of the new row
        return call

    # --------------------------------------------------------------------------- lifecycle
    async def answer(self, call_id: uuid.UUID, expected_version: int | None = None) -> EmergencyCall:
        call = await self.get(call_id, lock=True)
        if call.status != "ringing":
            if call.handled_by and call.handled_by != self.uow.actor.user_id:
                handler = await self.s.get(User, call.handled_by)
                raise ConflictError(
                    f"Notruf wurde bereits von {handler.display_name if handler else 'jemand anderem'} "
                    "angenommen",
                    details={"handled_by": str(call.handled_by)},
                )
            raise ConflictError("Notruf klingelt nicht mehr")
        call.status = "active"
        call.handled_by = self.uow.actor.user_id
        call.answered_at = datetime.now(UTC)
        self.uow.audit(
            "answer", "emergency_call", call.id, "Notruf angenommen", control_center_id=call.control_center_id
        )
        self._emit(call, "answered")
        await self.uow.commit()
        return call

    async def hold(self, call_id: uuid.UUID, expected_version: int | None = None) -> EmergencyCall:
        call = await self.get(call_id, lock=True)
        if call.status != "active":
            raise ConflictError("Nur ein aktives Gespräch kann gehalten werden")
        self._require_handler(call)
        call.status = "on_hold"
        self._emit(call, "on_hold")
        await self.uow.commit()
        return call

    async def resume(self, call_id: uuid.UUID, expected_version: int | None = None) -> EmergencyCall:
        """Pick up a held call – also by a colleague (takeover)."""
        call = await self.get(call_id, lock=True)
        if call.status != "on_hold":
            raise ConflictError("Der Notruf wird nicht gehalten")
        takeover = call.handled_by != self.uow.actor.user_id
        call.status = "active"
        call.handled_by = self.uow.actor.user_id
        if takeover:
            self.uow.audit(
                "takeover",
                "emergency_call",
                call.id,
                "Gehaltenen Notruf übernommen",
                control_center_id=call.control_center_id,
            )
        self._emit(call, "resumed")
        await self.uow.commit()
        return call

    async def end(self, call_id: uuid.UUID, expected_version: int | None = None) -> EmergencyCall:
        call = await self.get(call_id, lock=True)
        if call.status == "ended":
            return call
        if call.status != "ringing":
            self._require_handler(call)
        previous = call.status
        call.status = "ended"
        call.ended_at = datetime.now(UTC)
        text = "Notruf beendet" if previous != "ringing" else "Notruf ohne Annahme beendet"
        self.uow.audit("end", "emergency_call", call.id, text, control_center_id=call.control_center_id)
        self._emit(call, "ended")
        await self.uow.commit()
        return call

    def _require_handler(self, call: EmergencyCall) -> None:
        if call.handled_by != self.uow.actor.user_id:
            raise ConflictError("Dieser Notruf wird von einer anderen Person bearbeitet")

    # ----------------------------------------------------------------------------- content
    async def update(self, call_id: uuid.UUID, data: dict[str, Any], expected_version: int) -> EmergencyCall:
        call = await self.get(call_id)
        check_version(call, expected_version, "Der Notruf")
        if call.status == "ended":
            raise ConflictError("Beendete Notrufe sind abgeschlossen – Ergänzungen im Einsatz dokumentieren")
        if call.status in ("active", "on_hold"):
            self._require_handler(call)
        changed = False
        for field in CALL_FIELDS:
            if field in data and getattr(call, field) != data[field]:
                if field == "priority" and data[field] is None:
                    continue
                setattr(call, field, data[field])
                changed = True
        if changed:
            call.updated_at = datetime.now(UTC)
            self._emit(call, "updated")
            await self.uow.commit()
        return call

    async def add_note(self, call_id: uuid.UUID, kind: str, question: str | None, text: str) -> EmergencyCall:
        call = await self.get(call_id)
        if call.status == "ended":
            raise ConflictError("Beendete Notrufe sind abgeschlossen – Ergänzungen im Einsatz dokumentieren")
        self.s.add(
            CallNote(
                call_id=call.id,
                kind=kind,
                question=question,
                text=text.strip(),
                created_by=self.uow.actor.user_id,
                author_name=self.uow.actor.name,
            )
        )
        call.updated_at = datetime.now(UTC)
        self._emit(call, "note")
        await self.uow.commit()
        await self.s.refresh(call)
        return call

    async def link(self, call_id: uuid.UUID, incident_id: uuid.UUID, timezone: str) -> EmergencyCall:
        call = await self.get(call_id, lock=True)
        if call.incident_id is not None:
            raise ConflictError("Dieser Notruf ist bereits einem Einsatz zugeordnet")
        incidents = IncidentService(self.uow, self.visible, timezone)
        incident: Incident = await incidents.get(incident_id, lock=True)
        if incident.control_center_id != call.control_center_id:
            raise ValidationFailedError("Einsatz gehört zu einer anderen Leitstelle")
        if incident.status == "closed":
            raise ConflictError("Abgeschlossenen Einsätzen können keine Notrufe zugeordnet werden")
        call.incident_id = incident.id
        call.updated_at = datetime.now(UTC)
        notes = "; ".join(f"{n.question}: {n.text}" if n.question else n.text for n in call.notes)
        incidents.event(
            incident,
            "call_linked",
            _call_text(call) + (f" – {call.reason}" if call.reason else ""),
            {"call_id": str(call.id), "notes": notes or None},
        )
        self.uow.audit(
            "link",
            "emergency_call",
            call.id,
            f"Notruf Einsatz {incident.number} zugeordnet",
            control_center_id=call.control_center_id,
        )
        incidents.emit(incident, "call_linked")
        self._emit(call, "linked")
        await self.uow.commit()
        await self.s.refresh(call)
        return call
