/**
 * Karte: stations, vehicles (status colour, live positions at 1 Hz), open incidents and the
 * routes of simulated drives. Map tiles come from the server configuration (attribution is
 * always shown). Clicking the map sets an incident location or moves a simulated vehicle
 * when another window asked for it (see `pick.ts`).
 */
import { AttributionControl, Map as MlMap, Marker, NavigationControl, setWorkerUrl, type GeoJSONSource, type StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useFleet, useIncidents, useList, useMapConfig, useMovements, useSimulationClock, useStatusDefinitions } from '@/api/queries';
import type { FleetVehicle, MapConfig, Station } from '@/api/types';
import { ErrorAlert } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { describeError } from '@/api/http';
import { hasPermission, useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';
import { fmtEta, shownPosition, staleLiveIds, statusInfo, useLivePositions } from '../fleet/live';
import { useMapPick } from './pick';

setWorkerUrl(workerUrl);

const DEFAULT_CENTER: [number, number] = [53.5, 10.48];

function baseStyle(config: MapConfig): StyleSpecification {
  return {
    version: 8,
    sources: {
      tiles: { type: 'raster', tiles: [config.tile_url], tileSize: 256, maxzoom: config.max_zoom, attribution: config.attribution },
      routes: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#151b24' } },
      { id: 'tiles', type: 'raster', source: 'tiles', paint: { 'raster-saturation': -0.55, 'raster-brightness-max': 0.72, 'raster-contrast': 0.05 } },
      { id: 'routes-road', type: 'line', source: 'routes', filter: ['==', ['get', 'straight'], false], paint: { 'line-color': ['get', 'color'], 'line-width': 3, 'line-opacity': 0.85 } },
      { id: 'routes-straight', type: 'line', source: 'routes', filter: ['==', ['get', 'straight'], true], paint: { 'line-color': ['get', 'color'], 'line-width': 2, 'line-dasharray': [2, 2], 'line-opacity': 0.85 } },
    ],
  };
}

function el(className: string, html: string, title: string): HTMLElement {
  const node = document.createElement('div');
  node.className = className;
  node.innerHTML = html;
  node.title = title;
  return node;
}

const escape = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

export function MapPanel(): ReactNode {
  const me = useSession((s) => s.me)!;
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const { active } = useActiveControlCenter();
  const ccId = active?.id;
  const config = useMapConfig(ccId);
  const fleet = useFleet(ccId);
  const movements = useMovements(ccId);
  const stations = useList<Station>('stations', '/stations', { control_center_id: ccId }, !!ccId);
  const incidents = useIncidents(ccId, 'open');
  const defs = useStatusDefinitions();
  const clock = useSimulationClock();
  const live = useLivePositions((s) => s.byId);
  const drop = useLivePositions((s) => s.drop);
  const pick = useMapPick();
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markers = useRef(new Map<string, Marker>());
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [show, setShow] = useState({ vehicles: true, stations: true, incidents: true, routes: true });
  const [mapError, setMapError] = useState<string | null>(null);
  const canSim = hasPermission(me, 'simulation.control');
  const pickRef = useRef(pick);
  pickRef.current = pick;

  // ---------------------------------------------------------------- create the map once
  useEffect(() => {
    if (!config.data || !container.current || mapRef.current) return;
    try {
      const center = config.data.center ?? DEFAULT_CENTER;
      const map = new MlMap({
        container: container.current,
        style: baseStyle(config.data),
        center: [center[1], center[0]],
        zoom: 12,
        attributionControl: false,
      });
      map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
      map.addControl(new AttributionControl({ compact: false }), 'bottom-right');
      map.on('load', () => setLoaded(true));
      map.on('error', (e) => console.warn('Karte:', e.error?.message));
      map.on('click', (e) => void onMapClick(e.lngLat.lat, e.lngLat.lng));
      mapRef.current = map;
      const observer = new ResizeObserver(() => map.resize());
      observer.observe(container.current);
      return () => {
        observer.disconnect();
        for (const m of markers.current.values()) m.remove();
        markers.current.clear();
        map.remove();
        mapRef.current = null;
      };
    } catch (e) {
      setMapError(e instanceof Error ? e.message : 'Karte konnte nicht geladen werden');
    }
    return undefined;
  }, [config.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const onMapClick = async (lat: number, lon: number) => {
    const mode = pickRef.current.mode;
    if (!mode) return;
    if (mode.kind === 'incident-location') {
      useMapPick.getState().pickedIncidentLocation(lat, lon);
      sysmsg('info', 'Karte', `Einsatzort gesetzt: ${lat.toFixed(5)}, ${lon.toFixed(5)} – bitte im Einsatz speichern`);
    } else {
      useMapPick.getState().cancel();
      try {
        await api.post(`/simulation/vehicles/${mode.vehicleId}/position`, { lat, lon });
        await qc.invalidateQueries({ queryKey: ['fleet'] });
      } catch (e) {
        sysmsg('error', 'Karte', describeError(e));
      }
    }
  };

  // live entries of vehicles that stopped are no longer needed
  useEffect(() => {
    if (fleet.data) drop(staleLiveIds(fleet.data, useLivePositions.getState().byId));
  }, [fleet.data, drop]);

  // ---------------------------------------------------------------------- markers
  type Item = { key: string; lat: number; lon: number; className: string; html: string; title: string; onClick?: () => void };
  const items = useMemo<Item[]>(() => {
    const result: Item[] = [];
    if (show.stations) {
      for (const s of stations.data ?? []) {
        if (s.latitude === null || s.longitude === null) continue;
        result.push({ key: `s:${s.id}`, lat: s.latitude, lon: s.longitude, className: 'map-station', html: '<span>⌂</span>', title: s.name });
      }
    }
    if (show.incidents) {
      for (const i of incidents.data ?? []) {
        if (i.latitude === null || i.longitude === null) continue;
        result.push({
          key: `i:${i.id}`, lat: i.latitude, lon: i.longitude, className: `map-incident prio-${i.priority}`,
          html: `<b>${escape(i.keyword?.code ?? '?')}</b>`, title: `${i.number} ${i.address ?? ''}`,
        });
      }
    }
    if (show.vehicles) {
      for (const v of fleet.data ?? []) {
        const pos = shownPosition(v, live[v.id]);
        if (!pos) continue;
        const info = statusInfo(defs.data, v.status_code);
        const moving = pos.moving ? ' moving' : '';
        result.push({
          key: `v:${v.id}`, lat: pos.lat, lon: pos.lon, className: `map-vehicle${moving}${selected === v.id ? ' selected' : ''}`,
          html: `<i style="background:${info.color}">${v.status_code}</i><span>${escape(v.call_sign)}</span>`,
          title: `${v.call_sign} – ${info.label}${pos.eta_s ? ` – ETA ${fmtEta(pos.eta_s)}` : ''}`,
          onClick: () => setSelected(v.id),
        });
      }
    }
    return result;
  }, [show, stations.data, incidents.data, fleet.data, live, defs.data, selected]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const current = markers.current;
    const keys = new Set(items.map((i) => i.key));
    for (const [key, marker] of current) if (!keys.has(key)) { marker.remove(); current.delete(key); }
    for (const item of items) {
      let marker = current.get(item.key);
      if (!marker) {
        const node = el(item.className, item.html, item.title);
        node.dataset['key'] = item.key;
        node.dataset['cls'] = item.className;
        if (item.onClick) node.addEventListener('click', (e) => { e.stopPropagation(); item.onClick?.(); });
        marker = new Marker({ element: node }).setLngLat([item.lon, item.lat]).addTo(map);
        current.set(item.key, marker);
      } else {
        const node = marker.getElement();
        const previous = node.dataset['cls'] ?? '';
        if (previous !== item.className) { // keep MapLibre's own classes on the element
          node.classList.remove(...previous.split(' ').filter(Boolean));
          node.classList.add(...item.className.split(' ').filter(Boolean));
          node.dataset['cls'] = item.className;
        }
        if (node.innerHTML !== item.html) node.innerHTML = item.html;
        node.title = item.title;
        marker.setLngLat([item.lon, item.lat]);
      }
    }
  }, [items, loaded]);

  // ------------------------------------------------------------------------ routes
  useEffect(() => {
    const map = mapRef.current;
    const source = loaded ? (map?.getSource('routes') as GeoJSONSource | undefined) : undefined;
    if (!source) return;
    const features = show.routes ? (movements.data ?? []).filter((m) => m.geometry.length >= 2).map((m) => ({
      type: 'Feature' as const,
      properties: { straight: m.route_source !== 'osrm', color: m.kind === 'to_incident' ? '#ff6b6b' : '#7fb2ff' },
      geometry: { type: 'LineString' as const, coordinates: m.geometry },
    })) : [];
    source.setData({ type: 'FeatureCollection', features });
  }, [movements.data, loaded, show.routes]);

  const straight = (movements.data ?? []).some((m) => m.route_source === 'straight');
  const vehicle = fleet.data?.find((v) => v.id === selected) ?? null;

  const setClock = async (patch: { factor?: number; paused?: boolean }) => {
    try {
      await api.put('/simulation/clock', patch);
      await qc.invalidateQueries({ queryKey: ['simulation-clock'] });
    } catch (e) {
      sysmsg('error', 'Simulation', describeError(e));
    }
  };

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <div className="chips" role="group" aria-label="Ebenen">
          {([['vehicles', 'Fahrzeuge'], ['stations', 'Wachen'], ['incidents', 'Einsätze'], ['routes', 'Routen']] as const).map(([k, label]) => (
            <button key={k} type="button" className={`chip ${show[k] ? 'on' : ''}`} onClick={() => setShow((s) => ({ ...s, [k]: !s[k] }))}>{label}</button>
          ))}
        </div>
        {straight && <span className="badge warn" title="Kein Routing-Dienst: Fahrten verlaufen auf der Luftlinie (gestrichelt)">Luftlinie</span>}
        <div className="spacer" />
        {canSim && clock.data?.simulation_mode && (
          <div className="sim-clock" role="group" aria-label="Simulationsuhr">
            <button className="btn sm" onClick={() => void setClock({ paused: !clock.data!.paused })}>{clock.data.paused ? '▶ Fortsetzen' : '⏸ Pause'}</button>
            <select className="select" aria-label="Zeitfaktor" value={clock.data.factor} onChange={(e) => void setClock({ factor: Number(e.target.value) })}>
              {clock.data.factors.map((f) => <option key={f} value={f}>{f}×</option>)}
            </select>
          </div>
        )}
      </div>
      {pick.mode && (
        <div className="alert info map-pick" role="status">
          {pick.mode.kind === 'incident-location' ? `Einsatzort für ${pick.mode.label}: in die Karte klicken` : `${pick.mode.label} verschieben: Zielpunkt in die Karte klicken`}
          <button className="btn sm" onClick={() => pick.cancel()}>Abbrechen</button>
        </div>
      )}
      <ErrorAlert error={config.error ?? fleet.error} />
      {mapError && <div className="alert error">Karte nicht verfügbar: {mapError}</div>}
      <div className="map-wrap">
        <div ref={container} className={`map ${pick.mode ? 'picking' : ''}`} data-testid="map" />
        {vehicle && <VehicleCard vehicle={vehicle} canSim={canSim && !!clock.data?.simulation_mode} onClose={() => setSelected(null)} />}
      </div>
    </div>
  );
}

function VehicleCard({ vehicle, canSim, onClose }: { vehicle: FleetVehicle; canSim: boolean; onClose: () => void }): ReactNode {
  const defs = useStatusDefinitions();
  const live = useLivePositions((s) => s.byId[vehicle.id]);
  const pos = shownPosition(vehicle, live);
  const info = statusInfo(defs.data, vehicle.status_code);
  return (
    <div className="map-card" role="dialog" aria-label={`Fahrzeug ${vehicle.call_sign}`}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span className="fms" style={{ background: info.color }}>{vehicle.status_code}</span>
        <b>{vehicle.call_sign}</b>
        <span className="badge mono">{vehicle.vehicle_type}</span>
        <button className="btn ghost sm" style={{ marginLeft: 'auto' }} aria-label="Schließen" onClick={onClose}>✕</button>
      </div>
      <div className="muted">{info.label} · {vehicle.station}</div>
      {vehicle.incident && <div>Einsatz <span className="mono">{vehicle.incident.number}</span></div>}
      {pos?.moving && <div>{vehicle.position?.kind === 'to_station' || live?.kind === 'to_station' ? 'Rückfahrt' : 'Anfahrt'} · ETA {fmtEta(pos.eta_s)} min</div>}
      {vehicle.planned_departure_s !== null && <div>Abfahrt in {fmtEta(vehicle.planned_departure_s)} min (Ausrückzeit)</div>}
      {canSim && (
        <button className="btn sm" style={{ marginTop: 6 }} onClick={() => useMapPick.getState().start({ kind: 'move-vehicle', vehicleId: vehicle.id, label: vehicle.call_sign })}>
          Verschieben (Simulation)
        </button>
      )}
    </div>
  );
}
