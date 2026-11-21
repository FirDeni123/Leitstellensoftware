"""Fleet (Phase 6): vehicle status, fleet view, talk requests, movements, map, simulation control."""

import uuid
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.api.crud_router import visible_control_centers
from app.api.deps import AuthContext, AuthDep, UowDep, require, uow_for
from app.core.errors import ConflictError, PermissionDeniedError, ValidationFailedError
from app.core.permissions import P
from app.models import (
    Incident,
    IncidentVehicle,
    OperationMode,
    Station,
    TalkRequest,
    Vehicle,
)
from app.schemas.fleet import (
    Breakdown,
    ClockOut,
    ClockUpdate,
    FleetVehicle,
    MapConfig,
    MovementOut,
    MoveVehicle,
    StatusHistoryOut,
    StatusSet,
    TalkAction,
    TalkRequestAction,
    TalkRequestOut,
)
from app.services.system_service import SystemService
from app.services.uow import UnitOfWork
from app.services.vehicle_status_service import VehicleStatusService
from app.simulation.clock import FACTORS, load_clock, save_clock
from app.simulation.fleet import Fleet

router = APIRouter(tags=["Fahrzeuge und Simulation"])

ReadDep = Annotated[AuthContext, Depends(require(P.INCIDENTS_READ))]
StatusDep = Annotated[AuthContext, Depends(require(P.INCIDENTS_READ, P.VEHICLES_STATUS_SET))]
RadioDep = Annotated[AuthContext, Depends(require(P.RADIO_HANDLE))]
SimDep = Annotated[AuthContext, Depends(require(P.INCIDENTS_READ, P.SIMULATION_CONTROL))]


async def _mode(uow: UnitOfWork) -> OperationMode:
    return await SystemService(uow).operation_mode()


async def _fleet(request: Request, uow: UnitOfWork) -> Fleet | None:
    """Simulated vehicles follow dispatcher actions only in simulation mode."""
    return Fleet(uow, request.app.state.routing) if await _mode(uow) == OperationMode.SIMULATION else None


def _check_cc(auth: AuthContext, cc_id: uuid.UUID) -> None:
    if not auth.can_access_control_center(cc_id):
        raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")


async def fleet_items(
    uow: UnitOfWork, cc_id: uuid.UUID, vehicle_id: uuid.UUID | None = None
) -> list[FleetVehicle]:
    s = uow.session
    stmt = select(Vehicle).where(Vehicle.control_center_id == cc_id)
    if vehicle_id is not None:
        stmt = stmt.where(Vehicle.id == vehicle_id)
    vehicles = (await s.scalars(stmt.order_by(Vehicle.call_sign))).all()
    rows = (
        await s.execute(
            select(
                IncidentVehicle.vehicle_id,
                Incident.id,
                Incident.number,
                Incident.status,
                IncidentVehicle.alarmed_at,
            )
            .join(Incident, Incident.id == IncidentVehicle.incident_id)
            .where(IncidentVehicle.released_at.is_(None), Incident.control_center_id == cc_id)
        )
    ).all()
    incidents = {
        r[0]: {"id": r[1], "number": r[2], "status": r[3], "alarmed": r[4] is not None} for r in rows
    }
    talks = {
        t.vehicle_id: t
        for t in (
            await s.scalars(
                select(TalkRequest).where(
                    TalkRequest.control_center_id == cc_id,
                    TalkRequest.status.in_(("open", "deferred", "accepted")),
                )
            )
        ).all()
    }
    fleet = Fleet(uow)
    clock, movements = await fleet.snapshot(cc_id)
    now = clock.now()
    result = []
    for v in vehicles:
        movement = movements.get(v.id)
        position = fleet.position_of(v, movement, now)
        talk = talks.get(v.id)
        result.append(
            FleetVehicle(
                id=v.id,
                call_sign=v.call_sign,
                vehicle_type=v.vehicle_type.code,
                station_id=v.station_id,
                station=v.station.name,
                organization=v.organization.name,
                radio_group_id=v.radio_group_id,
                radio_group=v.radio_group.name if v.radio_group else None,
                status_code=v.status_code,
                status_changed_at=v.status_changed_at,
                available=v.available,
                position=asdict(position) if position else None,  # type: ignore[arg-type]
                incident=incidents.get(v.id),  # type: ignore[arg-type]
                talk_request={"id": talk.id, "priority": talk.priority, "status": talk.status}
                if talk
                else None,  # type: ignore[arg-type]
                planned_departure_s=max(0.0, movement.depart_sim - now)
                if movement is not None and movement.status == "pending"
                else None,
            )
        )
    return result


# ------------------------------------------------------------------------------- fleet
@router.get("/fleet", response_model=list[FleetVehicle], summary="Fahrzeuge mit Status, Position und Einsatz")
async def list_fleet(control_center_id: uuid.UUID, auth: ReadDep, uow: UowDep) -> list[FleetVehicle]:
    _check_cc(auth, control_center_id)
    return await fleet_items(uow, control_center_id)


