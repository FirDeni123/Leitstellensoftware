/**
 * Notrufannahme: call queue (priority, waiting time) and call taking form.
 * Strg+Leertaste answers the most urgent ringing call.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { describeError } from '@/api/http';
import { useCalls, useIncidents, useList } from '@/api/queries';
import type { Call, CallScenario, Incident, Keyword } from '@/api/types';
import { EmptyState, ErrorAlert, Field, fmtTime, Modal } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { hasPermission, useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';
import { parseNumber } from '../crud/fields';
import { useCallAlert } from './callAlert';
import { CALL_STATUS, elapsed, PRIORITY, STANDARD_QUESTIONS, useNow } from './labels';

export function CallsPanel(): ReactNode {
  const me = useSession((s) => s.me)!;
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const { active } = useActiveControlCenter();
  const calls = useCalls(active?.id);
  const now = useNow();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [manual, setManual] = useState(false);
  const { muted, toggle } = useCallAlert();
  const queue = calls.data ?? [];
  const selected = queue.find((c) => c.id === selectedId) ?? null;

  const answer = async (call: Call) => {
    // Switch the view immediately – input must never go into the previous call's form.
    setSelectedId(call.id);
    try {
      await api.post<Call>(`/calls/${call.id}/answer`, { expected_version: call.version });
      await qc.invalidateQueries({ queryKey: ['calls'] });
    } catch (e) {
      sysmsg('error', 'Notruf', describeError(e));
      await qc.invalidateQueries({ queryKey: ['calls'] });
    }
  };

  // Strg+Leertaste: answer the most urgent ringing call
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.code === 'Space') {
        const next = queue.find((c) => c.status === 'ringing');
        if (next) {
          e.preventDefault();
          void answer(next);
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  // keep my active call selected after it was answered elsewhere in the UI
  useEffect(() => {
    if (!selectedId) {
      const mine = queue.find((c) => c.handled_by === me.id && c.status === 'active');
      if (mine) setSelectedId(mine.id);
    }
  }, [queue, selectedId, me.id]);

  const ringing = queue.filter((c) => c.status === 'ringing').length;

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <span className={`badge ${ringing ? 'danger pulse-badge' : ''}`}>{ringing} klingelnd</span>
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{queue.length} offen · Strg+Leertaste = annehmen</span>
        <div className="spacer" />
        <button className="btn ghost sm" onClick={toggle} title="Signalton für neue Notrufe">{muted ? '🔕 Ton aus' : '🔔 Ton an'}</button>
        <button className="btn sm" disabled={!active} onClick={() => setManual(true)}>Anruf erfassen</button>
        {hasPermission(me, 'simulation.control') && active && <SimCallControl ccId={active.id} />}
      </div>
      <ErrorAlert error={calls.error} />
      <div className="panel-split">
        <div className="master table-wrap" style={{ flex: 1 }}>
          {queue.length === 0 ? (
            <EmptyState title="Keine offenen Notrufe">Neue Anrufe erscheinen hier sofort mit Signalton.</EmptyState>
          ) : (
            <table className="data">
              <thead><tr><th style={{ width: 92 }}>Status</th><th style={{ width: 92 }}>Priorität</th><th>Anrufer</th><th style={{ width: 70 }}>Wartet</th><th>Bearbeitung</th></tr></thead>
              <tbody>
                {queue.map((c) => (
                  <tr key={c.id} className={`clickable ${c.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(c.id)}
                    onDoubleClick={() => c.status === 'ringing' && void answer(c)}>
                    <td><span className={`badge ${CALL_STATUS[c.status].cls}`}>{CALL_STATUS[c.status].label}</span></td>
                    <td><span className={`badge ${PRIORITY[c.priority]?.cls}`}>{PRIORITY[c.priority]?.label}</span></td>
                    <td>
                      {c.source === 'sim' && <span className="badge sim-badge">SIM</span>} <span className="mono">{c.caller_phone ?? 'unterdrückt'}</span>
                      {c.caller_name && <span className="muted"> · {c.caller_name}</span>}
                    </td>
                    <td className="tabular">{elapsed(c.received_at, now)}</td>
                    <td className="muted">{c.handled_by_name ?? '–'}{c.incident && <> · {c.incident.number}</>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="detail" style={{ flex: 1.3 }}>
          {selected ? <CallDetail key={selected.id} call={selected} onAnswer={() => void answer(selected)} onClosed={() => setSelectedId(null)} />
            : <EmptyState title="Notruf auswählen">Doppelklick oder Strg+Leertaste nimmt an.</EmptyState>}
        </div>
      </div>
      {manual && active && <ManualCallDialog ccId={active.id} onClose={() => setManual(false)} onCreated={setSelectedId} />}
    </div>
  );
}

function SimCallControl({ ccId }: { ccId: string }): ReactNode {
  const api = useSession((s) => s.api)!;
  const scenarios = useQuery({ queryKey: ['call-scenarios'], queryFn: () => api.get<CallScenario[]>('/simulation/call-scenarios'), staleTime: Infinity });
  const [scenario, setScenario] = useState('');
  const create = async () => {
    try {
      await api.post('/simulation/calls', { control_center_id: ccId, scenario: scenario || null });
    } catch (e) {
      sysmsg('error', 'Simulation', describeError(e));
    }
  };
  return (
    <span style={{ display: 'inline-flex', gap: 4 }}>
      <select className="select" style={{ height: 24 }} aria-label="Szenario" value={scenario} onChange={(e) => setScenario(e.target.value)}>
        <option value="">Zufälliges Szenario</option>
        {(scenarios.data ?? []).map((s) => <option key={s.key} value={s.key}>{s.title}</option>)}
      </select>
      <button className="btn sm sim-button" onClick={() => void create()}>Simulierten Notruf erzeugen</button>
    </span>
  );
}

function CallDetail({ call, onAnswer, onClosed }: { call: Call; onAnswer: () => void; onClosed: () => void }): ReactNode {
  const me = useSession((s) => s.me)!;
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const mine = call.handled_by === me.id;
  const action = async (name: 'hold' | 'resume' | 'end') => {
    try {
      await api.post(`/calls/${call.id}/${name}`, { expected_version: call.version });
      await qc.invalidateQueries({ queryKey: ['calls'] });
      if (name === 'end') onClosed();
    } catch (e) {
      sysmsg('error', 'Notruf', describeError(e));
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span className={`badge ${CALL_STATUS[call.status].cls}`}>{CALL_STATUS[call.status].label}</span>
        <span className="mono" style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>{call.caller_phone ?? 'Rufnummer unterdrückt'}</span>
        {call.line && <span className="badge">Leitung {call.line}</span>}
        <span className="muted" style={{ marginLeft: 'auto' }}>Eingang {fmtTime(call.received_at)}</span>
      </div>
      {call.caller_location && (
        <div className="muted" style={{ fontSize: 'var(--fs-sm)', marginTop: 4 }}>
          Anruferstandort: {call.caller_location}{call.caller_latitude !== null && <span className="tabular"> ({call.caller_latitude.toFixed(5)}, {call.caller_longitude?.toFixed(5)})</span>}
        </div>
      )}
      {call.status === 'ringing' && (
        <div style={{ marginTop: 16 }}>
          <button className="btn primary" style={{ height: 40, fontSize: 'var(--fs-lg)' }} onClick={onAnswer}>Notruf annehmen</button>
          <button className="btn" style={{ marginLeft: 8 }} onClick={() => void action('end')}>Ohne Annahme beenden</button>
        </div>
      )}
      {call.status === 'on_hold' && (
        <div className="alert warning" style={{ marginTop: 12 }}>
          Gehalten von {call.handled_by_name}. <button className="btn sm" onClick={() => void action('resume')}>{mine ? 'Gespräch fortsetzen' : 'Gespräch übernehmen'}</button>
        </div>
      )}
      {call.status === 'active' && !mine && <div className="alert info" style={{ marginTop: 12 }}>Wird von {call.handled_by_name} bearbeitet.</div>}
      {call.status === 'active' && mine && <CallTakingForm call={call} onHold={() => void action('hold')} onEnd={() => void action('end')} />}
      {call.status !== 'active' && call.notes.length > 0 && <NotesList call={call} />}
    </div>
  );
}

interface CallForm {
  caller_name: string;
  caller_phone: string;
  address: string;
  latitude: string;
  longitude: string;
  reason: string;
  priority: number;
}

const toCallForm = (c: Call): CallForm => ({
  caller_name: c.caller_name ?? '', caller_phone: c.caller_phone ?? '', address: c.address ?? '',
  latitude: c.latitude?.toString() ?? '', longitude: c.longitude?.toString() ?? '', reason: c.reason ?? '', priority: c.priority,
});

/**
 * The call is edited only by the person handling it (enforced by the server), so the form
 * keeps local input and always saves against the latest version.
 */
