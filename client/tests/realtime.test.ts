import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { backoffDelay, RealtimeClient, websocketUrl, type RealtimeState } from '@/api/realtime';

class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number; reason: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly url: string) { FakeSocket.instances.push(this); }
  send(data: string) { this.sent.push(data); }
  close(code = 1000, reason = '') { this.readyState = 3; this.onclose?.({ code, reason }); }
  open() { this.readyState = 1; this.onopen?.(); }
  receive(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
  drop(code: number) { this.readyState = 3; this.onclose?.({ code, reason: '' }); }
}

function setup(overrides: Partial<ConstructorParameters<typeof RealtimeClient>[0]> = {}) {
  const states: RealtimeState[] = [];
  const events: string[] = [];
  const resyncs: string[] = [];
  const client = new RealtimeClient({
    url: 'ws://srv/api/v1/ws',
    getToken: () => 'tok',
    refreshToken: async () => true,
    onEvent: (e) => events.push(e.topic),
    onState: (s) => states.push(s),
    onResync: (r) => resyncs.push(r),
    WebSocketImpl: FakeSocket as unknown as typeof WebSocket,
    random: () => 0.5,
    heartbeatMs: 1000,
    ...overrides,
  });
  return { client, states, events, resyncs };
}

describe('RealtimeClient', () => {
  beforeEach(() => { FakeSocket.instances = []; vi.useFakeTimers(); });
  afterEach(() => vi.useRealTimers());

  it('authenticates with the first message and goes online on welcome', () => {
    const { client, states, events, resyncs } = setup();
    client.start();
    const ws = FakeSocket.instances[0]!;
    ws.open();
    expect(JSON.parse(ws.sent[0]!)).toEqual({ type: 'auth', token: 'tok' });
    ws.receive({ type: 'welcome' });
    ws.receive({ type: 'event', id: '1', topic: 'user.updated', ts: '', data: {} });
    expect(states.at(-1)).toBe('online');
    expect(events).toEqual(['user.updated']);
    expect(resyncs).toEqual(['connected']);
  });

  it('reconnects with exponential backoff after connection loss', () => {
    const { client, states } = setup();
    client.start();
    FakeSocket.instances[0]!.drop(1006);
    expect(states.at(-1)).toBe('reconnecting');
    vi.advanceTimersByTime(999);
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(2);
    FakeSocket.instances[1]!.drop(1006);
    vi.advanceTimersByTime(1999);
    expect(FakeSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(3);
  });

  it('reconnects immediately with resync when permissions changed (4002)', () => {
    const { client, resyncs } = setup();
    client.start();
    const first = FakeSocket.instances[0]!;
    first.open();
    first.receive({ type: 'welcome' });
    first.drop(4002);
    const second = FakeSocket.instances[1]!;
    second.open();
    second.receive({ type: 'welcome' });
    expect(resyncs).toEqual(['connected', 'permissions_changed']);
  });

  it('ends the session on 4003 and when refresh fails after 4001', async () => {
    const ended = vi.fn();
    const a = setup({ onSessionEnded: ended });
    a.client.start();
    FakeSocket.instances[0]!.drop(4003);
    expect(ended).toHaveBeenCalledTimes(1);

    const b = setup({ onSessionEnded: ended, refreshToken: async () => false });
    b.client.start();
    FakeSocket.instances.at(-1)!.drop(4001);
    await vi.runAllTimersAsync();
    expect(ended).toHaveBeenCalledTimes(2);
  });

  it('closes a dead connection when no pong arrives', () => {
    const { client } = setup();
    client.start();
    const ws = FakeSocket.instances[0]!;
    ws.open();
    ws.receive({ type: 'welcome' });
    vi.advanceTimersByTime(1000); // ping sent
    expect(JSON.parse(ws.sent.at(-1)!).type).toBe('ping');
    vi.advanceTimersByTime(1000); // no pong -> close -> reconnect scheduled
    expect(ws.readyState).toBe(3);
  });

  it('stop() prevents reconnects', () => {
    const { client } = setup();
    client.start();
    client.stop();
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });
});

describe('helpers', () => {
  it('backoff grows exponentially with jitter and is capped', () => {
    expect(backoffDelay(0, () => 0.5)).toBe(1000);
    expect(backoffDelay(3, () => 0.5)).toBe(8000);
    expect(backoffDelay(20, () => 1)).toBe(36000);
    expect(backoffDelay(20, () => 0)).toBe(24000);
  });
  it('derives the websocket url', () => {
    expect(websocketUrl('https://srv:8443/')).toBe('wss://srv:8443/api/v1/ws');
    expect(websocketUrl('http://localhost:8000')).toBe('ws://localhost:8000/api/v1/ws');
  });
});
