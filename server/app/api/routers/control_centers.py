from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import AuthContext, UowDep, require, uow_for
from app.core.permissions import P
from app.schemas.control_centers import ControlCenterCreate, ControlCenterOut, ControlCenterUpdate
from app.services.control_center_service import ControlCenterService

router = APIRouter(prefix="/control-centers", tags=["Leitstellen"])

CanRead = Annotated[AuthContext, Depends(require(P.CONTROL_CENTERS_READ))]
CanWrite = Annotated[AuthContext, Depends(require(P.CONTROL_CENTERS_WRITE))]


def _visible(auth: AuthContext) -> set[uuid.UUID] | None:
    return None if auth.is_admin else auth.control_center_ids()


@router.get("", response_model=list[ControlCenterOut], summary="Sichtbare Leitstellen")
async def list_control_centers(auth: CanRead, uow: UowDep) -> list[ControlCenterOut]:
    return [ControlCenterOut.model_validate(c) for c in await ControlCenterService(uow).list(_visible(auth))]


@router.get("/{cc_id}", response_model=ControlCenterOut)
async def get_control_center(cc_id: uuid.UUID, auth: CanRead, uow: UowDep) -> ControlCenterOut:
    return ControlCenterOut.model_validate(await ControlCenterService(uow).get(cc_id, _visible(auth)))


@router.post("", response_model=ControlCenterOut, status_code=status.HTTP_201_CREATED)
async def create_control_center(body: ControlCenterCreate, auth: CanWrite, uow: UowDep) -> ControlCenterOut:
    return ControlCenterOut.model_validate(await ControlCenterService(uow_for(auth, uow)).create(body))


@router.patch("/{cc_id}", response_model=ControlCenterOut)
async def update_control_center(
    cc_id: uuid.UUID, body: ControlCenterUpdate, auth: CanWrite, uow: UowDep
) -> ControlCenterOut:
    service = ControlCenterService(uow_for(auth, uow))
    await service.get(cc_id, _visible(auth))
    return ControlCenterOut.model_validate(await service.update(cc_id, body))


@router.delete("/{cc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_control_center(
    cc_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require(P.CONTROL_CENTERS_WRITE, P.SYSTEM_ADMIN))],
    uow: UowDep,
) -> None:
    await ControlCenterService(uow_for(auth, uow)).delete(cc_id)
