/** Übungsberichte: evaluation reports (own exercises; instructors: all of the control centre). */
import { useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { describeError } from '@/api/http';
import { useTrainingSession, useTrainingSessions } from '@/api/queries';
import { EmptyState, ErrorAlert, fmtDateTime } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { hasPermission, useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';
import { EvaluationView, ExerciseBanner, SESSION_STATUS, Transcript } from './components';

export function TrainingReportsPanel(): ReactNode {
  const me = useSession((s) => s.me)!;
  const instructor = hasPermission(me, 'training.instructor');
  const { active } = useActiveControlCenter();
  const [mine, setMine] = useState(!instructor);
  const sessions = useTrainingSessions({ controlCenterId: active?.id, mine }, !!active);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const done = (sessions.data ?? []).filter((s) => s.status === 'evaluated' || s.status === 'ended');

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        {instructor && (
          <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: 'var(--fs-sm)' }}>
            <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> nur meine
          </label>
        )}
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{done.length} Berichte</span>
      </div>
      <ErrorAlert error={sessions.error} />
      <div className="panel-split">
        <div className="master table-wrap">
          {done.length === 0 ? <EmptyState title="Noch keine Übungsberichte" /> : (
            <table className="data" aria-label="Übungsberichte">
              <thead><tr><th style={{ width: 130 }}>Datum</th><th>Teilnehmer</th><th>Szenario</th><th style={{ width: 70 }}>Ergebnis</th></tr></thead>
              <tbody>
                {done.map((s) => (
                  <tr key={s.id} className={`clickable ${s.id === selectedId ? 'selected' : ''}`} onClick={() => setSelectedId(s.id)}>
                    <td className="tabular">{fmtDateTime(s.created_at)}</td>
                    <td>{s.trainee_name}</td>
                    <td>{s.title}</td>
                    <td className="tabular">{s.score !== null ? `${s.score} %` : <span className={`badge ${SESSION_STATUS[s.status].cls}`}>…</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="detail" style={{ flex: 1.4 }}>
          {selectedId ? <Report key={selectedId} id={selectedId} instructor={instructor} /> : <EmptyState title="Bericht auswählen" />}
        </div>
      </div>
    </div>
  );
}

function Report({ id, instructor }: { id: string; instructor: boolean }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const detail = useTrainingSession(id);
  const [busy, setBusy] = useState(false);
  const s = detail.data;
  if (!s) return <ErrorAlert error={detail.error} />;
  const evaluate = async () => {
    setBusy(true);
    try {
      await api.post(`/training/sessions/${id}/evaluate`);
      await qc.invalidateQueries({ queryKey: ['training-session', id] });
      await qc.invalidateQueries({ queryKey: ['training-sessions'] });
    } catch (e) {
      sysmsg('error', 'Übungsbericht', describeError(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="exercise">
      <ExerciseBanner session={s} />
      <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{s.trainee_name} · {fmtDateTime(s.created_at)}</div>
      {s.evaluation ? <EvaluationView evaluation={s.evaluation} /> : <EmptyState title="Noch nicht ausgewertet" />}
      {(instructor || !s.evaluation) && (
        <div><button className="btn sm" disabled={busy} onClick={() => void evaluate()}>{s.evaluation ? 'Neu auswerten' : 'Jetzt auswerten'}</button></div>
      )}
      <h4 style={{ margin: '6px 0 0' }}>Gesprächsverlauf</h4>
      <Transcript messages={s.messages} showInstructor={instructor} />
    </div>
  );
}
