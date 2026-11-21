/** Map interaction requests from other windows: pick an incident location, move a vehicle. */
import { create } from 'zustand';

export type PickMode =
  | { kind: 'incident-location'; incidentId: string; label: string }
  | { kind: 'move-vehicle'; vehicleId: string; label: string };

interface PickState {
  mode: PickMode | null;
  result: { incidentId: string; lat: number; lon: number } | null;
  start(mode: PickMode): void;
  pickedIncidentLocation(lat: number, lon: number): void;
  consume(): void;
  cancel(): void;
}

export const useMapPick = create<PickState>((set, get) => ({
  mode: null,
  result: null,
  start: (mode) => set({ mode, result: null }),
  pickedIncidentLocation: (lat, lon) => {
    const mode = get().mode;
    if (mode?.kind === 'incident-location') {
      set({ mode: null, result: { incidentId: mode.incidentId, lat: Number(lat.toFixed(6)), lon: Number(lon.toFixed(6)) } });
    }
  },
  consume: () => set({ result: null }),
  cancel: () => set({ mode: null }),
}));
