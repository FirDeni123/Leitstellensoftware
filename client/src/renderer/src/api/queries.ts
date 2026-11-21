/**
 * Server data access via TanStack Query. Realtime events invalidate the matching query
 * keys, so every connected dispatcher sees changes within milliseconds without polling.
 */
import { QueryClient, useQuery } from '@tanstack/react-query';
import { onRealtimeEvent, onResync, useSession } from '@/state/session';
import { ApiClient, ApiError } from './http';
import type {
  ActiveAssignment, AuditPage, Call, ControlCenter, Incident, IncidentEvent, IncidentSummary, LoginEvent, Page, Permission,
  Role, SystemInfo, User,
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
  'system.mode_changed': [['system-info']],
  'incident.changed': [['incidents'], ['incident-events'], ['active-assignments']],
  'call.changed': [['calls'], ['incidents']],
};

export function keysForTopic(topic: string): readonly (readonly string[])[] {
  return TOPIC_INVALIDATIONS[topic] ?? [];
}

export function installRealtimeInvalidation(client: QueryClient): () => void {
  const offEvent = onRealtimeEvent((event) => {
    for (const key of keysForTopic(event.topic)) void client.invalidateQueries({ queryKey: key });
    // Generic master data event: the payload names the affected collection.
    const collection = event.data['collection'];
    if (event.topic === 'master_data.changed' && typeof collection === 'string') {
      void client.invalidateQueries({ queryKey: [collection] });
    }
  });
  // After a reconnect everything might be stale.
  const offResync = onResync(() => void client.invalidateQueries());
  return () => {
    offEvent();
    offResync();
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
