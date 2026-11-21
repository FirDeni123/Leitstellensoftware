"""System settings: operation mode, module status, per-user layouts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.models import OperationMode, SystemSetting, UserLayout
from app.schemas.system import ModuleStatus
from app.services.uow import UnitOfWork, check_version

MODE_KEY = "operation_mode"
REAL_MODE_CONFIRMATION = "ECHTBETRIEB"

WORKSTATIONS = ("call_taking", "dispatch", "radio", "management", "admin")

# Transparent implementation status of every planned module (shown in the client).
MODULES: tuple[ModuleStatus, ...] = (
    ModuleStatus(key="auth", name="Anmeldung, Sitzungen, Rechte", phase=1, status="available"),
    ModuleStatus(key="realtime", name="Echtzeit-Synchronisation", phase=1, status="available"),
    ModuleStatus(key="audit", name="Änderungsprotokoll", phase=1, status="available"),
    ModuleStatus(key="layouts", name="Anpassbare Arbeitsplätze", phase=1, status="available"),
    ModuleStatus(
        key="users",
        name="Benutzer- und Rollenverwaltung",
        phase=1,
        status="available",
        note="Server vollständig, Client-Oberfläche: Benutzerliste und Bearbeitung",
    ),
    ModuleStatus(
        key="control_centers",
        name="Leitstellenverwaltung",
        phase=2,
        status="partial",
        note="Anlegen/Bearbeiten/Löschen vorhanden; Verknüpfungen und Zuständigkeiten folgen",
    ),
    ModuleStatus(key="stations", name="Wachen", phase=2, status="planned"),
    ModuleStatus(key="vehicles", name="Fahrzeuge", phase=2, status="planned"),
    ModuleStatus(key="rics", name="RICs und Alarmierungsgruppen", phase=2, status="planned"),
    ModuleStatus(key="radio_groups", name="Funkrufgruppen", phase=2, status="planned"),
    ModuleStatus(key="import", name="Excel-/CSV-Import", phase=2, status="planned"),
    ModuleStatus(key="calls", name="Notrufannahme", phase=3, status="planned"),
    ModuleStatus(key="incidents", name="Einsatzbearbeitung", phase=3, status="planned"),
    ModuleStatus(key="alarming", name="Alarmierung (Stichworte, AAO, RIC)", phase=4, status="planned"),
    ModuleStatus(key="police_notice", name="Polizei-Hinweis (keine Alarmierung)", phase=4, status="planned"),
    ModuleStatus(key="proposal", name="Einsatzmittelvorschlag", phase=5, status="planned"),
    ModuleStatus(key="vehicle_status", name="Fahrzeugstatus und Sprechwünsche", phase=6, status="planned"),
    ModuleStatus(key="map", name="Karte und GPS-Simulation", phase=6, status="planned"),
    ModuleStatus(key="voice", name="Sprach- und Telefoniesimulation", phase=7, status="planned"),
    ModuleStatus(key="ai_caller", name="KI-Anrufsimulation und Ausbildermodus", phase=7, status="planned"),
    ModuleStatus(key="interfaces", name="Schnittstellen und Plugins", phase=4, status="planned"),
)


class SystemService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self.s = uow.session

    async def mode_setting(self) -> SystemSetting:
        setting = await self.s.get(SystemSetting, MODE_KEY)
        if setting is None:
            # The system always starts in simulation mode.
            setting = SystemSetting(key=MODE_KEY, value=OperationMode.SIMULATION.value)
            self.s.add(setting)
            await self.s.flush()
            await self.uow.commit()
        return setting

    async def operation_mode(self) -> OperationMode:
        return OperationMode((await self.mode_setting()).value)

    async def set_operation_mode(
        self, mode: OperationMode, reason: str, confirmation: str, expected_version: int
    ) -> SystemSetting:
        setting = await self.mode_setting()
        check_version(setting, expected_version, "Der Betriebsmodus")
        if mode == OperationMode.REAL and confirmation != REAL_MODE_CONFIRMATION:
            raise ValidationFailedError(f"Bestätigung '{REAL_MODE_CONFIRMATION}' erforderlich")
        old = setting.value
        if old == mode.value:
            return setting
        setting.value = mode.value
        setting.updated_by = self.uow.actor.user_id
        await self.s.flush()
        self.uow.audit(
            "mode_change",
            "system",
            MODE_KEY,
            f"Betriebsmodus von '{old}' auf '{mode.value}' geändert. Begründung: {reason}",
            changes={"mode": {"old": old, "new": mode.value}},
        )
        self.uow.emit("system.mode_changed", {"mode": mode.value})
        await self.uow.commit()
        return setting

    # ----------------------------------------------------------------------------- layouts
    async def get_layout(self, user_id: uuid.UUID, workstation: str) -> UserLayout:
        self._check_workstation(workstation)
        layout = await self.s.scalar(
            select(UserLayout).where(UserLayout.user_id == user_id, UserLayout.workstation == workstation)
        )
        if layout is None:
            raise NotFoundError("Kein gespeichertes Layout")
        return layout

    async def put_layout(
        self, user_id: uuid.UUID, workstation: str, layout: dict[str, Any], expected_version: int | None
    ) -> UserLayout:
        self._check_workstation(workstation)
        if len(str(layout)) > 200_000:
            raise ValidationFailedError("Layout ist zu groß")
        row = await self.s.scalar(
            select(UserLayout).where(UserLayout.user_id == user_id, UserLayout.workstation == workstation)
        )
        if row is None:
            if expected_version is not None:
                raise ConflictError(
                    "Layout wurde zwischenzeitlich gelöscht", details={"current_version": None}
                )
            row = UserLayout(user_id=user_id, workstation=workstation, layout=layout)
            self.s.add(row)
        else:
            if expected_version is None:
                raise ConflictError("Layout existiert bereits", details={"current_version": row.version})
            check_version(row, expected_version, "Das Layout")
            row.layout = layout
        await self.s.flush()
        # Same user on a second workstation PC: keep both in sync.
        self.uow.emit(
            "layout.changed",
            {"workstation": workstation, "version": row.version},
            channels=[f"user:{user_id}"],
        )
        await self.uow.commit()
        return row

    async def delete_layout(self, user_id: uuid.UUID, workstation: str) -> None:
        row = await self.get_layout(user_id, workstation)
        await self.s.delete(row)
        self.uow.emit(
            "layout.changed", {"workstation": workstation, "version": None}, channels=[f"user:{user_id}"]
        )
        await self.uow.commit()

    @staticmethod
    def _check_workstation(workstation: str) -> None:
        if workstation not in WORKSTATIONS:
            raise ValidationFailedError("Unbekannter Arbeitsplatz", details={"allowed": list(WORKSTATIONS)})
