"""Administrable rules of the proposal (stored per control centre as JSONB, validated here).

All weights are expressed in seconds of travel time, so every score is readable as a
"weighted travel time" – lower is better.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_SUBSTITUTES: dict[str, list[str]] = {
    "HLF20": ["LF20", "LF10"],
    "LF20": ["HLF20", "LF10"],
    "LF10": ["LF20", "HLF20", "TSF-W"],
    "TSF-W": ["LF10"],
    "TLF3000": ["LF20"],
    "RTW": ["ITW"],
    "KTW": ["RTW"],
}


class ProposalSettingsData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detour_factor: float = Field(default=1.3, ge=1.0, le=3.0, description="Umwegfaktor auf die Luftlinie")
    emergency_speed_factor: float = Field(
        default=1.15, ge=0.5, le=2.0, description="Faktor für Sonderrechtsfahrten (auf Geschwindigkeit)"
    )
    turnout_seconds_on_station: int = Field(
        default=90, ge=0, le=900, description="Ausrückzeit bei Status 2 (auf der Wache)"
    )
    substitute_penalty_seconds: int = Field(default=180, ge=0, le=3600, description="Malus für Ersatztypen")
    preferred_station_bonus_seconds: int = Field(
        default=60, ge=0, le=1800, description="Bonus für Wachen, die in der AAO eingetragen sind"
    )
    max_travel_minutes: int = Field(
        default=45, ge=5, le=240, description="Fahrzeuge darüber nicht vorschlagen"
    )
    alternatives: int = Field(default=2, ge=0, le=5, description="Alternativen je Bedarf")
    candidates_per_demand: int = Field(
        default=3, ge=1, le=10, description="Vorfilter je Bedarf (n × Anzahl, nach Luftlinie) für das Routing"
    )
    use_routing: bool = Field(default=True, description="Routing-Dienst (OSRM) nutzen, falls eingerichtet")
    substitutes: dict[str, list[str]] = Field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_SUBSTITUTES.items()},
        description="Fahrzeugtyp-Kürzel → zulässige Ersatztypen (Reihenfolge = Vorrang)",
    )

    @field_validator("substitutes")
    @classmethod
    def _norm_substitutes(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if len(value) > 200:
            raise ValueError("zu viele Ersatzregeln")
        result: dict[str, list[str]] = {}
        for code, subs in value.items():
            key = code.strip().upper()
            clean = [s.strip().upper() for s in subs if s.strip() and s.strip().upper() != key]
            if len(clean) > 20:
                raise ValueError(f"zu viele Ersatztypen für {key}")
            if key:
                result[key] = list(dict.fromkeys(clean))
        return result
