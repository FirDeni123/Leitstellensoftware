"""Feuersoftware Connect – öffentliche Schnittstelle (REAL interface).

Creates an operation ("Einsatz") in Feuersoftware Connect for every confirmed alarm, which
alerts the users of the Connect site (app, EinsatzMonitor). Only allowed in real operation;
the core redirects it to the simulation otherwise, and it is created disabled.

Request format after the official documentation (docsv2.feuersoftware.com →
Connect → Schnittstellen → Öffentliche Connect API, read 21.11.2026):
* ``POST {base}/operation?updateStrategy=…`` with ``Authorization: Bearer <API-Token>``,
  body ``CreateOperationModel`` (Start, Status, Priority, AlarmEnabled, Keyword, Address,
  Position, Facts, Ric ≤ 5 chars, Number, Source, Properties …); success = 204 No Content;
  400 validation, 403 permission, 429 rate limit (5 operations/min, 25/h).
* ``GET {base}/operation`` lists operations – used as a read-only connection test.
The field names inside ``Position`` (Latitude/Longitude) and ``Properties`` (Key/Value) are not
spelled out on that page; they follow community clients of the same endpoint.

Never tested against the real service from this project – only against a simulated endpoint.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.plugins.base import AlarmMessage, DeliveryResult, PluginMeta

# Tests inject an httpx.MockTransport here; production uses the default transport.
TRANSPORT: httpx.AsyncBaseTransport | None = None

DEFAULT_BASE_URL = "https://connectapi.feuersoftware.com/interfaces/public"
PRIORITY = {1: 3, 2: 2, 3: 1}  # ILS 1 kritisch / 2 dringend / 3 normal → High / Medium / Low
STATUS_NEW, STATUS_UPDATE = 0, 1
STREET_RE = re.compile(r"^(?P<street>.*?\D)\s*(?P<number>\d+\s*[a-zA-Z]?(?:\s*[-/]\s*\d+\s*[a-zA-Z]?)?)$")
CITY_RE = re.compile(r"^(?P<zip>\d{5})\s+(?P<city>.+)$")


def split_address(address: str | None) -> dict[str, str] | None:
    """'Industriestraße 30, 21493 Demostadt' → Street/HouseNumber/ZipCode/City (best effort)."""
    if not address or not address.strip():
        return None
    parts = [p.strip() for p in address.split(",") if p.strip()]
    result: dict[str, str] = {}
    first = parts[0]
    m = STREET_RE.match(first)
    if m:
        result["Street"], result["HouseNumber"] = m["street"].strip(), m["number"].replace(" ", "")
    else:
        result["Street"] = first
    for part in parts[1:]:
        c = CITY_RE.match(part)
        if c:
            result["ZipCode"], result["City"] = c["zip"], c["city"]
        elif "City" not in result:
            result["City"] = part
        else:
            result.setdefault("District", part)
    return {k: v[:255] for k, v in result.items()}


def _text(value: str | None, limit: int = 255) -> str | None:
    return value.strip()[:limit] if value and value.strip() else None


class FeuersoftwareConnectPlugin:
    meta = PluginMeta(
        key="feuersoftware_connect",
        name="Feuersoftware Connect (real)",
        description="Legt bei jeder bestätigten Alarmierung einen Einsatz in Feuersoftware Connect an "
        "(öffentliche Connect-Schnittstelle) – die Einsatzkräfte des Standorts werden über die App "
        "alarmiert. Reale Schnittstelle – nur im Echtbetrieb aktiv. Rate-Limit von Feuersoftware: "
        "5 Einsätze pro Minute, 25 pro Stunde.",
        is_real=True,
        secret_label="API-Token des Connect-Standorts",  # noqa: S106 – a label, not a secret
        secret_required=True,
        config_schema={
            "type": "object",
            "properties": {
                "alarm_enabled": {
                    "type": "boolean",
                    "title": "Einsatzkräfte alarmieren (AlarmEnabled)",
                    "description": "Aus = Einsatz nur anlegen, ohne Alarm an die Handys (erster Test)",
                    "default": True,
                },
                "update_strategy": {
                    "type": "string",
                    "title": "Abgleich bestehender Einsätze",
                    "enum": ["ByNumber", "None"],
                    "default": "ByNumber",
                    "description": "ByNumber: Nachalarmierungen und Wiederholungen aktualisieren den Einsatz "
                    "mit derselben Einsatznummer statt einen neuen anzulegen",
                },
                "ric": {
                    "type": "string",
                    "title": "RIC/Schleife für Connect (max. 5 Zeichen, optional)",
                    "pattern": "^[0-9A-Za-z]{1,5}$",
                },
                "keyword_format": {
                    "type": "string",
                    "title": "Stichwort",
                    "enum": ["code_name", "code"],
                    "default": "code_name",
                },
                "timezone": {
                    "type": "string",
                    "title": "Zeitzone der Einsatzzeit",
                    "default": "Europe/Berlin",
                    "pattern": "^[A-Za-z_]+(/[A-Za-z_]+)*$",
                    "maxLength": 64,
                },
                "base_url": {
                    "type": "string",
                    "title": "Basis-URL",
                    "format": "uri",
                    "pattern": "^https://",
                    "default": DEFAULT_BASE_URL,
                    "maxLength": 200,
                },
                "timeout_seconds": {
                    "type": "integer",
                    "title": "Zeitlimit (s)",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 10,
                },
            },
            "additionalProperties": False,
        },
    )

    # ------------------------------------------------------------------------- request
    @staticmethod
    def _base(config: dict[str, Any]) -> str:
        return str(config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")

    @staticmethod
    def _headers(secret: str | None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {secret or ''}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "ILS-Sim-Feuersoftware/1",
        }

    @staticmethod
    def _zone(config: dict[str, Any]) -> ZoneInfo:
        try:
            return ZoneInfo(str(config.get("timezone") or "Europe/Berlin"))
        except (KeyError, ValueError):
            return ZoneInfo("Europe/Berlin")

    def build_body(self, config: dict[str, Any], message: AlarmMessage) -> dict[str, Any]:
        start: datetime = message.created_at.astimezone(self._zone(config))
        keyword = message.keyword or message.keyword_name or "Einsatz"
        if (
            config.get("keyword_format", "code_name") == "code_name"
            and message.keyword
            and message.keyword_name
        ):
            keyword = f"{message.keyword} – {message.keyword_name}"
        facts = "\n".join(
            p
            for p in (
                message.description,
                f"Ortshinweis: {message.location_note}" if message.location_note else None,
            )
            if p
        )
        properties = [
            {"Key": key, "Value": value}
            for key, value in (
                ("Alarmierte Fahrzeuge", ", ".join(message.vehicles)),
                ("Alarmierte Wachen", ", ".join(message.stations)),
                ("RIC", ", ".join(message.rics)),
                ("Alarmstufe", str(message.stage) if message.stage else ""),
                ("Leitstelle", message.control_center),
            )
            if value
        ]
        body: dict[str, Any] = {
            "Start": start.isoformat(timespec="seconds"),
            "Status": STATUS_UPDATE if message.kind != "initial" else STATUS_NEW,
            "Priority": PRIORITY.get(message.priority, 0),
            "AlarmEnabled": bool(config.get("alarm_enabled", True)),
            "Keyword": keyword[:255],
            "Number": message.incident_number[:255],
            "Source": f"ILS-Sim {message.control_center}"[:255],
            "Properties": properties,
        }
        if (address := split_address(message.address)) is not None:
            body["Address"] = address
        if message.latitude is not None and message.longitude is not None:
            body["Position"] = {"Latitude": message.latitude, "Longitude": message.longitude}
        if facts:
            body["Facts"] = facts[:4000]
        if config.get("ric"):
            body["Ric"] = str(config["ric"])[:5]
        return body

    @staticmethod
    def _result(response: httpx.Response, success: str) -> DeliveryResult:
        code = response.status_code
        if 200 <= code < 300:
            return DeliveryResult(True, success)
        reason = {
            400: "Anfrage abgelehnt (Validierung)",
            401: "API-Token ungültig",
            403: "keine Berechtigung (Token auf Standortebene nötig)",
            404: "Adresse nicht gefunden – Basis-URL prüfen",
            429: "Rate-Limit von Feuersoftware erreicht",
        }.get(code, "Fehler bei Feuersoftware")
        detail = response.text.strip().replace("\n", " ")[:200]
        # 4xx except 408/429 will fail the same way again – no retries (they cost rate limit)
        retryable = code >= 500 or code in (408, 429)
        return DeliveryResult(
            False, f"HTTP {code}: {reason}" + (f" – {detail}" if detail else ""), retryable=retryable
        )

    async def _request(
        self, config: dict[str, Any], method: str, url: str, **kwargs: Any
    ) -> httpx.Response | str:
        timeout = float(config.get("timeout_seconds", 10))
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=TRANSPORT) as client:
                return await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            return f"Verbindungsfehler: {type(exc).__name__}"

    # ----------------------------------------------------------------------- interface
    async def test(self, config: dict[str, Any], secret: str | None) -> DeliveryResult:
        """Read-only: lists the latest operation – creates nothing, alarms nobody."""
        response = await self._request(
            config,
            "GET",
            f"{self._base(config)}/operation",
            params={"onlyLatest": "true", "$top": "1"},
            headers=self._headers(secret),
        )
        if isinstance(response, str):
            return DeliveryResult(False, response)
        result = self._result(response, "Verbindung und API-Token in Ordnung (nur gelesen)")
        if result.ok:
            try:
                latest = response.json()
                site = latest[0].get("SiteName") if isinstance(latest, list) and latest else None
            except ValueError:
                site = None
            if site:
                return DeliveryResult(True, f"Verbindung in Ordnung – Standort „{site}“ (nur gelesen)")
        return result

    async def send_alarm(
        self, config: dict[str, Any], secret: str | None, message: AlarmMessage
    ) -> DeliveryResult:
        strategy = config.get("update_strategy", "ByNumber")
        response = await self._request(
            config,
            "POST",
            f"{self._base(config)}/operation",
            params={"updateStrategy": strategy},
            json=self.build_body(config, message),
            headers=self._headers(secret),
        )
        if isinstance(response, str):
            return DeliveryResult(False, response)
        verb = "angelegt/aktualisiert" if strategy == "ByNumber" else "angelegt"
        alarmed = "mit Alarm" if config.get("alarm_enabled", True) else "ohne Alarm"
        return self._result(response, f"Einsatz {message.incident_number} in Connect {verb} ({alarmed})")
