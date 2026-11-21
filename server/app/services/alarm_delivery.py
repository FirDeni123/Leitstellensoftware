"""Delivery of a committed alarm to its interfaces (runs after the HTTP response).

The alarm and its targets are already stored. Here every pending interface target is handed to
``interface_service.deliver`` (which enforces the simulation/real separation, timeouts and
retries). No database transaction is held open while plugins talk to external systems.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.crypto import SecretBox, SecretBoxError
from app.core.errors import ValidationFailedError
from app.models import Alarm, ControlCenter, Incident, IncidentEvent, Interface, InterfaceEvent, Vehicle
from app.plugins.base import AlarmMessage, InterfacePlugin
from app.plugins.registry import get_plugin
from app.realtime.bus import EventBus
from app.services.alarm_service import DELIVERY_LABEL, alarm_status
from app.services.interface_service import REDIRECT_TEXT, Delivery, deliver, interface_channel, record_status
from app.services.uow import UnitOfWork

logger = logging.getLogger(__name__)
INTERRUPTED_AFTER = timedelta(minutes=5)


def build_message(
    alarm: Alarm,
    incident: Incident,
    cc: ControlCenter,
    vehicles: dict[str, Vehicle],
    interface: Interface,
) -> AlarmMessage:
    """Data minimisation: a station interface only receives its own station's units."""
    station_only = interface.scope == "station"
    vehicle_targets = [t for t in alarm.targets if t.target_type == "vehicle"]
    if station_only:
        vehicle_targets = [
            t
            for t in vehicle_targets
            if t.target_id in vehicles and vehicles[t.target_id].station_id == interface.station_id
        ]
    station_targets = [t for t in alarm.targets if t.target_type == "station"]
    if station_only:
        station_targets = [t for t in station_targets if t.target_id == str(interface.station_id)]
    return AlarmMessage(
        alarm_id=str(alarm.id),
        control_center=cc.name,
        incident_number=incident.number,
        keyword=incident.keyword.code if incident.keyword else None,
        keyword_name=incident.keyword.name if incident.keyword else None,
        incident_type=incident.incident_type,
        priority=incident.priority,
        address=incident.address,
        location_note=incident.location_note,
        latitude=incident.latitude,
        longitude=incident.longitude,
        description=incident.description,
        stage=alarm.stage,
        mode=alarm.mode,
        created_at=alarm.created_at,
        vehicles=[vehicles[t.target_id].call_sign for t in vehicle_targets if t.target_id in vehicles],
        stations=[t.label for t in station_targets],
        rics=[] if station_only else [t.label for t in alarm.targets if t.target_type == "ric"],
    )


async def deliver_alarm(sessionmaker: Any, bus: EventBus, box: SecretBox, alarm_id: uuid.UUID) -> None:
    try:
        await _deliver(sessionmaker, bus, box, alarm_id)
    except Exception:  # never crash the server; the alarm stays visible as "pending"
        logger.exception("Zustellung der Alarmierung %s fehlgeschlagen", alarm_id)


