import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { ApiClient, describeError } from '@/api/http';
import type { TokenResponse } from '@/api/types';
import { availableWorkstations, WORKSTATIONS } from '@/layout/workstations';
import { platform, type ClientConfig } from '@/platform/bridge';
import { useSession } from '@/state/session';
import { ChangePasswordForm } from './ChangePasswordForm';

type Probe = { state: 'idle' | 'testing' | 'ok' | 'error'; text?: string };

function isInsecureRemote(url: string): boolean {
  try {
    const u = new URL(url);
    return u.protocol === 'http:' && !['localhost', '127.0.0.1', '[::1]'].includes(u.hostname);
  } catch {
    return false;
  }
}

export function LoginScreen(): ReactNode {
  const { createApi, completeLogin, logoutReason } = useSession();
  const [config, setConfig] = useState<ClientConfig | null>(null);
  const [serverUrl, setServerUrl] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [probe, setProbe] = useState<Probe>({ state: 'idle' });
  const [showServer, setShowServer] = useState(false);
  const [pending, setPending] = useState<{ api: ApiClient; tokens: TokenResponse } | null>(null);

  useEffect(() => {
    void platform.loadConfig().then((cfg) => {
      setConfig(cfg);
      setServerUrl(cfg.serverUrl);
      setUsername(cfg.lastUsername);
    });
  }, []);

  const testConnection = async () => {
    setProbe({ state: 'testing' });
    try {
      const h = await new ApiClient({ baseUrl: serverUrl, timeoutMs: 5000 }).health();
      setProbe({ state: h.status === 'ok' ? 'ok' : 'error', text: `Server ${h.version} – ${Object.entries(h.checks).map(([k, v]) => `${k}: ${v}`).join(', ')}` });
    } catch (e) {
      setProbe({ state: 'error', text: describeError(e) });
    }
  };

  const finish = (api: ApiClient, tokens: TokenResponse) => {
    const perms = tokens.user.permissions;
    const allowed = availableWorkstations(perms);
    const preferred = allowed.find((w) => w.key === config?.lastWorkstation) ?? allowed[0] ?? WORKSTATIONS[1]!;
    completeLogin(api, tokens, preferred.key);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const api = createApi(serverUrl.trim());
      const tokens = await api.post<TokenResponse>('/auth/login', {
        username: username.trim(),
        password,
        client: { client_name: 'ILS-Sim Client', client_version: (await platform.appInfo()).version, workstation: config?.workstationName },
      });
      await platform.saveConfig({ serverUrl: serverUrl.trim(), lastUsername: username.trim() });
      setPassword('');
      if (tokens.user.must_change_password) {
        api.setTokens(tokens);
        setPending({ api, tokens });
      } else {
        finish(api, tokens);
      }
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-screen">
      <div className="login-drag" />
      <div className="login-card">
        <div className="login-brand">
          <div className="brand-mark" aria-hidden>ILS</div>
          <div>
            <div className="brand-title">ILS-Sim Leitstelle</div>
            <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Integrierte Leitstelle · Simulationssystem</div>
          </div>
        </div>
        <div className="sim-ribbon">SIMULATION · Training und Entwicklung – keine realen Alarmierungen</div>

        {pending ? (
          <ChangePasswordForm
            api={pending.api}
            intro="Bei der ersten Anmeldung oder nach einem Zurücksetzen muss ein neues Passwort vergeben werden."
            onDone={(tokens) => finish(pending.api, tokens)}
            onCancel={() => { pending.api.setTokens(null); setPending(null); }}
          />
        ) : (
          <form onSubmit={submit} className="login-form" aria-label="Anmeldung">
            {logoutReason && <div className="alert warning">{logoutReason}</div>}
            <div className="field">
              <label htmlFor="username">Benutzername</label>
              <input id="username" className="input" autoFocus={!username} value={username} autoComplete="username"
                onChange={(e) => setUsername(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="password">Passwort</label>
              <input id="password" className="input" type="password" autoFocus={!!username} value={password}
                autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} />
            </div>
            {error && <div className="alert error" role="alert">{error}</div>}
            <button className="btn primary" style={{ height: 34, justifyContent: 'center' }} disabled={busy || !username || !password || !serverUrl}>
              {busy ? 'Anmeldung läuft …' : 'Anmelden'}
            </button>

            <div className="login-server">
              <button type="button" className="btn ghost sm" onClick={() => setShowServer((v) => !v)}>
                Server: <span className="mono">{serverUrl || '–'}</span> {showServer ? '▴' : '▾'}
              </button>
              {showServer && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input aria-label="Serveradresse" className="input mono" style={{ flex: 1 }} value={serverUrl}
                      onChange={(e) => { setServerUrl(e.target.value); setProbe({ state: 'idle' }); }} placeholder="https://leitstelle-server:8443" />
                    <button type="button" className="btn" onClick={testConnection} disabled={probe.state === 'testing'}>Verbindung testen</button>
                  </div>
                  {probe.state !== 'idle' && (
                    <div className={`alert ${probe.state === 'ok' ? 'success' : probe.state === 'error' ? 'error' : 'info'}`}>
                      {probe.state === 'testing' ? 'Prüfe Verbindung …' : probe.text}
                    </div>
                  )}
                  {isInsecureRemote(serverUrl) && (
                    <div className="alert warning">Unverschlüsselte Verbindung (http) zu einem entfernten Server. Für den Betrieb im Netzwerk https verwenden.</div>
                  )}
                  <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>Arbeitsplatzname: {config?.workstationName}</div>
                </div>
              )}
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
