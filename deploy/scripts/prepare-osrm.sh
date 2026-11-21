#!/usr/bin/env bash
# Prepares OSRM routing data (car profile, MLD) for a region from Geofabrik.
#
#   deploy/scripts/prepare-osrm.sh                       # Schleswig-Holstein (Standard)
#   deploy/scripts/prepare-osrm.sh europe/germany/hamburg
#
# Afterwards: ILS_OSRM_URL=http://osrm:5000 in deploy/.env and
#   docker compose --profile routing up -d
# Re-run monthly to update the map data (then: docker compose restart osrm).
set -euo pipefail

REGION="${1:-europe/germany/schleswig-holstein}"
IMAGE="ghcr.io/project-osrm/osrm-backend:v5.27.1"
DIR="$(cd "$(dirname "$0")/.." && pwd)/osrm-data"
mkdir -p "$DIR"
cd "$DIR"

echo "Lade OSM-Extrakt ${REGION} von Geofabrik …"
curl -fL --retry 3 -o region.osm.pbf.tmp "https://download.geofabrik.de/${REGION}-latest.osm.pbf"
mv region.osm.pbf.tmp region.osm.pbf

echo "Bereite Routing-Daten auf (Autoprofil, kann einige Minuten dauern) …"
docker run --rm -v "$DIR:/data" "$IMAGE" osrm-extract -p /opt/car.lua /data/region.osm.pbf
docker run --rm -v "$DIR:/data" "$IMAGE" osrm-partition /data/region.osrm
docker run --rm -v "$DIR:/data" "$IMAGE" osrm-customize /data/region.osrm

echo "Fertig. Daten in ${DIR}. Kartendaten © OpenStreetMap-Mitwirkende (ODbL)."
