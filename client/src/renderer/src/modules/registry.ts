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
  // ---- implemented in phase 2 (administration) -------------------------------------------
  { id: 'control-centers', title: 'Leitstellen', permission: 'control_centers.read', phase: 2, implemented: true },
  { id: 'areas', title: 'Zuständigkeitsbereiche', permission: 'control_centers.read', phase: 2, implemented: true },
  { id: 'stations', title: 'Wachen', permission: 'master_data.read', phase: 2, implemented: true },
  { id: 'vehicle-admin', title: 'Fahrzeugverwaltung', permission: 'master_data.read', phase: 2, implemented: true },
  { id: 'rics', title: 'RICs', permission: 'master_data.read', phase: 2, implemented: true },
  { id: 'alarm-groups', title: 'Alarmierungsgruppen', permission: 'master_data.read', phase: 2, implemented: true },
  { id: 'radio-groups', title: 'Funkrufgruppen', permission: 'master_data.read', phase: 2, implemented: true },
  { id: 'organizations', title: 'Organisationen', permission: 'master_data.read', phase: 2, implemented: true },
  { id: 'vehicle-types', title: 'Fahrzeugtypen', permission: 'master_data.read', phase: 2, implemented: true },
  { id: 'status-definitions', title: 'Statusbezeichnungen', permission: 'master_data.read', phase: 2, implemented: true },
  { id: 'import', title: 'Datenimport', permission: 'data.import', phase: 2, implemented: true },
  { id: 'roles', title: 'Rollen & Rechte', permission: 'users.read', phase: 2, implemented: true },
  { id: 'login-log', title: 'Anmeldeprotokoll', permission: 'login_log.read', phase: 2, implemented: true },
  { id: 'keywords', title: 'Einsatzstichworte', permission: 'master_data.read', phase: 3, implemented: true },
  // ---- implemented in phase 3 (operations) -----------------------------------------------
  { id: 'emergency-calls', title: 'Neue Notrufe', permission: 'calls.handle', phase: 3, implemented: true },
  { id: 'active-calls', title: 'Laufende Telefonate', permission: 'calls.handle', phase: 3, implemented: true },
  { id: 'incidents', title: 'Aktuelle Einsätze', permission: 'incidents.read', phase: 3, implemented: true },
  // ---- implemented in phase 4 (alarming) -------------------------------------------------
  { id: 'alarms', title: 'Alarmierungsübersicht', permission: 'incidents.read', phase: 4, implemented: true },
  { id: 'alarm-rules', title: 'Alarmierungsregeln (AAO)', permission: 'master_data.read', phase: 4, implemented: true },
  { id: 'interfaces', title: 'Schnittstellen', permission: 'interfaces.read', phase: 4, implemented: true },
  // ---- implemented in phase 5 (Einsatzmittelvorschlag) -----------------------------------
  { id: 'proposal-settings', title: 'Vorschlagsregeln', permission: 'master_data.read', phase: 5, implemented: true },
  // ---- implemented in phase 6 (fleet, map, simulation) -----------------------------------
  { id: 'map', title: 'Karte', permission: 'incidents.read', phase: 6, implemented: true },
  { id: 'vehicles', title: 'Fahrzeugübersicht', permission: 'incidents.read', phase: 6, implemented: true },
  { id: 'status-board', title: 'Statusübersicht', permission: 'incidents.read', phase: 6, implemented: true },
  { id: 'talk-requests', title: 'Sprechwünsche', permission: 'radio.handle', phase: 6, implemented: true },
  // ---- implemented in phase 7 (training, AI caller) --------------------------------------
  { id: 'training-call', title: 'Übungsgespräch', permission: 'training.participate', phase: 7, implemented: true },
  { id: 'training-monitor', title: 'Ausbildung (Beobachten)', permission: 'training.instructor', phase: 7, implemented: true },
  { id: 'training-scenarios', title: 'Übungsszenarien', permission: 'training.instructor', phase: 7, implemented: true },
  { id: 'training-reports', title: 'Übungsberichte', permission: 'training.participate', phase: 7, implemented: true },
  { id: 'ai-settings', title: 'KI-Einstellungen', permission: 'system.admin', phase: 7, implemented: true },
];

export const PANEL_BY_ID = new Map(PANELS.map((p) => [p.id, p]));

export function canOpenPanel(panel: PanelDefinition, permissions: readonly string[]): boolean {
  return !panel.permission || permissions.includes(panel.permission);
}

export type ComponentMap = Record<string, FunctionComponent<{ params?: Record<string, unknown> }>>;
