"""Phase 5: pure tests of the proposal engine (no database)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.proposal.engine import Demand, InIncident, Unit, allocate, fmt_duration
from app.proposal.settings import ProposalSettingsData
from app.proposal.travel import Travel, estimate

HLF, LF, DLK, RTW = (uuid.uuid4() for _ in range(4))
CODES = {HLF: "HLF20", LF: "LF20", DLK: "DLK23", RTW: "RTW"}
ST_A, ST_B = uuid.uuid4(), uuid.uuid4()


def unit(name: str, type_id: uuid.UUID, status: int = 2, station: uuid.UUID = ST_A) -> Unit:
    return Unit(
        uuid.uuid4(),
        name,
        type_id,
        CODES[type_id],
        station,
        "Wache A" if station == ST_A else "Wache B",
        status,
    )


def demand(key: str, type_id: uuid.UUID, count: int = 1) -> Demand:
    return Demand(key, count, "AAO B2, Stufe 1", 1, type_id, CODES[type_id])


def t(seconds: float) -> Travel:
    return Travel(seconds, seconds * 12, "estimate", seconds * 10)


SETTINGS = ProposalSettingsData()


def test_nearest_exact_type_wins_and_reasons_are_readable():
    near, far = unit("HLF nah", HLF), unit("HLF fern", HLF)
    result = allocate([demand("a", HLF)], [], [near, far], {near.id: t(300), far.id: t(900)}, SETTINGS)
    assert [p.unit.call_sign for p in result.picks] == ["HLF nah"]
    reasons = result.picks[0].reasons
    assert reasons[0] == "AAO B2, Stufe 1: HLF20 (Bedarf 1/1)"
    assert "Status 2 auf Wache (+1:30 min Ausrücken)" in reasons
    assert any(
        r.startswith("Fahrzeit ca. 5:00 min ab Wache (Schätzung: 3.0 km Luftlinie × 1.3)") for r in reasons
    )
    assert [o.unit.call_sign for o in result.alternatives["a"]] == ["HLF fern"]
    assert result.shortfalls == []


def test_substitute_only_with_penalty_and_exact_preferred_within_penalty():
    hlf, lf = unit("HLF", HLF), unit("LF", LF)
    # LF is 2 min closer, but the substitute malus is 3 min -> HLF wins
    result = allocate([demand("a", HLF)], [], [hlf, lf], {hlf.id: t(600), lf.id: t(480)}, SETTINGS)
    assert result.picks[0].unit.call_sign == "HLF"
    # LF 5 min closer -> LF wins as substitute and says so
    result = allocate([demand("a", HLF)], [], [hlf, lf], {hlf.id: t(800), lf.id: t(480)}, SETTINGS)
    pick = result.picks[0]
    assert pick.unit.call_sign == "LF" and pick.match == "substitute"
    assert pick.reasons[0].startswith(
        "AAO B2, Stufe 1: Ersatz für HLF20 (Bedarf 1/1) – LF20, +3:00 min Malus"
    )
    # without a substitute rule the LF is never proposed for an HLF demand
    strict = ProposalSettingsData(substitutes={})
    result = allocate([demand("a", HLF)], [], [lf], {lf.id: t(60)}, strict)
    assert result.picks == [] and result.shortfalls[0].message == "HLF20: 1 von 1 nicht verfügbar (Stufe 1)"


def test_balancing_keeps_all_demands_covered():
    """Greedy alone would give the LF to the HLF demand (best single score) and leave the LF
    demand empty; balancing moves the far HLF in and the LF to its own demand."""
    lf_near, hlf_far = unit("LF nah", LF), unit("HLF fern", HLF)
    # an LF may replace an HLF (not vice versa); no malus, so greedy prefers the near LF for the HLF
    settings = ProposalSettingsData(substitute_penalty_seconds=0, substitutes={"HLF20": ["LF20"]})
    demands = [demand("hlf", HLF), demand("lf", LF)]
    travel = {lf_near.id: t(100), hlf_far.id: t(1200)}
    result = allocate(demands, [], [lf_near, hlf_far], travel, settings)
    by_demand = {p.demand.key: p.unit.call_sign for p in result.picks}
    assert by_demand == {"hlf": "HLF fern", "lf": "LF nah"}
    assert result.shortfalls == []


def test_equal_scores_prefer_matching_type_over_crosswise_substitutes():
    lf, hlf = unit("LF", LF), unit("HLF", HLF)
    settings = ProposalSettingsData(substitute_penalty_seconds=0)  # HLF↔LF mutually allowed by default
    result = allocate(
        [demand("hlf", HLF), demand("lf", LF)], [], [lf, hlf], {lf.id: t(300), hlf.id: t(300)}, settings
    )
    assert {p.demand.key: p.match for p in result.picks} == {"hlf": "exact", "lf": "exact"}


def test_units_in_incident_cover_demand_first():
    assigned, alarmed, free = unit("HLF zugeordnet", HLF), unit("DLK alarmiert", DLK), unit("HLF frei", HLF)
    demands = [demand("hlf", HLF, count=2), demand("dlk", DLK)]
    result = allocate(
        demands,
        [InIncident(assigned, alarmed=False), InIncident(alarmed, alarmed=True)],
        [free],
        {free.id: t(200)},
        SETTINGS,
    )
    picks = {(p.unit.call_sign, p.in_incident, p.alarmed, p.slot) for p in result.picks}
    assert picks == {
        ("HLF zugeordnet", True, False, 1),
        ("HLF frei", False, False, 2),
        ("DLK alarmiert", True, True, 1),
    }
    assert "bereits alarmiert" in next(p for p in result.picks if p.alarmed).reasons


def test_turnout_time_and_preferred_station_change_the_ranking():
    on_station = unit("HLF Wache", HLF, status=2, station=ST_A)
    on_radio = unit("HLF Funk", HLF, status=1, station=ST_B)
    travel = {on_station.id: t(300), on_radio.id: t(360)}
    # status 2 adds 90 s turnout -> the vehicle free via radio (60 s farther) wins
    assert (
        allocate([demand("a", HLF)], [], [on_station, on_radio], travel, SETTINGS).picks[0].unit.call_sign
        == "HLF Funk"
    )
    # station A is preferred in the AAO (-60 s) -> 300+90-60 = 330 < 360
    result = allocate([demand("a", HLF)], [], [on_station, on_radio], travel, SETTINGS, {ST_A})
    assert result.picks[0].unit.call_sign == "HLF Wache"
    assert any("laut AAO bevorzugt" in r for r in result.picks[0].reasons)


def test_too_far_and_unknown_positions():
    far, unknown = unit("HLF weit", HLF), unit("HLF ohne Ort", HLF)
    settings = ProposalSettingsData(max_travel_minutes=10)
    result = allocate(
        [demand("a", HLF, count=2)],
        [],
        [far, unknown],
        {far.id: t(3600), unknown.id: Travel(None, None, "none")},
        settings,
    )
    assert [p.unit.call_sign for p in result.picks] == ["HLF ohne Ort"]
    assert "Fahrzeit unbekannt (keine Koordinaten)" in result.picks[0].reasons
    assert result.too_far == 1 and result.shortfalls[0].missing == 1


def test_specific_vehicle_demand():
    rtw = unit("RTW 1", RTW)
    d = Demand("v", 1, "AAO RD2, Stufe 1", 1, vehicle_id=rtw.id, vehicle_label="RTW 1")
    result = allocate([d], [], [rtw, unit("RTW 2", RTW)], {}, SETTINGS)
    assert result.picks[0].unit.call_sign == "RTW 1" and result.picks[0].match == "vehicle"
    missing = allocate([d], [], [], {}, SETTINGS)
    assert missing.shortfalls[0].message == "RTW 1 ist nicht verfügbar (AAO RD2, Stufe 1)"


def test_estimate_and_formatting():
    travel = estimate((53.50, 10.48), (53.52, 10.48), speed_kmh=60, detour=1.3, factor=1.0)
    assert travel.source == "estimate" and 2200 < travel.straight_m < 2250
    assert travel.seconds == pytest.approx(travel.meters / (60 / 3.6))
    assert estimate(None, (53.5, 10.4), 60, 1.3, 1.0).seconds is None
    assert fmt_duration(400) == "6:40 min" and fmt_duration(None) == "unbekannt"


def test_settings_validation():
    data = ProposalSettingsData(substitutes={" hlf20 ": ["lf20", "LF20", "hlf20", ""]})
    assert data.substitutes == {"HLF20": ["LF20"]}
    with pytest.raises(ValidationError):
        ProposalSettingsData(detour_factor=0.5)
    with pytest.raises(ValidationError):
        ProposalSettingsData.model_validate({"unknown_weight": 1})
