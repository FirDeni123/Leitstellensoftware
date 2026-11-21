from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import or_, select

from app.api.deps import AuthContext, AuthDep, UowDep, require, uow_for
from app.core.config import APP_VERSION
from app.core.permissions import P
from app.models import AuditLog
from app.schemas.system import (
    AuditEntryOut,
    AuditPage,
    LayoutOut,
    LayoutPut,
    OperationModeOut,
    OperationModeUpdate,
    SystemInfo,
)
from app.services.system_service import MODULES, SystemService

router = APIRouter(tags=["System"])


@router.get("/system/info", response_model=SystemInfo, summary="Systeminformationen und Modulstatus")
async def system_info(request: Request, auth: AuthDep, uow: UowDep) -> SystemInfo:
    return SystemInfo(
        product="ILS-Sim",
        version=APP_VERSION,
        environment=request.app.state.settings.environment.value,
        server_time=datetime.now(UTC),
        operation_mode=await SystemService(uow).operation_mode(),
        realtime_backend=request.app.state.bus.name,
        modules=list(MODULES),
    )


@router.get("/system/operation-mode", response_model=OperationModeOut)
async def get_operation_mode(auth: AuthDep, uow: UowDep) -> OperationModeOut:
    s = await SystemService(uow).mode_setting()
    return OperationModeOut(mode=s.value, version=s.version, updated_at=s.updated_at)


@router.put("/system/operation-mode", response_model=OperationModeOut, summary="Betriebsmodus umschalten")
async def set_operation_mode(
    body: OperationModeUpdate,
    auth: Annotated[AuthContext, Depends(require(P.SYSTEM_MODE_CHANGE))],
    uow: UowDep,
) -> OperationModeOut:
    s = await SystemService(uow_for(auth, uow)).set_operation_mode(
        body.mode, body.reason, body.confirmation, body.expected_version
    )
    return OperationModeOut(mode=s.value, version=s.version, updated_at=s.updated_at)


# ------------------------------------------------------------------------------- audit log
@router.get("/audit", response_model=AuditPage, summary="Änderungsprotokoll (neueste zuerst)")
async def audit_log(
    auth: Annotated[AuthContext, Depends(require(P.AUDIT_READ))],
    uow: UowDep,
    entity_type: str | None = None,
    entity_id: str | None = None,
    control_center_id: uuid.UUID | None = None,
    before_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> AuditPage:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit + 1)
    if not auth.is_admin:
        # Non-admins see global entries and those of their own control centres.
        stmt = stmt.where(
            or_(
                AuditLog.control_center_id.is_(None),
                AuditLog.control_center_id.in_(auth.control_center_ids()),
            )
        )
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if control_center_id:
        stmt = stmt.where(AuditLog.control_center_id == control_center_id)
    if before_id:
        stmt = stmt.where(AuditLog.id < before_id)
    rows = list((await uow.session.scalars(stmt)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return AuditPage(
        items=[AuditEntryOut.model_validate(r) for r in rows],
        next_before_id=rows[-1].id if has_more and rows else None,
    )


# --------------------------------------------------------------------------------- layouts
@router.get(
    "/me/layouts/{workstation}", response_model=LayoutOut, summary="Gespeichertes Arbeitsplatz-Layout"
)
async def get_layout(workstation: str, auth: AuthDep, uow: UowDep) -> LayoutOut:
    row = await SystemService(uow).get_layout(auth.user.id, workstation)
    return LayoutOut(
        workstation=row.workstation, layout=row.layout, version=row.version, updated_at=row.updated_at
    )


@router.put("/me/layouts/{workstation}", response_model=LayoutOut)
async def put_layout(workstation: str, body: LayoutPut, auth: AuthDep, uow: UowDep) -> LayoutOut:
    row = await SystemService(uow_for(auth, uow)).put_layout(
        auth.user.id, workstation, body.layout, body.expected_version
    )
    return LayoutOut(
        workstation=row.workstation, layout=row.layout, version=row.version, updated_at=row.updated_at
    )


@router.delete(
    "/me/layouts/{workstation}", status_code=status.HTTP_204_NO_CONTENT, summary="Layout zurücksetzen"
)
async def delete_layout(workstation: str, auth: AuthDep, uow: UowDep) -> None:
    await SystemService(uow_for(auth, uow)).delete_layout(auth.user.id, workstation)
