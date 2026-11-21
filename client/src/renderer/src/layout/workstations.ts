/**
 * Workstation profiles (Arbeitsplätze). Each profile defines which permission is needed
 * and the default window arrangement. Users can rearrange freely; their layout is stored
 * per workstation on the server.
 */
import { canOpenPanel, PANEL_BY_ID } from '@/modules/registry';

export type WorkstationKey = 'call_taking' | 'dispatch' | 'radio' | 'management' | 'admin' | 'training';

/** Default layout description: columns of tab groups (first panel of a group is active). */
export interface DefaultLayout {
  /** `width` (px) applies to columns after the first; the first column takes the rest. */
  columns: { groups: string[][]; width?: number }[];
}

export interface Workstation {
  key: WorkstationKey;
  title: string;
  shortcut: string;
  permission: string;
  layout: DefaultLayout;
}

export const WORKSTATIONS: readonly Workstation[] = [
  {
    key: 'call_taking', title: 'Einsatzannahme', shortcut: 'F2', permission: 'calls.handle',
    layout: { columns: [
      { groups: [['emergency-calls']] },
      { groups: [['incidents'], ['active-calls', 'map', 'system-messages', 'module-status']], width: 620 },
    ] },
  },
  {
    key: 'dispatch', title: 'Disposition', shortcut: 'F3', permission: 'incidents.write',
    layout: { columns: [
      { groups: [['incidents']] },
      { groups: [['map', 'vehicles', 'status-board'], ['emergency-calls', 'active-calls', 'talk-requests', 'alarms', 'system-messages', 'audit-log']], width: 560 },
    ] },
  },
  {
    key: 'radio', title: 'Funk', shortcut: 'F4', permission: 'radio.handle',
    layout: { columns: [
      { groups: [['talk-requests'], ['radio-groups']] },
      { groups: [['status-board', 'vehicles'], ['system-messages']] },
    ] },
  },
  {
    key: 'management', title: 'Verwaltung', shortcut: 'F5', permission: 'control_centers.read',
    layout: { columns: [
      { groups: [['vehicle-admin', 'stations', 'rics', 'alarm-groups', 'radio-groups'], ['import']] },
      { groups: [['alarm-rules', 'proposal-settings', 'keywords', 'control-centers', 'areas', 'organizations', 'vehicle-types', 'status-definitions', 'interfaces'], ['audit-log', 'module-status', 'system-messages']] },
    ] },
  },
  {
    key: 'admin', title: 'Administrator', shortcut: 'F6', permission: 'system.admin',
    layout: { columns: [
      { groups: [['users', 'roles', 'login-log']] },
      { groups: [['control-centers', 'areas', 'keywords', 'alarm-rules', 'proposal-settings', 'organizations', 'vehicle-types', 'status-definitions', 'import']] },
      { groups: [['interfaces', 'ai-settings', 'audit-log'], ['module-status', 'system-messages']] },
    ] },
  },
  {
    key: 'training', title: 'Ausbildung', shortcut: 'F7', permission: 'training.participate',
    layout: { columns: [
      { groups: [['training-call', 'training-monitor', 'training-scenarios']] },
      { groups: [['emergency-calls', 'incidents'], ['map', 'training-reports', 'active-calls', 'system-messages']], width: 620 },
    ] },
  },
];

export function availableWorkstations(permissions: readonly string[]): Workstation[] {
  return WORKSTATIONS.filter((w) => permissions.includes(w.permission));
}

/** Default layout reduced to the panels the user may open. */
export function permittedLayout(ws: Workstation, permissions: readonly string[]): DefaultLayout {
  const allowed = (id: string) => {
    const def = PANEL_BY_ID.get(id);
    return !!def && canOpenPanel(def, permissions);
  };
  const columns = ws.layout.columns
    .map((c) => ({ ...c, groups: c.groups.map((g) => g.filter(allowed)).filter((g) => g.length > 0) }))
    .filter((c) => c.groups.length > 0);
  return { columns: columns.length ? columns : [{ groups: [['system-messages']] }] };
}