@router.post(
    "/vehicles/{vehicle_id}/status", response_model=FleetVehicle, summary="Fahrzeugstatus setzen (FMS)"
)
async def set_status(
    vehicle_id: uuid.UUID, body: StatusSet, request: Request, auth: StatusDep, uow: UowDep
) -> FleetVehicle:
    uow = uow_for(auth, uow)
    source = "dispatcher"
    if body.simulate:
        if not auth.has(P.SIMULATION_CONTROL):
            raise PermissionDeniedError(details={"missing_permissions": [P.SIMULATION_CONTROL.value]})
        if await _mode(uow) != OperationMode.SIMULATION:
            raise ConflictError("Statusmeldungen lassen sich nur im Simulationsbetrieb simulieren")
        source = "simulation"
    fleet = await _fleet(request, uow)
    service = VehicleStatusService(
        uow, visible_control_centers(auth), fleet=fleet, timezone=request.app.state.settings.timezone
    )
    before = (await service.vehicle(vehicle_id)).status_code
    result = await service.set_status(vehicle_id, body.status_code, source=source, note=body.note)
    vehicle = result.vehicle
    if result.talk_request is not None:
        summary = f"{vehicle.call_sign}: Sprechwunsch (Status {result.talk_request.priority})"
    else:
        summary = f"{vehicle.call_sign}: Status {before} → {vehicle.status_code}"
    if result.changed or result.talk_request is not None:
        uow.audit("status", "vehicle", vehicle.id, summary, control_center_id=vehicle.control_center_id)
    await uow.commit()
    return (await fleet_items(uow, vehicle.control_center_id, vehicle.id))[0]


@router.get("/vehicles/{vehicle_id}/status-history", response_model=list[StatusHistoryOut])
async def status_history(
    vehicle_id: uuid.UUID, auth: ReadDep, uow: UowDep, limit: int = Query(default=100, ge=1, le=1000)
) -> Any:
    return await VehicleStatusService(uow, visible_control_centers(auth)).history(vehicle_id, limit)


# ------------------------------------------------------------------------ talk requests
def _talk_out(t: TalkRequest, numbers: dict[uuid.UUID, str]) -> TalkRequestOut:
    return TalkRequestOut(
        id=t.id,
        control_center_id=t.control_center_id,
        vehicle_id=t.vehicle_id,
        call_sign=t.vehicle.call_sign,
        vehicle_type=t.vehicle.vehicle_type.code,
        station=t.vehicle.station.name,
        priority=t.priority,
        status=t.status,  # type: ignore[arg-type]
        source=t.source,
        incident_id=t.incident_id,
        incident_number=numbers.get(t.incident_id) if t.incident_id else None,
        created_at=t.created_at,
        handled_at=t.handled_at,
        handled_by_name=t.handled_by_name,
        note=t.note,
    )