function CallTakingForm({ call, onHold, onEnd }: { call: Call; onHold: () => void; onEnd: () => void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const [form, setForm] = useState<CallForm>(() => toCallForm(call));
  const [saved, setSaved] = useState<CallForm>(() => toCallForm(call));
  const [error, setError] = useState<unknown>(null);
  const [question, setQuestion] = useState<string | null>(null);
  const [answer, setAnswer] = useState('');
  const [note, setNote] = useState('');
  const [linkMode, setLinkMode] = useState<'new' | 'existing' | null>(null);
  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  const set = (patch: Partial<CallForm>) => setForm((f) => ({ ...f, ...patch }));
  const lat = parseNumber(form.latitude);
  const lon = parseNumber(form.longitude);
  const responsibility = useQuery({
    queryKey: ['responsibility', lat, lon],
    queryFn: () => api.get<{ control_center: { code: string; name: string }; area_name: string }[]>('/responsibility', { latitude: lat!, longitude: lon! }),
    enabled: lat !== null && lon !== null && !Number.isNaN(lat) && !Number.isNaN(lon),
  });

  const save = async (): Promise<boolean> => {
    if (!dirty) return true;
    if (Number.isNaN(lat) || Number.isNaN(lon) || (lat === null) !== (lon === null)) {
      setError(new Error('Koordinaten: Breite und Länge als Zahl angeben'));
      return false;
    }
    try {
      // No version: only the handling dispatcher may edit a call (server-enforced).
      const updated = await api.patch<Call>(`/calls/${call.id}`, {
        caller_name: form.caller_name || null, caller_phone: form.caller_phone || null,
        address: form.address || null, latitude: lat, longitude: lon, reason: form.reason || null, priority: form.priority,
      });
      setSaved(toCallForm(updated));
      setError(null);
      await qc.invalidateQueries({ queryKey: ['calls'] });
      return true;
    } catch (e) {
      setError(e);
      return false;
    }
  };

  const addNote = async (kind: 'note' | 'question', text: string, q?: string) => {
    try {
      await api.post(`/calls/${call.id}/notes`, { kind, question: q ?? null, text });
      await qc.invalidateQueries({ queryKey: ['calls'] });
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div style={{ marginTop: 10 }}>
      {call.sim_transcript && (
        <div className="sim-transcript selectable" aria-label="Simuliertes Gespräch">
          <div className="sim-transcript-head">SIMULATION · Gesprächsinhalt des simulierten Anrufers</div>
          {call.sim_transcript.split('\n').map((line) => <div key={line}>{line}</div>)}
        </div>
      )}
      <div className="form-grid" style={{ marginTop: 10 }}>
        <Field label="Name des Anrufers"><input className="input" value={form.caller_name} onChange={(e) => set({ caller_name: e.target.value })} /></Field>
        <Field label="Rückrufnummer"><input className="input mono" value={form.caller_phone} onChange={(e) => set({ caller_phone: e.target.value })} /></Field>
        <Field label="Einsatzort (Adresse)" className="full"><input className="input" value={form.address} onChange={(e) => set({ address: e.target.value })} placeholder="Straße Hausnummer, Ort" /></Field>
        <Field label="Breitengrad"><input className="input tabular" value={form.latitude} onChange={(e) => set({ latitude: e.target.value })} /></Field>
        <Field label="Längengrad"><input className="input tabular" value={form.longitude} onChange={(e) => set({ longitude: e.target.value })} /></Field>
        <div className="full" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 'var(--fs-sm)' }}>
          {call.caller_latitude !== null && (
            <button type="button" className="btn sm" onClick={() => set({ latitude: String(call.caller_latitude), longitude: String(call.caller_longitude) })}>Anruferstandort übernehmen</button>
          )}
          {responsibility.data && (responsibility.data.length
            ? <span className="badge ok">Zuständig: {responsibility.data[0]!.control_center.code} ({responsibility.data[0]!.area_name})</span>
            : <span className="badge warn">Außerhalb aller Zuständigkeitsbereiche</span>)}
          <span className="muted">Ortsauswahl auf der Karte folgt mit Phase 6.</span>
        </div>
        <Field label="Einsatzgrund" className="full"><textarea className="input" style={{ height: 54, padding: 8 }} value={form.reason} onChange={(e) => set({ reason: e.target.value })} /></Field>
        <div className="field full">
          <label>Priorität</label>
          <div className="chips">
            {[1, 2, 3].map((p) => <button type="button" key={p} className={`chip ${form.priority === p ? 'on' : ''}`} onClick={() => set({ priority: p })}>{PRIORITY[p]!.label}</button>)}
          </div>
        </div>
      </div>

      <div className="section-title">Rückfragen</div>
      <div className="chips">
        {STANDARD_QUESTIONS.map((q) => {
          const asked = call.notes.some((n) => n.question === q);
          return <button type="button" key={q} className={`chip ${question === q ? 'on' : ''} ${asked ? 'done' : ''}`} onClick={() => { setQuestion(q); setAnswer(''); }}>{asked ? '✓ ' : ''}{q}</button>;
        })}
      </div>
      {question && (
        <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          <input className="input" autoFocus aria-label="Antwort" style={{ flex: 1 }} placeholder={`Antwort auf „${question}“`} value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && answer.trim()) { void addNote('question', answer.trim(), question); setQuestion(null); } }} />
          <button type="button" className="btn sm" disabled={!answer.trim()} onClick={() => { void addNote('question', answer.trim(), question); setQuestion(null); }}>Dokumentieren</button>
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input className="input" aria-label="Gesprächsnotiz" style={{ flex: 1 }} placeholder="Gesprächsnotiz … (Enter)" value={note} onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && note.trim()) { void addNote('note', note.trim()); setNote(''); } }} />
      </div>
      <NotesList call={call} />

      {error ? <div style={{ marginTop: 10 }}><ErrorAlert error={error} /></div> : null}
      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        <button className="btn" disabled={!dirty} onClick={() => void save()}>Angaben speichern</button>
        {call.incident ? (
          <span className="badge ok" style={{ alignSelf: 'center' }}>Einsatz {call.incident.number}</span>
        ) : (
          <>
            <button className="btn primary" onClick={() => void save().then((ok) => ok && setLinkMode('new'))}>Neuer Einsatz …</button>
            <button className="btn" onClick={() => void save().then((ok) => ok && setLinkMode('existing'))}>Bestehendem Einsatz zuordnen …</button>
          </>
        )}
        <button className="btn" style={{ marginLeft: 'auto' }} onClick={onHold}>Halten</button>
        <button className="btn danger" onClick={() => void save().then((ok) => ok && onEnd())}>Gespräch beenden</button>
      </div>
      {linkMode === 'new' && <NewIncidentFromCallDialog call={call} onClose={() => setLinkMode(null)} />}
      {linkMode === 'existing' && <LinkCallDialog call={call} onClose={() => setLinkMode(null)} />}
    </div>
  );
}

