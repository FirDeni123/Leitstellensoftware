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

WORKSTATIONS = ("call_taking", "dispatch", "radio", "management", "admin", "training")

# Transparent implementation status of every planned module (shown in the client).
MODULES: tuple[ModuleStatus, ...] = (
    ModuleStatus(key="auth", name="Anmeldung, Sitzungen, Rechte", phase=1, status="available"),
    ModuleStatus(key="realtime", name="Echtzeit-Synchronisation", phase=1, status="available"),
    ModuleStatus(key="audit", name="Änderungsprotokoll", phase=1, status="available"),
    ModuleStatus(key="layouts", name="Anpassbare Arbeitsplätze", phase=1, status="available"),
    ModuleStatus(
        key="users",
        name="Benutzer-, Rollen- und Rechteverwaltung",
        phase=2,
        status="available",
        note="inkl. Rollen-Editor, individuelle Rechte, Anmeldeprotokoll",
    ),
    ModuleStatus(
        key="control_centers",
        name="Leitstellen, Verknüpfungen, Zuständigkeitsbereiche",
        phase=2,
        status="available",
        note="Bereiche per GeoJSON oder Gemeindeschlüssel; Zeichnen auf der Karte ab Phase 6",
    ),
    ModuleStatus(key="organizations", name="Organisationen und Fahrzeugtypen", phase=2, status="available"),
    ModuleStatus(
        key="stations",
        name="Wachen",
        phase=2,
        status="available",
        note="Schnittstellen je Wache über das Schnittstellen-Modul",
    ),
    ModuleStatus(
        key="vehicles",
        name="Fahrzeuge und Statusbezeichnungen",
        phase=2,
        status="available",
        note="Statuswechsel im Betrieb über die Fahrzeugübersicht",
    ),
    ModuleStatus(
        key="rics",
        name="RICs und Alarmierungsgruppen",
        phase=2,
        status="available",
        note="Zuordnung zu Stichworten über die AAO",
    ),
    ModuleStatus(key="radio_groups", name="Funkrufgruppen", phase=2, status="available"),
    ModuleStatus(
        key="import",
        name="Excel-/CSV-Import (Fahrzeuge, Wachen)",
        phase=2,
        status="available",
        note="Import aus OpenStreetMap (nur Standorte) geplant",
    ),
    ModuleStatus(
        key="calls",
        name="Notrufannahme (simulierte und manuell erfasste Anrufe)",
        phase=3,
        status="available",
        note="Übungsanrufe mit KI-Anrufer seit Phase 7; echte Telefonie/VoIP nicht angebunden",
    ),
    ModuleStatus(
        key="incidents",
        name="Einsatzbearbeitung, Einsatzverlauf, Stichwortkatalog",
        phase=3,
        status="available",
        note="„Alarmiert“ durch die Alarmierung, „Anfahrt/Am Einsatzort“ aus Status 3/4",
    ),
    ModuleStatus(
        key="alarming",
        name="Alarmierung (AAO, Vorschau, Bestätigung, Nachalarmierung, Protokoll)",
        phase=4,
        status="available",
        note="Funkalarmierung (POCSAG/TETRA) nicht angebunden",
    ),
    ModuleStatus(
        key="police_notice",
        name="Polizei-Hinweis (nur Information, keine Alarmierung)",
        phase=4,
        status="available",
    ),
    ModuleStatus(
        key="proposal",
        name="Einsatzmittelvorschlag (Bewertung, Begründungen, Übernahme)",
        phase=5,
        status="available",
        note="Fahrzeit geschätzt (Luftlinie × Umwegfaktor) oder per OSRM, falls eingerichtet",
    ),
    ModuleStatus(
        key="vehicle_status",
        name="Fahrzeugstatus, Statushistorie und Sprechwünsche",
        phase=6,
        status="available",
        note="Status manuell oder aus der Simulation; reale FMS-/TETRA-Anbindung als späteres Plugin",
    ),
    ModuleStatus(
        key="map",
        name="Karte, simulierte Fahrten und Positionen",
        phase=6,
        status="available",
        note="Straßengenaue Fahrten mit OSRM (Container); ohne Routing gekennzeichnete Luftlinie",
    ),
    ModuleStatus(
        key="ai_caller",
        name="KI-Anrufsimulation und Ausbildermodus",
        phase=7,
        status="available",
        note="Claude (vom Administrator einzuschalten) oder regelbasierter Anrufer ohne KI; "
        "Szenario-Editor, Beobachten, Eingriffe, automatische Auswertung",
    ),
    ModuleStatus(
        key="voice",
        name="Sprache im Übungsgespräch",
        phase=7,
        status="partial",
        note="Sprachausgabe über Windows-Stimmen; Spracherkennung nur mit optionalem faster-whisper "
        "auf dem Server; Piper und Gesprächsaufzeichnung noch nicht umgesetzt; keine echte Telefonie",
    ),
    ModuleStatus(
        key="interfaces",
        name="Schnittstellen und Plugins",
        phase=4,
        status="available",
        note="Simulations-Empfänger und Webhook; Feuerwehrsoftware-Anbindungen als spätere Plugins",
    ),
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
        if mode == OperationMode.REAL:
            # Entering real operation: simulated drives stop – no simulated positions in real mode.
            from app.simulation.fleet import Fleet

            stopped = await Fleet(self.uow).stop_all("Wechsel in den Echtbetrieb")
            if stopped:
                reason = f"{reason} – {stopped} simulierte Fahrt(en) beendet"
            from app.services.training_service import cancel_open_sessions

            cancelled = await cancel_open_sessions(self.uow, "Wechsel in den Echtbetrieb")
            if cancelled:
                reason = f"{reason} – {cancelled} laufende Übung(en) abgebrochen"
        if mode == OperationMode.SIMULATION:
            # Leaving real operation: every real interface is switched off (clear separation).
            from app.services.interface_service import disable_real_interfaces

            disabled = await disable_real_interfaces(self.uow)
            if disabled:
                reason = f"{reason} – automatisch deaktiviert: {', '.join(disabled)}"
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
