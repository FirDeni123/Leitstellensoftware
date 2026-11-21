import { describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError, describeError } from '@/api/http';

function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

const expired = { error: { code: 'unauthenticated', message: 'Sitzung abgelaufen', details: { reason: 'token_expired' }, request_id: 'r1' } };
const tokens = (n: number) => ({ access_token: `a${n}`, refresh_token: `r${n}`, access_token_expires_at: new Date().toISOString(), token_type: 'bearer', user: {} });

describe('ApiClient', () => {
  it('sends bearer token and parses JSON', async () => {
    const fetchImpl = vi.fn(async () => json(200, { ok: true }));
    const api = new ApiClient({ baseUrl: 'http://srv/', fetchImpl });
    api.setTokens({ access_token: 'a0', refresh_token: 'r0' });
    expect(await api.get('/x', { q: 'a b', empty: '' })).toEqual({ ok: true });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('http://srv/api/v1/x?q=a+b');
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer a0');
  });

  it('refreshes once on expired token and retries the request', async () => {
    let call = 0;
    const fetchImpl = vi.fn(async (url: string) => {
      call++;
      if (url.endsWith('/auth/refresh')) return json(200, tokens(1));
      if (call === 1 || call === 2) return json(401, expired);
      return json(200, { value: 42 });
    });
    const onTokens = vi.fn();
    const api = new ApiClient({ baseUrl: 'http://srv', fetchImpl: fetchImpl as typeof fetch, onTokens });
    api.setTokens({ access_token: 'a0', refresh_token: 'r0' });
    // two concurrent requests -> exactly one refresh (single flight)
    const [a, b] = await Promise.all([api.get<{ value: number }>('/a'), api.get<{ value: number }>('/b')]);
    expect(a.value).toBe(42);
    expect(b.value).toBe(42);
    expect(fetchImpl.mock.calls.filter(([u]) => String(u).endsWith('/auth/refresh'))).toHaveLength(1);
    expect(onTokens).toHaveBeenCalledOnce();
    expect(api.token).toBe('a1');
  });

  it('reports auth loss when refresh fails', async () => {
    const fetchImpl = vi.fn(async (url: string) =>
      url.endsWith('/auth/refresh') ? json(401, { error: { code: 'unauthenticated', message: 'Sitzung ungültig' } }) : json(401, expired));
    const onAuthLost = vi.fn();
    const api = new ApiClient({ baseUrl: 'http://srv', fetchImpl: fetchImpl as typeof fetch, onAuthLost });
    api.setTokens({ access_token: 'a0', refresh_token: 'r0' });
    await expect(api.get('/a')).rejects.toBeInstanceOf(ApiError);
    expect(onAuthLost).toHaveBeenCalled();
    expect(api.token).toBeNull();
  });

  it('normalises server errors including request id', async () => {
    const api = new ApiClient({ baseUrl: 'http://srv', fetchImpl: (async () => json(409, { error: { code: 'conflict', message: 'Geändert', details: { current_version: 3 }, request_id: 'abc' } })) as typeof fetch });
    const err = await api.get('/x').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).isConflict).toBe(true);
    expect((err as ApiError).details['current_version']).toBe(3);
    expect(describeError(err)).toBe('Geändert (Fehler-ID abc)');
  });

  it('maps network failures to a German message', async () => {
    const api = new ApiClient({ baseUrl: 'http://srv', fetchImpl: (async () => { throw new TypeError('fetch failed'); }) as typeof fetch });
    const err = (await api.get('/x').catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(0);
    expect(err.message).toBe('Server nicht erreichbar');
  });
});
