"""Routes for simulated drives and interpolation of positions along them (pure functions)."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from app.core.geo import haversine_m
from app.proposal.travel import Point, RoutingProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Route:
    geometry: list[list[float]]  # [[lon, lat], …]
    profile: list[float]  # cumulative seconds at each vertex
    distance_m: float
    source: str  # osrm | straight

    @property
    def duration_s(self) -> float:
        return self.profile[-1] if self.profile else 0.0


def straight_route(origin: Point, dest: Point, speed_kmh: float, detour: float, factor: float) -> Route:
    """Straight line, travelled at the speed that matches the estimated road time."""
    straight = haversine_m(origin[0], origin[1], dest[0], dest[1])
    road = straight * detour
    seconds = road / (max(speed_kmh * factor, 5.0) / 3.6)
    return Route([[origin[1], origin[0]], [dest[1], dest[0]]], [0.0, seconds], road, "straight")


async def plan_route(
    origin: Point,
    dest: Point,
    *,
    speed_kmh: float,
    detour: float,
    factor: float,
    routing: RoutingProvider | None,
) -> tuple[Route, str | None]:
    """OSRM route (durations divided by the emergency factor) or a marked straight line."""
    if routing is not None and hasattr(routing, "route"):
        try:
            geometry, durations, distance = await routing.route(origin, dest)  # type: ignore[attr-defined]
            profile = [0.0]
            for d in durations:
                profile.append(profile[-1] + d / factor)
            if len(geometry) >= 2 and len(profile) == len(geometry):
                return Route(geometry, profile, distance, "osrm"), None
        except Exception as exc:  # routing is optional – fall back and say so
            logger.warning("Routing für Fahrt nicht verfügbar: %s", exc)
            return straight_route(
                origin, dest, speed_kmh, detour, factor
            ), "Routing nicht erreichbar – Luftlinie"
    return straight_route(origin, dest, speed_kmh, detour, factor), None


def bearing(a: list[float], b: list[float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def position_at(
    geometry: list[list[float]], profile: list[float], elapsed: float
) -> tuple[float, float, float]:
    """(lat, lon, heading) after ``elapsed`` seconds along the route."""
    if not geometry:
        raise ValueError("leere Route")
    if len(geometry) == 1 or elapsed <= 0:
        head = bearing(geometry[0], geometry[1]) if len(geometry) > 1 else 0.0
        return geometry[0][1], geometry[0][0], head
    if elapsed >= profile[-1]:
        return geometry[-1][1], geometry[-1][0], bearing(geometry[-2], geometry[-1])
    # binary search for the segment
    lo, hi = 0, len(profile) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if profile[mid] <= elapsed:
            lo = mid
        else:
            hi = mid
    span = profile[hi] - profile[lo]
    frac = 0.0 if span <= 0 else (elapsed - profile[lo]) / span
    a, b = geometry[lo], geometry[hi]
    return a[1] + (b[1] - a[1]) * frac, a[0] + (b[0] - a[0]) * frac, bearing(a, b)
