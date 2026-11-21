"""Einsatzmittelvorschlag (Phase 5): compute, history, accept (assign only), settings."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.crud_router import visible_control_centers
from app.api.deps import AuthContext, UowDep, require, uow_for
from app.core.permissions import P
from app.models import Proposal
from app.proposal.settings import ProposalSettingsData
from app.schemas.proposals import (
    ProposalAccept,
    ProposalOut,
    ProposalRequest,
    ProposalSettingsOut,
    ProposalSettingsUpdate,
)
from app.services.proposal_service import ProposalService

router = APIRouter(tags=["Einsatzmittelvorschlag"])

ReadDep = Annotated[AuthContext, Depends(require(P.INCIDENTS_READ))]
WriteDep = Annotated[AuthContext, Depends(require(P.INCIDENTS_READ, P.INCIDENTS_WRITE))]
SettingsReadDep = Annotated[AuthContext, Depends(require(P.MASTER_DATA_READ))]
SettingsWriteDep = Annotated[AuthContext, Depends(require(P.MASTER_DATA_READ, P.PROPOSAL_SETTINGS_WRITE))]


def _service(request: Request, auth: AuthContext, uow: UowDep) -> ProposalService:
    state = request.app.state
    return ProposalService(
        uow_for(auth, uow), visible_control_centers(auth), state.routing, state.settings.timezone
    )


def proposal_out(p: Proposal) -> ProposalOut:
    data: dict[str, Any] = dict(p.result)
    data |= {
        "id": p.id,
        "incident_id": p.incident_id,
        "control_center_id": p.control_center_id,
        "computed_at": p.computed_at,
        "computed_by_name": p.computed_by_name,
        "duration_ms": p.duration_ms,
        "accepted_vehicle_ids": p.accepted_vehicle_ids,
        "accepted_at": p.accepted_at,
        "accepted_by_name": p.accepted_by_name,
    }
    return ProposalOut.model_validate(data)


@router.post(
    "/incidents/{incident_id}/proposal",
    response_model=ProposalOut,
    status_code=status.HTTP_201_CREATED,
    summary="Einsatzmittelvorschlag berechnen (alarmiert nicht, ordnet nicht zu)",
)
async def compute_proposal(
    incident_id: uuid.UUID, body: ProposalRequest, request: Request, auth: WriteDep, uow: UowDep
) -> ProposalOut:
    service = _service(request, auth, uow)
    extra = [e.model_dump() for e in body.extra]
    return proposal_out(await service.create(incident_id, body.stage, extra))


@router.get(
    "/incidents/{incident_id}/proposals", response_model=list[ProposalOut], summary="Gespeicherte Vorschläge"
)
async def proposal_history(
    incident_id: uuid.UUID,
    request: Request,
    auth: ReadDep,
    uow: UowDep,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[ProposalOut]:
    return [proposal_out(p) for p in await _service(request, auth, uow).history(incident_id, limit)]


@router.get("/proposals/{proposal_id}", response_model=ProposalOut)
async def get_proposal(proposal_id: uuid.UUID, request: Request, auth: ReadDep, uow: UowDep) -> ProposalOut:
    return proposal_out(await _service(request, auth, uow).get(proposal_id))


@router.post(
    "/proposals/{proposal_id}/accept",
    response_model=ProposalOut,
    summary="Vorschlag übernehmen: Fahrzeuge zuordnen (keine Alarmierung)",
)
async def accept_proposal(
    proposal_id: uuid.UUID, body: ProposalAccept, request: Request, auth: WriteDep, uow: UowDep
) -> ProposalOut:
    service = _service(request, auth, uow)
    return proposal_out(await service.accept(proposal_id, body.vehicle_ids, body.reassign))


@router.get(
    "/proposal-settings", response_model=ProposalSettingsOut, summary="Regeln des Vorschlags je Leitstelle"
)
async def get_settings(
    control_center_id: uuid.UUID, request: Request, auth: SettingsReadDep, uow: UowDep
) -> ProposalSettingsOut:
    service = _service(request, auth, uow)
    service.incidents._check_cc(control_center_id)
    row = await service.settings_row(control_center_id)
    return ProposalSettingsOut(
        control_center_id=control_center_id,
        settings=await service.settings_for(control_center_id),
        defaults=ProposalSettingsData(),
        is_default=row is None,
        version=row.version if row else None,
        updated_at=row.updated_at if row else None,
        updated_by_name=row.updated_by_name if row else None,
        routing_configured=request.app.state.routing is not None,
    )


@router.put("/proposal-settings", response_model=ProposalSettingsOut)
async def put_settings(
    body: ProposalSettingsUpdate, request: Request, auth: SettingsWriteDep, uow: UowDep
) -> ProposalSettingsOut:
    service = _service(request, auth, uow)
    row = await service.put_settings(body.control_center_id, body.settings, body.expected_version)
    return ProposalSettingsOut(
        control_center_id=row.control_center_id,
        settings=ProposalSettingsData.model_validate(row.settings),
        defaults=ProposalSettingsData(),
        is_default=False,
        version=row.version,
        updated_at=row.updated_at,
        updated_by_name=row.updated_by_name,
        routing_configured=request.app.state.routing is not None,
    )
