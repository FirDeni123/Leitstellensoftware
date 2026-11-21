/**
 * Realtime client (WebSocket) with authentication, heartbeat and automatic reconnection.
 *
 * Reconnect strategy: exponential backoff (1 s, 2 s, 4 s … max 30 s) with ±20 % jitter so
 * that many clients don't reconnect in lock-step after a server restart. After every
 * (re)connect `onResync` fires – the application then reloads its data via REST, because
 * events emitted while offline are not replayed by the server.
 *
 * Server close codes: 4001 auth failed/expired (refresh token, reconnect), 4002
 * permissions changed (reconnect immediately), 4003 session ended (logout), 4008
 * overloaded (reconnect with backoff).
 */

export type RealtimeState = 'idle' | 'connecting' | 'online' | 'reconnecting' | 'closed';

export interface RealtimeEvent {
  id: string;
  topic: string;
  ts: string;
  data: Record<string, unknown>;
}

export interface RealtimeOptions {
  url: string;
  getToken: () => string | null;
  refreshToken: () => Promise<boolean>;
  onEvent: (event: RealtimeEvent) => void;
  onState?: (state: RealtimeState, detail?: string) => void;
  onResync?: (reason: 'connected' | 'permissions_changed') => void;
  onSessionEnded?: () => void;
  onLatency?: (ms: number, serverTime: string) => void;
  WebSocketImpl?: typeof WebSocket;
  heartbeatMs?: number;
  random?: () => number;
}

const MAX_BACKOFF_MS = 30_000;

export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** Math.max(0, attempt));
  return Math.round(base * (0.8 + random() * 0.4));
}

export class RealtimeClient {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private state: RealtimeState = 'idle';
  private stopped = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pongDeadline: ReturnType<typeof setTimeout> | null = null;
  private resyncReason: 'connected' | 'permissions_changed' = 'connected';

  constructor(private readonly opts: RealtimeOptions) {}

  get currentState(): RealtimeState {
    return this.state;
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close(1000, 'client stop');
      this.ws = null;
    }
    this.setState('closed');
  }

  /** Send a fresh access token on the open connection (after a token refresh). */
  reauthenticate(): void {
    const token = this.opts.getToken();
    if (token && this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify({ type: 'auth', token }));
  }

  private setState(state: RealtimeState, detail?: string): void {
    this.state = state;
    this.opts.onState?.(state, detail);
  }

  private connect(): void {
    const token = this.opts.getToken();
    if (!token) {
      this.setState('closed', 'Kein Token');
      return;
    }
    this.setState(this.attempt === 0 ? 'connecting' : 'reconnecting');
    const Impl = this.opts.WebSocketImpl ?? WebSocket;
    const ws = new Impl(this.opts.url);
    this.ws = ws;

    ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: this.opts.getToken() }));
    ws.onmessage = (msg: MessageEvent) => this.handleMessage(String(msg.data));
    ws.onerror = () => {
      /* followed by onclose */
    };
    ws.onclose = (ev: CloseEvent) => this.handleClose(ev.code, ev.reason);
  }

  private handleMessage(raw: string): void {
    let msg: { type: string; [k: string]: unknown };
    try {
      msg = JSON.parse(raw) as { type: string };
    } catch {
      return;
    }
    switch (msg.type) {
      case 'welcome':
        this.attempt = 0;
        this.setState('online');
        this.startHeartbeat();
        this.opts.onResync?.(this.resyncReason);
        this.resyncReason = 'connected';
        break;
      case 'event':
        this.opts.onEvent(msg as unknown as RealtimeEvent);
        break;
      case 'pong': {
        if (this.pongDeadline) clearTimeout(this.pongDeadline);
        this.pongDeadline = null;
        const sent = Number(msg['ts']);
        if (Number.isFinite(sent)) this.opts.onLatency?.(Date.now() - sent, String(msg['server_time']));
        break;
      }
      default:
        break;
    }
  }

  private async handleClose(code: number, reason: string): Promise<void> {
    this.clearTimers();
    this.ws = null;
    if (this.stopped) return;
    if (code === 4003) {
      this.setState('closed', 'Sitzung beendet');
      this.opts.onSessionEnded?.();
      return;
    }
    if (code === 4001) {
      // Token expired or revoked: try to refresh once, otherwise the session is gone.
      const ok = await this.opts.refreshToken();
      if (!ok) {
        this.setState('closed', 'Anmeldung abgelaufen');
        this.opts.onSessionEnded?.();
        return;
      }
    }
    if (code === 4002) {
      this.resyncReason = 'permissions_changed';
      this.attempt = 0;
      this.connect();
      return;
    }
    const delay = backoffDelay(this.attempt, this.opts.random);
    this.attempt += 1;
    this.setState('reconnecting', `Verbindung verloren (${reason || code}), neuer Versuch in ${Math.round(delay / 1000)} s`);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  private startHeartbeat(): void {
    const interval = this.opts.heartbeatMs ?? 15_000;
    this.heartbeatTimer = setInterval(() => {
      if (!this.ws || this.ws.readyState !== 1) return;
      this.ws.send(JSON.stringify({ type: 'ping', ts: Date.now() }));
      if (!this.pongDeadline) {
        // No pong within the interval: the connection is dead even if the socket looks open.
        this.pongDeadline = setTimeout(() => this.ws?.close(4000, 'heartbeat timeout'), interval);
      }
    }, interval);
  }

  private clearTimers(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    if (this.pongDeadline) clearTimeout(this.pongDeadline);
    this.reconnectTimer = this.heartbeatTimer = this.pongDeadline = null;
  }
}

export function websocketUrl(serverUrl: string): string {
  return `${serverUrl.replace(/\/+$/, '').replace(/^http/, 'ws')}/api/v1/ws`;
}
