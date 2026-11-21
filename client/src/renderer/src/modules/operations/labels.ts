/** Shared labels and helpers of the operational modules (calls, incidents). */
import { useEffect, useState } from 'react';
import type { CallStatus, IncidentStatus, IncidentType } from '@/api/types';
import { useSession } from '@/state/session';

export const INCIDENT_STATUS: { key: IncidentStatus; label: string; cls: string }[] = [
  { key: 'new', label: 'Neu', cls: 'danger' },
  { key: 'in_progress', label: 'In Bearbeitung', cls: 'warn' },
  { key: 'alarmed', label: 'Alarmiert', cls: 'accent' },
  { key: 'en_route', label: 'Anfahrt', cls: 'accent' },
  { key: 'on_scene', label: 'Am Einsatzort', cls: 'info' },
  { key: 'finished', label: 'Einsatz beendet', cls: 'ok' },
  { key: 'closed', label: 'Abgeschlossen', cls: '' },
];
export const STATUS_BY_KEY = Object.fromEntries(INCIDENT_STATUS.map((s) => [s.key, s])) as Record<IncidentStatus, (typeof INCIDENT_STATUS)[number]>;

export const INCIDENT_TYPE: Record<IncidentType, string> = {
  fire: 'Brand', technical: 'Technische Hilfe', ems: 'Rettungsdienst', hazmat: 'Gefahrstoff', water: 'Wasserrettung', other: 'Sonstiges',
};

export const PRIORITY: Record<number, { label: string; cls: string }> = {
  1: { label: 'P1 kritisch', cls: 'danger' },
  2: { label: 'P2 dringend', cls: 'warn' },
  3: { label: 'P3 normal', cls: '' },
};

export const CALL_STATUS: Record<CallStatus, { label: string; cls: string }> = {
  ringing: { label: 'Klingelt', cls: 'danger pulse-badge' },
  active: { label: 'Im Gespräch', cls: 'ok' },
  on_hold: { label: 'Gehalten', cls: 'warn' },
  ended: { label: 'Beendet', cls: '' },
};

/** Current time synchronised with the server clock; re-renders every `intervalMs`. */
export function useNow(intervalMs = 1000): number {
  const offset = useSession((s) => s.serverTimeOffsetMs);
  const [now, setNow] = useState(() => Date.now() + offset);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() + offset), intervalMs);
    return () => clearInterval(id);
  }, [offset, intervalMs]);
  return now;
}

/** Elapsed time as m:ss (under one hour) or h:mm h. */
export function elapsed(fromIso: string, now: number): string {
  const s = Math.max(0, Math.floor((now - new Date(fromIso).getTime()) / 1000));
  if (s < 3600) return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  return `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')} h`;
}

/** Standard follow-up questions of the call taking (W-Fragen). */
export const STANDARD_QUESTIONS = [
  'Wo genau ist der Notfallort?',
  'Was ist passiert?',
  'Wie viele Personen sind betroffen?',
  'Welche Verletzungen / Beschwerden?',
  'Besteht eine Gefahr (Feuer, Rauch, Gas, Strom)?',
  'Wer ruft an – Rückrufnummer?',
] as const;
