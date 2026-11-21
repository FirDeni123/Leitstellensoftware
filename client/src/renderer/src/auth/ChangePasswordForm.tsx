import { useState, type FormEvent, type ReactNode } from 'react';
import { ApiClient, describeError } from '@/api/http';
import type { TokenResponse } from '@/api/types';

export function ChangePasswordForm(props: {
  api: ApiClient;
  intro?: string;
  onDone: (tokens: TokenResponse) => void;
  onCancel?: () => void;
}): ReactNode {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [repeat, setRepeat] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mismatch = repeat.length > 0 && next !== repeat;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const tokens = await props.api.post<TokenResponse>('/auth/change-password', {
        current_password: current,
        new_password: next,
      });
      props.api.setTokens(tokens);
      props.onDone(tokens);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="login-form" aria-label="Passwort ändern">
      {props.intro && <div className="alert info">{props.intro}</div>}
      <div className="field">
        <label htmlFor="pw-current">Aktuelles Passwort</label>
        <input id="pw-current" className="input" type="password" autoFocus value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
      </div>
      <div className="field">
        <label htmlFor="pw-new">Neues Passwort</label>
        <input id="pw-new" className="input" type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
      </div>
      <div className="field">
        <label htmlFor="pw-repeat">Neues Passwort wiederholen</label>
        <input id="pw-repeat" className={`input ${mismatch ? 'invalid' : ''}`} type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)} autoComplete="new-password" />
      </div>
      <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>
        Mindestens 10 Zeichen und drei Zeichenarten (Klein-, Großbuchstaben, Ziffern, Sonderzeichen); darf den Benutzernamen nicht enthalten.
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        {props.onCancel && <button type="button" className="btn" onClick={props.onCancel}>Abbrechen</button>}
        <button className="btn primary" disabled={busy || !current || !next || mismatch || next !== repeat}>
          {busy ? 'Speichere …' : 'Passwort ändern'}
        </button>
      </div>
    </form>
  );
}
