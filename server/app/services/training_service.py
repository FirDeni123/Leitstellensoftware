"""Training (Ausbildung): scenarios, exercise sessions with an AI caller, instructor mode, AI settings.

Safety
* exercises only in simulation mode; switching to real operation cancels running exercises;
* a training call is an ``emergency_calls`` row with ``source = training`` – it never touches
  telephony, and the AI caller has no tools: it can only produce text (``IS_REAL = False``);
* the AI never triggers anything: incident, keyword and alarm are always the trainee's actions;
* the API key is stored only encrypted (SecretBox) and never returned.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import Settings
from app.core.crypto import SecretBox, SecretBoxError
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.core.permissions import P
from app.models import (
    EmergencyCall,
    Keyword,
    SystemSetting,
    TrainingEvaluation,
    TrainingMessage,
    TrainingScenario,
    TrainingSession,
    User,
)
from app.services.call_service import CallService
from app.services.system_service import SystemService
from app.services.uow import UnitOfWork, check_version
from app.training import ai_settings
from app.training.brains import FALLBACK_BETA
from app.training.hooks import emit_message, emit_session, emit_to_session

SCENARIO_FIELDS = (
    "title",
    "description",
    "difficulty",
    "keyword_id",
    "persona",
    "facts",
    "opening_line",
    "checklist",
    "is_active",
)
OPEN_STATES = ("ringing", "active")


def snapshot_of(scenario: TrainingScenario) -> dict[str, Any]:
    kw = scenario.keyword
    return {
        "scenario_id": str(scenario.id),
        "title": scenario.title,
        "description": scenario.description,
        "difficulty": scenario.difficulty,
        "persona": scenario.persona or {},
        "facts": scenario.facts or {},
        "opening_line": scenario.opening_line,
        "checklist": scenario.checklist or [],
        "keyword": {"id": str(kw.id), "code": kw.code, "name": kw.name} if kw is not None else None,
    }


class TrainingService:
    def __init__(
        self,
        uow: UnitOfWork,
        visible: set[uuid.UUID] | None,
        permissions: frozenset[str],
        runtime: Any,
        settings: Settings,
        box: SecretBox,
    ) -> None:
        self.uow = uow
        self.s = uow.session
        self.visible = visible
        self.permissions = permissions
        self.runtime = runtime
        self.settings = settings
        self.box = box

    # --------------------------------------------------------------------------- helpers
    @property
    def is_instructor(self) -> bool:
        return P.TRAINING_INSTRUCTOR.value in self.permissions

    @property
    def me(self) -> uuid.UUID | None:
        return self.uow.actor.user_id

    def _check_cc(self, cc_id: uuid.UUID | None) -> None:
        if cc_id is not None and self.visible is not None and cc_id not in self.visible:
            raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")

    async def _require_simulation(self) -> None:
        if await SystemService(self.uow).operation_mode() != "simulation":
            raise ConflictError("Übungen sind nur im Simulationsbetrieb möglich")

    # ------------------------------------------------------------------------- scenarios
    async def scenario(self, scenario_id: uuid.UUID) -> TrainingScenario:
        scenario = await self.s.get(TrainingScenario, scenario_id)
        if scenario is None:
            raise NotFoundError("Szenario nicht gefunden")
        self._check_cc(scenario.control_center_id)
        return scenario

    async def scenarios(
        self, control_center_id: uuid.UUID | None, include_inactive: bool
    ) -> list[TrainingScenario]:
        stmt = select(TrainingScenario).order_by(TrainingScenario.title)
        if control_center_id is not None:
            self._check_cc(control_center_id)
            stmt = stmt.where(
                (TrainingScenario.control_center_id == control_center_id)
                | TrainingScenario.control_center_id.is_(None)
            )
        elif self.visible is not None:
            stmt = stmt.where(
                TrainingScenario.control_center_id.in_(self.visible or {uuid.uuid4()})
                | TrainingScenario.control_center_id.is_(None)
            )
        if not include_inactive:
            stmt = stmt.where(TrainingScenario.is_active.is_(True))
        return list((await self.s.scalars(stmt)).all())

    async def _check_keyword(self, keyword_id: uuid.UUID | None) -> None:
        if keyword_id is not None and await self.s.get(Keyword, keyword_id) is None:
            raise ValidationFailedError("Stichwort nicht gefunden")

    async def create_scenario(self, data: dict[str, Any]) -> TrainingScenario:
        cc_id = data.get("control_center_id")
        if cc_id is None and self.visible is not None:
            raise PermissionDeniedError("Leitstellenübergreifende Szenarien nur durch Administratoren")
        self._check_cc(cc_id)
        await self._check_keyword(data.get("keyword_id"))
        scenario = TrainingScenario(id=uuid.uuid4(), created_by=self.me, **data)
        self.s.add(scenario)
        await self.s.flush()
        self.uow.audit(
            "create",
            "training_scenario",
            scenario.id,
            f"Übungsszenario '{scenario.title}' angelegt",
            control_center_id=cc_id,
        )
        self.uow.emit(
            "training.scenario_changed",
            {"id": str(scenario.id)},
            required_permission=P.TRAINING_PARTICIPATE.value,
        )
        await self.uow.commit()
        await self.s.refresh(scenario)
        return scenario

    async def update_scenario(
        self, scenario_id: uuid.UUID, data: dict[str, Any], expected_version: int
    ) -> TrainingScenario:
        scenario = await self.scenario(scenario_id)
        if scenario.control_center_id is None and self.visible is not None:
            raise PermissionDeniedError("Leitstellenübergreifende Szenarien nur durch Administratoren")
        check_version(scenario, expected_version, "Das Szenario")
        if "keyword_id" in data:
            await self._check_keyword(data["keyword_id"])
        changed = [f for f in SCENARIO_FIELDS if f in data and getattr(scenario, f) != data[f]]
        for field in changed:
            setattr(scenario, field, data[field])
        if changed:
            scenario.updated_at = datetime.now(UTC)
            self.uow.audit(
                "update",
                "training_scenario",
                scenario.id,
                f"Übungsszenario '{scenario.title}' geändert ({', '.join(changed)})",
                control_center_id=scenario.control_center_id,
            )
            self.uow.emit(
                "training.scenario_changed",
                {"id": str(scenario.id)},
                required_permission=P.TRAINING_PARTICIPATE.value,
            )
            await self.uow.commit()
            await self.s.refresh(scenario)
        return scenario

    # -------------------------------------------------------------------------- sessions
    async def session(self, session_id: uuid.UUID, *, lock: bool = False) -> TrainingSession:
        stmt = select(TrainingSession).where(TrainingSession.id == session_id)
        if lock:
            stmt = stmt.with_for_update()
        session = await self.s.scalar(stmt)
        if session is None:
            raise NotFoundError("Übung nicht gefunden")
        self._check_cc(session.control_center_id)
        if session.trainee_id != self.me and not self.is_instructor:
            raise PermissionDeniedError("Fremde Übungen sehen nur Ausbilder")
        return session

    async def sessions(
        self, control_center_id: uuid.UUID | None, status: str | None, mine: bool, limit: int
    ) -> list[TrainingSession]:
        stmt = select(TrainingSession).order_by(TrainingSession.created_at.desc()).limit(limit)
        if mine or not self.is_instructor:
            stmt = stmt.where(TrainingSession.trainee_id == self.me)
        if control_center_id is not None:
            self._check_cc(control_center_id)
            stmt = stmt.where(TrainingSession.control_center_id == control_center_id)
        elif self.visible is not None:
            stmt = stmt.where(TrainingSession.control_center_id.in_(self.visible or {uuid.uuid4()}))
        if status == "open":
            stmt = stmt.where(TrainingSession.status.in_(OPEN_STATES))
        elif status:
            stmt = stmt.where(TrainingSession.status == status)
        return list((await self.s.scalars(stmt)).all())

    async def trainees(self, cc_id: uuid.UUID) -> list[User]:
        """Active users of a control centre who may take part in exercises (for instructors)."""
        self._check_cc(cc_id)
        users = (
            await self.s.scalars(select(User).where(User.is_active.is_(True)).order_by(User.display_name))
        ).all()
        result = []
        for user in users:
            perms = user.effective_permissions()
            if P.TRAINING_PARTICIPATE.value not in perms:
                continue
            if P.SYSTEM_ADMIN.value in perms or cc_id in {c.id for c in user.control_centers}:
                result.append(user)
        return result

    async def start(
        self, scenario_id: uuid.UUID, cc_id: uuid.UUID, trainee_id: uuid.UUID | None
    ) -> TrainingSession:
        await self._require_simulation()
        self._check_cc(cc_id)
        scenario = await self.scenario(scenario_id)
        if not scenario.is_active:
            raise ConflictError("Das Szenario ist deaktiviert")
        if scenario.control_center_id not in (None, cc_id):
            raise ValidationFailedError("Das Szenario gehört zu einer anderen Leitstelle")
        trainee_id = trainee_id or self.me
        if trainee_id != self.me and not self.is_instructor:
            raise PermissionDeniedError("Übungen für andere Personen starten nur Ausbilder")
        trainee = await self.s.get(User, trainee_id)
        if trainee is None or not trainee.is_active:
            raise ValidationFailedError("Übende Person nicht gefunden oder deaktiviert")
        perms = trainee.effective_permissions()
        if P.TRAINING_PARTICIPATE.value not in perms:
            raise ValidationFailedError(f"{trainee.display_name} hat keine Berechtigung zur Übungsteilnahme")
        if P.SYSTEM_ADMIN.value not in perms and cc_id not in {c.id for c in trainee.control_centers}:
            raise ValidationFailedError(f"{trainee.display_name} ist dieser Leitstelle nicht zugeordnet")
        running = await self.s.scalar(
            select(TrainingSession.id).where(
                TrainingSession.trainee_id == trainee_id, TrainingSession.status.in_(OPEN_STATES)
            )
        )
        if running is not None:
            raise ConflictError(
                f"{trainee.display_name} hat bereits eine laufende Übung",
                details={"session_id": str(running)},
            )

        _, config = await ai_settings.load(self.uow)
        try:
            has_key = bool(ai_settings.api_key_of(config, self.settings, self.box))
        except SecretBoxError:
            has_key = False
        use_ai = config.enabled and has_key
        snapshot = snapshot_of(scenario)
        persona, facts = scenario.persona or {}, scenario.facts or {}
        instructor = self.me if trainee_id != self.me else None
        session = TrainingSession(
            id=uuid.uuid4(),
            scenario_id=scenario.id,
            control_center_id=cc_id,
            trainee_id=trainee.id,
            trainee_name=trainee.display_name,
            instructor_id=instructor,
            instructor_name=self.uow.actor.name if instructor else None,
            status="ringing",
            caller_mode="claude" if use_ai else "rules",
            model=config.model if use_ai else None,
            scenario_snapshot=snapshot,
            pending_instructions=[],
        )

        async def attach(call: EmergencyCall) -> None:
            session.call_id = call.id
            self.s.add(session)
            await self.s.flush()
            self.uow.audit(
                "start",
                "training_session",
                session.id,
                f"Übung '{scenario.title}' für {trainee.display_name} gestartet "
                f"({'KI-Anrufer ' + (session.model or '') if use_ai else 'regelbasierter Anrufer'})",
                control_center_id=cc_id,
            )
            emit_session(self.uow, session, "started")

        # What the caller's phone transmits depends on the difficulty (easy: number + location).
        fields: dict[str, Any] = {"line": "112", "caller_phone": None}
        if scenario.difficulty != "hard":
            fields["caller_phone"] = persona.get("phone")
        if scenario.difficulty == "easy" and facts.get("lat") is not None:
            fields |= {
                "caller_location": facts.get("address"),
                "caller_latitude": facts.get("lat"),
                "caller_longitude": facts.get("lon"),
            }
        priority = scenario.keyword.default_priority if scenario.keyword else 2
        await CallService(self.uow, self.visible).receive(
            cc_id, source="training", priority=priority, on_created=attach, **fields
        )
        return session

    async def _call(self, session: TrainingSession) -> EmergencyCall | None:
        return await self.s.get(EmergencyCall, session.call_id) if session.call_id else None

    async def say(self, session_id: uuid.UUID, text: str, source: str) -> TrainingMessage:
        session = await self.session(session_id, lock=True)
        if session.trainee_id != self.me:
            raise PermissionDeniedError("Nur die übende Person spricht mit dem Anrufer")
        if session.status != "active":
            raise ConflictError("Das Übungsgespräch ist nicht aktiv")
        call = await self._call(session)
        if call is None or call.status != "active":
            raise ConflictError("Das Gespräch wird gehalten – zum Sprechen fortsetzen")
        message = TrainingMessage(
            session_id=session.id,
            role="dispatcher",
            text=text.strip(),
            source=source,
            author_name=self.uow.actor.name,
        )
        self.s.add(message)
        await self.s.flush()
        emit_message(self.uow, session, message)
        await self.uow.commit()
        self.runtime.schedule_reply(session.id)
        return message

    async def instruct(self, session_id: uuid.UUID, text: str, immediate: bool) -> TrainingSession:
        """Instructor intervention ("Regie"): reaches the caller with its next reply – the
        trainee never sees it."""
        session = await self.session(session_id, lock=True)
        if session.status != "active":
            raise ConflictError("Eingriffe sind nur während des Gesprächs möglich")
        pending = list(session.pending_instructions or [])
        pending.append(
            {
                "text": text.strip(),
                "author": self.uow.actor.name,
                "immediate": immediate,
                "ts": datetime.now(UTC).isoformat(),
            }
        )
        session.pending_instructions = pending
        flag_modified(session, "pending_instructions")
        self.uow.audit(
            "instruct",
            "training_session",
            session.id,
            "Ausbilder-Eingriff in Übungsgespräch",
            control_center_id=session.control_center_id,
        )
        emit_to_session(
            self.uow,
            session,
            "training.pending_changed",
            {"session_id": str(session.id), "pending": pending},
            trainee=False,
        )
        await self.uow.commit()
        if immediate:
            self.runtime.schedule_reply(session.id)
        return session

    async def note(self, session_id: uuid.UUID, text: str) -> TrainingMessage:
        """Instructor observation note (part of the report, never sent to the caller/trainee)."""
        session = await self.session(session_id)
        message = TrainingMessage(
            session_id=session.id,
            role="instructor",
            text=text.strip(),
            source="note",
            author_name=self.uow.actor.name,
        )
        self.s.add(message)
        await self.s.flush()
        emit_message(self.uow, session, message)
        await self.uow.commit()
        return message

    async def end(self, session_id: uuid.UUID) -> TrainingSession:
        session = await self.session(session_id)
        if session.status not in OPEN_STATES:
            return session
        call = await self._call(session)
        if call is not None and call.status != "ended":
            force = session.trainee_id != self.me  # an instructor ends someone else's exercise
            await CallService(self.uow, self.visible).end(call.id, force=force)
        await self.s.refresh(session)
        return session

    async def messages(self, session: TrainingSession) -> list[TrainingMessage]:
        stmt = (
            select(TrainingMessage)
            .where(TrainingMessage.session_id == session.id)
            .order_by(TrainingMessage.ts, TrainingMessage.id)
        )
        if not self.is_instructor:
            stmt = stmt.where(TrainingMessage.role.in_(("dispatcher", "caller", "system")))
        return list((await self.s.scalars(stmt)).all())

    async def evaluation_of(self, session_id: uuid.UUID) -> TrainingEvaluation | None:
        return await self.s.scalar(
            select(TrainingEvaluation).where(TrainingEvaluation.session_id == session_id)
        )

    async def evaluate(self, session_id: uuid.UUID) -> TrainingEvaluation:
        session = await self.session(session_id)
        if session.status not in ("ended", "evaluated"):
            raise ConflictError("Auswertung erst nach dem Ende des Gesprächs")
        if session.status == "evaluated" and not self.is_instructor:
            raise PermissionDeniedError("Neu auswerten können nur Ausbilder")
        await self.s.rollback()  # release the request transaction while the evaluation runs
        result = await self.runtime.evaluate(session_id, force=True)
        if result is None:
            raise ConflictError("Die Auswertung läuft bereits – bitte gleich erneut laden")
        return result

    # ------------------------------------------------------------------------ AI settings
    async def ai_settings(self) -> tuple[SystemSetting | None, ai_settings.AiConfig]:
        return await ai_settings.load(self.uow)

    async def update_ai_settings(
        self, data: dict[str, Any], expected_version: int | None
    ) -> tuple[SystemSetting, ai_settings.AiConfig]:
        row, config = await ai_settings.load(self.uow)
        if row is not None and expected_version is not None:
            check_version(row, expected_version, "Die KI-Einstellungen")
        changes: list[str] = []
        for field in ("enabled", "model", "caller_effort", "evaluation_effort"):
            if data.get(field) is not None and getattr(config, field) != data[field]:
                setattr(config, field, data[field])
                changes.append(field)
        if data.get("clear_key") and config.key_encrypted:
            config.key_encrypted, config.key_hint = None, None
            changes.append("API-Schlüssel entfernt")
        key = data.get("api_key")
        if key:
            plain = key.get_secret_value().strip()
            config.key_encrypted, config.key_hint = self.box.encrypt(plain), SecretBox.mask(plain)
            changes.append("API-Schlüssel gesetzt")
        value = {
            "enabled": config.enabled,
            "model": config.model,
            "caller_effort": config.caller_effort,
            "evaluation_effort": config.evaluation_effort,
            "key_encrypted": config.key_encrypted,
            "key_hint": config.key_hint,
        }
        if row is None:
            row = SystemSetting(key=ai_settings.AI_KEY, value=value, updated_by=self.me)
            self.s.add(row)
        else:
            row.value = value
            row.updated_by = self.me
        await self.s.flush()
        if changes:
            self.uow.audit(
                "update", "system", ai_settings.AI_KEY, f"KI-Einstellungen geändert: {', '.join(changes)}"
            )  # never the key itself
            self.uow.emit(
                "training.ai_settings_changed",
                {"enabled": config.enabled},
                required_permission=P.SYSTEM_ADMIN.value,
            )
        await self.uow.commit()
        return row, config

    async def test_ai(self) -> dict[str, Any]:
        """One minimal request – only on an administrator's explicit click."""
        import anthropic

        _, config = await ai_settings.load(self.uow)
        try:
            key = ai_settings.api_key_of(config, self.settings, self.box)
        except SecretBoxError:
            key = None
        if not key:
            return {
                "ok": False,
                "model": None,
                "latency_ms": None,
                "message": "Kein API-Schlüssel hinterlegt",
            }
        client = self.runtime._client(key)
        started = time.perf_counter()
        try:
            response = await client.beta.messages.create(
                model=config.model,
                max_tokens=2000,
                messages=[{"role": "user", "content": "Antworte nur mit: Verbindung steht."}],
                output_config={"effort": "low"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            return {
                "ok": False,
                "model": config.model,
                "latency_ms": None,
                "message": "API-Schlüssel ungültig",
            }
        except anthropic.APIStatusError as exc:
            return {
                "ok": False,
                "model": config.model,
                "latency_ms": None,
                "message": f"Fehler der KI-Schnittstelle ({exc.status_code})",
            }
        except anthropic.APIConnectionError:
            return {
                "ok": False,
                "model": config.model,
                "latency_ms": None,
                "message": "KI-Schnittstelle nicht erreichbar",
            }
        latency = round((time.perf_counter() - started) * 1000)
        if response.stop_reason == "refusal":
            return {
                "ok": False,
                "model": response.model,
                "latency_ms": latency,
                "message": "Anfrage abgelehnt",
            }
        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
        return {
            "ok": True,
            "model": response.model,
            "latency_ms": latency,
            "message": text or "Verbindung steht.",
        }


async def cancel_open_sessions(uow: UnitOfWork, reason: str) -> int:
    """Leaving simulation mode: running exercises end (and their training calls)."""
    sessions = list(
        (
            await uow.session.scalars(
                select(TrainingSession).where(TrainingSession.status.in_(OPEN_STATES)).with_for_update()
            )
        ).all()
    )
    now = datetime.now(UTC)
    for session in sessions:
        call = await uow.session.get(EmergencyCall, session.call_id) if session.call_id else None
        if call is not None and call.status != "ended":
            call.status, call.ended_at = "ended", now
            uow.emit(
                "call.changed",
                {
                    "id": str(call.id),
                    "status": "ended",
                    "priority": call.priority,
                    "action": "ended",
                    "handled_by": None,
                },
                channels=[f"cc:{call.control_center_id}"],
                required_permission=P.CALLS_HANDLE.value,
            )
        session.status, session.ended_at = "cancelled", now
        m = TrainingMessage(
            session_id=session.id, ts=now, role="system", text=f"Übung abgebrochen: {reason}", source="system"
        )
        uow.session.add(m)
        await uow.session.flush()
        emit_session(uow, session, "cancelled")
        emit_message(uow, session, m)
    return len(sessions)
