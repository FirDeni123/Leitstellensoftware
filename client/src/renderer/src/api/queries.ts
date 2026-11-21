/**
 * Server data access via TanStack Query. Realtime events invalidate the matching query
 * keys, so every connected dispatcher sees changes within milliseconds without polling.
 */
import { QueryClient, useQuery } from '@tanstack/react-query';
import { onRealtimeEvent, onResync, useSession } from '@/state/session';
import { ApiClient, ApiError } from './http';
import type {
  ActiveAssignment, Alarm, AlarmRule, AuditPage, Call, ControlCenter, Incident, IncidentEvent, IncidentSummary, InterfaceEventItem,
  FleetVehicle, InterfaceItem, LoginEvent, MapConfig, Movement, Page, Permission, PluginInfo, PoliceNotice, ProposalSettings, Role,
  SimulationClock, StatusDefinition, StatusHistoryEntry, SystemInfo, TalkRequest, User,
  AiSettings, TrainingScenario, TrainingSessionDetail, TrainingSessionSummary,
} from './types';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Retry only transient failures (network, 5xx) – never 4xx.
      retry: (count, error) => count < 2 && (!(error instanceof ApiError) || error.status === 0 || error.status >= 500),
      refetchOnWindowFocus: false,
    },
  },
});

/** Realtime topic -> affected query keys. */
export const TOPIC_INVALIDATIONS: Record<string, readonly (readonly string[])[]> = {
  'user.created': [['users']],
  'user.updated': [['users']],
  'role.changed': [['roles'], ['users']],
  'control_center.changed': [['control-centers']],
  'audit.created': [['audit'], ['import-jobs']],
  'system.mode_changed': [['system-info'], ['interfaces'], ['operation-mode']],
  'incident.changed': [['incidents'], ['incident-events'], ['active-assignments'], ['proposals']],
  'call.changed': [['calls'], ['incidents']],
  'alarm.changed': [['alarms'], ['incident-events'], ['incidents']],
  'police_notice.changed': [['police-notices'], ['alarms'], ['incident-events']],
  'interface.changed': [['interfaces'], ['interface-events']],
  'vehicle.status_changed': [['fleet'], ['incidents'], ['active-assignments'], ['status-history'], ['movements']],
  'movement.changed': [['movements'], ['fleet']],
  'talk_request.changed': [['talk-requests'], ['fleet'], ['incident-events']],
  'simulation.clock_changed': [['simulation-clock']],
  'training.session_changed': [['training-sessions'], ['training-session'], ['calls']],
  'training.message': [['training-session']],
  'training.pending_changed': [['training-session']],
  'training.scenario_changed': [['training-scenarios']],
  'training.ai_settings_changed': [['ai-settings']],
};

export function keysForTopic(topic: string): readonly (readonly string[])[] {
  return TOPIC_INVALIDATIONS[topic] ?? [];
}

/**
 * Coalesces realtime invalidations per query key: events within `delayMs` are merged, a
 * running refetch is never cancelled (cancelling under a steady stream of events would starve
 * the query), and if more events arrive while it runs, exactly one more refetch follows.
 * `isBusy`: a fetch of the key started elsewhere (e.g. a window just mounted) may predate the
 * event – invalidating then would only join that fetch and keep its old result, so the
 * invalidation waits until it has finished and then fetches anew.
 */
export function createInvalidationScheduler(
  invalidate: (key: readonly string[]) => Promise<unknown>,
  delayMs = 200,
  isBusy: (key: readonly string[]) => boolean = () => false,
): { request(key: readonly string[]): void; dispose(): void } {
  const state = new Map<string, { timer: ReturnType<typeof setTimeout> | null; dirty: boolean; running: boolean }>();
  const flush = async (id: string, key: readonly string[]) => {
    const entry = state.get(id)!;
    entry.timer = null;
    if (!entry.dirty) return;
    if (isBusy(key)) {
      entry.timer = setTimeout(() => void flush(id, key), Math.min(delayMs, 100) || 1);
      return;
    }
    entry.dirty = false;
    entry.running = true;
    try {
      await invalidate(key);
    } catch {
      /* errors surface in the query itself */
    } finally {
      entry.running = false;
    }
    if (entry.dirty && !entry.timer) entry.timer = setTimeout(() => void flush(id, key), delayMs);
  };
  return {
    request(key) {
      const id = JSON.stringify(key);
      const entry = state.get(id) ?? { timer: null, dirty: false, running: false };
      state.set(id, entry);
      entry.dirty = true;
      if (!entry.timer && !entry.running) entry.timer = setTimeout(() => void flush(id, key), delayMs);
    },
    dispose() {
      for (const entry of state.values()) if (entry.timer) clearTimeout(entry.timer);
      state.clear();
    },
  };
}

