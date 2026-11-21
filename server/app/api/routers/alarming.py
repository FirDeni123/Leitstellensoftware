"""Alarm rules (AAO), alarm preview, confirmed alarms and police notices (Phase 4)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request, Response, status

from app.api.crud_router import visible_control_centers
from app.api.deps import AuthContext, UowDep, require, uow_for
from app.core.errors import ValidationFailedError
from app.core.permissions import P
from app.models import Alarm, AlarmRule, PoliceNotice
from app.schemas.alarming import (
    AlarmCreate,
    AlarmOut,
    AlarmPreview,
    AlarmRuleCreate,
    AlarmRuleOut,
    AlarmRuleUpdate,
    PoliceAcknowledge,
    PoliceNoticeOut,
    PreviewRequest,
)
from app.services.alarm_delivery import deliver_alarm
from app.services.alarm_rule_service import AlarmRuleService, item_target_id
from app.services.alarm_service import AlarmService

router = APIRouter()

RulesReadDep = Annotated[AuthContext, Depends(require(P.MASTER_DATA_READ))]
RulesWriteDep = Annotated[AuthContext, Depends(require(P.MASTER_DATA_READ, P.ALARM_RULES_WRITE))]
ReadDep = Annotated[AuthContext, Depends(require(P.INCIDENTS_READ))]
TriggerDep = Annotated[AuthContext, Depends(require(P.INCIDENTS_READ, P.ALARM_TRIGGER))]
AckDep = Annotated[AuthContext, Depends(require(P.INCIDENTS_READ, P.INCIDENTS_WRITE))]


def _tz(request: Request) -> str:
    return request.app.state.settings.timezone


# ------------------------------------------------------------------------------ converters
async def rules_out(service: AlarmRuleService, rules: list[AlarmRule]) -> list[AlarmRuleOut]:
    labels = await service.labels(rules)
    areas = await service.area_names(rules)
    result = []
    for rule in rules:
        items = [
            {
                "id": i.id,
                "stage": i.stage,
                "position": i.position,
                "kind": i.kind,
                "count": i.count,
                "target_id": item_target_id(i),
                "target_label": labels.get((i.kind, item_target_id(i)), "(gelöscht)"),
                "note": i.note,
            }
            for i in rule.items
        ]
        result.append(
            AlarmRuleOut.model_validate(
                {
                    "id": rule.id,
                    "control_center_id": rule.control_center_id,
                    "keyword": rule.keyword,
                    "area": {"id": rule.area_id, "name": areas.get(rule.area_id, "?")}
                    if rule.area_id
                    else None,
                    "name": rule.name,
                    "is_active": rule.is_active,
                    "items": items,
                    "max_stage": max((i.stage for i in rule.items), default=0),
                    "created_at": rule.created_at,
                    "updated_at": rule.updated_at,
                    "version": rule.version,
                }
            )
        )
    return result


def notice_out(notice: PoliceNotice, numbers: dict[uuid.UUID, str]) -> PoliceNoticeOut:
    data: dict[str, Any] = {f: getattr(notice, f) for f in PoliceNoticeOut.model_fields if hasattr(notice, f)}
    data["incident_number"] = numbers.get(notice.incident_id, "")
    return PoliceNoticeOut.model_validate(data)


async def alarms_out(service: AlarmService, alarms: list[Alarm], replayed: bool = False) -> list[AlarmOut]:
    incident_ids = {a.incident_id for a in alarms}
    numbers = await service.numbers(incident_ids)
    notices: dict[uuid.UUID, PoliceNotice] = {}
    for notice in await service.notices_for(incident_ids):
        notices.setdefault(notice.incident_id, notice)
    result = []
    for alarm in alarms:
        data: dict[str, Any] = {f: getattr(alarm, f) for f in AlarmOut.model_fields if hasattr(alarm, f)}
        notice = notices.get(alarm.incident_id)
        data |= {
            "incident_number": numbers.get(alarm.incident_id, ""),
            "targets": list(alarm.targets),
            "replayed": replayed,
            "police_notice": notice_out(notice, numbers) if notice else None,
        }
        result.append(AlarmOut.model_validate(data))
    return result


# ----------------------------------------------------------------------------------- AAO
@router.get("/alarm-rules", response_model=list[AlarmRuleOut], tags=["Alarmierung"], summary="AAO")
async def list_rules(
    auth: RulesReadDep,
    uow: UowDep,
    control_center_id: uuid.UUID | None = None,
    keyword_id: uuid.UUID | None = None,
) -> list[AlarmRuleOut]:
    service = AlarmRuleService(uow, visible_control_centers(auth))
    return await rules_out(service, await service.list(control_center_id, keyword_id))


@router.get("/alarm-rules/{rule_id}", response_model=AlarmRuleOut, tags=["Alarmierung"])
async def get_rule(rule_id: uuid.UUID, auth: RulesReadDep, uow: UowDep) -> AlarmRuleOut:
    service = AlarmRuleService(uow, visible_control_centers(auth))
    return (await rules_out(service, [await service.get(rule_id)]))[0]


@router.post(
    "/alarm-rules", response_model=AlarmRuleOut, status_code=status.HTTP_201_CREATED, tags=["Alarmierung"]
)
async def create_rule(body: AlarmRuleCreate, auth: RulesWriteDep, uow: UowDep) -> AlarmRuleOut:
    service = AlarmRuleService(uow_for(auth, uow), visible_control_centers(auth))
    rule = await service.create(body.model_dump())
    return (await rules_out(service, [rule]))[0]


@router.patch("/alarm-rules/{rule_id}", response_model=AlarmRuleOut, tags=["Alarmierung"])
async def update_rule(
    rule_id: uuid.UUID, body: AlarmRuleUpdate, auth: RulesWriteDep, uow: UowDep
) -> AlarmRuleOut:
    service = AlarmRuleService(uow_for(auth, uow), visible_control_centers(auth))
    data = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    rule = await service.update(rule_id, data, body.expected_version)
    return (await rules_out(service, [rule]))[0]


@router.delete("/alarm-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Alarmierung"])
async def delete_rule(
    rule_id: uuid.UUID, auth: RulesWriteDep, uow: UowDep, expected_version: int = Query(ge=1)
) -> None:
    await AlarmRuleService(uow_for(auth, uow), visible_control_centers(auth)).delete(
        rule_id, expected_version
    )


# -------------------------------------------------------------------------------- alarms
@router.post(
    "/incidents/{incident_id}/alarm-preview",
    response_model=AlarmPreview,
    tags=["Alarmierung"],
    summary="Alarmierungsvorschau (löst nichts aus)",
)
async def alarm_preview(
    incident_id: uuid.UUID, body: PreviewRequest, request: Request, auth: ReadDep, uow: UowDep
) -> Any:
    service = AlarmService(uow, visible_control_centers(auth), _tz(request), request.app.state.routing)
    return await service.preview(incident_id, body.stage, body.selection)


@router.post(
    "/incidents/{incident_id}/alarms",
    response_model=AlarmOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Alarmierung"],
    summary="Alarmierung nach Bestätigung durch den Disponenten auslösen",
    description="Erfordert `confirmed: true` und einen eindeutigen `Idempotency-Key` je Alarmierung. "
    "Eine Wiederholung mit demselben Schlüssel liefert die bestehende Alarmierung (HTTP 200).",
)
async def trigger_alarm(
    incident_id: uuid.UUID,
    body: AlarmCreate,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    auth: TriggerDep,
    uow: UowDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AlarmOut:
    if not idempotency_key or not (8 <= len(idempotency_key) <= 80):
        raise ValidationFailedError("Header 'Idempotency-Key' (8–80 Zeichen) fehlt")
    service = AlarmService(
        uow_for(auth, uow), visible_control_centers(auth), _tz(request), request.app.state.routing
    )
    alarm, replayed = await service.trigger(incident_id, body, idempotency_key)
    if replayed:
        response.status_code = status.HTTP_200_OK
    elif alarm.status == "pending":
        state = request.app.state
        background.add_task(deliver_alarm, state.db.sessionmaker, state.bus, state.secret_box, alarm.id)
    return (await alarms_out(service, [alarm], replayed))[0]


@router.get("/incidents/{incident_id}/alarms", response_model=list[AlarmOut], tags=["Alarmierung"])
async def incident_alarms(
    incident_id: uuid.UUID, request: Request, auth: ReadDep, uow: UowDep
) -> list[AlarmOut]:
    service = AlarmService(uow, visible_control_centers(auth), _tz(request), request.app.state.routing)
    return await alarms_out(service, await service.list(None, incident_id, 200))


@router.get("/alarms", response_model=list[AlarmOut], tags=["Alarmierung"], summary="Alarmierungsübersicht")
async def list_alarms(
    request: Request,
    auth: ReadDep,
    uow: UowDep,
    control_center_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AlarmOut]:
    service = AlarmService(uow, visible_control_centers(auth), _tz(request), request.app.state.routing)
    return await alarms_out(service, await service.list(control_center_id, None, limit))


@router.get("/alarms/{alarm_id}", response_model=AlarmOut, tags=["Alarmierung"])
async def get_alarm(alarm_id: uuid.UUID, request: Request, auth: ReadDep, uow: UowDep) -> AlarmOut:
    service = AlarmService(uow, visible_control_centers(auth), _tz(request), request.app.state.routing)
    return (await alarms_out(service, [await service.get(alarm_id)]))[0]


# ------------------------------------------------------------------------ police notices
@router.get("/police-notices", response_model=list[PoliceNoticeOut], tags=["Alarmierung"])
async def list_police_notices(
    request: Request,
    auth: ReadDep,
    uow: UowDep,
    control_center_id: uuid.UUID | None = None,
    only_open: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[PoliceNoticeOut]:
    service = AlarmService(uow, visible_control_centers(auth), _tz(request), request.app.state.routing)
    notices = await service.police_notices(control_center_id, only_open, limit)
    numbers = await service.numbers({n.incident_id for n in notices})
    return [notice_out(n, numbers) for n in notices]


@router.post(
    "/police-notices/{notice_id}/acknowledge",
    response_model=PoliceNoticeOut,
    tags=["Alarmierung"],
    summary="Polizei-Hinweis zur Kenntnis nehmen (keine Übermittlung an die Polizei)",
)
async def acknowledge_police_notice(
    notice_id: uuid.UUID, body: PoliceAcknowledge, request: Request, auth: AckDep, uow: UowDep
) -> PoliceNoticeOut:
    service = AlarmService(
        uow_for(auth, uow), visible_control_centers(auth), _tz(request), request.app.state.routing
    )
    notice = await service.acknowledge(notice_id, body.note)
    return notice_out(notice, await service.numbers({notice.incident_id}))
