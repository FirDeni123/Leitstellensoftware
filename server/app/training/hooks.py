"""Glue between the emergency-call lifecycle and training sessions + realtime helpers.

Called by ``CallService`` for calls with ``source = training`` inside the same transaction:
* only the trainee may answer (or resume) a training call,
* answering starts the session and plays the scenario's opening line (no AI call needed),
* ending the call ends the session (a never answered call cancels it).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.errors import ConflictError
from app.core.permissions import P
from app.models import EmergencyCall, TrainingMessage, TrainingSession
from app.services.uow import UnitOfWork

TRAINEE_ROLES = ("dispatcher", "caller", "system")  # what the trainee sees of the transcript


def message_payload(m: TrainingMessage) -> dict[str, Any]:
    return {
        "id": m.id,
        "session_id": str(m.session_id),
        "ts": m.ts.isoformat(),
        "role": m.role,
        "text": m.text,
        "source": m.source,
        "latency_ms": m.latency_ms,
        "author_name": m.author_name,
    }


def emit_to_session(
    uow: UnitOfWork, session: TrainingSession, topic: str, data: dict[str, Any], *, trainee: bool = True
) -> None:
    """Trainee (own user channel) + instructors of the control centre. Never anyone else."""
    if trainee:
        uow.emit(topic, data, channels=[f"user:{session.trainee_id}"])
    uow.emit(
        topic,
        data,
        channels=[f"cc:{session.control_center_id}"],
        required_permission=P.TRAINING_INSTRUCTOR.value,
    )


def emit_session(uow: UnitOfWork, session: TrainingSession, action: str) -> None:
    emit_to_session(
        uow,
        session,
        "training.session_changed",
        {
            "id": str(session.id),
            "status": session.status,
            "action": action,
            "trainee_id": str(session.trainee_id),
            "call_id": str(session.call_id) if session.call_id else None,
            "control_center_id": str(session.control_center_id),
        },
    )


def emit_message(
    uow: UnitOfWork, session: TrainingSession, m: TrainingMessage, reply_id: str | None = None
) -> None:
    emit_to_session(
        uow,
        session,
        "training.message",
        message_payload(m) | {"reply_id": reply_id},
        trainee=m.role in TRAINEE_ROLES,
    )


async def session_for_call(
    uow: UnitOfWork, call: EmergencyCall, *, lock: bool = False
) -> TrainingSession | None:
    stmt = select(TrainingSession).where(TrainingSession.call_id == call.id)
    if lock:
        stmt = stmt.with_for_update()
    return await uow.session.scalar(stmt)


async def guard_handler(uow: UnitOfWork, call: EmergencyCall) -> TrainingSession | None:
    session = await session_for_call(uow, call, lock=True)
    if session is not None and session.trainee_id != uow.actor.user_id:
        raise ConflictError(
            f"Übungsanruf für {session.trainee_name} – nur die übende Person kann ihn annehmen",
            details={"training_session_id": str(session.id)},
        )
    return session


async def on_call_answered(uow: UnitOfWork, call: EmergencyCall) -> None:
    session = await guard_handler(uow, call)
    if session is None or session.status != "ringing":
        return
    now = datetime.now(UTC)
    session.status = "active"
    session.answered_at = now
    opening = TrainingMessage(
        session_id=session.id,
        ts=now,
        role="caller",
        text=(session.scenario_snapshot or {}).get("opening_line") or "Hallo? Ich brauche Hilfe!",
        source="opening",
        latency_ms=0,
    )
    uow.session.add(opening)
    await uow.session.flush()
    emit_session(uow, session, "answered")
    emit_message(uow, session, opening)


async def on_call_ended(uow: UnitOfWork, call: EmergencyCall, previous_status: str) -> TrainingSession | None:
    session = await session_for_call(uow, call, lock=True)
    if session is None or session.status not in ("ringing", "active"):
        return None
    now = datetime.now(UTC)
    session.ended_at = now
    if previous_status == "ringing":
        session.status = "cancelled"
        text = "Übung abgebrochen – Anruf wurde nicht angenommen."
    else:
        session.status = "ended"
        text = "Gespräch beendet."
    m = TrainingMessage(session_id=session.id, ts=now, role="system", text=text, source="system")
    uow.session.add(m)
    await uow.session.flush()
    emit_session(uow, session, session.status)
    emit_message(uow, session, m)
    return session
