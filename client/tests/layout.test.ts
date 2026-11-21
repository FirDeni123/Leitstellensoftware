import { describe, expect, it } from 'vitest';
import { keysForTopic } from '@/api/queries';
import { availableWorkstations, permittedLayout, WORKSTATIONS } from '@/layout/workstations';
import { canOpenPanel, PANEL_BY_ID, PANELS } from '@/modules/registry';

const DISPATCHER = ['calls.handle', 'incidents.read', 'incidents.write', 'incidents.close', 'alarm.trigger',
  'vehicles.status.set', 'radio.handle', 'control_centers.read', 'training.participate'];

describe('workstations', () => {
  it('offers workstations according to permissions', () => {
    expect(availableWorkstations(DISPATCHER).map((w) => w.key)).toEqual(['call_taking', 'dispatch', 'radio', 'management']);
    expect(availableWorkstations(['incidents.read'])).toEqual([]);
  });

  it('strips panels the user may not open from default layouts', () => {
    const dispatch = WORKSTATIONS.find((w) => w.key === 'dispatch')!;
    const ids = permittedLayout(dispatch, DISPATCHER).columns.flatMap((c) => c.groups.flat());
    expect(ids).not.toContain('audit-log');
    expect(ids).toContain('incidents');
    expect(ids).toContain('map');
  });

  it('every layout references registered panels only', () => {
    for (const ws of WORKSTATIONS) {
      for (const id of ws.layout.columns.flatMap((c) => c.groups.flat())) expect(PANEL_BY_ID.has(id)).toBe(true);
    }
  });

  it('keeps only permission-free panels for users without rights', () => {
    const admin = WORKSTATIONS.find((w) => w.key === 'admin')!;
    const ids = permittedLayout(admin, []).columns.flatMap((c) => c.groups.flat());
    expect(ids.sort()).toEqual(['module-status', 'system-messages']);
  });

  it('falls back to system messages when nothing is permitted', () => {
    const radio = WORKSTATIONS.find((w) => w.key === 'radio')!;
    const onlyRestricted = { ...radio, layout: { columns: [{ groups: [['talk-requests']] }] } };
    expect(permittedLayout(onlyRestricted, [])).toEqual({ columns: [{ groups: [['system-messages']] }] });
  });
});

describe('registry', () => {
  it('has unique ids and marks planned modules with scope', () => {
    expect(new Set(PANELS.map((p) => p.id)).size).toBe(PANELS.length);
    for (const p of PANELS.filter((p) => !p.implemented)) expect(p.scope?.length).toBeGreaterThan(0);
  });
  it('checks panel permissions', () => {
    expect(canOpenPanel(PANEL_BY_ID.get('users')!, DISPATCHER)).toBe(false);
    expect(canOpenPanel(PANEL_BY_ID.get('system-messages')!, [])).toBe(true);
  });
  it('maps realtime topics to query keys', () => {
    expect(keysForTopic('user.updated')).toEqual([['users']]);
    expect(keysForTopic('unknown.topic')).toEqual([]);
  });
});
