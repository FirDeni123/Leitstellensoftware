/**
 * Ausbildung (Ausbildermodus): start exercises for trainees, watch running conversations live,
 * steer the caller ("Regie" – never visible to the trainee), take notes, end exercises.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { describeError } from '@/api/http';
import { useTrainingScenarios, useTrainingSession, useTrainingSessions } from '@/api/queries';
import type { TrainingSessionDetail } from '@/api/types';
import { EmptyState, ErrorAlert, Field, fmtTime, Modal } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';
import { DIFFICULTY, EvaluationView, ExerciseBanner, SESSION_STATUS, Transcript } from './components';
import { useTrainingLive } from './live';

interface Trainee { id: string; username: string; display_name: string }

export function TrainingMonitorPanel(): ReactNode {
  const { active } = useActiveControlCenter();
  const sessions = useTrainingSessions({ controlCenterId: active?.id }, !!active);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const list = (sessions.data ?? []).slice(0, 30);
  const openCount = list.filter((s) => s.status === 'ringing' || s.status === 'active').length;

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <span className={`badge ${openCount ? 'ok' : ''}`}>{openCount} laufend</span>
        <div className="spacer" />
        <button className="btn sm" disabled={!active} onClick={() => setStarting(true)}>Übung für Teilnehmer starten</button>
      </div>
      <ErrorAlert error={sessions.error} />
      <div className="panel-split">
        <div className="master table-wrap">
          {list.length === 0 ? <EmptyState title="Keine Übungen">Gestartete Übungen dieser Leitstelle erscheinen hier live.</EmptyState> : (
            <table className="data" aria-label="Übungen">
              <thead><tr><th>Teilnehmer</th><th>Szenario</th><th style={{ width: 150 }}>Status</th><th style={{ width: 60 }}>Erg.</th></tr></thead>
              <tbody>
                {list.map((s) => (
                  <tr key={s.id} className={`clickable ${s.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(s.id)}>
                    <td>{s.trainee_name}<div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>{fmtTime(s.created_at)}</div></td>
                    <td>{s.title} <span className={`badge ${DIFFICULTY[s.difficulty].cls}`}>{DIFFICULTY[s.difficulty].label}</span></td>
                    <td><span className={`badge ${SESSION_STATUS[s.status].cls}`}>{SESSION_STATUS[s.status].label}</span></td>
                    <td className="tabular">{s.score !== null ? `${s.score} %` : '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="detail">
          {selectedId ? <Observation key={selectedId} id={selectedId} /> : <EmptyState title="Übung auswählen">Gespräch mitlesen und eingreifen.</EmptyState>}
        </div>
      </div>
      {starting && active && <StartForTrainee ccId={active.id} onClose={() => setStarting(false)} onStarted={(id) => { setSelectedId(id); setStarting(false); }} />}
    </div>
  );
}

function Observation({ id }: { id: string }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const detail = useTrainingSession(id);
  const streaming = useTrainingLive((s) => s.streaming[id]);
  const [instruction, setInstruction] = useState('');
  const [immediate, setImmediate] = useState(false);
  const [note, setNote] = useState('');
  const s = detail.data;
  if (!s) return <ErrorAlert error={detail.error} />;
  const running = s.status === 'active' || s.status === 'ringing';

  const run = async (fn: () => Promise<unknown>, done?: () => void) => {
    try {
      await fn();
      done?.();
      await qc.invalidateQueries({ queryKey: ['training-session', id] });
      await qc.invalidateQueries({ queryKey: ['training-sessions'] });
    } catch (e) {
      sysmsg('error', 'Ausbildung', describeError(e));
    }
  };

  return (
    <div className="exercise">
      <ExerciseBanner session={s} />
      <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
        Teilnehmer: <b>{s.trainee_name}</b>{s.instructor_name && ` · gestartet von ${s.instructor_name.replace(/ \(.*\)$/, '')}`}
      </div>
      {s.scenario && <FactsBox s={s} />}
      <Transcript messages={s.messages} streaming={streaming} showInstructor />
      {!!s.pending_instructions?.length && (
        <div className="pending" aria-label="Wartende Regieanweisungen">
          {s.pending_instructions.map((p) => (
            <div key={p.ts} className="badge warn">wartet: {p.text}{p.immediate ? ' (sofort)' : ''}</div>
          ))}
        </div>
      )}
      {s.status === 'active' && (
        <div className="composer" aria-label="Eingriff">
          <div style={{ display: 'flex', gap: 6 }}>
            <input className="input" style={{ flex: 1 }} aria-label="Regieanweisung an den Anrufer" placeholder="Regie, z. B. „Werde panisch und weine“ (nur der Anrufer erfährt davon)"
              value={instruction} onChange={(e) => setInstruction(e.target.value)} maxLength={1000} />
            <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: 'var(--fs-sm)' }}>
              <input type="checkbox" checked={immediate} onChange={(e) => setImmediate(e.target.checked)} /> sofort
            </label>
            <button className="btn primary sm" disabled={!instruction.trim()}
              onClick={() => void run(() => api.post(`/training/sessions/${id}/instructions`, { text: instruction.trim(), immediate }), () => setInstruction(''))}>Anweisen</button>
          </div>
        </div>
      )}
      <div style={{ display: 'flex', gap: 6 }}>
        <input className="input" style={{ flex: 1 }} aria-label="Beobachtungsnotiz" placeholder="Beobachtungsnotiz für die Nachbesprechung"
          value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
        <button className="btn sm" disabled={!note.trim()}
          onClick={() => void run(() => api.post(`/training/sessions/${id}/notes`, { text: note.trim() }), () => setNote(''))}>Notieren</button>
        {running && <button className="btn danger sm" onClick={() => void run(() => api.post(`/training/sessions/${id}/end`))}>Übung beenden</button>}
        {(s.status === 'ended' || s.status === 'evaluated') && (
          <button className="btn sm" onClick={() => void run(() => api.post(`/training/sessions/${id}/evaluate`))}>Neu auswerten</button>
        )}
      </div>
      {s.evaluation && <EvaluationView evaluation={s.evaluation} />}
    </div>
  );
}

function FactsBox({ s }: { s: TrainingSessionDetail }): ReactNode {
  const f = s.scenario!.facts;
  return (
    <details className="solution">
      <summary>Lage laut Szenario (nur für Ausbilder)</summary>
      <dl className="kv">
        {s.scenario!.keyword && <><dt>Stichwort</dt><dd>{s.scenario!.keyword.code} – {s.scenario!.keyword.name}</dd></>}
        <dt>Einsatzort</dt><dd>{f.address ?? '–'}{f.location_hint && ` (${f.location_hint})`}</dd>
        <dt>Lage</dt><dd>{f.situation ?? '–'}</dd>
        {f.persons && <><dt>Personen</dt><dd>{f.persons}</dd></>}
        {f.injuries && <><dt>Verletzungen</dt><dd>{f.injuries}</dd></>}
        {f.hazards && <><dt>Gefahren</dt><dd>{f.hazards}</dd></>}
      </dl>
    </details>
  );
}

function StartForTrainee({ ccId, onClose, onStarted }: { ccId: string; onClose(): void; onStarted(id: string): void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const scenarios = useTrainingScenarios(ccId);
  const trainees = useQuery({
    queryKey: ['training-trainees', ccId],
    queryFn: () => api.get<Trainee[]>('/training/trainees', { control_center_id: ccId }),
  });
  const [scenarioId, setScenarioId] = useState('');
  const [traineeId, setTraineeId] = useState('');
  const [error, setError] = useState<unknown>(null);
  const start = async () => {
    try {
      const s = await api.post<TrainingSessionDetail>('/training/sessions', { scenario_id: scenarioId, control_center_id: ccId, trainee_id: traineeId });
      onStarted(s.id);
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Modal title="Übung für Teilnehmer starten" onClose={onClose} width={460} footer={<>
      <button className="btn" onClick={onClose}>Abbrechen</button>
      <button className="btn primary" disabled={!scenarioId || !traineeId} onClick={() => void start()}>Starten</button>
    </>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <ErrorAlert error={error ?? scenarios.error ?? trainees.error} />
        <Field label="Teilnehmer">
          <select className="select" value={traineeId} onChange={(e) => setTraineeId(e.target.value)}>
            <option value="">– auswählen –</option>
            {(trainees.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.display_name} ({t.username})</option>)}
          </select>
        </Field>
        <Field label="Szenario">
          <select className="select" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
            <option value="">– auswählen –</option>
            {(scenarios.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.title} ({DIFFICULTY[s.difficulty].label})</option>)}
          </select>
        </Field>
        <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Der Übungsanruf klingelt beim Teilnehmer; nur er kann ihn annehmen.</div>
      </div>
    </Modal>
  );
}
