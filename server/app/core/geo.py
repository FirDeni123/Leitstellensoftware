"""Small, dependency-free geometry helpers (WGS84).

Enough for areas of responsibility and distance pre-filtering. Heavy GIS work (e.g. large
municipality polygons, spatial indexes) can move to PostGIS later without API changes.
"""

from __future__ import annotations

import math
from typing import Any

from app.core.errors import ValidationFailedError

EARTH_RADIUS_M = 6_371_008.8
MAX_VERTICES = 20_000


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _ring(raw: Any) -> list[list[float]]:
    if not isinstance(raw, list) or len(raw) < 3:
        raise ValidationFailedError("Ungültige Geometrie: ein Ring braucht mindestens 3 Punkte")
    ring: list[list[float]] = []
    for pt in raw:
        if not (
            isinstance(pt, list | tuple) and len(pt) >= 2 and all(isinstance(c, int | float) for c in pt[:2])
        ):
            raise ValidationFailedError("Ungültige Geometrie: Punkte müssen [Länge, Breite] sein")
        lon, lat = float(pt[0]), float(pt[1])
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValidationFailedError(
                "Ungültige Geometrie: Koordinate außerhalb des Wertebereichs (Reihenfolge [Länge, Breite]?)"
            )
        ring.append([lon, lat])
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))  # close the ring
    if len(ring) < 4:
        raise ValidationFailedError("Ungültige Geometrie: ein Ring braucht mindestens 3 verschiedene Punkte")
    return ring


def normalise_geometry(geometry: Any) -> dict[str, Any]:
    """Validate a GeoJSON Polygon/MultiPolygon (also accepts a Feature wrapping one)."""
    if isinstance(geometry, dict) and geometry.get("type") == "Feature":
        geometry = geometry.get("geometry")
    if not isinstance(geometry, dict):
        raise ValidationFailedError("Geometrie muss ein GeoJSON-Objekt sein")
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind == "Polygon":
        polygons = [coords]
    elif kind == "MultiPolygon":
        polygons = coords
    else:
        raise ValidationFailedError("Nur GeoJSON Polygon oder MultiPolygon wird unterstützt")
    if not isinstance(polygons, list) or not polygons:
        raise ValidationFailedError("Ungültige Geometrie: keine Koordinaten")
    result = []
    vertices = 0
    for poly in polygons:
        if not isinstance(poly, list) or not poly:
            raise ValidationFailedError("Ungültige Geometrie: Polygon ohne Ringe")
        rings = [_ring(r) for r in poly]
        vertices += sum(len(r) for r in rings)
        result.append(rings)
    if vertices > MAX_VERTICES:
        raise ValidationFailedError(f"Geometrie zu groß (mehr als {MAX_VERTICES} Punkte)")
    return {"type": "MultiPolygon", "coordinates": result}


def _in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-300) + xi:
            inside = not inside
        j = i
    return inside


def point_in_geometry(lat: float, lon: float, geometry: dict[str, Any]) -> bool:
    """Ray casting; the first ring of each polygon is the outline, further rings are holes."""
    polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    for rings in polygons:
        if rings and _in_ring(lon, lat, rings[0]) and not any(_in_ring(lon, lat, h) for h in rings[1:]):
            return True
    return False
