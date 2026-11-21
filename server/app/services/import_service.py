"""Excel/CSV import of vehicles and stations.

Workflow (each step is a separate API call, nothing is written before step 3):

1. **Upload** – the file is parsed, rows are stored in the import job and a column
   mapping is suggested from the headers (German synonyms).
2. **Mapping + validation** – the administrator confirms/changes the mapping; every row is
   resolved against the database (stations, vehicle types, organisations, RICs …) and gets
   an action (create / update / unchanged / error) with row-precise messages.
3. **Commit** – validation runs again (data may have changed meanwhile) and all rows are
   written in **one** transaction, each record with its own audit entry. Rows with errors
   are only skipped if explicitly requested; otherwise nothing is written.

Empty cells never overwrite existing values when updating.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.models import ImportJob, Organization, RadioGroup, Ric, Station, Vehicle, VehicleType
from app.services.crud import CrudService
from app.services.import_files import (
    normalise_header,
    parse_bool,
    parse_int,
    parse_number,
    read_table,
    split_list,
)
from app.services.master_data import STATIONS, VEHICLES
from app.services.uow import UnitOfWork, check_version, diff

PREVIEW_ROWS = 20


@dataclass(frozen=True, slots=True)
class TargetField:
    key: str
    label: str
    required: bool
    synonyms: tuple[str, ...]
    hint: str = ""


VEHICLE_FIELDS: tuple[TargetField, ...] = (
    TargetField(
        "call_sign",
        "Funkrufname",
        True,
        ("funkrufname", "rufname", "funkkenner", "call sign", "callsign", "fahrzeugname"),
        "eindeutig je Leitstelle; bestimmt, ob ein Fahrzeug neu angelegt oder aktualisiert wird",
    ),
    TargetField(
        "vehicle_type",
        "Fahrzeugtyp",
        True,
        ("fahrzeugtyp", "typ", "fahrzeugart", "fahrzeug typ", "type"),
        "Kürzel oder Name, z. B. HLF20 oder Rettungswagen",
    ),
    TargetField(
        "station",
        "Wache",
        True,
        ("wache", "standort", "station", "stationierung", "wachenname"),
        "Name oder Kurzname einer bestehenden Wache",
    ),
    TargetField(
        "organization",
        "Organisation",
        False,
        ("organisation", "traeger", "hilfsorganisation", "org"),
        "leer = Organisation der Wache",
    ),
    TargetField(
        "license_plate",
        "Kennzeichen",
        False,
        ("kennzeichen", "amtl kennzeichen", "amtliches kennzeichen", "kfz kennzeichen", "nummernschild"),
    ),
    TargetField(
        "radio_group",
        "Funkrufgruppe",
        False,
        ("funkrufgruppe", "funkgruppe", "tbz", "rufgruppe", "talkgroup"),
    ),
    TargetField(
        "rics",
        "RICs",
        False,
        ("rics", "ric", "alarmierung", "pager", "melder"),
        "mehrere durch Komma/Semikolon getrennt, z. B. 1234567A; 1234568",
    ),
    TargetField("crew_size", "Besatzung", False, ("besatzung", "staerke", "crew", "sitzplaetze")),
    TargetField(
        "sim_speed_kmh",
        "Simulationsgeschwindigkeit (km/h)",
        False,
        ("geschwindigkeit", "km/h", "kmh", "speed", "tempo", "simulationsgeschwindigkeit"),
    ),
    TargetField(
        "available",
        "Verfügbar",
        False,
        ("verfuegbar", "einsatzbereit", "in dienst", "verfuegbarkeit"),
        "ja/nein, x, 1/0",
    ),
    TargetField(
        "description", "Beschreibung", False, ("beschreibung", "bemerkung", "hinweis", "notiz", "kommentar")
    ),
)

STATION_FIELDS: tuple[TargetField, ...] = (
    TargetField(
        "name",
        "Name",
        True,
        ("name", "wache", "bezeichnung", "wachenname", "standort"),
        "eindeutig je Leitstelle; bestimmt, ob neu angelegt oder aktualisiert wird",
    ),
    TargetField(
        "organization",
        "Organisation",
        True,
        ("organisation", "traeger", "hilfsorganisation", "org"),
        "Schlüssel oder Name, z. B. feuerwehr, DRK",
    ),
    TargetField("short_name", "Kurzname", False, ("kurzname", "kuerzel", "abkuerzung", "kurzbezeichnung")),
    TargetField("address", "Anschrift", False, ("anschrift", "adresse", "strasse", "address")),
    TargetField("latitude", "Breitengrad", False, ("breitengrad", "breite", "lat", "latitude", "geo breite")),
    TargetField(
        "longitude", "Längengrad", False, ("laengengrad", "laenge", "lon", "lng", "longitude", "geo laenge")
    ),
    TargetField("phone", "Telefon", False, ("telefon", "telefonnummer", "tel", "phone")),
    TargetField("description", "Beschreibung", False, ("beschreibung", "bemerkung", "hinweis", "notiz")),
)

FIELDS: dict[str, tuple[TargetField, ...]] = {"vehicles": VEHICLE_FIELDS, "stations": STATION_FIELDS}


def suggest_mapping(kind: str, headers: list[str]) -> dict[str, int | None]:
    """Exact synonym matches first, then 'header contains synonym' (longest synonym wins)."""
    normalised = [normalise_header(h) for h in headers]
    mapping: dict[str, int | None] = {f.key: None for f in FIELDS[kind]}
    used: set[int] = set()
    for f in FIELDS[kind]:
        for i, h in enumerate(normalised):
            if i not in used and (h == f.key.replace("_", " ") or h in f.synonyms):
                mapping[f.key] = i
                used.add(i)
                break
    candidates = []
    for f in FIELDS[kind]:
        if mapping[f.key] is not None:
            continue
        for syn in f.synonyms:
            for i, h in enumerate(normalised):
                if i not in used and len(syn) >= 3 and syn in h:
                    candidates.append((len(syn), f.key, i))
    for _, key, i in sorted(candidates, reverse=True):
        if mapping[key] is None and i not in used:
            mapping[key] = i
            used.add(i)
    return mapping


def _k(text: str) -> str:
    return " ".join(text.lower().split())


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


_RIC_TOKEN = re.compile(r"^(\d{1,10})\s*[-/ ]?\s*([A-Da-d])?$")


@dataclass(slots=True)
class RowResult:
    row: int
    action: str = "create"  # create | update | unchanged | error
    values: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    existing: Any = None

    def public(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "action": self.action,
            "values": self.values,
            "errors": self.errors,
            "warnings": self.warnings,
            "changes": self.changes,
        }


class _Lookups:
    """Everything a row may reference, loaded once per validation run."""

    async def load(self, s: Any, cc_id: uuid.UUID) -> None:
        self.orgs: dict[str, Organization] = {}
        for o in (await s.scalars(select(Organization))).all():
            self.orgs[_k(o.key)] = o
            self.orgs[_k(o.name)] = o
        self.types: dict[str, VehicleType] = {}
        for t in (await s.scalars(select(VehicleType))).all():
            self.types[_compact(t.code)] = t
            self.types.setdefault(_compact(t.name), t)
        self.stations: dict[str, Station] = {}
        for st in (await s.scalars(select(Station).where(Station.control_center_id == cc_id))).all():
            self.stations[_k(st.name)] = st
            if st.short_name:
                self.stations.setdefault(_k(st.short_name), st)
        self.radio_groups: dict[str, RadioGroup] = {}
        for g in (await s.scalars(select(RadioGroup).where(RadioGroup.control_center_id == cc_id))).all():
            self.radio_groups[_k(g.name)] = g
            if g.talkgroup:
                self.radio_groups.setdefault(_k(g.talkgroup), g)
        self.rics: dict[tuple[str, str], Ric] = {}
        self.ric_codes: dict[str, list[Ric]] = {}
        for r in (await s.scalars(select(Ric).where(Ric.control_center_id == cc_id))).all():
            self.rics[(r.code, r.sub_address)] = r
            self.ric_codes.setdefault(r.code, []).append(r)
        self.vehicles = {
            _k(v.call_sign): v
            for v in (await s.scalars(select(Vehicle).where(Vehicle.control_center_id == cc_id))).all()
        }
        self.existing_stations = {_k(st.name): st for st in self.stations.values()}

    def ric(self, token: str) -> Ric:
        m = _RIC_TOKEN.match(token.strip())
        if not m:
            raise ValueError(f"„{token.strip()}“ ist keine gültige RIC (Ziffern + optional A–D)")
        code, sub = m.group(1), (m.group(2) or "").upper()
        if sub:
            ric = self.rics.get((code, sub))
        else:
            candidates = self.ric_codes.get(code, [])
            if len(candidates) > 1:
                raise ValueError(f"RIC {code} ist mehrdeutig (Subadresse angeben)")
            ric = candidates[0] if candidates else None
        if ric is None:
            raise ValueError(f"RIC {code}{sub} ist nicht angelegt")
        return ric


def _cells(row: list[str], mapping: dict[str, int | None]) -> dict[str, str]:
    return {key: row[idx].strip() for key, idx in mapping.items() if idx is not None and idx < len(row)}


def _validate_vehicle_row(res: RowResult, v: dict[str, str], lk: _Lookups) -> None:
    p = res.payload
    call_sign = v.get("call_sign", "")
    if len(call_sign) < 2:
        res.errors.append("Funkrufname fehlt")
    else:
        p["call_sign"] = call_sign[:80]

    raw = v.get("vehicle_type", "")
    vt = lk.types.get(_compact(raw)) if raw else None
    if not raw:
        res.errors.append("Fahrzeugtyp fehlt")
    elif vt is None:
        res.errors.append(f"Fahrzeugtyp „{raw}“ unbekannt")
    elif not vt.is_active:
        res.errors.append(f"Fahrzeugtyp {vt.code} ist deaktiviert")
    else:
        p["vehicle_type_id"] = vt.id

    raw = v.get("station", "")
    station = lk.stations.get(_k(raw)) if raw else None
    if not raw:
        res.errors.append("Wache fehlt")
    elif station is None:
        res.errors.append(f"Wache „{raw}“ unbekannt (vorher anlegen oder importieren)")
    else:
        p["station_id"] = station.id

    raw = v.get("organization", "")
    if raw:
        org = lk.orgs.get(_k(raw))
        if org is None:
            res.errors.append(f"Organisation „{raw}“ unbekannt")
        else:
            p["organization_id"] = org.id
    org_id = p.get("organization_id") or (station.organization_id if station else None)
    org_obj = next((o for o in lk.orgs.values() if o.id == org_id), None)
    if org_obj is not None and not org_obj.alarmable:
        res.errors.append(f"Fahrzeuge der Organisation „{org_obj.name}“ werden nicht disponiert")

    if v.get("license_plate"):
        p["license_plate"] = " ".join(v["license_plate"].upper().split())[:20]
    if v.get("radio_group"):
        group = lk.radio_groups.get(_k(v["radio_group"]))
        if group is None:
            res.errors.append(f"Funkrufgruppe „{v['radio_group']}“ unbekannt")
        else:
            p["radio_group_id"] = group.id
    if v.get("rics"):
        rics = []
        for token in split_list(v["rics"]):
            try:
                rics.append(lk.ric(token))
            except ValueError as exc:
                res.errors.append(str(exc))
        p["rics"] = list(dict.fromkeys(rics))
    for key, lo, hi, label in (
        ("crew_size", 0, 99, "Besatzung"),
        ("sim_speed_kmh", 5, 300, "Geschwindigkeit"),
    ):
        if v.get(key):
            try:
                p[key] = parse_int(v[key], lo, hi)
            except ValueError as exc:
                res.errors.append(f"{label}: {exc}")
    if v.get("available"):
        try:
            p["available"] = parse_bool(v["available"])
        except ValueError as exc:
            res.errors.append(f"Verfügbar: {exc}")
    if v.get("description"):
        p["description"] = v["description"][:4000]


def _validate_station_row(res: RowResult, v: dict[str, str], lk: _Lookups) -> None:
    p = res.payload
    name = v.get("name", "")
    if len(name) < 2:
        res.errors.append("Name fehlt")
    else:
        p["name"] = name[:200]
    raw = v.get("organization", "")
    if not raw:
        res.errors.append("Organisation fehlt")
    else:
        org = lk.orgs.get(_k(raw))
        if org is None:
            res.errors.append(f"Organisation „{raw}“ unbekannt")
        else:
            p["organization_id"] = org.id
    coords = {}
    for key, lo, hi, label in (("latitude", -90, 90, "Breitengrad"), ("longitude", -180, 180, "Längengrad")):
        if v.get(key):
            try:
                value = parse_number(v[key])
                if not lo <= value <= hi:
                    raise ValueError(f"„{v[key]}“ außerhalb {lo}…{hi}")
                coords[key] = value
            except ValueError as exc:
                res.errors.append(f"{label}: {exc}")
    if len(coords) == 1:
        res.errors.append("Breiten- und Längengrad nur gemeinsam angeben")
    p.update(coords)
    if coords and not (47 <= coords.get("latitude", 50) <= 56 and 5 <= coords.get("longitude", 10) <= 16):
        res.warnings.append("Koordinaten liegen außerhalb Deutschlands – Breite/Länge vertauscht?")
    for key, limit in (("short_name", 48), ("address", 300), ("phone", 64), ("description", 4000)):
        if v.get(key):
            p[key] = v[key][:limit]


_COMPARE = {
    "vehicles": (
        "call_sign",
        "license_plate",
        "station_id",
        "vehicle_type_id",
        "organization_id",
        "radio_group_id",
        "crew_size",
        "sim_speed_kmh",
        "available",
        "description",
    ),
    "stations": (
        "name",
        "organization_id",
        "short_name",
        "address",
        "latitude",
        "longitude",
        "phone",
        "description",
    ),
}
_LABELS = {f.key: f.label for fields in FIELDS.values() for f in fields} | {
    "station_id": "Wache",
    "vehicle_type_id": "Fahrzeugtyp",
    "organization_id": "Organisation",
    "radio_group_id": "Funkrufgruppe",
}


async def validate_rows(
    s: Any, job: ImportJob, mapping: dict[str, int | None], options: dict[str, Any]
) -> list[RowResult]:
    lk = _Lookups()
    await lk.load(s, job.control_center_id)
    update_existing = bool(options.get("update_existing"))
    seen: dict[str, int] = {}
    results = []
    unique_key = "call_sign" if job.kind == "vehicles" else "name"
    existing_map = lk.vehicles if job.kind == "vehicles" else lk.existing_stations
    validate = _validate_vehicle_row if job.kind == "vehicles" else _validate_station_row

    for offset, row in enumerate(job.rows or []):
        res = RowResult(row=job.options.get("first_data_row", 2) + offset)
        values = _cells(row, mapping)
        if not any(values.values()):
            res.action = "skip"
            res.warnings.append("Leere Zeile")
            results.append(res)
            continue
        res.values = values
        validate(res, values, lk)

        key = _k(values.get(unique_key, ""))
        if key:
            if key in seen:
                res.errors.append(f"Doppelt in der Datei (bereits in Zeile {seen[key]})")
            else:
                seen[key] = res.row
            existing = existing_map.get(key)
            if existing is not None:
                if not update_existing:
                    res.errors.append("Existiert bereits – Option „Vorhandene aktualisieren“ wählen")
                else:
                    res.existing = existing
                    # The matching key keeps its existing spelling (match is case-insensitive).
                    res.payload.pop(unique_key, None)
                    res.changes = [
                        _LABELS.get(f, f)
                        for f in _COMPARE[job.kind]
                        if f in res.payload and res.payload[f] != getattr(existing, f)
                    ]
                    if "rics" in res.payload and {r.id for r in res.payload["rics"]} != {
                        r.id for r in existing.rics
                    }:
                        res.changes.append("RICs")
        if res.errors:
            res.action = "error"
        elif res.existing is not None:
            res.action = "update" if res.changes else "unchanged"
        results.append(res)
    return results


def summarise(results: list[RowResult]) -> dict[str, int]:
    summary = {"create": 0, "update": 0, "unchanged": 0, "error": 0, "skip": 0}
    for r in results:
        summary[r.action] += 1
    summary["total"] = len(results)
    return summary


class ImportService:
    def __init__(self, uow: UnitOfWork, visible: set[uuid.UUID] | None) -> None:
        self.uow = uow
        self.s = uow.session
        self.visible = visible

    def _check(self, cc_id: uuid.UUID) -> None:
        if self.visible is not None and cc_id not in self.visible:
            raise PermissionDeniedError("Kein Zugriff auf diese Leitstelle")

    async def get(self, job_id: uuid.UUID) -> ImportJob:
        job = await self.s.get(ImportJob, job_id)
        if job is None:
            raise NotFoundError("Import nicht gefunden")
        self._check(job.control_center_id)
        return job

    async def list(self, control_center_id: uuid.UUID | None) -> list[ImportJob]:
        stmt = select(ImportJob).order_by(ImportJob.created_at.desc()).limit(100)
        if control_center_id:
            self._check(control_center_id)
            stmt = stmt.where(ImportJob.control_center_id == control_center_id)
        elif self.visible is not None:
            stmt = stmt.where(ImportJob.control_center_id.in_(self.visible or {uuid.uuid4()}))
        return list((await self.s.scalars(stmt)).all())

    async def upload(
        self, cc_id: uuid.UUID, kind: str, file_name: str, content: bytes, sheet: str | None
    ) -> tuple[ImportJob, list[str]]:
        self._check(cc_id)
        if kind not in FIELDS:
            raise ValidationFailedError("Unbekannte Importart")
        table = read_table(file_name, content, sheet)
        job = ImportJob(
            control_center_id=cc_id,
            kind=kind,
            status="uploaded",
            file_name=file_name[:255],
            sheet_name=table.sheet_name,
            created_by=self.uow.actor.user_id,
            headers=table.headers,
            rows=table.rows,
            row_count=len(table.rows),
            column_mapping=suggest_mapping(kind, table.headers),
            options={"first_data_row": table.first_data_row, "update_existing": False},
        )
        self.s.add(job)
        await self.s.flush()
        self.uow.audit(
            "upload",
            "import_job",
            job.id,
            f"Importdatei „{job.file_name}“ hochgeladen ({job.row_count} Zeilen, {kind})",
            control_center_id=cc_id,
        )
        await self.uow.commit()
        return job, table.sheets

    def _mapping(self, job: ImportJob, mapping: dict[str, int | None]) -> dict[str, int | None]:
        fields = {f.key: f for f in FIELDS[job.kind]}
        unknown = set(mapping) - set(fields)
        if unknown:
            raise ValidationFailedError("Unbekannte Zielfelder", details={"fields": sorted(unknown)})
        cleaned: dict[str, int | None] = {key: None for key in fields}
        used: dict[int, str] = {}
        for key, idx in mapping.items():
            if idx is None:
                continue
            if not 0 <= idx < len(job.headers):
                raise ValidationFailedError(f"Spalte {idx + 1} existiert nicht", details={"field": key})
            if idx in used:
                raise ValidationFailedError(
                    f"Spalte „{job.headers[idx]}“ ist mehrfach zugeordnet ({fields[used[idx]].label}, "
                    f"{fields[key].label})"
                )
            used[idx] = key
            cleaned[key] = idx
        missing = [f.label for f in fields.values() if f.required and cleaned[f.key] is None]
        if missing:
            raise ValidationFailedError("Pflichtfelder nicht zugeordnet: " + ", ".join(missing))
        return cleaned

    def _ensure_open(self, job: ImportJob) -> None:
        if job.status in ("committed", "discarded"):
            raise ConflictError("Dieser Import ist bereits abgeschlossen")

    async def validate(
        self, job_id: uuid.UUID, mapping: dict[str, int | None], update_existing: bool, expected_version: int
    ) -> ImportJob:
        job = await self.get(job_id)
        check_version(job, expected_version, "Der Import")
        self._ensure_open(job)
        job.column_mapping = self._mapping(job, mapping)
        job.options = {**job.options, "update_existing": update_existing}
        results = await validate_rows(self.s, job, job.column_mapping, job.options)
        job.validation = [r.public() for r in results]
        job.summary = summarise(results)
        job.status = "validated"
        await self.uow.commit()
        return job

    async def commit(self, job_id: uuid.UUID, expected_version: int, skip_invalid: bool) -> ImportJob:
        job = await self.get(job_id)
        check_version(job, expected_version, "Der Import")
        self._ensure_open(job)
        if job.status != "validated" or job.column_mapping is None:
            raise ConflictError("Bitte zuerst Spaltenzuordnung prüfen lassen")
        # Re-validate: stations/types/RICs may have changed since the preview.
        results = await validate_rows(self.s, job, job.column_mapping, job.options)
        summary = summarise(results)
        if summary["error"] and not skip_invalid:
            job.validation = [r.public() for r in results]
            job.summary = summary
            await self.uow.commit()
            raise ValidationFailedError(
                f"{summary['error']} Zeile(n) fehlerhaft – korrigieren oder fehlerhafte Zeilen ausdrücklich "
                "überspringen",
                details={"summary": summary},
            )

        spec = VEHICLES if job.kind == "vehicles" else STATIONS
        snap = CrudService(spec, self.uow, None).snapshot
        now = datetime.now(UTC)
        for res in results:
            if res.action not in ("create", "update"):
                continue
            payload = dict(res.payload)
            rics = payload.pop("rics", None)
            if res.action == "create":
                obj = spec.model(id=uuid.uuid4(), control_center_id=job.control_center_id)
                if job.kind == "vehicles":
                    obj.import_job_id = job.id
                    obj.status_code = 2
                    obj.status_changed_at = now
                    if "organization_id" not in payload:
                        station = await self.s.get(Station, payload["station_id"])
                        payload["organization_id"] = station.organization_id
                before: dict[str, Any] = {}
            else:
                obj = res.existing
                before = snap(obj)
                obj.updated_at = now
            for key, value in payload.items():
                setattr(obj, key, value)
            if rics is not None:
                obj.rics = rics
            if res.action == "create":
                self.s.add(obj)
            verb = "angelegt" if res.action == "create" else "aktualisiert"
            self.uow.audit(
                res.action,
                spec.entity_type,
                obj.id,
                f"{spec.label} {spec.title(obj)} {verb} (Import „{job.file_name}“, Zeile {res.row})",
                changes=diff(before, snap(obj)),
                control_center_id=job.control_center_id,
            )

        job.status = "committed"
        job.committed_at = now
        job.validation = [r.public() for r in results]
        job.summary = summary
        job.rows = None  # data minimisation: raw file content is no longer needed
        self.uow.audit(
            "commit",
            "import_job",
            job.id,
            f"Import „{job.file_name}“ übernommen: {summary['create']} neu, {summary['update']} "
            f"aktualisiert, {summary['error']} übersprungen",
            control_center_id=job.control_center_id,
        )
        self.uow.emit(
            "master_data.changed",
            {"collection": spec.collection, "id": None, "action": "imported"},
            channels=[f"cc:{job.control_center_id}"],
        )
        try:
            await self.uow.commit()
        except IntegrityError as exc:
            await self.uow.rollback()
            raise ConflictError(
                "Import fehlgeschlagen – Daten wurden zwischenzeitlich geändert. Bitte erneut prüfen."
            ) from exc
        return job

    async def discard(self, job_id: uuid.UUID) -> None:
        job = await self.get(job_id)
        self._ensure_open(job)
        job.status = "discarded"
        job.rows = None
        self.uow.audit(
            "discard",
            "import_job",
            job.id,
            f"Import „{job.file_name}“ verworfen",
            control_center_id=job.control_center_id,
        )
        await self.uow.commit()
