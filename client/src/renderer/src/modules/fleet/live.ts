/**
 * Live vehicle positions. The server sends one `vehicle.positions` event per control centre
 * and second with all moving vehicles; positions are merged into this store instead of
 * re-fetching the fleet every second. Status changes still re-fetch the fleet (query).
 */
import { create } from 'zustand';
import type { FleetVehicle, LivePosition, PositionsEvent, StatusDefinition } from '@/api/types';
import { onRealtimeEvent } from '@/state/session';

interface LiveState {
  byId: Record<string, LivePosition>;
  clock: { sim_time: number; factor: number; paused: boolean } | null;
  apply(event: PositionsEvent): void;
  drop(ids: string[]): void;
}

export const useLivePositions = create<LiveState>((set) => ({
  byId: {},
  clock: null,
  apply: (event) => set((s) => {
    const byId = { ...s.byId };
    for (const p of event.positions) byId[p.id] = p;
    return { byId, clock: { sim_time: event.sim_time, factor: event.factor, paused: event.paused } };
  }),
  drop: (ids) => set((s) => {
    if (!ids.some((id) => id in s.byId)) return s;
    const byId = { ...s.byId };
    for (const id of ids) delete byId[id];
    return { byId };
  }),
}));

export function installPositionUpdates(): () => void {
  return onRealtimeEvent((e) => {
    if (e.topic === 'vehicle.positions') useLivePositions.getState().apply(e.data as unknown as PositionsEvent);
  });
}

export interface ShownPosition {
  lat: number;
  lon: number;
  moving: boolean;
  heading: number | null;
  eta_s: number | null;
  source: string;
}

/** Live position while the vehicle drives, otherwise the stored one from the fleet query. */
export function shownPosition(vehicle: FleetVehicle, live: LivePosition | undefined): ShownPosition | null {
  if (live && vehicle.position?.moving !== false) {
    return { lat: live.lat, lon: live.lon, moving: true, heading: live.heading, eta_s: live.eta_s, source: 'sim' };
  }
  if (!vehicle.position) return null;
  const p = vehicle.position;
  return { lat: p.lat, lon: p.lon, moving: p.moving, heading: p.heading, eta_s: p.eta_s, source: p.source };
}

/** Vehicles that stopped according to the server no longer need a live entry. */
export function staleLiveIds(vehicles: readonly FleetVehicle[], live: Record<string, LivePosition>): string[] {
  return vehicles.filter((v) => v.position && !v.position.moving && v.id in live).map((v) => v.id);
}

export function fmtEta(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '';
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

export type Grouping = 'station' | 'radio_group' | 'organization';

export function groupVehicles(vehicles: readonly FleetVehicle[], by: Grouping): [string, FleetVehicle[]][] {
  const groups = new Map<string, FleetVehicle[]>();
  for (const v of vehicles) {
    const key = by === 'station' ? v.station : by === 'radio_group' ? (v.radio_group ?? 'ohne Funkrufgruppe') : v.organization;
    groups.set(key, [...(groups.get(key) ?? []), v]);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b, 'de'));
}

export function statusInfo(defs: readonly StatusDefinition[] | undefined, code: number): { color: string; label: string; short: string } {
  const d = defs?.find((x) => x.code === code);
  return { color: d?.color ?? '#6b7686', label: d?.label ?? `Status ${code}`, short: d?.short_label ?? String(code) };
}

/** Readable text colour on a status colour (WCAG-ish luminance check). */
export function textOn(hex: string): string {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(hex);
  if (!m) return '#fff';
  const [r, g, b] = [m[1], m[2], m[3]].map((x) => parseInt(x!, 16) / 255) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.55 ? '#111' : '#fff';
}