export function installRealtimeInvalidation(client: QueryClient): () => void {
  const scheduler = createInvalidationScheduler(
    (key) => client.invalidateQueries({ queryKey: key }, { cancelRefetch: false }),
    200,
    (key) => client.isFetching({ queryKey: key }) > 0,
  );
  const offEvent = onRealtimeEvent((event) => {
    for (const key of keysForTopic(event.topic)) scheduler.request(key);
    // Generic master data event: the payload names the affected collection.
    const collection = event.data['collection'];
    if (event.topic === 'master_data.changed' && typeof collection === 'string') scheduler.request([collection]);
  });
  // After a reconnect everything might be stale.
  const offResync = onResync(() => void client.invalidateQueries());
  return () => {
    offEvent();
    offResync();
    scheduler.dispose();
  };
}

function useApi(): ApiClient {
  const api = useSession((s) => s.api);
  if (!api) throw new Error('Nicht angemeldet');
  return api;
}

/** Generic list query for a REST collection; key = [collection, params]. */
export function useList<T>(collection: string, path: string, params: Record<string, string | undefined> = {}, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: [collection, params],
    queryFn: () => api.get<T[]>(path, params),
    enabled,
  });
}

export function useCalls(controlCenterId: string | undefined, includeEnded = false) {
  const api = useApi();
  return useQuery({
    queryKey: ['calls', controlCenterId, includeEnded],
    queryFn: () => api.get<Call[]>('/calls', { control_center_id: controlCenterId, include_ended: includeEnded || undefined }),
    enabled: !!controlCenterId,
    staleTime: 5_000,
  });
}

export function useIncidents(controlCenterId: string | undefined, scope: 'open' | 'closed' | 'all', q = '') {
  const api = useApi();
  return useQuery({
    queryKey: ['incidents', 'list', controlCenterId, scope, q],
    queryFn: () => api.get<IncidentSummary[]>('/incidents', { control_center_id: controlCenterId, scope, q }),
    enabled: !!controlCenterId,
    staleTime: 5_000,
  });
}

export function useIncident(id: string | null) {
  const api = useApi();
  return useQuery({ queryKey: ['incidents', 'detail', id], queryFn: () => api.get<Incident>(`/incidents/${id}`), enabled: !!id });
}

export function useIncidentEvents(id: string | null) {
  const api = useApi();
  return useQuery({ queryKey: ['incident-events', id], queryFn: () => api.get<IncidentEvent[]>(`/incidents/${id}/events`), enabled: !!id });
}

export function useActiveAssignments(controlCenterId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: ['active-assignments', controlCenterId],
    queryFn: () => api.get<ActiveAssignment[]>('/incidents/active-assignments', { control_center_id: controlCenterId }),
    enabled: !!controlCenterId,
  });
}

export function useSystemInfo() {
  const api = useApi();
  return useQuery({ queryKey: ['system-info'], queryFn: () => api.get<SystemInfo>('/system/info') });
}

export function useUsers(q: string) {
  const api = useApi();
  return useQuery({ queryKey: ['users', q], queryFn: () => api.get<Page<User>>('/users', { q, limit: 500 }) });
}

export function useRoles() {
  const api = useApi();
  return useQuery({ queryKey: ['roles'], queryFn: () => api.get<Role[]>('/roles') });
}

export function usePermissions() {
  const api = useApi();
  return useQuery({ queryKey: ['permissions'], queryFn: () => api.get<Permission[]>('/permissions'), staleTime: Infinity });
}

export function useControlCenters() {
  const api = useApi();
  return useQuery({ queryKey: ['control-centers'], queryFn: () => api.get<ControlCenter[]>('/control-centers') });
}

export function useAudit(entityType: string) {
  const api = useApi();
  return useQuery({
    queryKey: ['audit', entityType],
    queryFn: () => api.get<AuditPage>('/audit', { entity_type: entityType || undefined, limit: 300 }),
  });
}

export function useLoginEvents(enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: ['login-events'],
    queryFn: () => api.get<LoginEvent[]>('/login-events', { limit: 200 }),
    enabled,
  });
}

// ---------------------------------------------------------------------------- Phase 4: alarming
export function useAlarms(controlCenterId: string | undefined, incidentId?: string) {
  const api = useApi();
  return useQuery({
    queryKey: ['alarms', controlCenterId, incidentId ?? null],
    queryFn: () => (incidentId
      ? api.get<Alarm[]>(`/incidents/${incidentId}/alarms`)
      : api.get<Alarm[]>('/alarms', { control_center_id: controlCenterId, limit: 200 })),
    enabled: !!controlCenterId || !!incidentId,
    staleTime: 5_000,
  });
}

