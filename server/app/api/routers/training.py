"""Ausbildung (Phase 7): scenarios, exercises with an AI caller, instructor mode, evaluation."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status

from app.api.crud_router import visible_control_centers
from app.api.deps import AuthContext, UowDep, require, uow_for
from app.core.errors import NotAvailableError, ValidationFailedError
from app.core.permissions import P
from app.models import EmergencyCall, TrainingScenario, TrainingSession
from app.schemas.training import (
    AiSettingsOut,
    AiSettingsUpdate,
    AiTestOut,
    EvaluationOut,
    InstructionIn,
    MessageIn,
    MessageOut,
    NoteIn,
    ScenarioCreate,
    ScenarioOut,
    ScenarioUpdate,
    SessionDetail,
    SessionOut,
    SessionStart,
    SpeechOut,
    TraineeOut,
)
from app.services.training_service import TrainingService
from app.training.speech import MAX_AUDIO_BYTES, whisper_installed

router = APIRouter(prefix="/training", tags=["Ausbildung"])

ParticipateDep = Annotated[AuthContext, Depends(require(P.TRAINING_PARTICIPATE))]
InstructorDep = Annotated[AuthContext, Depends(require(P.TRAINING_INSTRUCTOR))]
AdminDep = Annotated[AuthContext, Depends(require(P.SYSTEM_ADMIN))]


def _service(request: Request, auth: AuthContext, uow: UowDep) -> TrainingService:
    state = request.app.state
    return TrainingService(
        uow_for(auth, uow),
        visible_control_centers(auth),
        auth.permissions,
        state.training,
        state.settings,
        state.secret_box,
    )


def scenario_out(s: TrainingScenario) -> ScenarioOut:
    out = ScenarioOut.model_validate(s)
    if s.keyword is not None:
        out.keyword_code, out.keyword_name = s.keyword.code, s.keyword.name
    return out


async def session_out(service: TrainingService, s: TrainingSession) -> SessionOut:
    call = await service.s.get(EmergencyCall, s.call_id) if s.call_id else None
    evaluation = await service.evaluation_of(s.id) if s.status == "evaluated" else None
    snap = s.scenario_snapshot or {}
    return SessionOut(
        id=s.id,
        scenario_id=s.scenario_id,
        control_center_id=s.control_center_id,
        title=snap.get("title", "Übung"),
        difficulty=snap.get("difficulty", "medium"),
        trainee_id=s.trainee_id,
        trainee_name=s.trainee_name,
        instructor_id=s.instructor_id,
        instructor_name=s.instructor_name,
        call_id=s.call_id,
        call_status=call.status if call else None,
        status=s.status,
        caller_mode=s.caller_mode,
        model=s.model,
        created_at=s.created_at,
        answered_at=s.answered_at,
        ended_at=s.ended_at,
        score=evaluation.score if evaluation else None,
    )


async def session_detail(service: TrainingService, s: TrainingSession) -> SessionDetail:
    base = await session_out(service, s)
    evaluation = await service.evaluation_of(s.id)
    over = s.status in ("ended", "evaluated", "cancelled")
    return SessionDetail(
        **base.model_dump(),
        messages=[MessageOut.model_validate(m) for m in await service.messages(s)],
        pending_instructions=list(s.pending_instructions or []) if service.is_instructor else None,
        scenario=s.scenario_snapshot if service.is_instructor or over else None,
        evaluation=EvaluationOut.model_validate(evaluation) if evaluation else None,
    )


# --------------------------------------------------------------------------- scenarios
@router.get("/scenarios", response_model=list[ScenarioOut], summary="Übungsszenarien")
async def list_scenarios(
    request: Request,
    auth: ParticipateDep,
    uow: UowDep,
    control_center_id: uuid.UUID | None = None,
    include_inactive: bool = False,
) -> list[ScenarioOut]:
    service = _service(request, auth, uow)
    scenarios = await service.scenarios(control_center_id, include_inactive and service.is_instructor)
    if not service.is_instructor:  # trainees see title and difficulty – not the solution
        return [
            scenario_out(s).model_copy(
                update={"facts": {}, "persona": {}, "checklist": [], "opening_line": "…"}
            )
            for s in scenarios
        ]
    return [scenario_out(s) for s in scenarios]


@router.get("/scenarios/{scenario_id}", response_model=ScenarioOut)
async def get_scenario(
    scenario_id: uuid.UUID, request: Request, auth: InstructorDep, uow: UowDep
) -> ScenarioOut:
    return scenario_out(await _service(request, auth, uow).scenario(scenario_id))


@router.post("/scenarios", response_model=ScenarioOut, status_code=status.HTTP_201_CREATED)
async def create_scenario(
    body: ScenarioCreate, request: Request, auth: InstructorDep, uow: UowDep
) -> ScenarioOut:
    return scenario_out(
        await _service(request, auth, uow).create_scenario(
            body.model_dump(mode="json")
            | {"control_center_id": body.control_center_id, "keyword_id": body.keyword_id}
        )
    )


@router.patch("/scenarios/{scenario_id}", response_model=ScenarioOut)
async def update_scenario(
    scenario_id: uuid.UUID, body: ScenarioUpdate, request: Request, auth: InstructorDep, uow: UowDep
) -> ScenarioOut:
    data = body.model_dump(mode="json", exclude_unset=True, exclude={"expected_version"})
    if "keyword_id" in body.model_fields_set:
        data["keyword_id"] = body.keyword_id
    return scenario_out(
        await _service(request, auth, uow).update_scenario(scenario_id, data, body.expected_version)
    )


@router.get("/trainees", response_model=list[TraineeOut], summary="Übende Personen einer Leitstelle")
async def list_trainees(
    control_center_id: uuid.UUID, request: Request, auth: InstructorDep, uow: UowDep
) -> list[TraineeOut]:
    users = await _service(request, auth, uow).trainees(control_center_id)
    return [TraineeOut(id=u.id, username=u.username, display_name=u.display_name) for u in users]


# ---------------------------------------------------------------------------- sessions
@router.get("/sessions", response_model=list[SessionOut], summary="Übungen (eigene; Ausbilder: alle)")
async def list_sessions(
    request: Request,
    auth: ParticipateDep,
    uow: UowDep,
    control_center_id: uuid.UUID | None = None,
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(open|ringing|active|ended|evaluated|cancelled)$"
    ),
    mine: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[SessionOut]:
    service = _service(request, auth, uow)
    return [
        await session_out(service, s)
        for s in await service.sessions(control_center_id, status_filter, mine, limit)
    ]


@router.post(
    "/sessions",
    response_model=SessionDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Übung starten – der Übungsanruf klingelt in der Notrufannahme",
)
async def start_session(
    body: SessionStart, request: Request, auth: ParticipateDep, uow: UowDep
) -> SessionDetail:
    service = _service(request, auth, uow)
    session = await service.start(body.scenario_id, body.control_center_id, body.trainee_id)
    return await session_detail(service, await service.session(session.id))


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: uuid.UUID, request: Request, auth: ParticipateDep, uow: UowDep
) -> SessionDetail:
    service = _service(request, auth, uow)
    return await session_detail(service, await service.session(session_id))


@router.post(
    "/sessions/{session_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Disponent spricht – die Antwort des Anrufers kommt per Echtzeit-Ereignis",
)
async def say(
    session_id: uuid.UUID, body: MessageIn, request: Request, auth: ParticipateDep, uow: UowDep
) -> MessageOut:
    return MessageOut.model_validate(
        await _service(request, auth, uow).say(session_id, body.text, body.source)
    )


@router.post(
    "/sessions/{session_id}/speech",
    response_model=SpeechOut,
    summary="Sprachaufnahme erkennen (faster-whisper, optional) und als Gesprächsbeitrag senden",
)
async def speech(
    session_id: uuid.UUID,
    request: Request,
    auth: ParticipateDep,
    uow: UowDep,
    audio: Annotated[UploadFile, File()],
    send: bool = True,
) -> SpeechOut:
    stt = request.app.state.training.stt
    if stt is None:
        raise NotAvailableError(
            "Spracherkennung ist auf diesem Server nicht installiert (faster-whisper) – bitte tippen"
        )
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise ValidationFailedError("Aufnahme zu lang (max. ca. 60 Sekunden)")
    service = _service(request, auth, uow)
    await service.session(session_id)  # access check before the (expensive) recognition
    text = (await stt.transcribe(data)).strip()
    if not text or not send:
        return SpeechOut(text=text, message=None)
    return SpeechOut(
        text=text, message=MessageOut.model_validate(await service.say(session_id, text[:2000], "voice"))
    )


@router.post("/sessions/{session_id}/end", response_model=SessionDetail, summary="Übung beenden (legt auf)")
async def end_session(
    session_id: uuid.UUID, request: Request, auth: ParticipateDep, uow: UowDep
) -> SessionDetail:
    service = _service(request, auth, uow)
    session = await service.end(session_id)
    return await session_detail(service, session)


@router.post(
    "/sessions/{session_id}/instructions", response_model=SessionDetail, summary="Ausbilder-Eingriff (Regie)"
)
async def instruct(
    session_id: uuid.UUID, body: InstructionIn, request: Request, auth: InstructorDep, uow: UowDep
) -> SessionDetail:
    service = _service(request, auth, uow)
    session = await service.instruct(session_id, body.text, body.immediate)
    return await session_detail(service, session)


@router.post(
    "/sessions/{session_id}/notes", response_model=MessageOut, summary="Beobachtungsnotiz des Ausbilders"
)
async def note(
    session_id: uuid.UUID, body: NoteIn, request: Request, auth: InstructorDep, uow: UowDep
) -> MessageOut:
    return MessageOut.model_validate(await _service(request, auth, uow).note(session_id, body.text))


@router.post("/sessions/{session_id}/evaluate", response_model=EvaluationOut, summary="(Neu) auswerten")
async def evaluate(
    session_id: uuid.UUID, request: Request, auth: ParticipateDep, uow: UowDep
) -> EvaluationOut:
    return EvaluationOut.model_validate(await _service(request, auth, uow).evaluate(session_id))


# ------------------------------------------------------------------------- AI settings
def ai_out(request: Request, row: object, config: object) -> AiSettingsOut:
    settings = request.app.state.settings
    return AiSettingsOut(
        **config.public(bool(settings.anthropic_api_key)),  # type: ignore[attr-defined]
        base_url=settings.anthropic_base_url,
        speech_to_text=whisper_installed(),
        version=getattr(row, "version", None),
    )


@router.get(
    "/ai-settings", response_model=AiSettingsOut, summary="KI-Einstellungen (Schlüssel wird nie ausgegeben)"
)
async def get_ai_settings(request: Request, auth: AdminDep, uow: UowDep) -> AiSettingsOut:
    row, config = await _service(request, auth, uow).ai_settings()
    return ai_out(request, row, config)


@router.put("/ai-settings", response_model=AiSettingsOut)
async def put_ai_settings(
    body: AiSettingsUpdate, request: Request, auth: AdminDep, uow: UowDep
) -> AiSettingsOut:
    data = body.model_dump(exclude={"expected_version", "api_key"}) | {"api_key": body.api_key}
    row, config = await _service(request, auth, uow).update_ai_settings(data, body.expected_version)
    return ai_out(request, row, config)


@router.post(
    "/ai-settings/test", response_model=AiTestOut, summary="Verbindung zur KI testen (eine kurze Anfrage)"
)
async def test_ai(request: Request, auth: AdminDep, uow: UowDep) -> AiTestOut:
    return AiTestOut(**await _service(request, auth, uow).test_ai())
