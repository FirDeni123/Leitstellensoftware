"""Plugins and configured interfaces (Schnittstellen)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.crud_router import visible_control_centers
from app.api.deps import AuthContext, UowDep, require, uow_for
from app.core.crypto import SecretBox
from app.core.permissions import P
from app.models import Interface, OperationMode, Station
from app.plugins.registry import all_plugins, get_plugin
from app.schemas.alarming import (
    InterfaceCreate,
    InterfaceEventOut,
    InterfaceOut,
    InterfaceTestResult,
    InterfaceToggle,
    InterfaceUpdate,
    PluginOut,
)
from app.services.interface_service import InterfaceService, is_effective
from app.services.system_service import SystemService

router = APIRouter(tags=["Schnittstellen"])

ReadDep = Annotated[AuthContext, Depends(require(P.INTERFACES_READ))]
WriteDep = Annotated[AuthContext, Depends(require(P.INTERFACES_READ, P.INTERFACES_WRITE))]


def _service(request: Request, auth: AuthContext, uow: UowDep) -> InterfaceService:
    box: SecretBox = request.app.state.secret_box
    return InterfaceService(
        uow_for(auth, uow),
        visible_control_centers(auth),
        box,
        is_admin=auth.is_admin,
        can_activate_real=auth.has(P.INTERFACES_ACTIVATE_REAL),
    )


async def interface_out(service: InterfaceService, interface: Interface, mode: OperationMode) -> InterfaceOut:
    plugin = get_plugin(interface.plugin_key)
    station = await service.s.get(Station, interface.station_id) if interface.station_id else None
    data: dict[str, Any] = {
        f: getattr(interface, f) for f in InterfaceOut.model_fields if hasattr(interface, f)
    }
    data |= {
        "plugin_name": plugin.meta.name,
        "is_real": plugin.meta.is_real,
        "station_name": station.name if station else None,
        "effective": is_effective(interface, mode),
        "has_secret": interface.secret_encrypted is not None,
    }
    return InterfaceOut.model_validate(data)


async def _mode(uow: UowDep) -> OperationMode:
    return await SystemService(uow).operation_mode()


@router.get("/plugins", response_model=list[PluginOut], summary="Installierte Schnittstellen-Plugins")
async def list_plugins(auth: ReadDep) -> list[PluginOut]:
    return [
        PluginOut(
            key=p.meta.key,
            name=p.meta.name,
            description=p.meta.description,
            is_real=p.meta.is_real,
            scopes=list(p.meta.scopes),  # type: ignore[arg-type]
            config_schema=p.meta.config_schema,
            secret_label=p.meta.secret_label,
            secret_required=p.meta.secret_required,
            capabilities=list(p.meta.capabilities),
        )
        for p in all_plugins()
    ]


@router.get("/interfaces", response_model=list[InterfaceOut])
async def list_interfaces(
    request: Request, auth: ReadDep, uow: UowDep, control_center_id: uuid.UUID | None = None
) -> list[InterfaceOut]:
    service = _service(request, auth, uow)
    mode = await _mode(uow)
    return [await interface_out(service, i, mode) for i in await service.list(control_center_id)]


@router.get("/interfaces/{interface_id}", response_model=InterfaceOut)
async def get_interface(
    interface_id: uuid.UUID, request: Request, auth: ReadDep, uow: UowDep
) -> InterfaceOut:
    service = _service(request, auth, uow)
    return await interface_out(service, await service.get(interface_id), await _mode(uow))


@router.post(
    "/interfaces",
    response_model=InterfaceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Schnittstelle anlegen (immer deaktiviert)",
)
async def create_interface(
    body: InterfaceCreate, request: Request, auth: WriteDep, uow: UowDep
) -> InterfaceOut:
    service = _service(request, auth, uow)
    interface = await service.create(body.model_dump())
    return await interface_out(service, interface, await _mode(uow))


@router.patch("/interfaces/{interface_id}", response_model=InterfaceOut)
async def update_interface(
    interface_id: uuid.UUID, body: InterfaceUpdate, request: Request, auth: WriteDep, uow: UowDep
) -> InterfaceOut:
    service = _service(request, auth, uow)
    data = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    interface = await service.update(interface_id, data, body.expected_version)
    return await interface_out(service, interface, await _mode(uow))


@router.delete("/interfaces/{interface_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interface(
    interface_id: uuid.UUID,
    request: Request,
    auth: WriteDep,
    uow: UowDep,
    expected_version: int = Query(ge=1),
) -> None:
    await _service(request, auth, uow).delete(interface_id, expected_version)


@router.post(
    "/interfaces/{interface_id}/enabled",
    response_model=InterfaceOut,
    summary="Aktivieren/Deaktivieren (reale Schnittstellen nur im Echtbetrieb mit interfaces.activate_real)",
)
async def toggle_interface(
    interface_id: uuid.UUID, body: InterfaceToggle, request: Request, auth: WriteDep, uow: UowDep
) -> InterfaceOut:
    service = _service(request, auth, uow)
    interface = await service.set_enabled(interface_id, body.enabled, body.expected_version, body.reason)
    return await interface_out(service, interface, await _mode(uow))


@router.post(
    "/interfaces/{interface_id}/test",
    response_model=InterfaceTestResult,
    summary="Verbindungstest (reale Schnittstellen nur im Echtbetrieb)",
)
async def test_interface(
    interface_id: uuid.UUID, request: Request, auth: WriteDep, uow: UowDep
) -> InterfaceTestResult:
    service = _service(request, auth, uow)
    result = await service.test(interface_id)
    interface = await service.get(interface_id)
    await service.s.refresh(interface)
    return InterfaceTestResult(
        ok=result.ok,
        detail=result.detail,
        interface=await interface_out(service, interface, await _mode(uow)),
    )


@router.get("/interfaces/{interface_id}/events", response_model=list[InterfaceEventOut])
async def interface_events(
    interface_id: uuid.UUID,
    request: Request,
    auth: ReadDep,
    uow: UowDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    return await _service(request, auth, uow).events(interface_id, limit)
