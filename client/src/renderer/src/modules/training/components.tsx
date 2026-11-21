/** Shared views of the training module: transcript, evaluation report, labels. */
import { useEffect, useRef, type ReactNode } from 'react';
import type { Difficulty, TrainingEvaluation, TrainingMessage, TrainingSessionSummary, TrainingStatus } from '@/api/types';
import { fmtDateTime, fmtTime } from '@/components/common';
import type { StreamingReply } from './live';

export const DIFFICULTY: Record<Difficulty, { label: string; cls: string }> = {
  easy: { label: 'leicht', cls: 'ok' },
  medium: { label: 'mittel', cls: 'info' },
  hard: { label: 'schwer', cls: 'danger' },
};

export const SESSION_STATUS: Record<TrainingStatus, { label: string; cls: string }> = {
  ringing: { label: 'klingelt', cls: 'danger' },
  active: { label: 'im Gespräch', cls: 'ok' },
  ended: { label: 'beendet – Auswertung läuft', cls: 'info' },
  evaluated: { label: 'ausgewertet', cls: '' },
  cancelled: { label: 'abgebrochen', cls: 'warn' },
};

export function callerModeLabel(s: Pick<TrainingSessionSummary, 'caller_mode' | 'model'>): string {
  return s.caller_mode === 'claude' ? `KI-Anrufer (${s.model ?? 'Claude'})` : 'Regelbasierter Anrufer (ohne KI)';
}

export function seconds(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '–';
  return `${(ms / 1000).toLocaleString('de-DE', { maximumFractionDigits: 1, minimumFractionDigits: 1 })} s`;
}

function secs(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–';
  if (value < 60) return `${Math.round(value)} s`;
  return `${Math.floor(value / 60)}:${String(Math.round(value % 60)).padStart(2, '0')} min`;
}

export function ExerciseBanner({ session }: { session: Pick<TrainingSessionSummary, 'caller_mode' | 'model' | 'title' | 'difficulty'> }): ReactNode {
  return (
    <div className="training-banner" role="note">
      <b>ÜBUNG · SIMULATION</b> – kein echter Notruf · {session.title} · <span className={`badge ${DIFFICULTY[session.difficulty].cls}`}>{DIFFICULTY[session.difficulty].label}</span>
      <span className="muted"> · {callerModeLabel(session)}</span>
    </div>
  );
}

export function Transcript(props: {
  messages: TrainingMessage[];
  streaming?: StreamingReply | undefined;
  /** instructors also see interventions ("Regie") and notes */
  showInstructor?: boolean;
}): ReactNode {
  const end = useRef<HTMLDivElement>(null);
  const live = props.streaming && !props.messages.some((m) => m.id === props.streaming!.finalId) ? props.streaming : undefined;
  const count = props.messages.length + (live?.parts.length ?? 0);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' });
  }, [count]);
  return (
    <div className="chat selectable" aria-label="Gesprächsverlauf" aria-live="polite">
      {props.messages.map((m) => {
        if (m.role === 'system') return <div key={m.id} className="chat-system">{fmtTime(m.ts)} · {m.text}</div>;
        if (m.role === 'instructor') {
          if (!props.showInstructor) return null;
          return (
            <div key={m.id} className="chat-row instructor">
              <div className="bubble instructor">
                <div className="bubble-head">{m.source === 'note' ? 'Notiz' : 'Regie'} · {m.author_name?.replace(/ \(.*\)$/, '') ?? 'Ausbilder'} · {fmtTime(m.ts)}</div>
                {m.text}
              </div>
            </div>
          );
        }
        const mine = m.role === 'dispatcher';
        return (
          <div key={m.id} className={`chat-row ${mine ? 'dispatcher' : 'caller'}`} data-role={m.role}>
            <div className={`bubble ${m.role}`}>
              <div className="bubble-head">
                {mine ? 'Disponent' : 'Anrufer'} · {fmtTime(m.ts)}
                {m.source === 'voice' && ' · gesprochen'}
                {m.source === 'rules' && <span className="badge warn" style={{ marginLeft: 4 }}>regelbasiert</span>}
                {m.role === 'caller' && m.source !== 'opening' && m.latency_ms !== null && <span className="muted"> · {seconds(m.latency_ms)}</span>}
              </div>
              {m.text}
            </div>
          </div>
        );
      })}
      {live && (
        <div className="chat-row caller" data-role="caller-live">
          <div className="bubble caller live">
            <div className="bubble-head">Anrufer · spricht …</div>
            {live.parts.join(' ')}
          </div>
        </div>
      )}
      <div ref={end} />
    </div>
  );
}

