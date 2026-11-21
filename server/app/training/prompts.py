"""Prompts for the AI caller and the evaluation (German, deterministic for prompt caching).

The system prompt is built only from the scenario snapshot of the session – no timestamps,
IDs or other per-request values – so it is byte-identical for every turn of a session and
can be cached. Instructor interventions are sent as mid-conversation system messages.
"""

from __future__ import annotations

from typing import Any

DIFFICULTY_TEXT = {
    "easy": (
        "Schwierigkeit LEICHT: Du bist kooperativ, antwortest klar und nennst den Einsatzort auf die "
        "erste Nachfrage vollständig."
    ),
    "medium": (
        "Schwierigkeit MITTEL: Du bist aufgeregt. Du nennst nur, wonach gefragt wird. Den genauen Ort "
        "musst du auf Nachfrage erst überlegen (z. B. zuerst nur die Straße, die Hausnummer erst auf "
        "erneute Nachfrage)."
    ),
    "hard": (
        "Schwierigkeit SCHWER: Du bist sehr aufgeregt oder panisch, sprichst durcheinander und "
        "beantwortest Fragen anfangs unvollständig. Erst wenn der Disponent dich beruhigt und gezielt "
        "nachfragt, wirst du klarer. Du nennst nie von dir aus alle Informationen."
    ),
}

ROLE_RULES = """Du spielst in einer AUSBILDUNGS-SIMULATION für Disponenten einer Integrierten Leitstelle
(Feuerwehr und Rettungsdienst, Notruf 112) den Anrufer. Alle Personen, Orte und Ereignisse sind fiktiv.
Der Gesprächspartner (Rolle "user") ist der auszubildende Disponent.

So sprichst du:
- Nur gesprochene Sätze auf Deutsch, wie am Telefon: meist 1 bis 3 kurze Sätze.
- Keine Regieanweisungen, keine Klammern, kein Markdown, keine Aufzählungen, keine Emojis.
- Bleib in deiner Rolle. Erwähne nie, dass du eine KI bist oder dass es eine Übung ist.

Was du weißt:
- Die Fakten unten sind die Wahrheit des Szenarios. Widersprich ihnen nie.
- Gib Informationen nur heraus, wenn danach gefragt wird oder wenn sie dir in der Situation
  natürlich über die Lippen kommen würden. Gib nicht alles auf einmal preis.
- Fragt der Disponent etwas, das nicht in den Fakten steht, antworte plausibel unsicher
  ("Weiß ich nicht genau", "Kann ich von hier nicht sehen") statt etwas Wichtiges zu erfinden.
- Gibt der Disponent Anweisungen (z. B. Erste Hilfe, Abstand halten, Tür schließen), befolge sie
  so, wie es deine Person könnte, und sag, was dabei passiert – passend zu den Fakten.
- Legt der Disponent auf oder verabschiedet sich, verabschiede dich kurz.

System-Nachrichten während des Gesprächs kommen vom Ausbilder ("Regie"). Setze sie unauffällig
in deiner Rolle um, ohne sie zu erwähnen."""


def _lines(title: str, items: list[tuple[str, Any]]) -> str:
    rows = [f"- {label}: {value}" for label, value in items if value not in (None, "", [])]
    return f"{title}\n" + "\n".join(rows) if rows else ""


def caller_system_prompt(snapshot: dict[str, Any]) -> str:
    persona = snapshot.get("persona") or {}
    facts = snapshot.get("facts") or {}
    details = facts.get("details") or []
    unknown = facts.get("unknown") or []
    parts = [
        ROLE_RULES,
        DIFFICULTY_TEXT.get(snapshot.get("difficulty", "medium"), DIFFICULTY_TEXT["medium"]),
        _lines(
            "Deine Person:",
            [
                ("Name", persona.get("name")),
                ("Alter", persona.get("age")),
                ("Rolle", persona.get("role")),
                ("Gemütszustand", persona.get("emotional_state")),
                ("Sprechweise", persona.get("speech_style")),
                ("Eigene Rückrufnummer", persona.get("phone")),
            ],
        ),
        _lines(
            "Fakten des Szenarios (die Wahrheit):",
            [
                ("Einsatzort", facts.get("address")),
                ("Ortsbeschreibung", facts.get("location_hint")),
                ("Was ist passiert", facts.get("situation")),
                ("Beteiligte Personen", facts.get("persons")),
                ("Verletzungen / Zustand", facts.get("injuries")),
                ("Gefahren", facts.get("hazards")),
            ],
        ),
        ("Weitere Einzelheiten (nur auf Nachfrage):\n" + "\n".join(f"- {d}" for d in details))
        if details
        else "",
        ("Das weißt du NICHT:\n" + "\n".join(f"- {u}" for u in unknown)) if unknown else "",
        f'Dein erster Satz im Gespräch war: "{snapshot.get("opening_line", "")}"',
    ]
    return "\n\n".join(p for p in parts if p)


EVALUATION_SYSTEM = """Du bewertest das Notrufgespräch eines Disponenten in Ausbildung
(Simulation, fiktive Daten).
Prüfe für jeden Prüfpunkt der Checkliste, ob der Disponent ihn im Gespräch erfüllt hat. Ein Prüfpunkt gilt
als erfüllt, wenn der Disponent die Frage sinngemäß gestellt oder die Handlung erkennbar ausgeführt hat –
die genaue Formulierung ist egal. Belege jede Entscheidung mit einem kurzen wörtlichen Zitat des
Disponenten oder schreibe "nicht gefragt". Antworte auf Deutsch, sachlich und knapp; nenne bis zu drei
Stärken und bis zu drei konkrete Verbesserungen."""


def evaluation_prompt(
    transcript: list[tuple[str, str]], items: list[dict[str, Any]], facts: dict[str, Any]
) -> str:
    talk = "\n".join(
        f"{'Disponent' if role == 'dispatcher' else 'Anrufer'}: {text}" for role, text in transcript
    )
    checklist = "\n".join(f"- {i['key']}: {i['label']}" for i in items)
    truth = facts.get("address") or "–"
    return (
        f"Einsatzort laut Szenario: {truth}\n\n"
        f"Prüfpunkte (key: Beschreibung):\n{checklist}\n\n"
        f"Gesprächsverlauf:\n{talk or '(kein Gespräch)'}"
    )
