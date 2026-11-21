import { describe, expect, it } from 'vitest';
import { initialValue, parseNumber, toPayload } from '@/modules/crud/fields';
import type { FieldDef } from '@/modules/crud/types';
import * as md from '@/modules/masterdata/configs';
import { PANELS } from '@/modules/registry';

const num: FieldDef = { key: 'latitude', label: 'Breitengrad', type: 'number', min: -90, max: 90 };

describe('field conversion', () => {
  it('parses German and English numbers', () => {
    expect(parseNumber('53,5036')).toBe(53.5036);
    expect(parseNumber('1.234,5')).toBe(1234.5);
    expect(parseNumber(' 10.48 ')).toBe(10.48);
    expect(parseNumber('')).toBeNull();
    expect(parseNumber('abc')).toBeNaN();
  });

  it('validates number ranges and required fields', () => {
    expect(toPayload(num, '53,5')).toEqual({ value: 53.5 });
    expect(toPayload(num, '123').error).toContain('zwischen -90 und 90');
    expect(toPayload(num, 'x').error).toContain('keine gültige Zahl');
    expect(toPayload({ ...num, required: true }, '').error).toContain('erforderlich');
    expect(toPayload({ key: 'name', label: 'Name', type: 'text', required: true }, '  ').error).toContain('erforderlich');
  });

  it('uses the configured empty value (RIC sub address is "" instead of null)', () => {
    const sub = md.RICS.fields.find((f) => f.key === 'sub_address')!;
    expect(toPayload(sub, '')).toEqual({ value: '' });
    expect(toPayload({ key: 'x', label: 'X', type: 'select' }, '')).toEqual({ value: null });
  });

  it('parses GeoJSON text', () => {
    const geo: FieldDef = { key: 'geometry', label: 'Gebiet', type: 'geojson' };
    expect(toPayload(geo, '{"type":"Polygon","coordinates":[]}')).toEqual({ value: { type: 'Polygon', coordinates: [] } });
    expect(toPayload(geo, '{kaputt').error).toContain('kein gültiges JSON');
    expect(toPayload(geo, '')).toEqual({ value: null });
  });

  it('derives form values from records (nested references, numbers as text)', () => {
    const station = md.VEHICLES.fields.find((f) => f.key === 'station_id')!;
    expect(initialValue(station, { station: { id: 's1' } })).toBe('s1');
    expect(initialValue(num, { latitude: 53.5 })).toBe('53.5');
    expect(initialValue(num, { latitude: null })).toBe('');
    const available = md.VEHICLES.fields.find((f) => f.key === 'available')!;
    expect(initialValue(available, undefined)).toBe(true);
  });
});

describe('master data configuration', () => {
  it('every implemented master data panel is registered and permission-guarded', () => {
    for (const id of ['stations', 'vehicle-admin', 'rics', 'alarm-groups', 'radio-groups', 'organizations', 'vehicle-types',
      'status-definitions', 'areas', 'import', 'roles', 'login-log']) {
      const panel = PANELS.find((p) => p.id === id);
      expect(panel?.implemented).toBe(true);
      expect(panel?.permission).toBeTruthy();
    }
  });

  it('police can never be marked alarmable in the organisation form', () => {
    const alarmable = md.ORGANIZATIONS.fields.find((f) => f.key === 'alarmable')!;
    expect(alarmable.disabledWhen?.({ kind: 'police' })).toBe(true);
    expect(alarmable.disabledWhen?.({ kind: 'fire' })).toBe(false);
  });
});
