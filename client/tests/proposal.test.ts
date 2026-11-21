import { describe, expect, it } from 'vitest';
import type { Proposal } from '@/api/types';
import { fmtDuration, initialSelection, picksByDemand, swapVehicle } from '@/modules/proposal/labels';
import { PANEL_BY_ID } from '@/modules/registry';

const pick = (id: string, demand: string, inIncident = false) => ({
  demand_key: demand, vehicle_id: id, call_sign: id, vehicle_type: 'HLF20', station_id: 's', station: 'Wache', status_code: 2,
  slot: 1, match: 'exact' as const, score_seconds: 100, travel_seconds: 90, distance_m: 1000, travel_source: 'estimate' as const,
  in_incident: inIncident, alarmed: false, reasons: [],
});

const PROPOSAL = {
  demands: [{ key: 'a', label: 'HLF20', source: 'AAO', count: 2, stage: 1, covered: 2 }, { key: 'b', label: 'DLK23', source: 'AAO', count: 1, stage: 1, covered: 0 }],
  picks: [pick('v1', 'a', true), pick('v2', 'a')],
} as unknown as Proposal;

describe('Einsatzmittelvorschlag helpers', () => {
  it('formats durations like the server', () => {
    expect(fmtDuration(400)).toBe('6:40 min');
    expect(fmtDuration(59.6)).toBe('1:00 min');
    expect(fmtDuration(null)).toBe('–');
  });

  it('selects only vehicles that are not yet in the incident', () => {
    expect(initialSelection(PROPOSAL)).toEqual(['v2']);
  });

  it('groups picks by demand in demand order, also empty demands', () => {
    const grouped = picksByDemand(PROPOSAL);
    expect([...grouped.keys()]).toEqual(['a', 'b']);
    expect(grouped.get('a')!.map((p) => p.vehicle_id)).toEqual(['v1', 'v2']);
    expect(grouped.get('b')).toEqual([]);
  });

  it('swaps a proposed vehicle for an alternative without duplicates', () => {
    expect(swapVehicle(['v2', 'v3'], 'v2', 'v9')).toEqual(['v9', 'v3']);
    expect(swapVehicle(['v2', 'v3'], 'v2', 'v3')).toEqual(['v3']);
  });

  it('registers the settings window', () => {
    expect(PANEL_BY_ID.get('proposal-settings')?.implemented).toBe(true);
  });
});
