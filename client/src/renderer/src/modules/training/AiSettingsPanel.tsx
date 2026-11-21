/** KI-Einstellungen (administrators): AI caller on/off, model, effort, API key (stored encrypted
 *  on the server, never shown again), connection test. Off by default. */
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { useAiSettings } from '@/api/queries';
import type { AiSettings, Effort } from '@/api/types';
import { ErrorAlert, Field } from '@/components/common';
import { useSession } from '@/state/session';

const EFFORTS: { value: Effort; label: string }[] = [
  { value: 'low', label: 'niedrig – schnellste Antworten (empfohlen für das Gespräch)' },
  { value: 'medium', label: 'mittel (empfohlen für die Auswertung)' },
  { value: 'high', label: 'hoch' },
  { value: 'xhigh', label: 'sehr hoch' },
  { value: 'max', label: 'maximal' },
];

export function AiSettingsPanel(): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const settings = useAiSettings();
  const [form, setForm] = useState<AiSettings | null>(null);
  const [key, setKey] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; message: string; latency_ms: number | null; model: string | null } | null>(null);
  useEffect(() => {
    if (settings.data) setForm(settings.data);
  }, [settings.data]);
  if (!form) return <div className="panel"><ErrorAlert error={settings.error} /></div>;

  const save = async (extra: Record<string, unknown> = {}) => {
    try {
      const next = await api.put<AiSettings>('/training/ai-settings', {
        enabled: form.enabled, model: form.model.trim(), caller_effort: form.caller_effort, evaluation_effort: form.evaluation_effort,
        api_key: key.trim() || null, expected_version: settings.data?.version ?? null, ...extra,
      });
      setKey('');
      setError(null);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      qc.setQueryData(['ai-settings'], next);
    } catch (e) {
      setError(e);
    }
  };
  const runTest = async () => {
    setTest(null);
    try {
      setTest(await api.post('/training/ai-settings/test'));
    } catch (e) {
      setError(e);
    }
  };

  const keySource = form.has_key ? `hinterlegt (${form.key_hint ?? '••••'})` : form.server_key ? 'aus Serverkonfiguration (ILS_ANTHROPIC_API_KEY)' : 'keiner';
  return (
    <div className="panel">
      <div className="panel-body" style={{ maxWidth: 760 }}>
        <ErrorAlert error={error} />
        <div className="notice" role="note">
          <b>Datenschutz:</b> Ist der KI-Anrufer eingeschaltet, werden Szenario (Persona, Lage) und Gesprächsverlauf der Übungen an die
          Claude-API von Anthropic ({form.base_url}) übertragen. Nur fiktive Übungsdaten verwenden – keine echten Personen- oder Einsatzdaten.
          Die KI spielt ausschließlich den Anrufer: Sie kann nichts alarmieren, anlegen oder anrufen. Ohne KI läuft der regelbasierte Anrufer.
        </div>
        <div className="form-grid" style={{ marginTop: 12 }}>
          <label className="field full"><span className="field-label">KI-Anrufer</span>
            <span><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} aria-label="KI-Anrufer eingeschaltet" /> eingeschaltet</span>
          </label>
          <Field label="Modell"><input className="input mono" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></Field>
          <Field label="Aufwand im Gespräch">
            <select className="select" value={form.caller_effort} onChange={(e) => setForm({ ...form, caller_effort: e.target.value as Effort })}>
              {EFFORTS.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
            </select>
          </Field>
          <Field label="Aufwand bei der Auswertung">
            <select className="select" value={form.evaluation_effort} onChange={(e) => setForm({ ...form, evaluation_effort: e.target.value as Effort })}>
              {EFFORTS.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
            </select>
          </Field>
          <Field label={`API-Schlüssel – ${keySource}`} className="full">
            <input className="input mono" type="password" autoComplete="off" placeholder={form.has_key ? 'neuen Schlüssel eingeben, um ihn zu ersetzen' : 'sk-ant-…'}
              value={key} onChange={(e) => setKey(e.target.value)} />
          </Field>
        </div>
        <div className="muted" style={{ fontSize: 'var(--fs-sm)', marginTop: 4 }}>
          Der Schlüssel wird verschlüsselt gespeichert und nie wieder angezeigt. Spracherkennung (Sprechtaste) auf dem Server: {form.speech_to_text ? 'installiert' : 'nicht installiert (optional, faster-whisper)'}.
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 12, alignItems: 'center' }}>
          <button className="btn primary" onClick={() => void save()}>Speichern</button>
          {form.has_key && <button className="btn danger" onClick={() => void save({ clear_key: true, api_key: null })}>Schlüssel entfernen</button>}
          <button className="btn" onClick={() => void runTest()} disabled={!form.has_key && !form.server_key}>Verbindung testen</button>
          {saved && <span className="badge ok">gespeichert</span>}
          {test && <span className={`badge ${test.ok ? 'ok' : 'danger'}`}>{test.message}{test.latency_ms !== null && ` · ${test.latency_ms} ms`}{test.model && ` · ${test.model}`}</span>}
        </div>
      </div>
    </div>
  );
}
