import { Component, type ErrorInfo, type ReactNode } from 'react';
import { EmptyState } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { canOpenPanel, type PanelDefinition } from './registry';
import { useSession } from '@/state/session';
import { CrudPanel } from './crud/CrudPanel';
import * as md from './masterdata/configs';
import { AlarmRulesPanel } from './alarming/AlarmRulesPanel';
import { AlarmsPanel } from './alarming/AlarmsPanel';
import { InterfacesPanel } from './alarming/InterfacesPanel';
import { StatusBoardPanel } from './fleet/StatusBoardPanel';
import { TalkRequestsPanel } from './fleet/TalkRequestsPanel';
import { VehiclesPanel } from './fleet/VehiclesPanel';
import { MapPanel } from './map/MapPanel';
import { ActiveCallsPanel } from './operations/ActiveCallsPanel';
import { ProposalSettingsPanel } from './proposal/ProposalSettingsPanel';
import { CallsPanel } from './operations/CallsPanel';
import { IncidentsPanel } from './operations/IncidentsPanel';
import { AuditLogPanel } from './panels/AuditLogPanel';
import { ImportPanel } from './panels/ImportPanel';
import { LoginLogPanel } from './panels/LoginLogPanel';
import { RolesPanel } from './panels/RolesPanel';
import { ControlCentersPanel } from './panels/ControlCentersPanel';
import { ModuleStatusPanel } from './panels/ModuleStatusPanel';
import { PlannedPanel } from './panels/PlannedPanel';
import { SystemMessagesPanel } from './panels/SystemMessagesPanel';
import { UsersPanel } from './panels/UsersPanel';
import { AiSettingsPanel } from './training/AiSettingsPanel';
import { ScenariosPanel } from './training/ScenariosPanel';
import { TrainingCallPanel } from './training/TrainingCallPanel';
import { TrainingMonitorPanel } from './training/TrainingMonitorPanel';
import { TrainingReportsPanel } from './training/TrainingReportsPanel';

const IMPLEMENTED: Record<string, () => ReactNode> = {
  'emergency-calls': () => <CallsPanel />,
  'active-calls': () => <ActiveCallsPanel />,
  incidents: () => <IncidentsPanel />,
  alarms: () => <AlarmsPanel />,
  'alarm-rules': () => <AlarmRulesPanel />,
  interfaces: () => <InterfacesPanel />,
  'proposal-settings': () => <ProposalSettingsPanel />,
  map: () => <MapPanel />,
  vehicles: () => <VehiclesPanel />,
  'status-board': () => <StatusBoardPanel />,
  'talk-requests': () => <TalkRequestsPanel />,
  'training-call': () => <TrainingCallPanel />,
  'training-monitor': () => <TrainingMonitorPanel />,
  'training-scenarios': () => <ScenariosPanel />,
  'training-reports': () => <TrainingReportsPanel />,
  'ai-settings': () => <AiSettingsPanel />,
  keywords: () => <CrudPanel config={md.KEYWORDS} />,
  stations: () => <CrudPanel config={md.STATIONS} />,
  'vehicle-admin': () => <CrudPanel config={md.VEHICLES} />,
  rics: () => <CrudPanel config={md.RICS} />,
  'alarm-groups': () => <CrudPanel config={md.ALARM_GROUPS} />,
  'radio-groups': () => <CrudPanel config={md.RADIO_GROUPS} />,
  organizations: () => <CrudPanel config={md.ORGANIZATIONS} />,
  'vehicle-types': () => <CrudPanel config={md.VEHICLE_TYPES} />,
  'status-definitions': () => <CrudPanel config={md.STATUS_DEFINITIONS} />,
  areas: () => <CrudPanel config={md.AREAS} />,
  import: () => <ImportPanel />,
  roles: () => <RolesPanel />,
  'login-log': () => <LoginLogPanel />,
  'system-messages': () => <SystemMessagesPanel />,
  'audit-log': () => <AuditLogPanel />,
  'module-status': () => <ModuleStatusPanel />,
  users: () => <UsersPanel />,
  'control-centers': () => <ControlCentersPanel />,
};

/** Isolates panel crashes: one faulty module must never take down the whole workstation. */
class PanelErrorBoundary extends Component<{ title: string; children: ReactNode }, { error: Error | null }> {
  override state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  override componentDidCatch(error: Error, info: ErrorInfo) {
    sysmsg('error', this.props.title, `Modulfehler: ${error.message}`);
    console.error(error, info.componentStack);
  }
  override render() {
    if (this.state.error) {
      return (
        <EmptyState title="Dieses Modul ist auf einen Fehler gestoßen">
          <div className="mono" style={{ fontSize: 'var(--fs-xs)' }}>{this.state.error.message}</div>
          <button className="btn sm" onClick={() => this.setState({ error: null })}>Neu laden</button>
        </EmptyState>
      );
    }
    return this.props.children;
  }
}

export function PanelHost({ definition }: { definition: PanelDefinition }): ReactNode {
  const permissions = useSession((s) => s.me?.permissions ?? []);
  if (!canOpenPanel(definition, permissions)) {
    return <EmptyState title="Keine Berechtigung">Für „{definition.title}" fehlt die Berechtigung {definition.permission}.</EmptyState>;
  }
  const render = IMPLEMENTED[definition.id];
  return (
    <PanelErrorBoundary title={definition.title}>
      {definition.implemented && render ? render() : <PlannedPanel definition={definition} />}
    </PanelErrorBoundary>
  );
}
