import { beforeEach, describe, expect, it } from 'vitest';
import type { FleetVehicle, LivePosition } from '@/api/types';
import { fmtEta, groupVehicles, shownPosition, staleLiveIds, statusInfo, textOn, useLivePositions } from '@/modules/fleet/live';
import { useMapPick } from '@/modules/map/pick';
import { PANELS } from '@/modules/registry';

const vehicle = (id: string, extra: Partial<FleetVehicle> = {}): FleetVehicle => ({
  id, call_sign: id, vehicle_type: 'HLF20', station_id: 's', station: 'Wache Nord', organization: 'Feuerwehr',
  radio_group_id: null, radio_group: null, status_code: 2, status_changed_at: null, available: true,
  position: { lat: 53.5, lon: 10.4, source: 'station', moving: false, heading: null, eta_s: null, kind: null },
  incident: null, talk_request: null, planned_departure_s: null, ...extra,
});
const live = (id: string): LivePosition => ({ id, lat: 53.6, lon: 10.5, heading: 90, eta_s: 125, kind: 'to_incident', incident_id: null, status_code: 3 });

describe('live positions', () => {
  beforeEach(() => useLivePositions.setState({ byId: {}, clock: null }));

  it('merges 1-Hz events and keeps the simulation clock', () => {
    useLivePositions.getState().apply({ sim_time: 100, factor: 5, paused: false, positions: [live('a'), live('b')] });
    useLivePositions.getState().apply({ sim_time: 101, factor: 5, paused: false, positions: [{ ...live('a'), lat: 53.7 }] });
    const state = useLivePositions.getState();
    expect(Object.keys(state.byId).sort()).toEqual(['a', 'b']);
    expect(state.byId['a']!.lat).toBe(53.7);
    expect(state.clock).toEqual({ sim_time: 101, factor: 5, paused: false });
  });

  it('prefers the live position while driving and drops it after arrival', () => {
    const driving = vehicle('a', { position: { lat: 53.5, lon: 10.4, source: 'sim', moving: true, heading: 0, eta_s: 200, kind: 'to_incident' } });
    expect(shownPosition(driving, live('a'))).toMatchObject({ lat: 53.6, moving: true, eta_s: 125 });
    const arrived = vehicle('a', { position: { lat: 53.62, lon: 10.52, source: 'sim', moving: false, heading: null, eta_s: null, kind: null } });
    expect(shownPosition(arrived, live('a'))).toMatchObject({ lat: 53.62, moving: false });
    expect(staleLiveIds([arrived, vehicle('b')], { a: live('a') })).toEqual(['a']);
    useLivePositions.getState().apply({ sim_time: 1, factor: 1, paused: false, positions: [live('a')] });
    useLivePositions.getState().drop(['a']);
    expect(useLivePositions.getState().byId).toEqual({});
  });
});

describe('fleet helpers', () => {
  it('formats ETAs and groups vehicles', () => {
    expect(fmtEta(125)).toBe('2:05');
    expect(fmtEta(null)).toBe('');
    const groups = groupVehicles([vehicle('x', { station: 'Süd' }), vehicle('y', { station: 'Nord' }), vehicle('z', { station: 'Nord' })], 'station');
    expect(groups.map(([g, v]) => [g, v.length])).toEqual([['Nord', 2], ['Süd', 1]]);
    expect(groupVehicles([vehicle('r')], 'radio_group')[0]![0]).toBe('ohne Funkrufgruppe');
  });

  it('resolves status colours and readable text colours', () => {
    const defs = [{ code: 3, label: 'Einsatzauftrag übernommen', short_label: 'Anfahrt', color: '#f2a93b', counts_as_available: false, description: null, version: 1 }];
    expect(statusInfo(defs, 3)).toEqual({ color: '#f2a93b', label: 'Einsatzauftrag übernommen', short: 'Anfahrt' });
    expect(statusInfo(defs, 9).label).toBe('Status 9');
    expect(textOn('#f2a93b')).toBe('#111');
    expect(textOn('#1f4fbf')).toBe('#fff');
  });
});

describe('map picking', () => {
  it('delivers a picked incident location once', () => {
    useMapPick.getState().start({ kind: 'incident-location', incidentId: 'i1', label: '2026-000001' });
    useMapPick.getState().pickedIncidentLocation(53.123456789, 10.987654321);
    expect(useMapPick.getState().mode).toBeNull();
    expect(useMapPick.getState().result).toEqual({ incidentId: 'i1', lat: 53.123457, lon: 10.987654 });
    useMapPick.getState().consume();
    expect(useMapPick.getState().result).toBeNull();
  });

  it('has no planned (unimplemented) windows left in the registry for phase 6', () => {
    expect(PANELS.filter((p) => p.phase <= 6 && !p.implemented)).toEqual([]);
  });
});
