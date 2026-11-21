"""Permission catalogue and default role definitions.

Permissions are stable string codes ``<area>.<action>``. The catalogue is the single
source of truth: it is synchronised into the ``permissions`` table on bootstrap, so new
permissions only need to be added here. Roles are stored in the database and are fully
editable by administrators; the definitions below are only the initial defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class P(StrEnum):
    # System / administration
    SYSTEM_ADMIN = "system.admin"  # implies access to all control centres
    SYSTEM_MODE_CHANGE = "system.mode.change"  # switch simulation <-> real operation
    AUDIT_READ = "audit.read"
    # Users & roles
    USERS_READ = "users.read"
    USERS_WRITE = "users.write"
    ROLES_WRITE = "roles.write"
    LOGIN_LOG_READ = "login_log.read"
    # Master data
    MASTER_DATA_READ = "master_data.read"  # stations, vehicles, RICs, radio groups, organisations
    ORGANIZATIONS_WRITE = "organizations.write"  # organisations and vehicle types (global catalogues)
    CONTROL_CENTERS_READ = "control_centers.read"
    CONTROL_CENTERS_WRITE = "control_centers.write"
    STATIONS_WRITE = "stations.write"
    VEHICLES_WRITE = "vehicles.write"
    RICS_WRITE = "rics.write"
    RADIO_GROUPS_WRITE = "radio_groups.write"
    KEYWORDS_WRITE = "keywords.write"
    ALARM_RULES_WRITE = "alarm_rules.write"
    PROPOSAL_SETTINGS_WRITE = "proposal_settings.write"
    DATA_IMPORT = "data.import"
    # Interfaces
    INTERFACES_READ = "interfaces.read"
    INTERFACES_WRITE = "interfaces.write"
    INTERFACES_ACTIVATE_REAL = "interfaces.activate_real"  # enable real (non-simulated) interfaces
    # Operations
    CALLS_HANDLE = "calls.handle"
    INCIDENTS_READ = "incidents.read"
    INCIDENTS_WRITE = "incidents.write"
    INCIDENTS_CLOSE = "incidents.close"
    ALARM_TRIGGER = "alarm.trigger"
    VEHICLES_STATUS_SET = "vehicles.status.set"
    RADIO_HANDLE = "radio.handle"
    # Training / simulation
    SIMULATION_CONTROL = "simulation.control"
    TRAINING_INSTRUCTOR = "training.instructor"
    TRAINING_PARTICIPATE = "training.participate"


@dataclass(frozen=True, slots=True)
class PermissionInfo:
    code: P
    area: str
    description: str


CATALOGUE: tuple[PermissionInfo, ...] = (
    PermissionInfo(P.SYSTEM_ADMIN, "System", "Vollzugriff auf alle Leitstellen und die Systemkonfiguration"),
    PermissionInfo(P.SYSTEM_MODE_CHANGE, "System", "Betriebsmodus (Simulation/Echtbetrieb) umschalten"),
    PermissionInfo(P.AUDIT_READ, "System", "Änderungsprotokoll einsehen"),
    PermissionInfo(P.USERS_READ, "Benutzer", "Benutzer anzeigen"),
    PermissionInfo(P.USERS_WRITE, "Benutzer", "Benutzer anlegen, bearbeiten, deaktivieren"),
    PermissionInfo(P.ROLES_WRITE, "Benutzer", "Rollen und Berechtigungen verwalten"),
    PermissionInfo(P.LOGIN_LOG_READ, "Benutzer", "Anmeldeprotokoll einsehen"),
    PermissionInfo(
        P.MASTER_DATA_READ, "Stammdaten", "Stammdaten anzeigen (Wachen, Fahrzeuge, RICs, Funkrufgruppen …)"
    ),
    PermissionInfo(P.ORGANIZATIONS_WRITE, "Stammdaten", "Organisationen und Fahrzeugtypen verwalten"),
    PermissionInfo(P.CONTROL_CENTERS_READ, "Stammdaten", "Leitstellen anzeigen"),
    PermissionInfo(P.CONTROL_CENTERS_WRITE, "Stammdaten", "Leitstellen verwalten"),
    PermissionInfo(P.STATIONS_WRITE, "Stammdaten", "Wachen verwalten"),
    PermissionInfo(P.VEHICLES_WRITE, "Stammdaten", "Fahrzeuge verwalten"),
    PermissionInfo(P.RICS_WRITE, "Stammdaten", "RICs und Alarmierungsgruppen verwalten"),
    PermissionInfo(P.RADIO_GROUPS_WRITE, "Stammdaten", "Funkrufgruppen verwalten"),
    PermissionInfo(P.KEYWORDS_WRITE, "Stammdaten", "Einsatzstichworte verwalten"),
    PermissionInfo(P.ALARM_RULES_WRITE, "Stammdaten", "Alarmierungsregeln (AAO) verwalten"),
    PermissionInfo(P.PROPOSAL_SETTINGS_WRITE, "Stammdaten", "Regeln des Einsatzmittelvorschlags verwalten"),
    PermissionInfo(P.DATA_IMPORT, "Stammdaten", "Datenimport (Excel/CSV) durchführen"),
    PermissionInfo(P.INTERFACES_READ, "Schnittstellen", "Schnittstellen anzeigen"),
    PermissionInfo(P.INTERFACES_WRITE, "Schnittstellen", "Schnittstellen konfigurieren"),
    PermissionInfo(
        P.INTERFACES_ACTIVATE_REAL, "Schnittstellen", "Reale (nicht simulierte) Schnittstellen aktivieren"
    ),
    PermissionInfo(P.CALLS_HANDLE, "Einsatz", "Notrufe annehmen und bearbeiten"),
    PermissionInfo(P.INCIDENTS_READ, "Einsatz", "Einsätze anzeigen"),
    PermissionInfo(P.INCIDENTS_WRITE, "Einsatz", "Einsätze anlegen und bearbeiten"),
    PermissionInfo(P.INCIDENTS_CLOSE, "Einsatz", "Einsätze abschließen"),
    PermissionInfo(P.ALARM_TRIGGER, "Einsatz", "Alarmierungen auslösen"),
    PermissionInfo(P.VEHICLES_STATUS_SET, "Einsatz", "Fahrzeugstatus setzen"),
    PermissionInfo(P.RADIO_HANDLE, "Einsatz", "Sprechwünsche und Funk bearbeiten"),
    PermissionInfo(P.SIMULATION_CONTROL, "Simulation", "Simulation steuern (Fahrzeuge, Ereignisse)"),
    PermissionInfo(P.TRAINING_INSTRUCTOR, "Simulation", "Ausbildermodus: Szenarien und Auswertungen"),
    PermissionInfo(P.TRAINING_PARTICIPATE, "Simulation", "An Trainings (KI-Anrufsimulation) teilnehmen"),
)

ALL_PERMISSIONS: frozenset[str] = frozenset(p.code.value for p in CATALOGUE)

_OPERATIONS = {
    P.CALLS_HANDLE,
    P.INCIDENTS_READ,
    P.INCIDENTS_WRITE,
    P.INCIDENTS_CLOSE,
    P.ALARM_TRIGGER,
    P.VEHICLES_STATUS_SET,
    P.RADIO_HANDLE,
    P.CONTROL_CENTERS_READ,
    P.MASTER_DATA_READ,
    P.TRAINING_PARTICIPATE,
}


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    key: str
    name: str
    description: str
    permissions: frozenset[str]


DEFAULT_ROLES: tuple[RoleDefinition, ...] = (
    RoleDefinition("admin", "Administrator", "Vollzugriff inkl. Systemkonfiguration", ALL_PERMISSIONS),
    RoleDefinition(
        "lead",
        "Leitstellenleitung",
        "Leitung: Einsatzbetrieb, Stammdaten, Auswertungen",
        frozenset(
            p.value
            for p in _OPERATIONS
            | {
                P.AUDIT_READ,
                P.USERS_READ,
                P.LOGIN_LOG_READ,
                P.ORGANIZATIONS_WRITE,
                P.STATIONS_WRITE,
                P.VEHICLES_WRITE,
                P.RICS_WRITE,
                P.RADIO_GROUPS_WRITE,
                P.KEYWORDS_WRITE,
                P.ALARM_RULES_WRITE,
                P.PROPOSAL_SETTINGS_WRITE,
                P.DATA_IMPORT,
                P.INTERFACES_READ,
                P.SIMULATION_CONTROL,
                P.TRAINING_INSTRUCTOR,
            }
        ),
    ),
    RoleDefinition(
        "dispatcher",
        "Disponent",
        "Notrufannahme, Disposition, Alarmierung, Funk",
        frozenset(p.value for p in _OPERATIONS),
    ),
    RoleDefinition(
        "call_taker",
        "Einsatzbearbeiter",
        "Notrufannahme und Einsatzbearbeitung ohne Alarmierung",
        frozenset(
            p.value
            for p in {
                P.CALLS_HANDLE,
                P.INCIDENTS_READ,
                P.INCIDENTS_WRITE,
                P.CONTROL_CENTERS_READ,
                P.MASTER_DATA_READ,
                P.TRAINING_PARTICIPATE,
            }
        ),
    ),
    RoleDefinition(
        "observer",
        "Beobachter",
        "Nur lesender Zugriff",
        frozenset(p.value for p in {P.INCIDENTS_READ, P.CONTROL_CENTERS_READ, P.MASTER_DATA_READ}),
    ),
)
