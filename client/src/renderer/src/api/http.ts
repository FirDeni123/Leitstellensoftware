/**
 * HTTP client for the server API.
 *
 * - Bearer access token in memory; on 401 with reason "token_expired" exactly one refresh
 *   runs (single flight) and the original request is retried once.
 * - Errors are normalised into {@link ApiError} with the server's stable error code and
 *   request id (shown to the user as "Fehler-ID" for support).
 * - Network failures become ApiError(status 0, code "network").
 */
import type { TokenResponse } from './types';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  get isConflict(): boolean {
    return this.status === 409;
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  clientName?: string;
  /** Called with fresh tokens after a successful refresh. */
  onTokens?: (tokens: TokenResponse) => void;
  /** Called when the session cannot be recovered (refresh failed). */
  onAuthLost?: (reason: string) => void;
  timeoutMs?: number;
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export class ApiClient {
  private accessToken: string | null = null;
  private refreshToken: string | null = null;
  private refreshing: Promise<boolean> | null = null;
  private readonly fetchImpl: typeof fetch;

  constructor(private readonly opts: ApiClientOptions) {
    this.fetchImpl = opts.fetchImpl ?? ((...args) => fetch(...args));
  }

  get baseUrl(): string {
    return this.opts.baseUrl.replace(/\/+$/, '');
  }

  get token(): string | null {
    return this.accessToken;
  }

  setTokens(tokens: Pick<TokenResponse, 'access_token' | 'refresh_token'> | null): void {
    this.accessToken = tokens?.access_token ?? null;
    this.refreshToken = tokens?.refresh_token ?? null;
  }

  async get<T>(path: string, query?: Record<string, string | number | boolean | undefined | null>): Promise<T> {
    return this.request<T>('GET', withQuery(path, query));
  }
  post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('POST', path, body);
  }
  put<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('PUT', path, body);
  }
  patch<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>('PATCH', path, body);
  }
  delete<T = void>(path: string): Promise<T> {
    return this.request<T>('DELETE', path);
  }
  /** multipart/form-data upload (file imports). */
  upload<T>(path: string, form: FormData): Promise<T> {
    return this.request<T>('POST', path, form);
  }

  /** Unauthenticated health probe used by the login screen ("Verbindung testen"). */
  async health(): Promise<{ status: string; version: string; checks: Record<string, string> }> {
    const res = await this.send('GET', `${this.baseUrl}/health`, undefined, false);
    return (await res.json()) as { status: string; version: string; checks: Record<string, string> };
  }

  async request<T>(method: Method, path: string, body?: unknown, retry = true): Promise<T> {
    const res = await this.send(method, `${this.baseUrl}/api/v1${path}`, body, true);
    if (res.status === 401 && retry && this.refreshToken && !path.startsWith('/auth/')) {
      const err = await toApiError(res);
      if (err.details['reason'] === 'token_expired' && (await this.refresh())) {
        return this.request<T>(method, path, body, false);
      }
      this.opts.onAuthLost?.(err.message);
      throw err;
    }
    if (!res.ok) throw await toApiError(res);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  /** Rotates the refresh token. Concurrent callers share one in-flight refresh. */
  refresh(): Promise<boolean> {
    if (!this.refreshToken) return Promise.resolve(false);
    if (!this.refreshing) {
      const token = this.refreshToken;
      this.refreshing = (async () => {
        try {
          const res = await this.send('POST', `${this.baseUrl}/api/v1/auth/refresh`, { refresh_token: token }, false);
          if (!res.ok) {
            const err = await toApiError(res);
            this.setTokens(null);
            this.opts.onAuthLost?.(err.message);
            return false;
          }
          const tokens = (await res.json()) as TokenResponse;
          this.setTokens(tokens);
          this.opts.onTokens?.(tokens);
          return true;
        } catch {
          return false; // network error: keep tokens, caller may retry later
        } finally {
          this.refreshing = null;
        }
      })();
    }
    return this.refreshing;
  }

  private async send(method: Method, url: string, body: unknown, auth: boolean): Promise<Response> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
    if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json';
    if (auth && this.accessToken) headers['Authorization'] = `Bearer ${this.accessToken}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.opts.timeoutMs ?? 15000);
    try {
      return await this.fetchImpl(url, {
        method,
        headers,
        body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (e) {
      const aborted = e instanceof DOMException && e.name === 'AbortError';
      throw new ApiError(
        0,
        aborted ? 'timeout' : 'network',
        aborted ? 'Zeitüberschreitung – Server antwortet nicht' : 'Server nicht erreichbar',
      );
    } finally {
      clearTimeout(timer);
    }
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as {
      error?: { code: string; message: string; details?: Record<string, unknown>; request_id?: string };
    };
    if (body.error) {
      return new ApiError(res.status, body.error.code, body.error.message, body.error.details ?? {},
        body.error.request_id ?? null);
    }
  } catch {
    /* non-JSON body */
  }
  return new ApiError(res.status, 'http_error', `Serverfehler (HTTP ${res.status})`, {},
    res.headers.get('x-request-id'));
}

function withQuery(path: string, query?: Record<string, string | number | boolean | undefined | null>): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== '') params.set(k, String(v));
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

/** German, user-facing description of any error. */
export function describeError(e: unknown): string {
  if (e instanceof ApiError) return e.requestId ? `${e.message} (Fehler-ID ${e.requestId})` : e.message;
  if (e instanceof Error) return e.message;
  return 'Unbekannter Fehler';
}