async def _numbers(uow: UnitOfWork, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await uow.session.execute(select(Incident.id, Incident.number).where(Incident.id.in_(ids)))
    return dict(rows.tuples().all())


@router.get("/talk-requests", response_model=list[TalkRequestOut], summary="Sprechwünsche")
async def list_talk_requests(
    auth: RadioDep,
    uow: UowDep,
    control_center_id: uuid.UUID | None = None,
    only_open: bool = True,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[TalkRequestOut]:
    service = VehicleStatusService(uow, visible_control_centers(auth))
    items = await service.talk_requests(control_center_id, only_open, limit)
    numbers = await _numbers(uow, {t.incident_id for t in items if t.incident_id})
    return [_talk_out(t, numbers) for t in items]


@router.post("/talk-requests/{request_id}/{action}", response_model=TalkRequestOut)
async def handle_talk_request(
    request_id: uuid.UUID, action: TalkAction, body: TalkRequestAction, auth: RadioDep, uow: UowDep
) -> TalkRequestOut:
    service = VehicleStatusService(uow_for(auth, uow), visible_control_centers(auth))
    item = await service.handle_talk_request(request_id, action, body.note)
    return _talk_out(item, await _numbers(uow, {item.incident_id} if item.incident_id else set()))


# --------------------------------------------------------------------------- movements
@router.get(
    "/movements", response_model=list[MovementOut], summary="Laufende und geplante (simulierte) Fahrten"
)
async def list_movements(control_center_id: uuid.UUID, auth: ReadDep, uow: UowDep) -> list[MovementOut]:
    _check_cc(auth, control_center_id)
    clock, movements = await Fleet(uow).snapshot(control_center_id)
    now = clock.now()
    return [
        MovementOut(
            id=m.id,
            vehicle_id=m.vehicle_id,
            call_sign=m.vehicle.call_sign,
            incident_id=m.incident_id,
            kind=m.kind,  # type: ignore[arg-type]
            status=m.status,  # type: ignore[arg-type]
            route_source=m.route_source,
            emergency=m.emergency,
            geometry=m.geometry,
            dest=[m.dest_lat, m.dest_lon],
            eta_s=max(0.0, m.arrive_sim - now) if m.status == "active" else None,
            depart_in_s=max(0.0, m.depart_sim - now) if m.status == "pending" else None,
            note=m.note,
        )
        for m in movements.values()
    ]


@router.get("/map/config", response_model=MapConfig, summary="Kartenkacheln und Startausschnitt")
async def map_config(
    request: Request, auth: AuthDep, uow: UowDep, control_center_id: uuid.UUID | None = None
) -> MapConfig:
    settings = request.app.state.settings
    center = None
    if control_center_id is not None and auth.can_access_control_center(control_center_id):
        row = (
            await uow.session.execute(
                select(func.avg(Station.latitude), func.avg(Station.longitude)).where(
                    Station.control_center_id == control_center_id, Station.latitude.is_not(None)
                )
            )
        ).one()
        if row[0] is not None:
            center = [float(row[0]), float(row[1])]
    return MapConfig(
        tile_url=settings.map_tile_url,
        attribution=settings.map_tile_attribution,
        max_zoom=settings.map_max_zoom,
        center=center,
        routing=request.app.state.routing is not None,
    )


# -------------------------------------------------------------------- simulation control
async def _clock_out(uow: UnitOfWork) -> ClockOut:
    clock = await load_clock(uow)
    return ClockOut(
        sim_time=clock.now(),
        factor=clock.factor,
        paused=clock.paused,
        factors=list(FACTORS),
        simulation_mode=await _mode(uow) == OperationMode.SIMULATION,
    )


@router.get("/simulation/clock", response_model=ClockOut, summary="Simulationsuhr (Pause, Zeitraffer)")
async def get_clock(auth: ReadDep, uow: UowDep) -> ClockOut:
    return await _clock_out(uow)


@router.put("/simulation/clock", response_model=ClockOut)
async def put_clock(body: ClockUpdate, auth: SimDep, uow: UowDep) -> ClockOut:
    uow = uow_for(auth, uow)
    if await _mode(uow) != OperationMode.SIMULATION:
        raise ConflictError("Die Simulationsuhr lässt sich nur im Simulationsbetrieb steuern")
    if body.factor is not None and body.factor not in FACTORS:
        raise ValidationFailedError("Zeitfaktor nicht erlaubt", details={"allowed": list(FACTORS)})
    clock = await load_clock(uow)
    new = clock.rebased(factor=body.factor, paused=body.paused)
    await save_clock(uow, new)
    text = ("pausiert" if new.paused else "läuft") + f", Zeitfaktor {new.factor:g}×"
    uow.audit("update", "simulation", "clock", f"Simulationsuhr: {text}")
    uow.emit("simulation.clock_changed", {"factor": new.factor, "paused": new.paused})
    await uow.commit()
    return await _clock_out(uow)


async def _sim_vehicle(auth: AuthContext, uow: UnitOfWork, vehicle_id: uuid.UUID) -> Vehicle:
    if await _mode(uow) != OperationMode.SIMULATION:
        raise ConflictError("Nur im Simulationsbetrieb möglich")
    return await VehicleStatusService(uow, visible_control_centers(auth)).vehicle(vehicle_id, lock=True)


@router.post(
    "/simulation/vehicles/{vehicle_id}/position", response_model=FleetVehicle, summary="Fahrzeug verschieben"
)
async def move_vehicle(
    vehicle_id: uuid.UUID, body: MoveVehicle, request: Request, auth: SimDep, uow: UowDep
) -> FleetVehicle:
    uow = uow_for(auth, uow)
    vehicle = await _sim_vehicle(auth, uow, vehicle_id)
    await Fleet(uow, request.app.state.routing).move_to(vehicle, body.lat, body.lon)
    uow.audit(
        "move",
        "vehicle",
        vehicle.id,
        f"{vehicle.call_sign} manuell verschoben (Simulation)",
        control_center_id=vehicle.control_center_id,
    )
    uow.emit(
        "vehicle.status_changed",
        {
            "id": str(vehicle.id),
            "status_code": vehicle.status_code,
            "previous": vehicle.status_code,
            "source": "simulation",
        },
        channels=[f"cc:{vehicle.control_center_id}"],
        required_permission="incidents.read",
    )
    await uow.commit()
    return (await fleet_items(uow, vehicle.control_center_id, vehicle.id))[0]


@router.post(
    "/simulation/vehicles/{vehicle_id}/breakdown", response_model=FleetVehicle, summary="Ausfall simulieren"
)
async def breakdown(
    vehicle_id: uuid.UUID, body: Breakdown, request: Request, auth: SimDep, uow: UowDep
) -> FleetVehicle:
    uow = uow_for(auth, uow)
    vehicle = await _sim_vehicle(auth, uow, vehicle_id)
    fleet = Fleet(uow, request.app.state.routing)
    await fleet.stop(vehicle, body.note or "Ausfall simuliert")
    service = VehicleStatusService(uow, visible_control_centers(auth))
    await service.set_status(vehicle.id, 6, source="simulation", note=body.note or "Ausfall simuliert")
    uow.audit(
        "breakdown",
        "vehicle",
        vehicle.id,
        f"{vehicle.call_sign}: Ausfall simuliert",
        control_center_id=vehicle.control_center_id,
    )
    await uow.commit()
    return (await fleet_items(uow, vehicle.control_center_id, vehicle.id))[0]
