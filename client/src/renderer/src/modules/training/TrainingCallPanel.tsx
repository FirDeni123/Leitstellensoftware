/**
 * Übungsgespräch: the trainee's side of an exercise.
 * Start a scenario → the training call rings in "Neue Notrufe" (and here) → talk to the caller
 * (typed or push-to-talk) while capturing the incident in the normal windows → hang up →
 * automatic evaluation. Nothing here ever reaches a real emergency line.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { ApiError, describeError } from '@/api/http';
import { useTrainingScenarios, useTrainingSession, useTrainingSessions } from '@/api/queries';
import type { TrainingSessionDetail } from '@/api/types';
import { EmptyState, ErrorAlert, fmtDateTime } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';
import { DIFFICULTY, EvaluationView, ExerciseBanner, SESSION_STATUS, Transcript } from './components';
import {
  recordingAvailable, speakSession, speechOutputAvailable, startRecording, useSpeechOutput, useTrainingLive, type Recording,
} from './live';

export function TrainingCallPanel(): ReactNode {
  const open = useTrainingSessions({ mine: true, status: 'open' });
  const [viewId, setViewId] = useState<string | null>(null);
  const currentId = open.data?.[0]?.id ?? viewId;
  const detail = useTrainingSession(currentId);

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Ausbildung · Übungsanrufe sind Simulation</span>
        <div className="spacer" />
        {currentId && !open.data?.length && <button className="btn sm" onClick={() => setViewId(null)}>Neue Übung</button>}
      </div>
      <ErrorAlert error={open.error ?? detail.error} />
      <div className="panel-body">
        {!currentId ? <StartExercise onStarted={setViewId} onOpen={setViewId} />
          : detail.data ? <ExerciseView session={detail.data} />
            : <EmptyState title="Übung wird geladen …" />}
      </div>
    </div>
  );
}

function StartExercise({ onStarted, onOpen }: { onStarted(id: string): void; onOpen(id: string): void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const { active } = useActiveControlCenter();
  const scenarios = useTrainingScenarios(active?.id);
  const recent = useTrainingSessions({ mine: true });
  const [busy, setBusy] = useState(false);

  const start = async (scenarioId: string) => {
    if (!active) return;
    setBusy(true);
    try {
      const session = await api.post<TrainingSessionDetail>('/training/sessions', { scenario_id: scenarioId, control_center_id: active.id });
      onStarted(session.id);
      await qc.invalidateQueries({ queryKey: ['training-sessions'] });
      sysmsg('info', 'Ausbildung', 'Übungsanruf klingelt – bitte annehmen.');
    } catch (e) {
      sysmsg('error', 'Ausbildung', describeError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <ErrorAlert error={scenarios.error} />
      <h3 style={{ margin: 0 }}>Übung auswählen</h3>
      {(scenarios.data ?? []).length === 0 && !scenarios.isLoading ? (
        <EmptyState title="Keine Übungsszenarien">Ausbilder legen Szenarien im Fenster „Übungsszenarien" an.</EmptyState>
      ) : (
        <table className="data" aria-label="Übungsszenarien">
          <thead><tr><th>Szenario</th><th style={{ width: 80 }}>Stufe</th><th style={{ width: 120 }} /></tr></thead>
          <tbody>
            {(scenarios.data ?? []).map((s) => (
              <tr key={s.id}>
                <td><b>{s.title}</b>{s.description && <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{s.description}</div>}</td>
                <td><span className={`badge ${DIFFICULTY[s.difficulty].cls}`}>{DIFFICULTY[s.difficulty].label}</span></td>
                <td><button className="btn primary sm" disabled={busy || !active} onClick={() => void start(s.id)}>Übung starten</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!!recent.data?.length && (
        <>
          <h3 style={{ margin: '8px 0 0' }}>Meine letzten Übungen</h3>
          <table className="data" aria-label="Meine Übungen">
            <thead><tr><th>Übung</th><th style={{ width: 140 }}>Zeitpunkt</th><th style={{ width: 150 }}>Status</th><th style={{ width: 70 }}>Ergebnis</th></tr></thead>
            <tbody>
              {recent.data.slice(0, 10).map((s) => (
                <tr key={s.id} className="clickable" onClick={() => onOpen(s.id)}>
                  <td>{s.title}</td>
                  <td className="tabular">{fmtDateTime(s.created_at)}</td>
                  <td><span className={`badge ${SESSION_STATUS[s.status].cls}`}>{SESSION_STATUS[s.status].label}</span></td>
                  <td className="tabular">{s.score !== null ? `${s.score} %` : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function ExerciseView({ session }: { session: TrainingSessionDetail }): ReactNode {
  const api = useSession((s) => s.api)!;
  const me = useSession((s) => s.me)!;
  const qc = useQueryClient();
  const streaming = useTrainingLive((s) => s.streaming[session.id]);
  const mine = session.trainee_id === me.id;
  const talking = session.status === 'active';

  useEffect(() => (mine && talking ? speakSession(session.id) : undefined), [mine, talking, session.id]);

  const refresh = () => qc.invalidateQueries({ queryKey: ['training-session', session.id] });
  const answer = async () => {
    try {
      await api.post(`/calls/${session.call_id}/answer`, {});
      await qc.invalidateQueries({ queryKey: ['calls'] });
      await refresh();
    } catch (e) {
      sysmsg('error', 'Ausbildung', describeError(e));
    }
  };
  const hangUp = async () => {
    try {
      await api.post(`/training/sessions/${session.id}/end`);
      await qc.invalidateQueries({ queryKey: ['calls'] });
      await qc.invalidateQueries({ queryKey: ['training-sessions'] });
      await refresh();
    } catch (e) {
      sysmsg('error', 'Ausbildung', describeError(e));
    }
  };

  return (
    <div className="exercise">
      <ExerciseBanner session={session} />
      {session.status === 'ringing' && (
        <div className="exercise-ringing" role="alert">
          <b>Übungsanruf klingelt</b> – Annahme hier oder im Fenster „Neue Notrufe".
          <button className="btn primary" onClick={() => void answer()}>Annehmen</button>
          <button className="btn ghost sm" onClick={() => void hangUp()}>Übung abbrechen</button>
        </div>
      )}
      {(session.status === 'active' || session.status === 'ended' || session.status === 'evaluated' || session.status === 'cancelled') && (
        <Transcript messages={session.messages} streaming={streaming} />
      )}
      {talking && mine && <Composer session={session} onHangUp={() => void hangUp()} />}
      {session.status === 'ended' && <EmptyState title="Gespräch beendet">Die Auswertung wird erstellt …</EmptyState>}
      {session.status === 'cancelled' && <EmptyState title="Übung abgebrochen">Es wurde keine Auswertung erstellt.</EmptyState>}
      {session.evaluation && <EvaluationView evaluation={session.evaluation} />}
      {session.scenario && session.status !== 'active' && <ScenarioSolution scenario={session.scenario} />}
    </div>
  );
}

function Composer({ session, onHangUp }: { session: TrainingSessionDetail; onHangUp(): void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [recording, setRecording] = useState(false);
  const [sttMissing, setSttMissing] = useState(false);
  const rec = useRef<Recording | null>(null);
  const tts = useSpeechOutput();
  const onHold = session.call_status === 'on_hold';

  const send = async () => {
    const words = text.trim();
    if (!words || sending) return;
    setSending(true);
    try {
      await api.post(`/training/sessions/${session.id}/messages`, { text: words, source: 'text' });
      setText('');
      await qc.invalidateQueries({ queryKey: ['training-session', session.id] });
    } catch (e) {
      sysmsg('error', 'Übungsgespräch', describeError(e));
    } finally {
      setSending(false);
    }
  };

  const pressTalk = async () => {
    if (recording || sttMissing) return;
    try {
      rec.current = await startRecording();
      setRecording(true);
    } catch (e) {
      sysmsg('error', 'Sprechtaste', `Mikrofon nicht verfügbar: ${describeError(e)}`);
    }
  };
  const releaseTalk = async () => {
    const current = rec.current;
    rec.current = null;
    setRecording(false);
    if (!current) return;
    const audio = await current.stop();
    if (audio.size < 2000) return; // too short – nothing said
    const form = new FormData();
    form.append('audio', audio, 'aufnahme.webm');
    try {
      await api.upload(`/training/sessions/${session.id}/speech`, form);
      await qc.invalidateQueries({ queryKey: ['training-session', session.id] });
    } catch (e) {
      if (e instanceof ApiError && e.status === 501) setSttMissing(true);
      sysmsg(e instanceof ApiError && e.status === 501 ? 'warning' : 'error', 'Sprechtaste', describeError(e));
    }
  };
  useEffect(() => () => rec.current?.cancel(), []);

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  return (
    <div className="composer">
      {onHold && <div className="badge warn">Gespräch wird gehalten – zum Weitersprechen im Fenster „Laufende Telefonate" fortsetzen.</div>}
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          className="input" style={{ flex: 1 }} aria-label="Ihre Antwort an den Anrufer" placeholder="Sprechen Sie mit dem Anrufer … (Enter sendet)"
          value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} disabled={onHold} maxLength={2000} autoFocus
        />
        <button className="btn primary" onClick={() => void send()} disabled={!text.trim() || sending || onHold}>Senden</button>
        {recordingAvailable() && (
          <button
            className={`btn ${recording ? 'danger' : ''}`} disabled={onHold || sttMissing}
            title={sttMissing ? 'Spracherkennung auf dem Server nicht installiert' : 'Gedrückt halten und sprechen'}
            onPointerDown={() => void pressTalk()} onPointerUp={() => void releaseTalk()} onPointerLeave={() => recording && void releaseTalk()}
          >
            {recording ? '● Aufnahme …' : '🎤 Sprechtaste'}
          </button>
        )}
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 'var(--fs-sm)' }}>
        {speechOutputAvailable() && (
          <button className="btn ghost sm" onClick={tts.toggle} aria-pressed={tts.enabled}>{tts.enabled ? '🔊 Sprachausgabe an' : '🔇 Sprachausgabe aus'}</button>
        )}
        <span className="muted">Einsatz parallel in „Neue Notrufe"/„Aktuelle Einsätze" anlegen und alarmieren.</span>
        <div className="spacer" />
        <button className="btn danger sm" onClick={onHangUp}>Auflegen</button>
      </div>
    </div>
  );
}

function ScenarioSolution({ scenario }: { scenario: NonNullable<TrainingSessionDetail['scenario']> }): ReactNode {
  const f = scenario.facts;
  return (
    <details className="solution">
      <summary>Lösung: tatsächliche Lage des Szenarios</summary>
      <dl className="kv">
        {scenario.keyword && <><dt>Stichwort</dt><dd>{scenario.keyword.code} – {scenario.keyword.name}</dd></>}
        {f.address && <><dt>Einsatzort</dt><dd>{f.address}{f.location_hint && ` (${f.location_hint})`}</dd></>}
        {f.situation && <><dt>Lage</dt><dd>{f.situation}</dd></>}
        {f.persons && <><dt>Personen</dt><dd>{f.persons}</dd></>}
        {f.injuries && <><dt>Verletzungen</dt><dd>{f.injuries}</dd></>}
        {f.hazards && <><dt>Gefahren</dt><dd>{f.hazards}</dd></>}
        {scenario.persona.name && <><dt>Anrufer</dt><dd>{scenario.persona.name}{scenario.persona.phone && `, ${scenario.persona.phone}`}</dd></>}
      </dl>
    </details>
  );
}