function NotesList({ call }: { call: Call }): ReactNode {
  if (!call.notes.length) return null;
  return (
    <div className="call-notes">
      {[...call.notes].reverse().map((n) => (
        <div key={n.id} className="call-note">
          <span className="tabular muted">{fmtTime(n.ts)}</span>
          <span>{n.question ? <><b>{n.question}</b> {n.text}</> : n.text}</span>
        </div>
      ))}
    </div>
  );
}

function NewIncidentFromCallDialog({ call, onClose }: { call: Call; onClose: () => void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const keywords = useList<Keyword>('keywords', '/keywords');
  const [keywordId, setKeywordId] = useState('');
  const [error, setError] = useState<unknown>(null);
  const active = useMemo(() => (keywords.data ?? []).filter((k) => k.is_active), [keywords.data]);
  const submit = async () => {
    try {
      const incident = await api.post<Incident>('/incidents', { control_center_id: call.control_center_id, call_id: call.id, keyword_id: keywordId || null });
      await qc.invalidateQueries({ queryKey: ['calls'] });
      await qc.invalidateQueries({ queryKey: ['incidents'] });
      sysmsg('success', 'Einsatz', `Einsatz ${incident.number} angelegt`);
      onClose();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Modal title="Neuen Einsatz aus Notruf anlegen" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Abbrechen</button>
      <button className="btn primary" onClick={() => void submit()}>Einsatz anlegen</button>
    </>}>
      <Field label="Einsatzstichwort">
        <select className="select" autoFocus value={keywordId} onChange={(e) => setKeywordId(e.target.value)}>
          <option value="">– später festlegen –</option>
          {active.map((k) => <option key={k.id} value={k.id}>{k.code} – {k.name}</option>)}
        </select>
      </Field>
      <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Anruferdaten, Einsatzort und Einsatzgrund werden aus dem Notruf übernommen. Die Disposition sieht den Einsatz sofort.</div>
      <ErrorAlert error={error} />
    </Modal>
  );
}

function LinkCallDialog({ call, onClose }: { call: Call; onClose: () => void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const incidents = useIncidents(call.control_center_id, 'open');
  const [incidentId, setIncidentId] = useState('');
  const [error, setError] = useState<unknown>(null);
  const submit = async () => {
    try {
      await api.post(`/calls/${call.id}/link`, { incident_id: incidentId });
      await qc.invalidateQueries({ queryKey: ['calls'] });
      sysmsg('success', 'Notruf', 'Notruf dem Einsatz zugeordnet');
      onClose();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Modal title="Notruf einem bestehenden Einsatz zuordnen" width={620} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Abbrechen</button>
      <button className="btn primary" disabled={!incidentId} onClick={() => void submit()}>Zuordnen</button>
    </>}>
      <div className="table-wrap" style={{ maxHeight: 300 }}>
        <table className="data">
          <thead><tr><th>Nr.</th><th>Stichwort</th><th>Einsatzort</th></tr></thead>
          <tbody>
            {(incidents.data ?? []).map((i) => (
              <tr key={i.id} className={`clickable ${i.id === incidentId ? 'selected' : ''}`} onClick={() => setIncidentId(i.id)}>
                <td className="mono">{i.number}</td><td>{i.keyword?.code ?? '–'}</td><td>{i.address ?? '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {incidents.data?.length === 0 && <EmptyState title="Keine offenen Einsätze" />}
      </div>
      <ErrorAlert error={error} />
    </Modal>
  );
}

function ManualCallDialog({ ccId, onClose, onCreated }: { ccId: string; onClose: () => void; onCreated: (id: string) => void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const [phone, setPhone] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState<unknown>(null);
  const submit = async () => {
    try {
      const call = await api.post<Call>('/calls', { control_center_id: ccId, caller_phone: phone || null, caller_name: name || null });
      await qc.invalidateQueries({ queryKey: ['calls'] });
      onCreated(call.id);
      onClose();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Modal title="Anruf manuell erfassen" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Abbrechen</button>
      <button className="btn primary" onClick={() => void submit()}>Erfassen</button>
    </>}>
      <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Für Anrufe, die außerhalb des Systems eingehen (z. B. Amtsleitung ohne Anbindung). Der Anruf wird Ihnen direkt zugeordnet.</div>
      <Field label="Rückrufnummer"><input className="input mono" autoFocus value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
      <Field label="Name des Anrufers"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <ErrorAlert error={error} />
    </Modal>
  );
}
