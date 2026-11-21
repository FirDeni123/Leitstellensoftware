/** Labels and pure helpers for the alarming module (unit tested). */
import type { Alarm, AlarmPreview, AlarmSelection, DeliveryStatus, RuleItemKind } from '@/api/types';

export const DELIVERY: Record<DeliveryStatus, { label: string; cls: string }> = {
  simulated: { label: 'simuliert', cls: 'info' },
  sent: { label: 'übertragen', cls: 'ok' },
  failed: { label: 'fehlgeschlagen', cls: 'danger' },
  skipped: { label: 'nicht übertragen', cls: '' },
  not_delivered: { label: 'nicht zugestellt', cls: 'warn' },
  pending: { label: 'ausstehend', cls: 'warn' },
};

export const ALARM_KIND: Record<Alarm['kind'], string> = {
  initial: 'Erstalarm',
  follow_up: 'Nachalarmierung',
  manual: 'Alarmierung',
};

export const ALARM_STATUS: Record<Alarm['status'], { label: string; cls: string }> = {
  pending: { label: 'Zustellung läuft', cls: 'warn' },
  completed: { label: 'abgeschlossen', cls: 'ok' },
  partial: { label: 'teilweise fehlgeschlagen', cls: 'danger' },
};

export const TARGET_TYPE: Record<string, string> = {
  vehicle: 'Fahrzeug',
  station: 'Wache',
  ric: 'RIC',
  interface: 'Schnittstelle',
};

export const RULE_KIND: Record<RuleItemKind, string> = {
  vehicle_type: 'Fahrzeugtyp',
  vehicle: 'Fahrzeug',
  station: 'Wache',
  ric: 'RIC',
  alarm_group: 'Alarmierungsgruppe',
  interface: 'Schnittstelle',
};

export const EFFECT: Record<AlarmPreview['interfaces'][number]['effect'], { label: string; cls: string }> = {
  deliver: { label: 'REAL', cls: 'danger' },
  simulate: { label: 'Simulation', cls: 'info' },
  redirect: { label: 'umgeleitet', cls: 'warn' },
  skip: { label: 'deaktiviert', cls: '' },
};

/** Toggle one id in a selection list. */
export function toggle(list: readonly string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

/** True if at least one target is selected (the server rejects empty alarms as well). */
export function hasTargets(selection: AlarmSelection): boolean {
  return selection.vehicle_ids.length + selection.station_ids.length + selection.ric_ids.length + selection.interface_ids.length > 0;
}

/** Count delivery results of an alarm per status (for the protocol summary). */
export function deliverySummary(alarm: Pick<Alarm, 'targets'>): string {
  const counts = new Map<DeliveryStatus, number>();
  for (const t of alarm.targets) counts.set(t.delivery_status, (counts.get(t.delivery_status) ?? 0) + 1);
  return [...counts.entries()].map(([status, n]) => `${n} ${DELIVERY[status].label}`).join(' · ');
}

/** A fresh key per confirmed alarm dialog – retries of the same request reuse it. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