async def _deliver(sessionmaker: Any, bus: EventBus, box: SecretBox, alarm_id: uuid.UUID) -> None:
    from app.services.system_service import SystemService

    jobs: list[tuple[int, uuid.UUID, InterfacePlugin, dict[str, Any], str | None, AlarmMessage, bool]] = []
    early: dict[int, Delivery] = {}
    async with sessionmaker() as s:
        uow = UnitOfWork(s, bus)
        mode = await SystemService(uow).operation_mode()  # checked again at delivery time
        alarm = await s.get(Alarm, alarm_id)
        if alarm is None or alarm.status != "pending":
            return
        incident = await s.get(Incident, alarm.incident_id)
        cc = await s.get(ControlCenter, alarm.control_center_id)
        assert incident is not None and cc is not None
        vehicle_ids = [uuid.UUID(t.target_id) for t in alarm.targets if t.target_type == "vehicle"]
        vehicles = (
            {
                str(v.id): v
                for v in (await s.scalars(select(Vehicle).where(Vehicle.id.in_(vehicle_ids)))).all()
            }
            if vehicle_ids
            else {}
        )
        for target in alarm.targets:
            if target.target_type != "interface" or target.delivery_status != "pending":
                continue
            interface = await s.get(Interface, uuid.UUID(target.target_id))
            if interface is None:
                early[target.id] = Delivery("failed", "Schnittstelle existiert nicht mehr")
                continue
            try:
                plugin = get_plugin(interface.plugin_key)
                secret = box.decrypt(interface.secret_encrypted) if interface.secret_encrypted else None
            except ValidationFailedError:
                early[target.id] = Delivery(
                    "failed", f"Plugin „{interface.plugin_key}“ ist nicht installiert"
                )
                continue
            except SecretBoxError:
                early[target.id] = Delivery("failed", "Schlüssel kann nicht entschlüsselt werden")
                continue
            message = build_message(alarm, incident, cc, vehicles, interface)
            jobs.append(
                (target.id, interface.id, plugin, dict(interface.config), secret, message, interface.enabled)
            )
        await s.commit()

    results = await asyncio.gather(
        *(
            deliver(plugin, config, secret, message, enabled=enabled, mode=mode)
            for _, _, plugin, config, secret, message, enabled in jobs
        )
    )
    outcome: dict[int, tuple[uuid.UUID | None, Delivery]] = {tid: (None, d) for tid, d in early.items()}
    for (target_id, interface_id, *_), result in zip(jobs, results, strict=True):
        outcome[target_id] = (interface_id, result)

    async with sessionmaker() as s:
        uow = UnitOfWork(s, bus)
        alarm = await s.get(Alarm, alarm_id)
        incident = await s.get(Incident, alarm.incident_id) if alarm else None
        if alarm is None or incident is None:
            return
        now = datetime.now(UTC)
        by_id = {t.id: t for t in alarm.targets}
        lines: list[str] = []
        touched: set[uuid.UUID] = set()
        for target_id, (interface_id, result) in outcome.items():
            target = by_id[target_id]
            target.delivery_status = result.status
            target.detail = result.detail[:2000]
            target.delivered_at = now if result.status in ("sent", "simulated") else None
            lines.append(
                f"{target.label}: {DELIVERY_LABEL[result.status]}"
                + (f" ({result.detail})" if result.status in ("failed", "skipped") else "")
            )
            if interface_id is None:
                continue
            touched.add(interface_id)
            if result.detail == REDIRECT_TEXT:
                s.add(
                    InterfaceEvent(
                        interface_id=interface_id,
                        level="warning",
                        kind="redirected",
                        message=f"Alarm {incident.number}: {REDIRECT_TEXT}",
                        data={"alarm_id": str(alarm.id)},
                    )
                )
            elif result.attempts:
                await record_status(
                    uow,
                    interface_id,
                    result.status != "failed",
                    "delivery",
                    f"Alarm {incident.number}: {result.detail}",
                )
            else:
                s.add(
                    InterfaceEvent(
                        interface_id=interface_id,
                        level="info",
                        kind="delivery",
                        message=f"Alarm {incident.number}: {result.detail}",
                    )
                )
        alarm.status = alarm_status(alarm.targets)
        if lines:
            s.add(
                IncidentEvent(
                    incident_id=incident.id,
                    kind="alarm_delivery",
                    text="Zustellung über Schnittstellen – " + "; ".join(lines),
                    data={"alarm_id": str(alarm.id), "status": alarm.status},
                    actor_user_id=None,
                    actor_name="System",
                )
            )
        channel = [f"cc:{incident.control_center_id}"]
        uow.emit(
            "alarm.changed",
            {
                "id": str(alarm.id),
                "incident_id": str(incident.id),
                "status": alarm.status,
                "action": "delivered",
            },
            channels=channel,
            required_permission="incidents.read",
        )
        uow.emit(
            "incident.changed",
            {
                "id": str(incident.id),
                "number": incident.number,
                "action": "alarm_delivery",
                "status": incident.status,
            },
            channels=channel,
            required_permission="incidents.read",
        )
        for interface_id in touched:
            interface = await s.get(Interface, interface_id)
            if interface is not None:
                uow.emit(
                    "interface.changed",
                    {"id": str(interface_id), "action": "delivery"},
                    channels=interface_channel(interface),
                    required_permission="interfaces.read",
                )
        await uow.commit()


async def recover_interrupted_deliveries(uow: UnitOfWork) -> int:
    """At startup: deliveries interrupted by a restart are marked as failed – never re-sent
    automatically (the dispatcher decides whether to alarm again)."""
    cutoff = datetime.now(UTC) - INTERRUPTED_AFTER
    alarms = (
        await uow.session.scalars(select(Alarm).where(Alarm.status == "pending", Alarm.created_at < cutoff))
    ).all()
    for alarm in alarms:
        for target in alarm.targets:
            if target.delivery_status == "pending":
                target.delivery_status = "failed"
                target.detail = (
                    "Zustellung durch Serverneustart unterbrochen – bitte prüfen und ggf. erneut alarmieren"
                )
        alarm.status = alarm_status(alarm.targets)
        uow.session.add(
            IncidentEvent(
                incident_id=alarm.incident_id,
                kind="alarm_delivery",
                text="Zustellung über Schnittstellen durch Serverneustart unterbrochen – bitte prüfen",
                data={"alarm_id": str(alarm.id)},
                actor_user_id=None,
                actor_name="System",
            )
        )
    if alarms:
        uow.audit(
            "recover", "alarm", None, f"{len(alarms)} unterbrochene Zustellungen als fehlgeschlagen markiert"
        )
    await uow.commit()
    return len(alarms)
