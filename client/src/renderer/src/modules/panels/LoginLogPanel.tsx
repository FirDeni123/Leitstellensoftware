import { useQuery } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import type { LoginEvent } from '@/api/types';
import { ErrorAlert, fmtDateTime } from '@/components/common';
import { useSession } from '@/state/session';

const EVENT: Record<string, string> = { login: 'Anmeldung', logout: 'Abmeldung', refresh_reuse: 'Token-Wiederverwendung' };
const REASON: Record<string, string> = {
  wrong_password: 'Falsches Passwort', wrong_password_locked: 'Falsches Passwort – Konto gesperrt', unknown_user: 'Unbekannter Benutzer',
  locked: 'Konto gesperrt', inactive: 'Konto deaktiviert',
};

/** Login protocol. Refreshes every 30 s (login events are not pushed in realtime). */
export function LoginLogPanel(): ReactNode {
  const api = useSession((s) => s.api)!;
  const [username, setUsername] = useState('');
  const [onlyFailures, setOnlyFailures] = useState(false);
  const events = useQuery({
    queryKey: ['login-events', username, onlyFailures],
    queryFn: () => api.get<LoginEvent[]>('/login-events', { username: username.trim() || undefined, success: onlyFailures ? false : undefined, limit: 500 }),
    refetchInterval: 30_000,
  });
  return (
    <div className="panel">
      <div className="panel-toolbar">
        <input className="input" placeholder="Benutzername" aria-label="Benutzername filtern" value={username} onChange={(e) => setUsername(e.target.value)} style={{ width: 200 }} />
        <label className="checkbox"><input type="checkbox" checked={onlyFailures} onChange={(e) => setOnlyFailures(e.target.checked)} /> Nur Fehlversuche</label>
        <div className="spacer" />
        <button className="btn sm" onClick={() => void events.refetch()}>Aktualisieren</button>
      </div>
      <ErrorAlert error={events.error} />
      <div className="panel-body">
        <table className="data">
          <thead><tr><th style={{ width: 150 }}>Zeitpunkt</th><th>Benutzer</th><th>Ereignis</th><th>Ergebnis</th><th>Arbeitsplatz</th><th>IP</th></tr></thead>
          <tbody>
            {(events.data ?? []).map((e) => (
              <tr key={e.id}>
                <td className="tabular">{fmtDateTime(e.ts)}</td>
                <td className="mono">{e.username}</td>
                <td>{EVENT[e.event] ?? e.event}</td>
                <td>{e.success ? <span className="badge ok">Erfolgreich</span> : <span className="badge danger">{REASON[e.reason ?? ''] ?? e.reason ?? 'Fehlgeschlagen'}</span>}</td>
                <td className="muted">{e.workstation ?? e.client_name ?? ''}</td>
                <td className="mono muted">{e.ip_address ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
