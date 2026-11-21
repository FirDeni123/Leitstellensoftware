"""Automatic evaluation of a training session.

Two kinds of checklist items:
* **action** items are checked deterministically against what the trainee actually did in the
  system (incident created from the call, keyword, location, alarm) – no AI involved;
* **question** items (asked for the location, the callback number, …) are judged from the
  transcript – by Claude when the AI is enabled, otherwise by keyword hints (rule-based).

Score = share of fulfilled *required* items (0–100). Metrics are measured times and counts.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

from app.core.geo import haversine_m

LOCATION_TOLERANCE_M = 300.0

# Used when a scenario defines no question items of its own.
DEFAULT_QUESTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "ask_location",
        "label": "Einsatzort (Ort, Straße, Hausnummer) erfragt",
        "required": True,
        "hints": ["wo ", "wo?", "adresse", "straße", "hausnummer", "ort"],
    },
    {
        "key": "ask_what",
        "label": "Nach dem Ereignis gefragt (Was ist passiert?)",
        "required": True,
        "hints": ["was ist", "passiert", "was genau", "was sehen"],
    },
    {
        "key": "ask_persons",
        "label": "Nach Betroffenen/Verletzten gefragt",
        "required": True,
        "hints": ["verletzt", "personen", "wie viele", "jemand", "betroffen"],
    },
    {
        "key": "ask_callback",
        "label": "Rückrufnummer erfragt",
        "required": True,
        "hints": ["nummer", "rückruf", "erreichbar"],
    },
    {
        "key": "ask_name",
        "label": "Name des Anrufers erfragt",
        "required": False,
        "hints": ["name", "wer spricht", "heißen sie"],
    },
    {
        "key": "give_advice",
        "label": "Verhaltenshinweise gegeben",
        "required": False,
        "hints": [
            "bleiben sie",
            "verlassen sie",
            "gehen sie",
            "schließen sie",
            "legen sie",
            "nicht auflegen",
        ],
    },
)


def question_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items = [i for i in snapshot.get("checklist") or [] if i.get("key") and i.get("label")]
    return items or [dict(i) for i in DEFAULT_QUESTIONS]


def _norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = text.replace("ß", "ss").replace("str.", "strasse").replace("straße", "strasse")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _street(address: str | None) -> str:
    """'Hauptstraße 12, 21493 Schwarzenbek' → 'hauptstrasse 12'."""
    first = (address or "").split(",")[0]
    return _norm(first)


def location_matches(
    facts: dict[str, Any], address: str | None, lat: float | None, lon: float | None
) -> tuple[bool, str]:
    truth_lat, truth_lon = facts.get("lat"), facts.get("lon")
    if truth_lat is not None and truth_lon is not None and lat is not None and lon is not None:
        distance = haversine_m(lat, lon, float(truth_lat), float(truth_lon))
        if distance <= LOCATION_TOLERANCE_M:
            return True, f"Koordinate {round(distance)} m vom tatsächlichen Einsatzort"
        street_ok = bool(_street(facts.get("address"))) and _street(facts.get("address")) in _norm(address)
        if street_ok:
            return True, f"Adresse stimmt (Koordinate {round(distance)} m entfernt)"
        return False, f"Koordinate {round(distance)} m vom tatsächlichen Einsatzort entfernt"
    truth = _street(facts.get("address"))
    if truth and truth in _norm(address):
        return True, "Adresse stimmt"
    return False, "Einsatzort weicht ab" if address else "kein Einsatzort erfasst"


def action_items(
    snapshot: dict[str, Any],
    incident: Any | None,
    alarm_count: int,
) -> list[dict[str, Any]]:
    facts = snapshot.get("facts") or {}
    expected_keyword = snapshot.get("keyword") or {}
    items: list[dict[str, Any]] = []

    items.append(
        {
            "key": "incident_created",
            "label": "Einsatz aus dem Notruf angelegt",
            "kind": "action",
            "required": True,
            "fulfilled": incident is not None,
            "evidence": f"Einsatz {incident.number}"
            if incident is not None
            else "kein Einsatz mit dem Notruf verknüpft",
        }
    )
    if expected_keyword.get("id"):
        actual = getattr(incident, "keyword", None) if incident is not None else None
        ok = incident is not None and str(incident.keyword_id) == expected_keyword["id"]
        items.append(
            {
                "key": "keyword_correct",
                "label": f"Stichwort {expected_keyword.get('code', '')} gewählt".replace("  ", " "),
                "kind": "action",
                "required": True,
                "fulfilled": ok,
                "evidence": (f"gewählt: {actual.code}" if actual is not None else "kein Stichwort gewählt")
                + ("" if ok else f" (erwartet: {expected_keyword.get('code', '?')})"),
            }
        )
    if facts.get("address") or facts.get("lat") is not None:
        ok, evidence = (
            location_matches(facts, incident.address, incident.latitude, incident.longitude)
            if incident is not None
            else (False, "kein Einsatz")
        )
        items.append(
            {
                "key": "location_correct",
                "label": "Einsatzort korrekt erfasst",
                "kind": "action",
                "required": True,
                "fulfilled": ok,
                "evidence": evidence,
            }
        )
    items.append(
        {
            "key": "alarm_triggered",
            "label": "Alarmierung ausgelöst (durch den Disponenten)",
            "kind": "action",
            "required": bool(snapshot.get("alarm_required", True)),
            "fulfilled": alarm_count > 0,
            "evidence": f"{alarm_count} Alarmierung(en)" if alarm_count else "keine Alarmierung",
        }
    )
    return items


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds(), 1)


def metrics(
    session: Any,
    incident_created_at: datetime | None,
    first_alarm_at: datetime | None,
    messages: list[Any],
) -> dict[str, Any]:
    replies = [m.latency_ms for m in messages if m.role == "caller" and m.latency_ms is not None]
    return {
        "answer_seconds": _seconds(session.created_at, session.answered_at),
        "incident_seconds": _seconds(session.answered_at, incident_created_at),
        "alarm_seconds": _seconds(session.answered_at, first_alarm_at),
        "conversation_seconds": _seconds(session.answered_at, session.ended_at),
        "dispatcher_turns": sum(1 for m in messages if m.role == "dispatcher"),
        "caller_turns": sum(1 for m in messages if m.role == "caller"),
        "voice_turns": sum(1 for m in messages if m.role == "dispatcher" and m.source == "voice"),
        "reply_latency_avg_ms": round(sum(replies) / len(replies)) if replies else None,
        "reply_latency_max_ms": max(replies) if replies else None,
        "rule_replies": sum(1 for m in messages if m.role == "caller" and m.source == "rules"),
    }


def score(items: list[dict[str, Any]]) -> int:
    required = [i for i in items if i.get("required")]
    if not required:
        return 100
    return round(100 * sum(1 for i in required if i.get("fulfilled")) / len(required))
