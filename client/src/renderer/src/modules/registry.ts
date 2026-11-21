/**
 * Module registry: every window ("Panel") of the dispatcher UI is registered here with
 * its title, required permission and implementation phase. New modules are added by
 * registering a component – the shell, menus and layouts pick them up automatically.
 */
import type { FunctionComponent } from 'react';

export interface PanelDefinition {
  id: string;
  title: string;
  /** Permission required to open the panel (undefined = every logged-in user). */
  permission?: string;
  /** Phase in which the module gets implemented; panels of later phases show a clear notice. */
  phase: number;
  implemented: boolean;
  /** Short description of the planned scope (shown for not yet implemented modules). */
  scope?: string[];
}

export const PANELS: readonly PanelDefinition[] = [
  // ---- implemented in phase 1 ----------------------------------------------------------
  { id: 'system-messages', title: 'Systemmeldungen', phase: 1, implemented: true },
  { id: 'audit-log', title: 'Ereignisprotokoll', permission: 'audit.read', phase: 1, implemented: true },
  { id: 'module-status', title: 'Modulstatus', phase: 1, implemented: true },
  { id: 'users', title: 'Benutzerverwaltung', permission: 'users.read', phase: 1, implemented: true },
  { id: 'control-centers', title: 'Leitstellen', permission: 'control_centers.read', phase: 2, implemented: true },
  // ---- planned modules (transparently marked) -------------------------------------------
  {
    id: 'incidents', title: 'Aktuelle Einsätze', permission: 'incidents.read', phase: 3, implemented: false,
    scope: ['Einsatzliste mit Status, Stichwort, Ort, Priorität', 'Einsatzdetail mit Verlauf und Dokumentation',
      'Fahrzeuge zuordnen, abziehen, umsetzen'],
  },
  {
    id: 'emergency-calls', title: 'Neue Notrufe', permission: 'calls.handle', phase: 3, implemented: false,
    scope: ['Anrufannahme und Priorisierung', 'Anruferdaten, Standort, Gesprächsnotizen',
      'Zuordnung zu bestehendem Einsatz oder neuer Einsatz'],
  },
  {
    id: 'active-calls', title: 'Laufende Telefonate', permission: 'calls.handle', phase: 7, implemented: false,
    scope: ['Simulierte Telefonie (Phase 3)', 'Sprachsimulation und VoIP-Anbindung (Phase 7)'],
  },
  {
    id: 'talk-requests', title: 'Sprechwünsche', permission: 'radio.handle', phase: 6, implemented: false,
    scope: ['Sprechwünsche nach Priorität', 'Annehmen, zurückstellen, ablehnen', 'Dokumentation mit Zeitstempel'],
  },
  {
    id: 'vehicles', title: 'Fahrzeugübersicht', permission: 'incidents.read', phase: 6, implemented: false,
    scope: ['Alle Fahrzeuge mit Status, Wache, Position', 'Filter nach Organisation und Wache'],
  },
  {
    id: 'status-board', title: 'Statusübersicht', permission: 'incidents.read', phase: 6, implemented: false,
    scope: ['FMS-Status 1–6 je Wache (Statustableau)', 'Statushistorie'],
  },
  {
    id: 'alarms', title: 'Alarmierungsübersicht', permission: 'alarm.trigger', phase: 4, implemented: false,
    scope: ['Alarmierungsvorschau und -bestätigung', 'Alarmierungsprotokoll', 'Polizei-Hinweise (keine Alarmierung)'],
  },
  {
    id: 'radio-groups', title: 'Funkgruppen', permission: 'radio.handle', phase: 2, implemented: false,
    scope: ['Funkrufgruppen je Wache/Organisation', 'Zuordnung von Fahrzeugen'],
  },
  {
    id: 'map', title: 'Karte', phase: 6, implemented: false,
    scope: ['OpenStreetMap-Karte mit Wachen, Fahrzeugen, Einsatzorten', 'Straßenbasierte Routen (OSRM)',
      'GPS-Simulation in Echtzeit'],
  },
];

export const PANEL_BY_ID = new Map(PANELS.map((p) => [p.id, p]));

export function canOpenPanel(panel: PanelDefinition, permissions: readonly string[]): boolean {
  return !panel.permission || permissions.includes(panel.permission);
}

export type ComponentMap = Record<string, FunctionComponent<{ params?: Record<string, unknown> }>>;
