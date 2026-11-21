"""Allocation engine of the Einsatzmittelvorschlag – pure functions, no database access.

1. Units already in the incident cover the demand first (exact type, then substitutes).
2. Every free candidate is scored per demand it is eligible for:
   ``score = travel time + turnout time (status 2) + substitute malus − AAO station bonus``
   (all in seconds; lower is better). Candidates beyond the maximum travel time are dropped.
3. Greedy allocation by score, then a balancing pass: an unmet demand may take a unit from
   another demand if that demand can be served by a free alternative (keeps the number of
   covered demands maximal, e.g. LF as substitute vs. HLF only for HLF).
4. Every pick carries human-readable reasons; unmet demand is reported explicitly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.proposal.settings import ProposalSettingsData
from app.proposal.travel import Travel

UNKNOWN_TRAVEL_SECONDS = 24 * 3600  # sorts units without coordinates last


@dataclass(frozen=True, slots=True)
class Unit:
    id: uuid.UUID
    call_sign: str
    type_id: uuid.UUID
    type_code: str
    station_id: uuid.UUID
    station_name: str
    status_code: int
    position: str = "Wache"  # "Fahrzeugposition" | "Wache" | "unbekannt"


@dataclass(frozen=True, slots=True)
class Demand:
    key: str
    count: int
    source: str  # e.g. "AAO B2, Stufe 1" or "Zusatzbedarf"
    stage: int | None = None
    type_id: uuid.UUID | None = None
    type_code: str | None = None
    vehicle_id: uuid.UUID | None = None
    vehicle_label: str | None = None

    @property
    def label(self) -> str:
        return self.vehicle_label if self.vehicle_id else (self.type_code or "?")


@dataclass(frozen=True, slots=True)
class InIncident:
    unit: Unit
    alarmed: bool


@dataclass(slots=True)
class Pick:
    demand: Demand
    unit: Unit
    slot: int  # 1-based position within the demand ("Bedarf 1/2")
    score: float | None
    travel: Travel | None
    match: str  # exact | substitute | vehicle | covered
    reasons: list[str] = field(default_factory=list)
    in_incident: bool = False
    alarmed: bool = False


@dataclass(slots=True)
class Option:
    unit: Unit
    score: float
    travel: Travel
    match: str


@dataclass(slots=True)
class Shortfall:
    demand: Demand
    missing: int
    message: str


@dataclass(slots=True)
class EngineResult:
    picks: list[Pick]
    alternatives: dict[str, list[Option]]
    shortfalls: list[Shortfall]
    too_far: int = 0


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unbekannt"
    total = max(0, round(seconds))
    return f"{total // 60}:{total % 60:02d} min"


def match_kind(demand: Demand, unit: Unit, substitutes: dict[str, list[str]]) -> str | None:
    if demand.vehicle_id is not None:
        return "vehicle" if unit.id == demand.vehicle_id else None
    if unit.type_id == demand.type_id:
        return "exact"
    if demand.type_code and unit.type_code in substitutes.get(demand.type_code, []):
        return "substitute"
    return None


def score_of(
    demand: Demand,
    unit: Unit,
    travel: Travel,
    match: str,
    settings: ProposalSettingsData,
    preferred_stations: set[uuid.UUID],
) -> float:
    seconds = travel.seconds if travel.seconds is not None else UNKNOWN_TRAVEL_SECONDS
    score = seconds
    if unit.status_code == 2:
        score += settings.turnout_seconds_on_station
    if match == "substitute":
        score += settings.substitute_penalty_seconds
    if unit.station_id in preferred_stations:
        score -= settings.preferred_station_bonus_seconds
    return score


def reasons_for(pick: Pick, settings: ProposalSettingsData, preferred_stations: set[uuid.UUID]) -> list[str]:
    d, u, t = pick.demand, pick.unit, pick.travel
    reasons: list[str] = []
    if pick.match == "vehicle":
        reasons.append(f"{d.source}: namentlich vorgesehen")
    elif pick.match == "substitute":
        reasons.append(
            f"{d.source}: Ersatz für {d.type_code} (Bedarf {pick.slot}/{d.count}) – "
            f"{u.type_code}, +{fmt_duration(settings.substitute_penalty_seconds)} Malus"
        )
    else:
        reasons.append(f"{d.source}: {u.type_code} (Bedarf {pick.slot}/{d.count})")
    if pick.in_incident:
        reasons.append("bereits alarmiert" if pick.alarmed else "bereits dem Einsatz zugeordnet")
        return reasons
    if u.status_code == 2:
        reasons.append(f"Status 2 auf Wache (+{fmt_duration(settings.turnout_seconds_on_station)} Ausrücken)")
    elif u.status_code == 1:
        reasons.append("Status 1 – frei über Funk")
    if t is None or t.seconds is None:
        reasons.append("Fahrzeit unbekannt (keine Koordinaten)")
    elif t.source == "osrm":
        reasons.append(
            f"Fahrzeit {fmt_duration(t.seconds)} ab {u.position} (Route, {t.meters / 1000:.1f} km)"
        )
    else:
        straight = (t.straight_m or 0) / 1000
        reasons.append(
            f"Fahrzeit ca. {fmt_duration(t.seconds)} ab {u.position} "
            f"(Schätzung: {straight:.1f} km Luftlinie × {settings.detour_factor:g})"
        )
    if u.station_id in preferred_stations:
        reasons.append(
            f"Wache {u.station_name} laut AAO bevorzugt "
            f"(−{fmt_duration(settings.preferred_station_bonus_seconds)})"
        )
    return reasons


def allocate(
    demands: list[Demand],
    in_incident: list[InIncident],
    candidates: list[Unit],
    travel: dict[uuid.UUID, Travel],
    settings: ProposalSettingsData,
    preferred_stations: set[uuid.UUID] | None = None,
) -> EngineResult:
    preferred = preferred_stations or set()
    subs = settings.substitutes
    remaining = {d.key: d.count for d in demands}
    picks: list[Pick] = []

    # 1. Units already in the incident cover the demand (exact matches before substitutes).
    pool = list(in_incident)
    for wanted in ("exact_or_vehicle", "substitute"):
        for d in demands:
            for item in list(pool):
                if remaining[d.key] == 0:
                    break
                kind = match_kind(d, item.unit, subs)
                if kind is None or (wanted == "substitute") != (kind == "substitute"):
                    continue
                pool.remove(item)
                slot = d.count - remaining[d.key] + 1
                remaining[d.key] -= 1
                picks.append(
                    Pick(
                        d,
                        item.unit,
                        slot,
                        None,
                        travel.get(item.unit.id),
                        kind,
                        in_incident=True,
                        alarmed=item.alarmed,
                    )
                )

    # 2. Score all eligible (demand, free candidate) pairs.
    max_seconds = settings.max_travel_minutes * 60
    taken = {p.unit.id for p in picks}
    options: dict[str, list[Option]] = {d.key: [] for d in demands}
    too_far: set[uuid.UUID] = set()
    for d in demands:
        for unit in candidates:
            if unit.id in taken:
                continue
            kind = match_kind(d, unit, subs)
            if kind is None:
                continue
            t = travel.get(unit.id) or Travel(None, None, "none")
            if t.seconds is not None and t.seconds > max_seconds:
                too_far.add(unit.id)
                continue
            options[d.key].append(Option(unit, score_of(d, unit, t, kind, settings, preferred), t, kind))
    for opts in options.values():
        opts.sort(key=lambda o: (o.score, o.match == "substitute", o.unit.call_sign))

    # 3a. Greedy by score over all pairs.
    assigned: dict[uuid.UUID, tuple[str, Option]] = {}
    pairs = sorted(
        ((o.score, d_key, o) for d_key, opts in options.items() for o in opts),
        # on equal scores a matching type goes before a substitute
        key=lambda p: (p[0], p[2].match == "substitute", p[2].unit.call_sign),
    )
    for _, d_key, opt in pairs:
        if remaining[d_key] > 0 and opt.unit.id not in assigned:
            assigned[opt.unit.id] = (d_key, opt)
            remaining[d_key] -= 1

    # 3b. Balancing: an unmet demand takes a unit from another demand that has a free alternative.
    improved = True
    while improved:
        improved = False
        for d in demands:
            if remaining[d.key] == 0:
                continue
            best: tuple[float, uuid.UUID, Option, Option] | None = None
            for opt in options[d.key]:
                holder = assigned.get(opt.unit.id)
                if holder is None:
                    continue
                other_key, other_opt = holder
                if other_key == d.key:
                    continue
                free = next((o for o in options[other_key] if o.unit.id not in assigned), None)
                if free is None:
                    continue
                delta = opt.score + free.score - other_opt.score
                if best is None or delta < best[0]:
                    best = (delta, opt.unit.id, opt, free)
            if best is not None:
                _, unit_id, opt, free = best
                other_key = assigned[unit_id][0]
                assigned[unit_id] = (d.key, opt)
                assigned[free.unit.id] = (other_key, free)
                remaining[d.key] -= 1
                improved = True

    # 4. Picks in demand order with slots, reasons and alternatives.
    covered_count = {d.key: sum(1 for p in picks if p.demand.key == d.key) for d in demands}
    new_picks: list[Pick] = []
    for d in demands:
        chosen = sorted((o for k, o in assigned.values() if k == d.key), key=lambda o: o.score)
        for i, opt in enumerate(chosen):
            slot = covered_count[d.key] + i + 1
            new_picks.append(Pick(d, opt.unit, slot, opt.score, opt.travel, opt.match))
    picks.extend(new_picks)
    for pick in picks:
        pick.reasons = reasons_for(pick, settings, preferred)
    order = {d.key: i for i, d in enumerate(demands)}
    picks.sort(key=lambda p: (order[p.demand.key], p.slot))

    alternatives = {
        d.key: [o for o in options[d.key] if o.unit.id not in assigned][: settings.alternatives]
        for d in demands
    }
    shortfalls = []
    for d in demands:
        missing = remaining[d.key]
        if missing <= 0:
            continue
        if d.vehicle_id is not None:
            message = f"{d.label} ist nicht verfügbar ({d.source})"
        else:
            stage = f" (Stufe {d.stage})" if d.stage else ""
            message = f"{d.label}: {missing} von {d.count} nicht verfügbar{stage}"
        shortfalls.append(Shortfall(d, missing, message))
    return EngineResult(picks, alternatives, shortfalls, len(too_far - set(assigned)))
