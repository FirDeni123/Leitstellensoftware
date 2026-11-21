/**
 * Session state: server connection, logged-in user, API and realtime clients.
 * Tokens live only in memory (ApiClient) – never in localStorage or on disk.
 */
import { create } from 'zustand';
import { ApiClient, describeError } from '@/api/http';
import { RealtimeClient, websocketUrl, type RealtimeEvent, type RealtimeState } from '@/api/realtime';
import type { Me, SystemInfo, TokenResponse } from '@/api/types';
import { platform } from '@/platform/bridge';
import { sysmsg } from './messages';

export type EventListener = (event: RealtimeEvent) => void;

interface SessionState {
  serverUrl: string;
  api: ApiClient | null;
  realtime: RealtimeClient | null;
  me: Me | null;
  systemInfo: SystemInfo | null;
  rtState: RealtimeState;
  rtDetail: string | null;
  latencyMs: number | null;
  serverTimeOffsetMs: number;
  workstation: string;
  logoutReason: string | null;

  createApi(serverUrl: string): ApiClient;
  completeLogin(api: ApiClient, tokens: TokenResponse, workstation: string): void;
  setMe(me: Me): void;
  setSystemInfo(info: SystemInfo): void;
  setWorkstation(ws: string): void;
  logout(reason?: string): Promise<void>;
}

const listeners = new Set<EventListener>();
const resyncListeners = new Set<() => void>();

/** Subscribe to realtime events (used by the query invalidation layer and panels). */
export function onRealtimeEvent(listener: EventListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function onResync(listener: () => void): () => void {
  resyncListeners.add(listener);
  return () => resyncListeners.delete(listener);
}

let refreshTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleProactiveRefresh(api: ApiClient, expiresAt: string): void {
  if (refreshTimer) clearTimeout(refreshTimer);
  const ms = Math.max(10_000, new Date(expiresAt).getTime() - Date.now() - 60_000);
  refreshTimer = setTimeout(() => void api.refresh(), ms);
}

export const useSession = create<SessionState>((set, get) => ({
  serverUrl: '',
  api: null,
  realtime: null,
  me: null,
  systemInfo: null,
  rtState: 'idle',
  rtDetail: null,
  latencyMs: null,
  serverTimeOffsetMs: 0,
  workstation: 'dispatch',
  logoutReason: null,

  createApi(serverUrl) {
    const api = new ApiClient({
      baseUrl: serverUrl,
      onTokens: (tokens) => {
        get().setMe(tokens.user);
        scheduleProactiveRefresh(api, tokens.access_token_expires_at);
        get().realtime?.reauthenticate();
      },
      onAuthLost: (reason) => void get().logout(reason),
    });
    set({ serverUrl });
    return api;
  },

  completeLogin(api, tokens, workstation) {
    api.setTokens(tokens);
    scheduleProactiveRefresh(api, tokens.access_token_expires_at);
    const realtime = new RealtimeClient({
      url: websocketUrl(api.baseUrl),
      getToken: () => api.token,
      refreshToken: () => api.refresh(),
      onEvent: (event) => listeners.forEach((l) => l(event)),
      onState: (rtState, detail) => {
        const prev = get().rtState;
        set({ rtState, rtDetail: detail ?? null });
        if (rtState === 'online' && prev === 'reconnecting') sysmsg('success', 'Verbindung', 'Verbindung zum Server wiederhergestellt');
        if (rtState === 'reconnecting' && prev === 'online') sysmsg('error', 'Verbindung', detail ?? 'Verbindung verloren');
      },
      onResync: (reason) => {
        if (reason === 'permissions_changed') {
          sysmsg('info', 'Berechtigungen', 'Ihre Berechtigungen wurden geändert und neu geladen');
        }
        void api.get<Me>('/auth/me').then((me) => get().setMe(me)).catch(() => undefined);
        resyncListeners.forEach((l) => l());
      },
      onSessionEnded: () => void get().logout('Die Sitzung wurde beendet. Bitte erneut anmelden.'),
      onLatency: (latencyMs, serverTime) =>
        set({ latencyMs, serverTimeOffsetMs: new Date(serverTime).getTime() + latencyMs / 2 - Date.now() }),
    });
    set({ api, realtime, me: tokens.user, workstation, logoutReason: null });
    realtime.start();
    sysmsg('info', 'Anmeldung', `Angemeldet als ${tokens.user.display_name}`);
  },

  setMe: (me) => set({ me }),
  setSystemInfo: (systemInfo) =>
    set({ systemInfo, serverTimeOffsetMs: new Date(systemInfo.server_time).getTime() - Date.now() }),
  setWorkstation(workstation) {
    set({ workstation });
    void platform.saveConfig({ lastWorkstation: workstation }).catch(() => undefined);
  },

  async logout(reason) {
    const { api, realtime } = get();
    if (refreshTimer) clearTimeout(refreshTimer);
    realtime?.stop();
    if (api?.token && !reason) {
      try {
        await api.post('/auth/logout');
      } catch (e) {
        sysmsg('warning', 'Abmeldung', describeError(e));
      }
    }
    api?.setTokens(null);
    set({ api: null, realtime: null, me: null, systemInfo: null, rtState: 'idle', logoutReason: reason ?? null });
  },
}));

export function hasPermission(me: Me | null, permission: string): boolean {
  return !!me && me.permissions.includes(permission);
}
