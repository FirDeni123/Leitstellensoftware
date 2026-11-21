"""Shared AAO lookups for the alarm preview (Phase 4) and the Einsatzmittelvorschlag (Phase 5)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geo import point_in_geometry
from app.models import (
    Alarm,
    AlarmRule,
    ControlCenterArea,
    Incident,
    IncidentVehicle,
    Vehicle,
    VehicleStatusDefinition,
)


async def rule_for(s: AsyncSession, incident: Incident) -> tuple[AlarmRule | None, str | None]:
    """Active AAO for the incident's keyword: an area rule whose geometry contains the incident
    location wins (lowest area priority first), otherwise the general rule."""
    if incident.keyword_id is None:
        return None, None
    rules = list(
        (
            await s.scalars(
                select(AlarmRule).where(
                    AlarmRule.control_center_id == incident.control_center_id,
                    AlarmRule.keyword_id == incident.keyword_id,
                    AlarmRule.is_active.is_(True),
                )
            )
        ).all()
    )
    general = next((r for r in rules if r.area_id is None), None)
    area_rules = [r for r in rules if r.area_id is not None]
    if area_rules and incident.latitude is not None and incident.longitude is not None:
        areas = {
            a.id: a
            for a in (
                await s.scalars(
                    select(ControlCenterArea).where(ControlCenterArea.id.in_([r.area_id for r in area_rules]))
                )
            ).all()
        }
        matching = [
            (areas[r.area_id], r)
            for r in area_rules
            if r.area_id in areas
            and areas[r.area_id].geometry
            and point_in_geometry(incident.latitude, incident.longitude, areas[r.area_id].geometry)
        ]
        if matching:
            area, rule = min(matching, key=lambda m: (m[0].priority, m[0].name))
            return rule, area.name
    return general, None


async def next_stage(
    s: AsyncSession, incident: Incident, max_stage: int, stage: int | None
) -> tuple[int | None, str, bool]:
    """(stage to use, next alarm kind, all stages already alarmed)."""
    count, last = (
        await s.execute(
            select(func.count(Alarm.id), func.max(Alarm.stage)).where(Alarm.incident_id == incident.id)
        )
    ).one()
    kind = "follow_up" if count else "initial"
    last_stage = last or 0
    exhausted = bool(count) and max_stage > 0 and last_stage >= max_stage
    if stage is None and max_stage:
        stage = min(last_stage + 1, max_stage)
    return stage, kind, exhausted


async def free_vehicles(s: AsyncSession, control_center_id: object) -> list[Vehicle]:
    """Vehicles that may be proposed: available, status counts as available, not bound to any
    incident, alarmable organisation (never police), active station."""
    codes = select(VehicleStatusDefinition.code).where(VehicleStatusDefinition.counts_as_available.is_(True))
    busy = select(IncidentVehicle.vehicle_id).where(IncidentVehicle.released_at.is_(None))
    rows = (
        await s.scalars(
            select(Vehicle).where(
                Vehicle.control_center_id == control_center_id,
                Vehicle.available.is_(True),
                Vehicle.status_code.in_(codes),
                Vehicle.id.not_in(busy),
            )
        )
    ).all()
    return [v for v in rows if v.organization.alarmable and v.station.is_active]


async def active_assignments(s: AsyncSession, incident: Incident) -> list[IncidentVehicle]:
    stmt = select(IncidentVehicle).where(
        IncidentVehicle.incident_id == incident.id, IncidentVehicle.released_at.is_(None)
    )
    return list((await s.scalars(stmt.order_by(IncidentVehicle.id))).all())
