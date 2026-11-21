"""External interfaces (Schnittstellen): configuration, activation, tests and delivery.

Safety rules enforced here – for *every* plugin, independent of the plugin's own code:

* New interfaces are always created **disabled**.
* Real plugins (``meta.is_real``) can only be enabled or tested in **real operation** and only
  with ``interfaces.activate_real``. Switching back to simulation disables them
  (``disable_real_interfaces``).
* At delivery time the core checks the operation mode again: a real plugin is never called in
  simulation mode – the delivery is redirected to the simulation and logged (defence in depth,
  e.g. against a mode switch between preview and alarm).
* Secrets are encrypted with :class:`SecretBox` before they reach the database and are never
  returned (only a masked hint). They do not appear in the audit log or in events.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.crypto import SecretBox
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.models import Interface, InterfaceEvent, OperationMode, Station
from app.plugins.base import AlarmMessage, DeliveryResult, InterfacePlugin
from app.plugins.registry import get_plugin
from app.services.uow import UnitOfWork, check_version

SCOPES = ("global", "control_center", "station")
SCOPE_LABEL = {"global": "systemweit", "control_center": "Leitstelle", "station": "Wache"}
REDIRECT_TEXT = "Im Simulationsbetrieb umgeleitet – keine reale Übertragung"

# Delivery: one attempt plus retries with these back-off delays (seconds). Tests set them to 0.
RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0)
ATTEMPT_TIMEOUT_SECONDS = 20.0


def validate_config(plugin: InterfacePlugin, config: dict[str, Any]) -> None:
    errors = sorted(Draft202012Validator(plugin.meta.config_schema).iter_errors(config), key=str)
    if errors:
        messages = [
            f"{'.'.join(str(p) for p in e.absolute_path) or 'Konfiguration'}: {e.message}"
            for e in errors[:10]
        ]
        raise ValidationFailedError("Konfiguration ungültig", details={"errors": messages})


def is_effective(interface: Interface, mode: OperationMode) -> bool:
    """Would a delivery really reach the plugin? (enabled, and real plugins only in real mode)."""
    if not interface.enabled:
        return False
    return not get_plugin(interface.plugin_key).meta.is_real or mode == OperationMode.REAL


def interface_channel(interface: Interface) -> list[str]:
    return [f"cc:{interface.control_center_id}"] if interface.control_center_id else ["broadcast"]


@dataclass(slots=True)
class Delivery:
    status: str  # simulated | sent | failed | skipped
    detail: str
    attempts: int = 0


class InterfaceService:
    def __init__(
        self,
        uow: UnitOfWork,
        visible: set[uuid.UUID] | None,
        box: SecretBox,
        *,
        is_admin: bool = False,
        can_activate_real: bool = False,
    ) -> None:
        self.uow = uow
        self.s = uow.session
        self.visible = visible
        self.box = box
        self.is_admin = is_admin
        self.can_activate_real = can_activate_real

    # ------------------------------------------------------------------------- helpers
    def _check_access(self, interface: Interface, *, write: bool = False) -> None:
        if interface.control_center_id is None:
            if write and not self.is_admin:
                raise PermissionDeniedError("Systemweite Schnittstellen dürfen nur Administratoren ändern")
            return
        if self.visible is not None and interface.control_center_id not in self.visible:
            raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")

    def _require_real_permission(self, plugin: InterfacePlugin, action: str) -> None:
        if plugin.meta.is_real and not self.can_activate_real:
            raise PermissionDeniedError(
                f"{action} einer realen Schnittstelle erfordert 'interfaces.activate_real'",
                details={"missing_permissions": ["interfaces.activate_real"]},
            )

    async def _mode(self) -> OperationMode:
        from app.services.system_service import SystemService

        return await SystemService(self.uow).operation_mode()

    def _log(
        self, interface_id: uuid.UUID, level: str, kind: str, message: str, data: dict | None = None
    ) -> None:
        self.s.add(
            InterfaceEvent(interface_id=interface_id, level=level, kind=kind, message=message, data=data)
        )

    def _emit(self, interface: Interface, action: str) -> None:
        self.uow.emit(
            "interface.changed",
            {"id": str(interface.id), "action": action},
            channels=interface_channel(interface),
            required_permission="interfaces.read",
        )

    async def _validate_scope(
        self, scope: str, cc_id: uuid.UUID | None, station_id: uuid.UUID | None
    ) -> None:
        if scope not in SCOPES:
            raise ValidationFailedError("Unbekannter Geltungsbereich")
        if scope == "global":
            if cc_id or station_id:
                raise ValidationFailedError("Systemweite Schnittstellen haben keine Leitstelle/Wache")
            if not self.is_admin:
                raise PermissionDeniedError("Systemweite Schnittstellen dürfen nur Administratoren anlegen")
            return
        if cc_id is None:
            raise ValidationFailedError("Leitstelle fehlt")
        if self.visible is not None and cc_id not in self.visible:
            raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")
        if scope == "control_center" and station_id:
            raise ValidationFailedError("Für den Geltungsbereich „Leitstelle“ keine Wache angeben")
        if scope == "station":
            station = await self.s.get(Station, station_id) if station_id else None
            if station is None or station.control_center_id != cc_id:
                raise ValidationFailedError("Wache fehlt oder gehört zu einer anderen Leitstelle")
            if not station.organization.alarmable:
                raise ValidationFailedError(
                    f"{station.organization.name} ist nicht alarmierbar – keine Schnittstelle möglich"
                )

    def _set_secret(self, interface: Interface, secret: str | None, clear: bool) -> str | None:
        if clear:
            interface.secret_encrypted = None
            interface.secret_hint = None
            return "entfernt"
        if secret:
            interface.secret_encrypted = self.box.encrypt(secret)
            interface.secret_hint = SecretBox.mask(secret)
            return "geändert"
        return None

    def secret_of(self, interface: Interface) -> str | None:
        return self.box.decrypt(interface.secret_encrypted) if interface.secret_encrypted else None

    # ---------------------------------------------------------------------------- read
    async def get(self, interface_id: uuid.UUID) -> Interface:
        interface = await self.s.get(Interface, interface_id)
        if interface is None:
            raise NotFoundError("Schnittstelle nicht gefunden")
        self._check_access(interface)
        return interface

    async def list(self, control_center_id: uuid.UUID | None) -> list[Interface]:
        stmt = select(Interface)
        if control_center_id is not None:
            if self.visible is not None and control_center_id not in self.visible:
                raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")
            stmt = stmt.where(
                or_(Interface.control_center_id == control_center_id, Interface.control_center_id.is_(None))
            )
        elif self.visible is not None:
            stmt = stmt.where(
                or_(
                    Interface.control_center_id.in_(self.visible or {uuid.uuid4()}),
                    Interface.control_center_id.is_(None),
                )
            )
        stmt = stmt.order_by(Interface.scope, Interface.name)
        return list((await self.s.scalars(stmt)).all())

    async def events(self, interface_id: uuid.UUID, limit: int) -> list[InterfaceEvent]:
        await self.get(interface_id)
        stmt = (
            select(InterfaceEvent)
            .where(InterfaceEvent.interface_id == interface_id)
            .order_by(InterfaceEvent.id.desc())
            .limit(limit)
        )
        return list((await self.s.scalars(stmt)).all())

    # --------------------------------------------------------------------------- write
    async def create(self, data: dict[str, Any]) -> Interface:
        plugin = get_plugin(data["plugin_key"])
        scope = data["scope"]
        if scope not in plugin.meta.scopes:
            raise ValidationFailedError(f"{plugin.meta.name} unterstützt den Geltungsbereich „{scope}“ nicht")
        await self._validate_scope(scope, data.get("control_center_id"), data.get("station_id"))
        config = data.get("config") or {}
        validate_config(plugin, config)
        if plugin.meta.secret_required and not data.get("secret"):
            raise ValidationFailedError(f"{plugin.meta.secret_label or 'Schlüssel'} fehlt")
        interface = Interface(
            id=uuid.uuid4(),
            plugin_key=plugin.meta.key,
            name=data["name"].strip(),
            scope=scope,
            control_center_id=data.get("control_center_id"),
            station_id=data.get("station_id"),
            enabled=False,  # never active on creation
            config=config,
        )
        self._set_secret(interface, data.get("secret"), False)
        self.s.add(interface)
        await self.s.flush()
        self._log(interface.id, "info", "config", "Schnittstelle angelegt (deaktiviert)")
        self.uow.audit(
            "create",
            "interface",
            interface.id,
            f"Schnittstelle „{interface.name}“ ({plugin.meta.name}, {SCOPE_LABEL[scope]}) "
            "angelegt – deaktiviert",
            changes={"config": {"old": None, "new": config}, "secret": {"old": None, "new": "gesetzt"}}
            if interface.secret_encrypted
            else {"config": {"old": None, "new": config}},
            control_center_id=interface.control_center_id,
        )
        self._emit(interface, "created")
        await self.uow.commit()
        await self.s.refresh(interface)
        return interface

    async def update(self, interface_id: uuid.UUID, data: dict[str, Any], expected_version: int) -> Interface:
        interface = await self.get(interface_id)
        self._check_access(interface, write=True)
        check_version(interface, expected_version, f"Schnittstelle „{interface.name}“")
        plugin = get_plugin(interface.plugin_key)
        if interface.enabled:
            # Re-targeting an active real interface is as powerful as activating it.
            self._require_real_permission(plugin, "Das Ändern")
        changes: dict[str, Any] = {}
        if data.get("name") is not None and data["name"].strip() != interface.name:
            changes["name"] = {"old": interface.name, "new": data["name"].strip()}
            interface.name = data["name"].strip()
        if data.get("config") is not None and data["config"] != interface.config:
            validate_config(plugin, data["config"])
            changes["config"] = {"old": interface.config, "new": data["config"]}
            interface.config = data["config"]
        secret_change = self._set_secret(interface, data.get("secret"), bool(data.get("clear_secret")))
        if secret_change:
            changes["secret"] = {"old": "••••", "new": secret_change}
        if not changes:
            return interface
        await self.s.flush()
        self._log(interface.id, "info", "config", "Konfiguration geändert: " + ", ".join(changes))
        self.uow.audit(
            "update",
            "interface",
            interface.id,
            f"Schnittstelle „{interface.name}“ geändert",
            changes=changes,
            control_center_id=interface.control_center_id,
        )
        self._emit(interface, "updated")
        await self.uow.commit()
        await self.s.refresh(interface)
        return interface

    async def delete(self, interface_id: uuid.UUID, expected_version: int) -> None:
        interface = await self.get(interface_id)
        self._check_access(interface, write=True)
        check_version(interface, expected_version, f"Schnittstelle „{interface.name}“")
        if interface.enabled:
            raise ConflictError("Aktive Schnittstellen zuerst deaktivieren")
        name, cc_id = interface.name, interface.control_center_id
        await self.s.delete(interface)
        self.uow.audit(
            "delete", "interface", interface_id, f"Schnittstelle „{name}“ gelöscht", control_center_id=cc_id
        )
        self._emit(interface, "deleted")
        try:
            await self.uow.commit()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError(
                "Die Schnittstelle wird noch in einer Alarmierungsregel (AAO) verwendet"
            ) from exc

    async def set_enabled(
        self, interface_id: uuid.UUID, enabled: bool, expected_version: int, reason: str | None
    ) -> Interface:
        interface = await self.get(interface_id)
        self._check_access(interface, write=True)
        check_version(interface, expected_version, f"Schnittstelle „{interface.name}“")
        if interface.enabled == enabled:
            return interface
        plugin = get_plugin(interface.plugin_key)
        if enabled and plugin.meta.is_real:
            self._require_real_permission(plugin, "Das Aktivieren")
            if await self._mode() != OperationMode.REAL:
                raise ConflictError(
                    "Reale Schnittstellen können nur im Echtbetrieb aktiviert werden "
                    "(Simulationsbetrieb aktiv)"
                )
            if not reason or len(reason.strip()) < 5:
                raise ValidationFailedError("Begründung für die Aktivierung einer realen Schnittstelle fehlt")
        interface.enabled = enabled
        await self.s.flush()
        verb = "aktiviert" if enabled else "deaktiviert"
        text = f"Schnittstelle „{interface.name}“ {verb}" + (
            f". Begründung: {reason.strip()}" if reason else ""
        )
        self._log(interface.id, "warning" if enabled and plugin.meta.is_real else "info", "config", text)
        self.uow.audit(
            "enable" if enabled else "disable",
            "interface",
            interface.id,
            text + (" (REALE SCHNITTSTELLE)" if plugin.meta.is_real else ""),
            changes={"enabled": {"old": not enabled, "new": enabled}},
            control_center_id=interface.control_center_id,
        )
        self._emit(interface, "enabled" if enabled else "disabled")
        await self.uow.commit()
        await self.s.refresh(interface)
        return interface

    async def test(self, interface_id: uuid.UUID) -> DeliveryResult:
        interface = await self.get(interface_id)
        self._check_access(interface, write=True)
        plugin = get_plugin(interface.plugin_key)
        if plugin.meta.is_real:
            self._require_real_permission(plugin, "Der Test")
            if await self._mode() != OperationMode.REAL:
                raise ConflictError(
                    "Test realer Schnittstellen nur im Echtbetrieb möglich – "
                    "im Simulationsbetrieb wird nichts übertragen"
                )
        config, secret = dict(interface.config), self.secret_of(interface)
        await self.s.commit()  # no transaction is held open during network I/O
        try:
            result = await asyncio.wait_for(plugin.test(config, secret), ATTEMPT_TIMEOUT_SECONDS)
        except TimeoutError:
            result = DeliveryResult(False, "Zeitüberschreitung")
        except Exception as exc:  # a plugin error must never break the server
            result = DeliveryResult(False, f"Plugin-Fehler: {type(exc).__name__}")
        await record_status(self.uow, interface.id, result.ok, "test", f"Test: {result.detail}")
        refreshed = await self.get(interface_id)
        self._emit(refreshed, "tested")
        self.uow.audit(
            "test",
            "interface",
            interface_id,
            f"Schnittstelle „{refreshed.name}“ getestet: {'erfolgreich' if result.ok else 'fehlgeschlagen'}",
            control_center_id=refreshed.control_center_id,
        )
        await self.uow.commit()
        return result


async def record_status(uow: UnitOfWork, interface_id: uuid.UUID, ok: bool, kind: str, message: str) -> None:
    """Operational status (not configuration): plain UPDATE without version bump, so status
    changes never cause edit conflicts for administrators."""
    now = datetime.now(UTC)
    values: dict[str, Any] = {"status": "ok" if ok else "error", "last_checked_at": now}
    if ok:
        values |= {"last_ok_at": now, "last_error": None}
    else:
        values["last_error"] = message[:2000]
    await uow.session.execute(update(Interface).where(Interface.id == interface_id).values(**values))
    uow.session.add(
        InterfaceEvent(interface_id=interface_id, level="info" if ok else "error", kind=kind, message=message)
    )


async def disable_real_interfaces(uow: UnitOfWork) -> list[str]:
    """Called when the system leaves real operation: every real interface is disabled."""
    from app.plugins.registry import all_plugins

    real_keys = [p.meta.key for p in all_plugins() if p.meta.is_real]
    rows = (
        await uow.session.scalars(
            select(Interface).where(Interface.enabled.is_(True), Interface.plugin_key.in_(real_keys))
        )
    ).all()
    for interface in rows:
        interface.enabled = False
        uow.session.add(
            InterfaceEvent(
                interface_id=interface.id,
                level="warning",
                kind="config",
                message="Automatisch deaktiviert: Wechsel in den Simulationsbetrieb",
            )
        )
        uow.audit(
            "disable",
            "interface",
            interface.id,
            f"Reale Schnittstelle „{interface.name}“ automatisch deaktiviert "
            "(Wechsel in den Simulationsbetrieb)",
            control_center_id=interface.control_center_id,
        )
        uow.emit(
            "interface.changed",
            {"id": str(interface.id), "action": "disabled"},
            channels=interface_channel(interface),
            required_permission="interfaces.read",
        )
    return [r.name for r in rows]


async def deliver(
    plugin: InterfacePlugin,
    config: dict[str, Any],
    secret: str | None,
    message: AlarmMessage,
    *,
    enabled: bool,
    mode: OperationMode,
) -> Delivery:
    """Deliver one alarm to one interface. The simulation/real separation is checked here,
    right before the plugin would be called – never inside the plugin."""
    if not enabled:
        return Delivery("skipped", "Schnittstelle deaktiviert – nicht übertragen")
    if plugin.meta.is_real and (mode != OperationMode.REAL or message.mode != OperationMode.REAL.value):
        return Delivery("simulated", REDIRECT_TEXT)
    attempts = 0
    last = DeliveryResult(False, "nicht versucht")
    for delay in (0.0, *RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        attempts += 1
        try:
            last = await asyncio.wait_for(plugin.send_alarm(config, secret, message), ATTEMPT_TIMEOUT_SECONDS)
        except TimeoutError:
            last = DeliveryResult(False, "Zeitüberschreitung")
        except Exception as exc:  # a plugin error must never break the alarm
            last = DeliveryResult(False, f"Plugin-Fehler: {type(exc).__name__}")
        if last.ok:
            status = "sent" if plugin.meta.is_real else "simulated"
            return Delivery(status, last.detail, attempts)
        if not last.retryable:
            break
    return Delivery(
        "failed", f"{last.detail} (nach {attempts} Versuch{'en' if attempts > 1 else ''})", attempts
    )
