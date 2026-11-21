"""Reference data shipped with the system (editable afterwards by administrators).

* FMS status definitions 0–9: always ensured (codes are structural, labels editable).
* Default organisations and vehicle types: seeded exactly once per installation
  (flag in ``system_settings``) – if an administrator deletes entries they stay deleted.
"""

from __future__ import annotations

from sqlalchemy import select, text

from app.models import Organization, SystemSetting, VehicleStatusDefinition, VehicleType
from app.services.uow import UnitOfWork

SEED_FLAG = "reference_data_seeded_v1"

# code, label, short label, colour, counts as available
STATUS_DEFAULTS: tuple[tuple[int, str, str, str, bool], ...] = (
    (0, "Priorisierter Sprechwunsch (Notruf)", "Notruf", "#ff2d55", False),
    (1, "Einsatzbereit über Funk", "Frei Funk", "#39c27a", True),
    (2, "Einsatzbereit auf Wache", "Frei Wache", "#1f8f55", True),
    (3, "Einsatzauftrag übernommen", "Anfahrt", "#f2a93b", False),
    (4, "Am Einsatzort", "Einsatzort", "#ef4f55", False),
    (5, "Sprechwunsch", "Sprechwunsch", "#3d8bfd", False),
    (6, "Nicht einsatzbereit", "Außer Dienst", "#6b7686", False),
    (7, "Patient aufgenommen", "Patient", "#b36bf2", False),
    (8, "Am Transportziel", "Transportziel", "#8f6bf2", False),
    (9, "Fremdanmeldung / Sonstiges", "Sonstiges", "#6b7686", False),
)

# key, name, kind, alarmable, colour
ORGANIZATION_DEFAULTS: tuple[tuple[str, str, str, bool, str], ...] = (
    ("feuerwehr", "Feuerwehr", "fire", True, "#d93a3f"),
    ("rettungsdienst", "Rettungsdienst", "ems", True, "#e4e7eb"),
    ("thw", "Technisches Hilfswerk (THW)", "technical_relief", True, "#1f4fbf"),
    ("katastrophenschutz", "Katastrophenschutz", "civil_protection", True, "#f2a93b"),
    ("drk", "Deutsches Rotes Kreuz", "aid", True, "#e30613"),
    ("asb", "Arbeiter-Samariter-Bund", "aid", True, "#f39200"),
    ("juh", "Johanniter-Unfall-Hilfe", "aid", True, "#c9a227"),
    ("mhd", "Malteser Hilfsdienst", "aid", True, "#9b1c31"),
    ("dlrg", "DLRG", "aid", True, "#ffcc00"),
    ("polizei", "Polizei (nur Information, keine Alarmierung)", "police", False, "#1a4f9c"),
)

# code, name, category, default speed km/h, default crew, capabilities
VEHICLE_TYPE_DEFAULTS: tuple[tuple[str, str, str, int, int | None, list[str]], ...] = (
    ("ELW1", "Einsatzleitwagen 1", "fire", 70, 3, ["command"]),
    (
        "HLF20",
        "Hilfeleistungslöschgruppenfahrzeug 20",
        "fire",
        60,
        9,
        ["water", "extinguish", "rescue_equipment"],
    ),
    ("LF20", "Löschgruppenfahrzeug 20", "fire", 60, 9, ["water", "extinguish"]),
    ("LF10", "Löschgruppenfahrzeug 10", "fire", 60, 9, ["water", "extinguish"]),
    ("TSF-W", "Tragkraftspritzenfahrzeug-Wasser", "fire", 60, 6, ["water", "extinguish"]),
    ("TLF3000", "Tanklöschfahrzeug 3000", "fire", 55, 3, ["water", "extinguish"]),
    ("DLK23", "Drehleiter mit Korb 23/12", "fire", 55, 3, ["ladder"]),
    ("RW", "Rüstwagen", "fire", 55, 3, ["rescue_equipment", "heavy_rescue"]),
    ("GW-G", "Gerätewagen Gefahrgut", "fire", 55, 3, ["hazmat"]),
    ("GW-L2", "Gerätewagen Logistik 2", "fire", 55, 3, ["logistics"]),
    ("MTW", "Mannschaftstransportwagen", "fire", 70, 9, ["transport"]),
    ("RTW", "Rettungswagen", "ems", 70, 2, ["ems", "patient_transport"]),
    ("NEF", "Notarzteinsatzfahrzeug", "ems", 80, 2, ["emergency_physician"]),
    ("KTW", "Krankentransportwagen", "ems", 65, 2, ["patient_transport"]),
    ("ITW", "Intensivtransportwagen", "ems", 65, 3, ["ems", "patient_transport", "intensive_care"]),
    ("RTH", "Rettungshubschrauber", "ems", 220, 3, ["emergency_physician", "air"]),
    ("GKW", "Gerätekraftwagen (THW)", "technical_relief", 55, 9, ["rescue_equipment", "heavy_rescue"]),
    ("GW-SAN", "Gerätewagen Sanität", "civil_protection", 60, 4, ["ems_mass_casualty"]),
)


async def ensure_reference_data(uow: UnitOfWork) -> dict[str, int]:
    s = uow.session
    await s.execute(text("SELECT pg_advisory_xact_lock(470012)"))
    existing_codes = set((await s.scalars(select(VehicleStatusDefinition.code))).all())
    statuses = 0
    for code, label, short, color, available in STATUS_DEFAULTS:
        if code not in existing_codes:
            s.add(
                VehicleStatusDefinition(
                    code=code, label=label, short_label=short, color=color, counts_as_available=available
                )
            )
            statuses += 1

    orgs = types = 0
    if await s.get(SystemSetting, SEED_FLAG) is None:
        org_keys = set((await s.scalars(select(Organization.key))).all())
        for key, name, kind, alarmable, color in ORGANIZATION_DEFAULTS:
            if key not in org_keys:
                s.add(Organization(key=key, name=name, kind=kind, alarmable=alarmable, color=color))
                orgs += 1
        type_codes = set((await s.scalars(select(VehicleType.code))).all())
        for code, name, category, speed, crew, caps in VEHICLE_TYPE_DEFAULTS:
            if code not in type_codes:
                s.add(
                    VehicleType(
                        code=code,
                        name=name,
                        category=category,
                        default_speed_kmh=speed,
                        default_crew=crew,
                        capabilities=caps,
                    )
                )
                types += 1
        s.add(SystemSetting(key=SEED_FLAG, value=True))

    if statuses or orgs or types:
        uow.audit(
            "sync",
            "reference_data",
            None,
            f"Referenzdaten angelegt ({statuses} Status, {orgs} Organisationen, {types} Fahrzeugtypen)",
        )
    await uow.commit()
    return {"statuses": statuses, "organizations": orgs, "vehicle_types": types}
