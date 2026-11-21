"""Background work of training sessions: caller replies and automatic evaluations.

Replies
* scheduled by the worker that stored the dispatcher's message (or an immediate instruction);
* serialised per session across all server workers with a PostgreSQL advisory lock – a second
  worker that cannot get the lock leaves the work to the holder, which re-checks after unlocking
  (so no message is ever left unanswered);
* streamed: every complete sentence is published at once (``training.caller_chunk``) so the
  client can show and speak it while the rest is still generated. ``latency_ms`` of the stored
  reply = time from the dispatcher's message to the first published sentence;
* if the AI fails (no key, network, rate limit, refusal) the turn is answered rule-based and a
  visible system message says so – the exercise goes on, nothing is hidden.

Evaluations run when a session ends (observed on the event bus, deduplicated by a lock).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text

from app.core.crypto import SecretBoxError
from app.core.permissions import P
from app.models import Alarm, EmergencyCall, Incident, TrainingEvaluation, TrainingMessage, TrainingSession
from app.realtime.bus import BusMessage
from app.services.uow import UnitOfWork
from app.training import ai_settings, evaluation
from app.training.brains import (
    Brain,
    CallerUnavailableError,
    ClaudeBrain,
    ReplyStats,
    RuleBrain,
    Turn,
    split_sentences,
)
from app.training.hooks import emit_message, emit_session
from app.training.speech import SpeechToText, create_stt

logger = logging.getLogger(__name__)

LOCK_NS_REPLY = 470067
LOCK_NS_EVALUATION = 470068
MAX_REPLIES_PER_RUN = 6
# Conversation order = when something was said. A caller reply is dated to its first sentence, so
# a message the dispatcher sends while the caller is already talking comes after it and gets its
# own reply; one sent before the caller started speaking is covered by that reply.
CHRONOLOGICAL = (TrainingMessage.ts, TrainingMessage.id)


def lock_key(session_id: uuid.UUID) -> int:
    return int.from_bytes(session_id.bytes[:4], "big", signed=True)


def needs_reply(session: TrainingSession, last: TrainingMessage | None) -> bool:
    if session.status != "active":
        return False
    if any(i.get("immediate") for i in session.pending_instructions or []):
        return True
    return last is not None and last.role == "dispatcher"


async def last_turn(uow: UnitOfWork, session_id: uuid.UUID) -> TrainingMessage | None:
    return await uow.session.scalar(
        select(TrainingMessage)
        .where(TrainingMessage.session_id == session_id, TrainingMessage.role.in_(("dispatcher", "caller")))
        .order_by(TrainingMessage.ts.desc(), TrainingMessage.id.desc())
        .limit(1)
    )


def conversation_turns(messages: list[TrainingMessage]) -> list[Turn]:
    return [
        Turn(m.role, m.text)
        for m in messages
        if m.role in ("dispatcher", "caller") or (m.role == "instructor" and m.source == "instructor")
    ]


class TrainingRuntime:
    def __init__(self, state: Any) -> None:
        self.state = state
        self._tasks: set[asyncio.Task[Any]] = set()
        self._evaluating: set[uuid.UUID] = set()
        self._clients: dict[str, Any] = {}
        self.stt: SpeechToText | None = create_stt(state.settings.stt_model, state.settings.stt_device)

    # ------------------------------------------------------------------------ scheduling
    def _spawn(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def schedule_reply(self, session_id: uuid.UUID) -> None:
        self._spawn(self._reply_loop(session_id))

    def schedule_evaluation(self, session_id: uuid.UUID) -> None:
        if session_id in self._evaluating:
            return
        self._evaluating.add(session_id)
        self._spawn(self.evaluate(session_id))

    async def observe(self, message: BusMessage) -> None:
        """Bus listener (every worker): a session that just ended gets evaluated once."""
        if message.kind != "event" or message.topic != "training.session_changed":
            return
        if message.data.get("action") == "ended" and message.data.get("status") == "ended":
            with contextlib.suppress(ValueError, KeyError):
                self.schedule_evaluation(uuid.UUID(message.data["id"]))

    async def drain(self) -> None:
        """Wait until all background work is done (tests, shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
        for client in self._clients.values():
            with contextlib.suppress(Exception):
                await client.close()
        self._clients.clear()

    # --------------------------------------------------------------------------- helpers
    @contextlib.asynccontextmanager
    async def _uow(self) -> AsyncIterator[UnitOfWork]:
        async with self.state.db.sessionmaker() as session:
            yield UnitOfWork(session, self.state.bus)

    @contextlib.asynccontextmanager
    async def _advisory(self, namespace: int, session_id: uuid.UUID) -> AsyncIterator[bool]:
        async with self.state.db.engine.connect() as raw:
            conn = await raw.execution_options(isolation_level="AUTOCOMMIT")
            params = {"ns": namespace, "key": lock_key(session_id)}
            got = bool(await conn.scalar(text("SELECT pg_try_advisory_lock(:ns, :key)"), params))
            try:
                yield got
            finally:
                if got:
                    await conn.execute(text("SELECT pg_advisory_unlock(:ns, :key)"), params)

    def _client(self, api_key: str) -> Any:
        settings = self.state.settings
        ident = hashlib.sha256(f"{settings.anthropic_base_url}|{api_key}".encode()).hexdigest()
        if ident not in self._clients:
            self._clients[ident] = ai_settings.make_client(
                api_key, settings.anthropic_base_url, settings.anthropic_timeout_seconds
            )
        return self._clients[ident]

    async def _brain(self, model: str | None, want_ai: bool) -> tuple[Brain, str | None]:
        """The brain to use now – and a visible note when the AI cannot be used."""
        if not want_ai:
            return RuleBrain(), None
        async with self._uow() as uow:
            _, config = await ai_settings.load(uow)
        if not config.enabled:
            return RuleBrain(), "KI-Anrufer wurde deaktiviert – Antwort regelbasiert (ohne KI)"
        try:
            key = ai_settings.api_key_of(config, self.state.settings, self.state.secret_box)
        except SecretBoxError:
            key = None
        if not key:
            return RuleBrain(), "Kein gültiger API-Schlüssel – Antwort regelbasiert (ohne KI)"
        brain = ClaudeBrain(
            self._client(key), model or config.model, config.caller_effort, config.evaluation_effort
        )
        return brain, None

    async def _publish(self, session: TrainingSession, topic: str, data: dict[str, Any]) -> None:
        bus = self.state.bus
        await bus.publish(
            BusMessage(kind="event", topic=topic, data=data, channels=[f"user:{session.trainee_id}"])
        )
        await bus.publish(
            BusMessage(
                kind="event",
                topic=topic,
                data=data,
                channels=[f"cc:{session.control_center_id}"],
                required_permission=P.TRAINING_INSTRUCTOR.value,
            )
        )

    # ----------------------------------------------------------------------------- reply
    async def _reply_loop(self, session_id: uuid.UUID) -> None:
        for _ in range(MAX_REPLIES_PER_RUN):
            async with self._advisory(LOCK_NS_REPLY, session_id) as got:
                if not got:
                    return  # another worker is answering; it re-checks after its reply
                try:
                    await self._reply_once(session_id)
                except Exception:  # never loop on an unexpected error
                    logger.exception("Training reply failed", extra={"ctx": {"session_id": str(session_id)}})
                    return
            async with self._uow() as uow:
                session = await uow.session.get(TrainingSession, session_id)
                if session is None or not needs_reply(session, await last_turn(uow, session_id)):
                    return

    async def _reply_once(self, session_id: uuid.UUID) -> None:
        async with self._uow() as uow:
            session = await uow.session.scalar(
                select(TrainingSession).where(TrainingSession.id == session_id).with_for_update()
            )
            if session is None:
                return
            last = await last_turn(uow, session_id)
            if not needs_reply(session, last):
                return
            now = datetime.now(UTC)
            trigger = last.ts if last is not None and last.role == "dispatcher" else now
            for item in session.pending_instructions or []:  # instructions reach the caller now
                m = TrainingMessage(
                    session_id=session.id,
                    ts=now,
                    role="instructor",
                    text=item["text"],
                    source="instructor",
                    author_name=item.get("author"),
                )
                uow.session.add(m)
                await uow.session.flush()
                emit_message(uow, session, m)
            session.pending_instructions = []
            messages = list(
                (
                    await uow.session.scalars(
                        select(TrainingMessage)
                        .where(TrainingMessage.session_id == session_id)
                        .order_by(*CHRONOLOGICAL)
                    )
                ).all()
            )
            snapshot = dict(session.scenario_snapshot or {})
            want_ai, model = session.caller_mode == "claude", session.model
            await uow.commit()  # expire_on_commit=False: `session`/`messages` stay readable

        brain, note = await self._brain(model, want_ai)
        turns = conversation_turns(messages)
        spoken_at: list[datetime] = []
        reply_id = uuid.uuid4().hex
        stats = ReplyStats()
        try:
            parts, latency = await self._stream(
                session, brain, snapshot, turns, stats, reply_id, trigger, spoken_at
            )
            source = brain.mode
        except CallerUnavailableError as exc:
            await self._publish(
                session,
                "training.caller_chunk",
                {"session_id": str(session_id), "reply_id": reply_id, "retract": True},
            )
            note = f"{exc} – Antwort regelbasiert (ohne KI)"
            reply_id = uuid.uuid4().hex
            spoken_at.clear()
            parts, latency = await self._stream(
                session, RuleBrain(), snapshot, turns, ReplyStats(), reply_id, trigger, spoken_at
            )
            source = "rules"
        if stats.fallback_used:
            note = f"Antwort von Ausweichmodell {stats.model} (Hauptmodell hat abgelehnt)"

        async with self._uow() as uow:
            current = await uow.session.scalar(
                select(TrainingSession).where(TrainingSession.id == session_id).with_for_update()
            )
            if current is None or current.status != "active":
                await self._publish(
                    current or session,
                    "training.caller_chunk",
                    {"session_id": str(session_id), "reply_id": reply_id, "retract": True},
                )
                return
            spoken = spoken_at[0] if spoken_at else datetime.now(UTC)
            if note:  # shown right before the reply it explains
                info = TrainingMessage(
                    session_id=session_id, ts=spoken, role="system", text=note, source="system"
                )
                uow.session.add(info)
                await uow.session.flush()
                emit_message(uow, current, info)
            reply = TrainingMessage(
                session_id=session_id,
                ts=spoken,
                role="caller",
                text=" ".join(parts).strip() or "…",
                source=source,
                latency_ms=latency,
            )
            uow.session.add(reply)
            await uow.session.flush()
            emit_message(uow, current, reply, reply_id)
            await uow.commit()

    async def _stream(
        self,
        session: TrainingSession,
        brain: Brain,
        snapshot: dict[str, Any],
        turns: list[Turn],
        stats: ReplyStats,
        reply_id: str,
        trigger: datetime,
        spoken_at: list[datetime],
    ) -> tuple[list[str], int | None]:
        parts: list[str] = []
        latency: int | None = None
        buffer = ""
        base = {"session_id": str(session.id), "reply_id": reply_id}

        async def publish(sentence: str) -> None:
            nonlocal latency
            if latency is None:
                now = datetime.now(UTC)
                spoken_at.append(now)
                latency = max(0, round((now - trigger).total_seconds() * 1000))
                stats.first_sentence_ms = latency
            await self._publish(
                session, "training.caller_chunk", base | {"seq": len(parts), "text": sentence}
            )
            parts.append(sentence)

        async for delta in brain.reply(snapshot, turns, stats):
            buffer += delta
            sentences, buffer = split_sentences(buffer)
            for sentence in sentences:
                await publish(sentence)
        if buffer.strip():
            await publish(buffer.strip())
        return parts, latency

    # ------------------------------------------------------------------------ evaluation
    async def evaluate(self, session_id: uuid.UUID, *, force: bool = False) -> TrainingEvaluation | None:
        self._evaluating.add(session_id)
        try:
            async with self._advisory(LOCK_NS_EVALUATION, session_id) as got:
                if not got:
                    return None
                return await self._evaluate(session_id, force)
        finally:
            self._evaluating.discard(session_id)

    async def _evaluate(self, session_id: uuid.UUID, force: bool) -> TrainingEvaluation | None:
        async with self._uow() as uow:
            s = uow.session
            session = await s.get(TrainingSession, session_id)
            if session is None or session.status not in ("ended", "evaluated"):
                return None
            existing = await s.scalar(
                select(TrainingEvaluation).where(TrainingEvaluation.session_id == session_id)
            )
            if existing is not None and not force:
                return existing
            messages = list(
                (
                    await s.scalars(
                        select(TrainingMessage)
                        .where(TrainingMessage.session_id == session_id)
                        .order_by(*CHRONOLOGICAL)
                    )
                ).all()
            )
            call = await s.get(EmergencyCall, session.call_id) if session.call_id else None
            incident = (
                await s.get(Incident, call.incident_id) if call is not None and call.incident_id else None
            )
            alarm_count, first_alarm = 0, None
            if incident is not None:
                alarm_count, first_alarm = (
                    await s.execute(
                        select(func.count(Alarm.id), func.min(Alarm.created_at)).where(
                            Alarm.incident_id == incident.id
                        )
                    )
                ).one()
            snapshot = dict(session.scenario_snapshot or {})
            actions = evaluation.action_items(snapshot, incident, alarm_count)
            measured = evaluation.metrics(
                session, incident.created_at if incident else None, first_alarm, messages
            )
            transcript = [(m.role, m.text) for m in messages if m.role in ("dispatcher", "caller")]
            questions = evaluation.question_items(snapshot)
            want_ai = session.caller_mode == "claude"
            model = None

        brain, note = await self._brain(None, want_ai)
        try:
            judgement = await brain.judge(snapshot, transcript, questions)
            method, model = brain.mode, brain.model
        except CallerUnavailableError as exc:
            judgement = await RuleBrain().judge(snapshot, transcript, questions)
            method, note = "rules", f"{exc} – regelbasierte Auswertung"
        judged = {j.key: j for j in judgement.items}
        items = actions + [
            {
                "key": q["key"],
                "label": q["label"],
                "kind": "question",
                "required": bool(q.get("required", True)),
                "fulfilled": bool(judged[q["key"]].fulfilled) if q["key"] in judged else False,
                "evidence": judged[q["key"]].evidence if q["key"] in judged else "nicht bewertet",
            }
            for q in questions
        ]
        feedback = {
            "summary": judgement.summary,
            "strengths": judgement.strengths,
            "improvements": judgement.improvements,
            "note": note,
        }

        async with self._uow() as uow:
            s = uow.session
            session = await s.scalar(
                select(TrainingSession).where(TrainingSession.id == session_id).with_for_update()
            )
            if session is None:
                return None
            old = await s.scalar(
                select(TrainingEvaluation).where(TrainingEvaluation.session_id == session_id)
            )
            if old is not None:
                await s.delete(old)
                await s.flush()
            result = TrainingEvaluation(
                session_id=session_id,
                method=method,
                model=model,
                score=evaluation.score(items),
                metrics=measured,
                checklist=items,
                feedback=feedback,
            )
            s.add(result)
            session.status = "evaluated"
            uow.audit(
                "evaluate",
                "training_session",
                session_id,
                f"Übung ausgewertet ({'KI' if method == 'claude' else 'regelbasiert'}): {result.score} %",
                control_center_id=session.control_center_id,
            )
            emit_session(uow, session, "evaluated")
            await uow.commit()
            await s.refresh(result)
            return result
