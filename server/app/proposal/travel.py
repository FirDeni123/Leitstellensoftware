"""Travel times from candidate positions to the incident.

* ``estimate``: straight line × detour factor at the vehicle's speed × emergency factor.
* ``osrm``: OSRM ``table`` service (one request for all candidates). On any error the
  estimate is used and the result is marked as such – never silently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.geo import haversine_m

logger = logging.getLogger(__name__)

# Tests inject an httpx.MockTransport here.
TRANSPORT: httpx.AsyncBaseTransport | None = None


@dataclass(frozen=True, slots=True)
class Travel:
    seconds: float | None
    meters: float | None
    source: str  # osrm | estimate | none
    straight_m: float | None = None


Point = tuple[float, float]  # (lat, lon)


def estimate(
    origin: Point | None, dest: Point | None, speed_kmh: float, detour: float, factor: float
) -> Travel:
    if origin is None or dest is None:
        return Travel(None, None, "none")
    straight = haversine_m(origin[0], origin[1], dest[0], dest[1])
    meters = straight * detour
    speed_ms = max(speed_kmh * factor, 5.0) / 3.6
    return Travel(meters / speed_ms, meters, "estimate", straight)


class RoutingProvider(Protocol):
    name: str

    async def table(self, origins: list[Point], dest: Point) -> list[tuple[float, float] | None]:
        """Duration (s) and distance (m) per origin, None where no route exists."""
        ...


class OsrmProvider:
    name = "osrm"

    def __init__(self, base_url: str, timeout: float = 2.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def table(self, origins: list[Point], dest: Point) -> list[tuple[float, float] | None]:
        coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in [*origins, dest])
        n = len(origins)
        url = f"{self.base_url}/table/v1/driving/{coords}"
        params = {
            "sources": ";".join(str(i) for i in range(n)),
            "destinations": str(n),
            "annotations": "duration,distance",
        }
        async with httpx.AsyncClient(timeout=self.timeout, transport=TRANSPORT) as client:
            response = await client.get(url, params=params)
        response.raise_for_status()
        body = response.json()
        if body.get("code") != "Ok":
            raise ValueError(f"OSRM: {body.get('code')}")
        durations, distances = body["durations"], body.get("distances") or [[None]] * n
        result: list[tuple[float, float] | None] = []
        for i in range(n):
            d, m = durations[i][0], distances[i][0]
            result.append((float(d), float(m or 0.0)) if d is not None else None)
        return result


async def travel_times(
    origins: list[Point | None],
    speeds_kmh: list[float],
    dest: Point | None,
    *,
    detour: float,
    factor: float,
    routing: RoutingProvider | None,
) -> tuple[list[Travel], str | None]:
    """Returns travel per origin and an optional warning (routing failed → estimate)."""
    estimates = [estimate(o, dest, s, detour, factor) for o, s in zip(origins, speeds_kmh, strict=True)]
    if routing is None or dest is None:
        return estimates, None
    routable = [i for i, o in enumerate(origins) if o is not None]
    if not routable:
        return estimates, None
    try:
        table = await routing.table([origins[i] for i in routable], dest)  # type: ignore[misc]
    except Exception as exc:  # routing is optional – fall back, but say so
        logger.warning("Routing nicht verfügbar: %s", exc)
        return (
            estimates,
            "Routing-Dienst nicht erreichbar – Fahrzeiten sind Schätzungen (Luftlinie × Umwegfaktor)",
        )
    result = list(estimates)
    missing = 0
    for idx, row in zip(routable, table, strict=True):
        if row is None:
            missing += 1
            continue
        seconds, meters = row
        result[idx] = Travel(seconds / factor, meters, "osrm", estimates[idx].straight_m)
    warning = f"{missing} Fahrzeug(e) ohne Route – Fahrzeit geschätzt" if missing else None
    return result, warning
