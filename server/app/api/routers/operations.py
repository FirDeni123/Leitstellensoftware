"""Emergency calls, incidents and call simulation (Phase 3)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.crud_router import visible_control_centers
from app.api.deps import AuthContext, UowDep, require, uow_for
from app.core.errors import ConflictError
from app.core.permissions import P
from app.models import EmergencyCall, Incident
from app.schemas.master_data import StationRef
from app.schemas.operations import (
    ActiveAssignment,
    AssignVehicles,
    CallAction,
    CallCreate,
    CallLink,
    CallNoteCreate,
    CallOut,
    CallUpdate,
    IncidentCreate,
    IncidentEventOut,
    IncidentOut,
    IncidentSummary,
    IncidentUpdate,
    NoteCreate,
    ScenarioOut,
    SimulatedCallRequest,
    StatusChange,
)
from app.services.call_service import CallService
from app.services.incident_service import IncidentService
from app.services.system_service import SystemService
from app.simulation import telephony

router = APIRouter()

CallsDep = Annotated[AuthContext, Depends(require(P.CALLS_HANDLE))]
ReadDep = Annotated[AuthContext, Depends(require(P.INCIDENTS_READ))]
WriteDep = Annotated[AuthContext, Depends(require(P.INCIDENTS_READ, P.INCIDENTS_WRITE))]
SimDep = Annotated[AuthContext, Depends(require(P.SIMULATION_CONTROL, P.CALLS_HANDLE))]


def _tz(request: Request) -> str:
    return request.app.state.settings.timezone


# ------------------------------------------------------------------------------ converters
def call_out(call: EmergencyCall, names: dict[uuid.UUID, str], incident: Incident | None) -> CallOut:
    data: dict[str, Any] = {
        f: getattr(call, f) for f in CallOut.model_fields if hasattr(call, f) and f != "incident"
    }
    data["incident"] = incident
    data["handled_by_name"] = names.get(call.handled_by) if call.handled_by else None
    return CallOut.model_validate(data, from_attributes=True)


async def _call_response(service: CallService, call: EmergencyCall) -> CallOut:
    names = await service.handler_names([call])
    incident = await service.s.get(Incident, call.incident_id) if call.incident_id else None
    return call_out(call, names, incident)


def _active_vehicles(incident: Incident) -> list[str]:
    return [a.vehicle.call_sign for a in incident.assignments if a.released_at is None]


def incident_summary(incident: Incident) -> IncidentSummary:
    data = {f: getattr(incident, f) for f in IncidentSummary.model_fields if hasattr(incident, f)}
    data["vehicles"] = _active_vehicles(incident)
    return IncidentSummary.model_validate(data, from_attributes=True)


def incident_out(incident: Incident) -> IncidentOut:
    data: dict[str, Any] = {f: getattr(incident, f) for f in IncidentOut.model_fields if hasattr(incident, f)}
    data["vehicles"] = _active_vehicles(incident)
    data["assignments"] = [
        {
            "id": a.id,
            "vehicle": {
                "id": a.vehicle.id,
                "call_sign": a.vehicle.call_sign,
                "vehicle_type": a.vehicle.vehicle_type.code,
                "station": a.vehicle.station.name,
            },
            "assigned_at": a.assigned_at,
            "alarmed_at": a.alarmed_at,
            "s3_at": a.s3_at,
            "s4_at": a.s4_at,
            "released_at": a.released_at,
            "released_reason": a.released_reason,
        }
        for a in incident.assignments
    ]
    stations = {
        a.vehicle.station.id: a.vehicle.station for a in incident.assignments if a.released_at is None
    }
    data["stations"] = [StationRef.model_validate(s) for s in sorted(stations.values(), key=lambda s: s.name)]
    return IncidentOut.model_validate(data, from_attributes=True)


# ----------------------------------------------------------------------------------- calls
@router.get(
    "/calls", response_model=list[CallOut], tags=["Notrufe"], summary="Offene Notrufe (Warteschlange)"
)
async def list_calls(
    auth: CallsDep,
    uow: UowDep,
    control_center_id: uuid.UUID | None = None,
    include_ended: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
) -> Any:
    service = CallService(uow, visible_control_centers(auth))
    calls = await service.list(control_center_id, include_ended, limit)
    names = await service.handler_names(calls)
    incident_ids = {c.incident_id for c in calls if c.incident_id}
    incidents = {i.id: i for i in [await uow.session.get(Incident, iid) for iid in incident_ids] if i}
    return [call_out(c, names, incidents.get(c.incident_id) if c.incident_id else None) for c in calls]


@router.get("/calls/{call_id}", response_model=CallOut, tags=["Notrufe"])
async def get_call(call_id: uuid.UUID, auth: CallsDep, uow: UowDep) -> CallOut:
    service = CallService(uow, visible_control_centers(auth))
    return await _call_response(service, await service.get(call_id))


@router.post(
    "/calls",
    response_model=CallOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Notrufe"],
    summary="Anruf manuell erfassen",
)
async def create_call(body: CallCreate, auth: CallsDep, uow: UowDep) -> CallOut:
    service = CallService(uow_for(auth, uow), visible_control_centers(auth))
    data = body.model_dump(exclude={"control_center_id", "priority"})
    call = await service.receive(body.control_center_id, source="manual", priority=body.priority, **data)
    call = await service.answer(call.id, call.version)  # the person capturing it is on the line
    return await _call_response(service, call)


@router.patch("/calls/{call_id}", response_model=CallOut, tags=["Notrufe"])
async def update_call(call_id: uuid.UUID, body: CallUpdate, auth: CallsDep, uow: UowDep) -> CallOut:
    service = CallService(uow_for(auth, uow), visible_control_centers(auth))
    data = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    return await _call_response(service, await service.update(call_id, data, body.expected_version))


async def _call_action(
    action: str, call_id: uuid.UUID, body: CallAction, auth: AuthContext, uow: Any
) -> CallOut:
    service = CallService(uow_for(auth, uow), visible_control_centers(auth))
    call = await getattr(service, action)(call_id, body.expected_version)
    return await _call_response(service, call)


@router.post("/calls/{call_id}/answer", response_model=CallOut, tags=["Notrufe"], summary="Annehmen")
async def answer_call(call_id: uuid.UUID, body: CallAction, auth: CallsDep, uow: UowDep) -> CallOut:
    return await _call_action("answer", call_id, body, auth, uow)


@router.post("/calls/{call_id}/hold", response_model=CallOut, tags=["Notrufe"], summary="Halten")
async def hold_call(call_id: uuid.UUID, body: CallAction, auth: CallsDep, uow: UowDep) -> CallOut:
    return await _call_action("hold", call_id, body, auth, uow)


@router.post(
    "/calls/{call_id}/resume", response_model=CallOut, tags=["Notrufe"], summary="Fortsetzen/Übernehmen"
)
async def resume_call(call_id: uuid.UUID, body: CallAction, auth: CallsDep, uow: UowDep) -> CallOut:
    return await _call_action("resume", call_id, body, auth, uow)


@router.post("/calls/{call_id}/end", response_model=CallOut, tags=["Notrufe"], summary="Beenden")
async def end_call(call_id: uuid.UUID, body: CallAction, auth: CallsDep, uow: UowDep) -> CallOut:
    return await _call_action("end", call_id, body, auth, uow)


@router.post(
    "/calls/{call_id}/notes",
    response_model=CallOut,
    tags=["Notrufe"],
    summary="Gesprächsnotiz oder Rückfrage dokumentieren",
)
async def add_call_note(call_id: uuid.UUID, body: CallNoteCreate, auth: CallsDep, uow: UowDep) -> CallOut:
    service = CallService(uow_for(auth, uow), visible_control_centers(auth))
    return await _call_response(service, await service.add_note(call_id, body.kind, body.question, body.text))


@router.post(
    "/calls/{call_id}/link",
    response_model=CallOut,
    tags=["Notrufe"],
    summary="Notruf einem bestehenden Einsatz zuordnen",
)
async def link_call(
    call_id: uuid.UUID,
    body: CallLink,
    request: Request,
    auth: Annotated[AuthContext, Depends(require(P.CALLS_HANDLE, P.INCIDENTS_WRITE))],
    uow: UowDep,
) -> CallOut:
    service = CallService(uow_for(auth, uow), visible_control_centers(auth))
    call = await service.link(call_id, body.incident_id, _tz(request))
    return await _call_response(service, call)


# ------------------------------------------------------------------------------- incidents
@router.get("/incidents", response_model=list[IncidentSummary], tags=["Einsätze"])
async def list_incidents(
    auth: ReadDep,
    uow: UowDep,
    request: Request,
    control_center_id: uuid.UUID | None = None,
    scope: str = Query(default="open", pattern="^(open|closed|all)$"),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=300, ge=1, le=1000),
) -> Any:
    service = IncidentService(uow, visible_control_centers(auth), _tz(request))
    return [incident_summary(i) for i in await service.list(control_center_id, scope, q, limit)]


@router.get(
    "/incidents/active-assignments",
    response_model=list[ActiveAssignment],
    tags=["Einsätze"],
    summary="Fahrzeuge, die aktuell einem Einsatz zugeordnet sind",
)
async def active_assignments(
    auth: ReadDep, uow: UowDep, request: Request, control_center_id: uuid.UUID
) -> Any:
    service = IncidentService(uow, visible_control_centers(auth), _tz(request))
    return [
        ActiveAssignment(
            vehicle_id=a.vehicle_id, incident_id=i.id, incident_number=i.number, assigned_at=a.assigned_at
        )
        for a, i in await service.active_assignments(control_center_id)
    ]


@router.get("/incidents/{incident_id}", response_model=IncidentOut, tags=["Einsätze"])
async def get_incident(incident_id: uuid.UUID, auth: ReadDep, uow: UowDep, request: Request) -> IncidentOut:
    return incident_out(
        await IncidentService(uow, visible_control_centers(auth), _tz(request)).get(incident_id)
    )


@router.post(
    "/incidents",
    response_model=IncidentOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Einsätze"],
    summary="Einsatz anlegen (optional aus einem Notruf)",
)
async def create_incident(body: IncidentCreate, auth: WriteDep, uow: UowDep, request: Request) -> IncidentOut:
    service = IncidentService(uow_for(auth, uow), visible_control_centers(auth), _tz(request))
    return incident_out(await service.create(body.model_dump()))


@router.patch("/incidents/{incident_id}", response_model=IncidentOut, tags=["Einsätze"])
async def update_incident(
    incident_id: uuid.UUID, body: IncidentUpdate, auth: WriteDep, uow: UowDep, request: Request
) -> IncidentOut:
    service = IncidentService(uow_for(auth, uow), visible_control_centers(auth), _tz(request))
    data = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    return incident_out(await service.update(incident_id, data, body.expected_version))


@router.post(
    "/incidents/{incident_id}/status",
    response_model=IncidentOut,
    tags=["Einsätze"],
    summary="Einsatzstatus setzen (Abschließen erfordert incidents.close)",
)
async def change_status(
    incident_id: uuid.UUID, body: StatusChange, auth: WriteDep, uow: UowDep, request: Request
) -> IncidentOut:
    service = IncidentService(uow_for(auth, uow), visible_control_centers(auth), _tz(request))
    incident = await service.change_status(
        incident_id, body.status, body.expected_version, body.note, auth.has(P.INCIDENTS_CLOSE)
    )
    return incident_out(incident)


@router.get(
    "/incidents/{incident_id}/events",
    response_model=list[IncidentEventOut],
    tags=["Einsätze"],
    summary="Einsatzverlauf (unveränderbar)",
)
async def incident_events(incident_id: uuid.UUID, auth: ReadDep, uow: UowDep, request: Request) -> Any:
    service = IncidentService(uow, visible_control_centers(auth), _tz(request))
    return [IncidentEventOut.model_validate(e) for e in await service.events(incident_id)]


@router.post(
    "/incidents/{incident_id}/notes",
    response_model=IncidentEventOut,
    status_code=status.HTTP_201_CREATED,
    tags=["Einsätze"],
    summary="Dokumentation ergänzen",
)
async def add_incident_note(
    incident_id: uuid.UUID, body: NoteCreate, auth: WriteDep, uow: UowDep, request: Request
) -> IncidentEventOut:
    service = IncidentService(uow_for(auth, uow), visible_control_centers(auth), _tz(request))
    return IncidentEventOut.model_validate(await service.add_note(incident_id, body.text))


@router.post(
    "/incidents/{incident_id}/vehicles",
    response_model=IncidentOut,
    tags=["Einsätze"],
    summary="Fahrzeuge zuordnen (optional aus anderen Einsätzen umsetzen)",
)
async def assign_vehicles(
    incident_id: uuid.UUID, body: AssignVehicles, auth: WriteDep, uow: UowDep, request: Request
) -> IncidentOut:
    service = IncidentService(uow_for(auth, uow), visible_control_centers(auth), _tz(request))
    return incident_out(await service.assign(incident_id, body.vehicle_ids, body.reassign))


@router.delete(
    "/incidents/{incident_id}/vehicles/{vehicle_id}",
    response_model=IncidentOut,
    tags=["Einsätze"],
    summary="Fahrzeug freigeben (abziehen)",
)
async def release_vehicle(
    incident_id: uuid.UUID, vehicle_id: uuid.UUID, auth: WriteDep, uow: UowDep, request: Request
) -> IncidentOut:
    service = IncidentService(uow_for(auth, uow), visible_control_centers(auth), _tz(request))
    return incident_out(await service.release(incident_id, vehicle_id))


# ------------------------------------------------------------------------------ simulation
@router.get("/simulation/call-scenarios", response_model=list[ScenarioOut], tags=["Simulation"])
async def call_scenarios(auth: SimDep) -> list[ScenarioOut]:
    return [
        ScenarioOut(key=s.key, title=s.title, expected_keyword=s.expected_keyword)
        for s in telephony.SCENARIOS
    ]


@router.post(
    "/simulation/calls",
    response_model=list[CallOut],
    status_code=status.HTTP_201_CREATED,
    tags=["Simulation"],
    summary="Simulierte Notrufe erzeugen (nur im Simulationsbetrieb)",
)
async def simulate_calls(body: SimulatedCallRequest, auth: SimDep, uow: UowDep) -> Any:
    if await SystemService(uow).operation_mode() != "simulation":
        raise ConflictError("Im Echtbetrieb sind simulierte Anrufe gesperrt")
    if body.scenario and body.scenario not in telephony.SCENARIO_BY_KEY:
        raise ConflictError("Unbekanntes Szenario")
    service = CallService(uow_for(auth, uow), visible_control_centers(auth))
    results = []
    for _ in range(body.count):
        sim = telephony.generate(body.scenario)
        transcript = "\n".join(
            [
                f"Anrufer: {sim.scenario.transcript}",
                f"Auf Nachfrage „Wo genau?“: {sim.true_address}"
                + (f" ({sim.scenario.location_hint})" if sim.scenario.location_hint else ""),
                f"Auf Nachfrage „Wie heißen Sie?“: {sim.caller_name}",
                f"Auf Nachfrage „Rückrufnummer?“: {sim.caller_phone}",
            ]
        )
        call = await service.receive(
            body.control_center_id,
            source="sim",
            priority=2,
            line="112",
            caller_phone=sim.caller_phone,
            caller_location=sim.caller_location,
            caller_latitude=sim.caller_latitude,
            caller_longitude=sim.caller_longitude,
            sim_transcript=transcript,
        )
        results.append(await _call_response(service, call))
    return results