export function EvaluationView({ evaluation }: { evaluation: TrainingEvaluation }): ReactNode {
  const m = evaluation.metrics;
  const fb = evaluation.feedback;
  const cls = evaluation.score >= 80 ? 'ok' : evaluation.score >= 50 ? 'warn' : 'danger';
  return (
    <div className="evaluation" aria-label="Auswertung">
      <div className="evaluation-head">
        <div className={`score ${cls}`} aria-label="Ergebnis">{evaluation.score} %</div>
        <div>
          <div><b>Auswertung</b> vom {fmtDateTime(evaluation.created_at)}</div>
          <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
            {evaluation.method === 'claude' ? `Gesprächsführung bewertet durch KI (${evaluation.model ?? 'Claude'})` : 'Regelbasierte Auswertung (Schlüsselwörter, ohne KI)'}
            {' · '}Handlungen im System werden immer direkt geprüft
          </div>
          {fb.note && <div className="badge warn" style={{ marginTop: 4 }}>{fb.note}</div>}
        </div>
      </div>
      <table className="data" aria-label="Checkliste">
        <thead><tr><th style={{ width: 28 }} /><th>Prüfpunkt</th><th style={{ width: 70 }}>Art</th><th>Beleg</th></tr></thead>
        <tbody>
          {evaluation.checklist.map((item) => (
            <tr key={item.key} data-key={item.key} className={item.fulfilled ? 'ok-row' : 'miss-row'}>
              <td aria-label={item.fulfilled ? 'erfüllt' : 'nicht erfüllt'}>{item.fulfilled ? '✓' : '✗'}</td>
              <td>{item.label}{!item.required && <span className="muted"> (optional)</span>}</td>
              <td className="muted">{item.kind === 'action' ? 'Handlung' : 'Gespräch'}</td>
              <td className="muted">{item.evidence}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="metrics" aria-label="Kennzahlen">
        <Metric label="Annahme nach" value={secs(m['answer_seconds'])} />
        <Metric label="Einsatz angelegt nach" value={secs(m['incident_seconds'])} />
        <Metric label="Alarmierung nach" value={secs(m['alarm_seconds'])} />
        <Metric label="Gesprächsdauer" value={secs(m['conversation_seconds'])} />
        <Metric label="Beiträge Disponent / Anrufer" value={`${m['dispatcher_turns'] ?? 0} / ${m['caller_turns'] ?? 0}`} />
        <Metric label="Antwortzeit Anrufer Ø / max" value={`${seconds(m['reply_latency_avg_ms'])} / ${seconds(m['reply_latency_max_ms'])}`} />
        {(m['voice_turns'] ?? 0) > 0 && <Metric label="Gesprochene Beiträge" value={String(m['voice_turns'])} />}
        {(m['rule_replies'] ?? 0) > 0 && <Metric label="Regelbasierte Antworten" value={String(m['rule_replies'])} />}
      </div>
      {fb.summary && <p style={{ margin: '8px 0' }}>{fb.summary}</p>}
      {!!fb.strengths?.length && (
        <div><b>Stärken</b><ul>{fb.strengths.map((s) => <li key={s}>{s}</li>)}</ul></div>
      )}
      {!!fb.improvements?.length && (
        <div><b>Verbesserungsvorschläge</b><ul>{fb.improvements.map((s) => <li key={s}>{s}</li>)}</ul></div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }): ReactNode {
  return (
    <div className="metric">
      <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>{label}</div>
      <div className="tabular">{value}</div>
    </div>
  );
}
