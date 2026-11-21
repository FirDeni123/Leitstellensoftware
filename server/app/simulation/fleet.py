"""Simulated fleet: drives to incidents and back, positions, departures and arrivals.

Only active in simulation mode. A drive is planned as a *pending* movement (destination +
departure time in simulation seconds); at departure the route is computed from the position
at that moment (OSRM or marked straight line), the crew reports status 3 (to an incident) or
1 (return), and on arrival status 4 or 2. Positions are computed from the route and the
simulation clock – they are identical for every client and survive a restart.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.models import Incident, Station, Vehicle, VehicleMovement
from app.proposal.travel import Point, RoutingProvider
from app.services.uow import UnitOfWork
from app.simulation.clock import ClockState, load_clock
from app.simulation.route import plan_route, position_at

TURNOUT_ON_RADIO_S = 15.0  # status 1: crew is already on the road


@dataclass(slots=True)
class Position:
    lat: float
    lon: float
    source: str  # station | sim | gps | unknown
    moving: bool = False
    heading: float | None = None
    eta_s: float | None = None
    kind: str | None = None


def station_point(station: Station) -> Point | None:
    if station.latitude is None or station.longitude is None:
        return None
    return station.latitude, station.longitude


def resting_point(vehicle: Vehicle) -> Point | None:
    """Stored position: at the station, or where the vehicle stopped last."""
    if (
        vehicle.position_source != "station"
        and vehicle.latitude is not None
        and vehicle.longitude is not None
    ):
        return vehicle.latitude, vehicle.longitude
    return station_point(vehicle.station)


def at_station(vehicle: Vehicle) -> bool:
    return vehicle.position_source == "station"


class Fleet:
    def __init__(self, uow: UnitOfWork, routing: RoutingProvider | None = None) -> None:
        self.uow = uow
        self.s = uow.session
        self.routing = routing
        self._clock: ClockState | None = None
        self._settings: dict[uuid.UUID, Any] = {}
        self.notes: list[str] = []

    async def clock(self) -> ClockState:
        if self._clock is None:
            self._clock = await load_clock(self.uow)
        return self._clock

    async def now(self) -> float:
        return (await self.clock()).now()

    async def open_movement(self, vehicle_id: uuid.UUID) -> VehicleMovement | None:
        return await self.s.scalar(
            select(VehicleMovement)
            .where(
                VehicleMovement.vehicle_id == vehicle_id, VehicleMovement.status.in_(("pending", "active"))
            )
            .with_for_update()
        )

    def _emit(self, movement: VehicleMovement, action: str) -> None:
        self.uow.emit(
            "movement.changed",
            {**movement.as_dict(), "action": action},
            channels=[f"cc:{movement.control_center_id}"],
            required_permission="incidents.read",
        )

    def position_of(self, vehicle: Vehicle, movement: VehicleMovement | None, now: float) -> Position | None:
        if movement is not None and movement.status == "active" and movement.geometry:
            lat, lon, heading = position_at(movement.geometry, movement.profile, now - movement.depart_sim)
            return Position(
                lat, lon, "sim", True, heading, max(0.0, movement.arrive_sim - now), movement.kind
            )
        point = resting_point(vehicle)
        if point is None:
            return None
        source = "station" if at_station(vehicle) else (vehicle.position_source or "sim")
        eta = None
        if movement is not None and movement.status == "pending":
            eta = None  # not yet departed
        return Position(point[0], point[1], source, False, None, eta, movement.kind if movement else None)

    async def _stop_here(self, vehicle: Vehicle, movement: VehicleMovement, now: float, note: str) -> None:
        position = self.position_of(vehicle, movement, now)
        if movement.status == "active" and position is not None:
            vehicle.latitude, vehicle.longitude = position.lat, position.lon
            vehicle.position_source = "sim"
            vehicle.position_updated_at = datetime.now(UTC)
        movement.status = "cancelled"
        movement.finished_at = datetime.now(UTC)
        movement.note = note
        self._emit(movement, "cancelled")
        await self.s.flush()  # the partial unique index allows the next movement only after this

    # ----------------------------------------------------------------------- planning
    async def schedule_trip(
        self, vehicle: Vehicle, incident: Incident, depart_in_s: float
    ) -> VehicleMovement | None:
        """Plan a drive to the incident (after the turnout time)."""
        if incident.latitude is None or incident.longitude is None:
            self.notes.append(f"{vehicle.call_sign}: Einsatzort ohne Koordinaten – keine simulierte Anfahrt")
            return None
        if vehicle.position_source == "gps":
            return None  # real positions are never simulated
        now = await self.now()
        current = await self.open_movement(vehicle.id)
        if current is not None:
            if current.kind == "to_incident" and current.incident_id == incident.id:
                return current
            await self._stop_here(vehicle, current, now, "durch neue Fahrt ersetzt")
        movement = VehicleMovement(
            id=uuid.uuid4(),
            control_center_id=vehicle.control_center_id,
            vehicle_id=vehicle.id,
            incident_id=incident.id,
            kind="to_incident",
            status="pending",
            emergency=True,
            dest_lat=incident.latitude,
            dest_lon=incident.longitude,
            depart_sim=now + max(0.0, depart_in_s),
        )
        self.s.add(movement)
        await self.s.flush()
        self._emit(movement, "planned")
        return movement

    async def depart_now(self, vehicle: Vehicle, incident: Incident) -> None:
        now = await self.now()
        movement = await self.open_movement(vehicle.id)
        if movement is not None and movement.status == "pending":
            movement.depart_sim = now
            return
        if movement is None:
            await self.schedule_trip(vehicle, incident, 0.0)

    async def arrive_now(self, vehicle: Vehicle) -> None:
        movement = await self.open_movement(vehicle.id)
        if movement is not None:
            self._finish(vehicle, movement)

    async def to_station_now(self, vehicle: Vehicle) -> None:
        now = await self.now()
        movement = await self.open_movement(vehicle.id)
        if movement is not None:
            await self._stop_here(vehicle, movement, now, "Status 2 gesetzt – Fahrzeug auf der Wache")
        vehicle.position_source = "station"
        vehicle.latitude = vehicle.longitude = None
        vehicle.position_updated_at = datetime.now(UTC)

    async def plan_return(self, vehicle: Vehicle) -> VehicleMovement | None:
        """Drive back to the station without special rights (status 1 → 2 on arrival)."""
        now = await self.now()
        current = await self.open_movement(vehicle.id)
        if current is not None:
            if current.kind == "to_station":
                return current
            await self._stop_here(vehicle, current, now, "Rückfahrt zur Wache")
        if at_station(vehicle) or vehicle.position_source == "gps":
            return None
        target = station_point(vehicle.station)
        if target is None:
            return None
        movement = VehicleMovement(
            id=uuid.uuid4(),
            control_center_id=vehicle.control_center_id,
            vehicle_id=vehicle.id,
            incident_id=None,
            kind="to_station",
            status="pending",
            emergency=False,
            dest_lat=target[0],
            dest_lon=target[1],
            depart_sim=now,
        )
        self.s.add(movement)
        await self.s.flush()
        self._emit(movement, "planned")
        return movement

    async def stop(self, vehicle: Vehicle, note: str) -> None:
        movement = await self.open_movement(vehicle.id)
        if movement is not None:
            await self._stop_here(vehicle, movement, await self.now(), note)

    async def move_to(self, vehicle: Vehicle, lat: float, lon: float) -> None:
        await self.stop(vehicle, "manuell verschoben")
        vehicle.latitude, vehicle.longitude = lat, lon
        vehicle.position_source = "sim"
        vehicle.position_updated_at = datetime.now(UTC)

    async def stop_all(self, note: str) -> int:
        rows = (
            await self.s.scalars(
                select(VehicleMovement).where(VehicleMovement.status.in_(("pending", "active")))
            )
        ).all()
        now = await self.now()
        for movement in rows:
            await self._stop_here(movement.vehicle, movement, now, note)
        return len(rows)

    def _finish(self, vehicle: Vehicle, movement: VehicleMovement) -> None:
        vehicle.position_updated_at = datetime.now(UTC)
        if movement.kind == "to_station":
            vehicle.position_source = "station"
            vehicle.latitude = vehicle.longitude = None
        else:
            vehicle.latitude, vehicle.longitude = movement.dest_lat, movement.dest_lon
            vehicle.position_source = "sim"
        movement.status = "arrived"
        movement.finished_at = datetime.now(UTC)
        self._emit(movement, "arrived")

    # --------------------------------------------------------------------------- tick
    async def _depart(self, movement: VehicleMovement, now: float) -> bool:
        from app.services.proposal_service import ProposalService, speed_of

        vehicle = movement.vehicle
        origin = resting_point(vehicle)
        if origin is None:
            await self._stop_here(vehicle, movement, now, "Startposition unbekannt (Wache ohne Koordinaten)")
            return False
        settings = self._settings.get(vehicle.control_center_id)
        if settings is None:
            settings = await ProposalService(self.uow, None).settings_for(vehicle.control_center_id)
            self._settings[vehicle.control_center_id] = settings
        factor = settings.emergency_speed_factor if movement.emergency else 1.0
        route, warning = await plan_route(
            origin,
            (movement.dest_lat, movement.dest_lon),
            speed_kmh=speed_of(vehicle),
            detour=settings.detour_factor,
            factor=factor,
            routing=self.routing if settings.use_routing else None,
        )
        movement.geometry, movement.profile = route.geometry, route.profile
        movement.duration_s, movement.distance_m, movement.route_source = (
            route.duration_s,
            route.distance_m,
            route.source,
        )
        movement.depart_sim = now
        movement.status = "active"
        if warning:
            movement.note = warning
        self._emit(movement, "departed")
        return True

    async def tick(self) -> dict[uuid.UUID, list[dict[str, Any]]]:
        """Advance the simulation to the current simulation time. Returns positions of moving
        vehicles per control centre (for the ``vehicle.positions`` event)."""
        from app.services.vehicle_status_service import VehicleStatusService

        clock = await self.clock()
        now = clock.now()
        status = VehicleStatusService(self.uow, None, fleet=self)
        movements = (
            await self.s.scalars(
                select(VehicleMovement)
                .where(VehicleMovement.status.in_(("pending", "active")))
                .order_by(VehicleMovement.depart_sim)
            )
        ).all()
        positions: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
        for movement in movements:
            vehicle = movement.vehicle
            bound = movement.kind != "to_incident" or await self._still_assigned(movement)
            if movement.status == "pending":
                if now < movement.depart_sim:
                    continue
                if not bound:
                    await self._stop_here(vehicle, movement, now, "nicht mehr dem Einsatz zugeordnet")
                    continue
                if not await self._depart(movement, now):
                    continue
                if movement.kind == "to_incident" and vehicle.status_code != 3:
                    await status.set_status(vehicle.id, 3, source="simulation")
                elif movement.kind == "to_station" and vehicle.status_code != 1:
                    await status.set_status(vehicle.id, 1, source="simulation")
            if movement.status == "active" and now >= movement.arrive_sim:
                self._finish(vehicle, movement)
                if bound:  # a vehicle moved to another incident meanwhile just stops there
                    code = 4 if movement.kind == "to_incident" else 2
                    await status.set_status(vehicle.id, code, source="simulation")
                continue
            position = self.position_of(vehicle, movement, now)
            if position is not None:
                positions[movement.control_center_id].append(
                    {
                        "id": str(vehicle.id),
                        "lat": round(position.lat, 6),
                        "lon": round(position.lon, 6),
                        "heading": round(position.heading or 0.0, 1),
                        "eta_s": round(position.eta_s or 0.0, 1),
                        "kind": movement.kind,
                        "incident_id": str(movement.incident_id) if movement.incident_id else None,
                        "status_code": vehicle.status_code,
                    }
                )
        await self.s.flush()
        return dict(positions)

    async def _still_assigned(self, movement: VehicleMovement) -> bool:
        from app.models import IncidentVehicle

        incident_id = await self.s.scalar(
            select(IncidentVehicle.incident_id).where(
                IncidentVehicle.vehicle_id == movement.vehicle_id, IncidentVehicle.released_at.is_(None)
            )
        )
        return incident_id is not None and incident_id == movement.incident_id

    async def snapshot(
        self, control_center_id: uuid.UUID
    ) -> tuple[ClockState, dict[uuid.UUID, VehicleMovement]]:
        clock = await self.clock()
        rows = (
            await self.s.scalars(
                select(VehicleMovement).where(
                    VehicleMovement.control_center_id == control_center_id,
                    VehicleMovement.status.in_(("pending", "active")),
                )
            )
        ).all()
        return clock, {m.vehicle_id: m for m in rows}