export function usePoliceNotices(controlCenterId: string | undefined, onlyOpen = true) {
  const api = useApi();
  return useQuery({
    queryKey: ['police-notices', controlCenterId, onlyOpen],
    queryFn: () => api.get<PoliceNotice[]>('/police-notices', { control_center_id: controlCenterId, only_open: onlyOpen }),
    enabled: !!controlCenterId,
    staleTime: 5_000,
  });
}

export function useAlarmRules(controlCenterId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: ['alarm-rules', controlCenterId],
    queryFn: () => api.get<AlarmRule[]>('/alarm-rules', { control_center_id: controlCenterId }),
    enabled: !!controlCenterId,
  });
}

export function usePlugins() {
  const api = useApi();
  return useQuery({ queryKey: ['plugins'], queryFn: () => api.get<PluginInfo[]>('/plugins'), staleTime: Infinity });
}

export function useInterfaces(controlCenterId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: ['interfaces', controlCenterId],
    queryFn: () => api.get<InterfaceItem[]>('/interfaces', { control_center_id: controlCenterId }),
  });
}

export function useInterfaceEvents(id: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: ['interface-events', id],
    queryFn: () => api.get<InterfaceEventItem[]>(`/interfaces/${id}/events`, { limit: 100 }),
    enabled: !!id,
  });
}

// ---------------------------------------------------------------------- Phase 5: proposal
export function useProposalSettings(controlCenterId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: ['proposal-settings', controlCenterId],
    queryFn: () => api.get<ProposalSettings>('/proposal-settings', { control_center_id: controlCenterId }),
    enabled: !!controlCenterId,
  });
}

// ------------------------------------------------------------------- Phase 6: fleet & map
export function useFleet(controlCenterId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: ['fleet', controlCenterId],
    queryFn: () => api.get<FleetVehicle[]>('/fleet', { control_center_id: controlCenterId }),
    enabled: !!controlCenterId,
    staleTime: 10_000,
  });
}

export function useMovements(controlCenterId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: ['movements', controlCenterId],
    queryFn: () => api.get<Movement[]>('/movements', { control_center_id: controlCenterId }),
    enabled: !!controlCenterId,
  });
}

export function useStatusDefinitions() {
  const api = useApi();
  return useQuery({ queryKey: ['vehicle-status'], queryFn: () => api.get<StatusDefinition[]>('/vehicle-status-definitions'), staleTime: 60_000 });
}

export function useStatusHistory(vehicleId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: ['status-history', vehicleId],
    queryFn: () => api.get<StatusHistoryEntry[]>(`/vehicles/${vehicleId}/status-history`, { limit: 50 }),
    enabled: !!vehicleId,
  });
}

export function useTalkRequests(controlCenterId: string | undefined, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: ['talk-requests', controlCenterId],
    queryFn: () => api.get<TalkRequest[]>('/talk-requests', { control_center_id: controlCenterId }),
    enabled: enabled && !!controlCenterId,
    staleTime: 5_000,
  });
}

export function useMapConfig(controlCenterId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: ['map-config', controlCenterId],
    queryFn: () => api.get<MapConfig>('/map/config', { control_center_id: controlCenterId }),
    staleTime: Infinity,
  });
}

export function useSimulationClock() {
  const api = useApi();
  return useQuery({ queryKey: ['simulation-clock'], queryFn: () => api.get<SimulationClock>('/simulation/clock') });
}

export function useTrainingScenarios(controlCenterId: string | undefined, includeInactive = false) {
  const api = useApi();
  return useQuery({
    queryKey: ['training-scenarios', controlCenterId, includeInactive],
    queryFn: () => api.get<TrainingScenario[]>('/training/scenarios', { control_center_id: controlCenterId, include_inactive: includeInactive || undefined }),
    enabled: !!controlCenterId,
  });
}

export function useTrainingSessions(params: { controlCenterId?: string; status?: string; mine?: boolean }, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: ['training-sessions', params],
    queryFn: () => api.get<TrainingSessionSummary[]>('/training/sessions', {
      control_center_id: params.controlCenterId, status: params.status, mine: params.mine || undefined,
    }),
    enabled,
    staleTime: 5_000,
  });
}

export function useTrainingSession(id: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: ['training-session', id],
    queryFn: () => api.get<TrainingSessionDetail>(`/training/sessions/${id}`),
    enabled: !!id,
    staleTime: 2_000,
  });
}

export function useAiSettings(enabled = true) {
  const api = useApi();
  return useQuery({ queryKey: ['ai-settings'], queryFn: () => api.get<AiSettings>('/training/ai-settings'), enabled });
}
