"""Reading Excel/CSV files and parsing cell values (German conventions).

Pure functions without database access – easy to test and reuse (e.g. for an
OpenStreetMap import that produces the same row structure).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from zipfile import BadZipFile

from app.core.errors import ValidationFailedError

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 60


@dataclass(slots=True)
class ParsedTable:
    headers: list[str]
    rows: list[list[str]]
    first_data_row: int  # 1-based row number of the first data row in the source file
    sheet_name: str | None
    sheets: list[str]


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "ja" if value else "nein"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value).strip()


def _unique_headers(raw: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for i, h in enumerate(raw):
        name = h.strip() or f"Spalte {i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        result.append(name)
    return result


def _filled_width(row: list[str]) -> int:
    for i in range(len(row) - 1, -1, -1):
        if row[i]:
            return i + 1
    return 0


def _table(rows: list[list[str]], sheet: str | None, sheets: list[str]) -> ParsedTable:
    # header = first non-empty row; trailing empty columns are dropped
    start = next((i for i, r in enumerate(rows) if any(c for c in r)), None)
    if start is None:
        raise ValidationFailedError("Die Datei enthält keine Daten")
    header = rows[start]
    width = max(_filled_width(r) for r in rows[start:])
    if width == 0:
        raise ValidationFailedError("Keine Spalten gefunden")
    if width > MAX_COLUMNS:
        raise ValidationFailedError(f"Zu viele Spalten (maximal {MAX_COLUMNS})")
    headers = _unique_headers([(header[i] if i < len(header) else "") for i in range(width)])
    data = []
    for r in rows[start + 1 :]:
        padded = [(r[i] if i < len(r) else "") for i in range(width)]
        data.append(padded)
    while data and not any(data[-1]):
        data.pop()
    if len(data) > MAX_ROWS:
        raise ValidationFailedError(f"Zu viele Zeilen ({len(data)}); maximal {MAX_ROWS} pro Import")
    if not data:
        raise ValidationFailedError("Die Datei enthält nur eine Kopfzeile")
    return ParsedTable(headers, data, start + 2, sheet, sheets)


def read_xlsx(content: bytes, sheet: str | None = None) -> ParsedTable:
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, BadZipFile, KeyError, OSError, ValueError) as exc:
        raise ValidationFailedError(
            "Excel-Datei konnte nicht gelesen werden (beschädigt oder kein .xlsx)"
        ) from exc
    try:
        sheets = list(wb.sheetnames)
        name = sheet or sheets[0]
        if name not in sheets:
            raise ValidationFailedError(f"Tabellenblatt „{name}“ nicht gefunden", details={"sheets": sheets})
        rows: list[list[str]] = []
        for i, row in enumerate(wb[name].iter_rows(values_only=True)):
            if i > MAX_ROWS + 50:
                raise ValidationFailedError(f"Zu viele Zeilen; maximal {MAX_ROWS} pro Import")
            rows.append([_cell(v) for v in row[: MAX_COLUMNS + 1]])
        return _table(rows, name, sheets)
    finally:
        wb.close()


def read_csv(content: bytes) -> ParsedTable:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 decodes nearly everything
        raise ValidationFailedError("Zeichenkodierung der CSV-Datei nicht erkannt")
    sample = text[:8192]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t").delimiter
    except csv.Error:
        delimiter = max(";,\t", key=sample.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = []
    for i, row in enumerate(reader):
        if i > MAX_ROWS + 50:
            raise ValidationFailedError(f"Zu viele Zeilen; maximal {MAX_ROWS} pro Import")
        rows.append([c.strip() for c in row[: MAX_COLUMNS + 1]])
    return _table(rows, None, [])


def read_table(file_name: str, content: bytes, sheet: str | None = None) -> ParsedTable:
    if len(content) > MAX_FILE_BYTES:
        raise ValidationFailedError(f"Datei zu groß (maximal {MAX_FILE_BYTES // (1024 * 1024)} MB)")
    lower = file_name.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        return read_xlsx(content, sheet)
    if lower.endswith((".csv", ".txt")):
        return read_csv(content)
    if lower.endswith(".xls"):
        raise ValidationFailedError("Altes Excel-Format (.xls) – bitte als .xlsx oder .csv speichern")
    raise ValidationFailedError("Dateiformat nicht unterstützt – erlaubt sind .xlsx und .csv")


# ------------------------------------------------------------------------------ cell parsing
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def normalise_header(text: str) -> str:
    t = text.lower().translate(_UMLAUTS)
    t = re.sub(r"[^a-z0-9/ ]+", " ", t)
    return " ".join(t.split())


TRUE_WORDS = {
    "ja",
    "j",
    "x",
    "1",
    "true",
    "wahr",
    "yes",
    "y",
    "verfuegbar",
    "verfügbar",
    "aktiv",
    "in dienst",
}
FALSE_WORDS = {
    "nein",
    "n",
    "0",
    "false",
    "falsch",
    "no",
    "nicht verfuegbar",
    "nicht verfügbar",
    "inaktiv",
    "ausser dienst",
    "außer dienst",
}


def parse_bool(text: str) -> bool | None:
    t = text.strip().lower()
    if t in TRUE_WORDS:
        return True
    if t in FALSE_WORDS:
        return False
    raise ValueError(f"„{text}“ ist kein Ja/Nein-Wert")


def parse_number(text: str) -> float:
    """German or English notation: '53,5036', '53.5036', '1.234,5', '60 km/h'."""
    t = text.strip().lower().replace("km/h", "").replace("kmh", "").strip()
    t = t.replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError as exc:
        raise ValueError(f"„{text}“ ist keine Zahl") from exc


def parse_int(text: str, lo: int, hi: int) -> int:
    value = parse_number(text)
    if not value.is_integer() or not lo <= value <= hi:
        raise ValueError(f"„{text}“: ganze Zahl zwischen {lo} und {hi} erwartet")
    return int(value)


def split_list(text: str) -> list[str]:
    return [p for p in re.split(r"[,;\n|]+", text) if p.strip()]
