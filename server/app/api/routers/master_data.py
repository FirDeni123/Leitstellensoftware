"""Master data endpoints (Phase 2)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.api.crud_router import register_crud, visible_control_centers
from app.api.deps import AuthContext, UowDep, require, uow_for
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.geo import point_in_geometry
from app.core.permissions import P
from app.models import ControlCenter, ControlCenterArea, ControlCenterLink
from app.schemas.auth import ControlCenterRef
from app.schemas.master_data import (
    AlarmGroupCreate,
    AlarmGroupOut,
    AlarmGroupUpdate,
    AreaCreate,
    AreaOut,
    AreaUpdate,
    LinkCreate,
    LinkOut,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
    RadioGroupCreate,
    RadioGroupOut,
    RadioGroupUpdate,
    ResponsibilityOut,
    RicCreate,
    RicOut,
    RicUpdate,
    StationCreate,
    StationOut,
    StationUpdate,
    StatusDefinitionOut,
    StatusDefinitionUpdate,
    VehicleCreate,
    VehicleOut,
    VehicleTypeCreate,
    VehicleTypeOut,
    VehicleTypeUpdate,
    VehicleUpdate,
)
from app.services import master_data as md

router = APIRouter()

register_crud(
    router,
    spec=md.ORGANIZATIONS,
    path="/organizations",
    create_model=OrganizationCreate,
    update_model=OrganizationUpdate,
    out_model=OrganizationOut,
    read_perm=P.MASTER_DATA_READ,
    write_perm=P.ORGANIZATIONS_WRITE,
    filters={"kind": str},
)
register_crud(
    router,
    spec=md.VEHICLE_TYPES,
    path="/vehicle-types",
    create_model=VehicleTypeCreate,
    update_model=VehicleTypeUpdate,
    out_model=VehicleTypeOut,
    read_perm=P.MASTER_DATA_READ,
    write_perm=P.ORGANIZATIONS_WRITE,
    filters={"category": str},
)
register_crud(
    router,
    spec=md.STATUS_DEFINITIONS,
    path="/vehicle-status-definitions",
    create_model=None,
    update_model=StatusDefinitionUpdate,
    out_model=StatusDefinitionOut,
    read_perm=P.MASTER_DATA_READ,
    write_perm=P.VEHICLES_WRITE,
    id_type=int,
    allow_delete=False,
)
register_crud(
    router,
    spec=md.STATIONS,
    path="/stations",
    create_model=StationCreate,
    update_model=StationUpdate,
    out_model=StationOut,
    read_perm=P.MASTER_DATA_READ,
    write_perm=P.STATIONS_WRITE,
    filters={"organization_id": uuid.UUID},
)
register_crud(
    router,
    spec=md.VEHICLES,
    path="/vehicles",
    create_model=VehicleCreate,
    update_model=VehicleUpdate,
    out_model=VehicleOut,
    to_out=md.vehicle_out,
    read_perm=P.MASTER_DATA_READ,
    write_perm=P.VEHICLES_WRITE,
    filters={
        "station_id": uuid.UUID,
        "vehicle_type_id": uuid.UUID,
        "organization_id": uuid.UUID,
        "radio_group_id": uuid.UUID,
    },
)
register_crud(
    router,
    spec=md.RICS,
    path="/rics",
    create_model=RicCreate,
    update_model=RicUpdate,
    out_model=RicOut,
    read_perm=P.MASTER_DATA_READ,
    write_perm=P.RICS_WRITE,
)
register_crud(
    router,
    spec=md.ALARM_GROUPS,
    path="/alarm-groups",
    create_model=AlarmGroupCreate,
    update_model=AlarmGroupUpdate,
    out_model=AlarmGroupOut,
    read_perm=P.MASTER_DATA_READ,
    write_perm=P.RICS_WRITE,
)
register_crud(
    router,
    spec=md.RADIO_GROUPS,
    path="/radio-groups",
    create_model=RadioGroupCreate,
    update_model=RadioGroupUpdate,
    out_model=RadioGroupOut,
    read_perm=P.MASTER_DATA_READ,
    write_perm=P.RADIO_GROUPS_WRITE,
)
register_crud(
    router,
    spec=md.AREAS,
    path="/control-center-areas",
    create_model=AreaCreate,
    update_model=AreaUpdate,
    out_model=AreaOut,
    read_perm=P.CONTROL_CENTERS_READ,
    write_perm=P.CONTROL_CENTERS_WRITE,
)


# ------------------------------------------------------------------------- responsibility
@router.get(
    "/responsibility",
    response_model=list[ResponsibilityOut],
    tags=["Zuständigkeitsbereich"],
    summary="Zuständige Leitstelle(n) für eine Koordinate (nach Priorität)",
)
async def responsibility(
    auth: Annotated[AuthContext, Depends(require(P.CONTROL_CENTERS_READ))],
    uow: UowDep,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
) -> list[ResponsibilityOut]:
    stmt = select(ControlCenterArea).where(ControlCenterArea.geometry.is_not(None))
    visible = visible_control_centers(auth)
    if visible is not None:
        stmt = stmt.where(ControlCenterArea.control_center_id.in_(visible))
    areas = [
        a
        for a in (await uow.session.scalars(stmt)).all()
        if point_in_geometry(latitude, longitude, a.geometry)
    ]
    areas.sort(key=lambda a: (a.priority, a.name))
    return [
        ResponsibilityOut(
            area_id=a.id,
            area_name=a.name,
            priority=a.priority,
            control_center=ControlCenterRef.model_validate(a.control_center),
        )
        for a in areas
    ]


# ---------------------------------------------------------------------------------- links
LinkRead = Annotated[AuthContext, Depends(require(P.CONTROL_CENTERS_READ))]
LinkWrite = Annotated[AuthContext, Depends(require(P.CONTROL_CENTERS_READ, P.CONTROL_CENTERS_WRITE))]


@router.get(
    "/control-center-links",
    response_model=list[LinkOut],
    tags=["Leitstellen"],
    summary="Verknüpfungen (eingehend und ausgehend)",
)
async def list_links(
    auth: LinkRead, uow: UowDep, control_center_id: uuid.UUID | None = None
) -> list[LinkOut]:
    stmt = select(ControlCenterLink).order_by(ControlCenterLink.created_at)
    visible = visible_control_centers(auth)
    ids = {control_center_id} if control_center_id else visible
    if control_center_id and visible is not None and control_center_id not in visible:
        raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")
    if ids is not None:
        stmt = stmt.where(
            or_(
                ControlCenterLink.from_control_center_id.in_(ids),
                ControlCenterLink.to_control_center_id.in_(ids),
            )
        )
    return [LinkOut.model_validate(link) for link in (await uow.session.scalars(stmt)).all()]


@router.post(
    "/control-center-links",
    response_model=LinkOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Leitstellen"],
    summary="Leitstellen verknüpfen",
)
async def create_link(body: LinkCreate, auth: LinkWrite, uow: UowDep) -> LinkOut:
    visible = visible_control_centers(auth)
    if visible is not None and body.from_control_center_id not in visible:
        raise PermissionDeniedError("Kein Zugriff auf die Ausgangsleitstelle")
    s = uow.session
    source = await s.get(ControlCenter, body.from_control_center_id)
    target = await s.get(ControlCenter, body.to_control_center_id)
    if source is None or target is None:
        raise NotFoundError("Leitstelle nicht gefunden")
    if source.id == target.id:
        raise ConflictError("Eine Leitstelle kann nicht mit sich selbst verknüpft werden")
    link = ControlCenterLink(
        from_control_center_id=source.id, to_control_center_id=target.id, kind=body.kind, note=body.note
    )
    s.add(link)
    try:
        await s.flush()
    except IntegrityError as exc:
        await uow.rollback()
        raise ConflictError("Diese Verknüpfung existiert bereits") from exc
    uow = uow_for(auth, uow)
    uow.audit(
        "create",
        "control_center_link",
        link.id,
        f"Leitstelle {source.code} → {target.code} verknüpft ({body.kind})",
        control_center_id=source.id,
    )
    uow.emit(
        "master_data.changed", {"collection": "control-center-links", "id": str(link.id), "action": "created"}
    )
    await uow.commit()
    await s.refresh(link)
    return LinkOut.model_validate(link)


@router.delete(
    "/control-center-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Leitstellen"]
)
async def delete_link(link_id: uuid.UUID, auth: LinkWrite, uow: UowDep) -> None:
    s = uow.session
    link = await s.get(ControlCenterLink, link_id)
    if link is None:
        raise NotFoundError("Verknüpfung nicht gefunden")
    visible = visible_control_centers(auth)
    if visible is not None and link.from_control_center_id not in visible:
        raise PermissionDeniedError("Kein Zugriff auf die Ausgangsleitstelle")
    summary = f"Verknüpfung {link.from_control_center.code} → {link.to_control_center.code} entfernt"
    source_id = link.from_control_center_id
    await s.delete(link)
    uow = uow_for(auth, uow)
    uow.audit("delete", "control_center_link", link_id, summary, control_center_id=source_id)
    uow.emit(
        "master_data.changed", {"collection": "control-center-links", "id": str(link_id), "action": "deleted"}
    )
    await uow.commit()
