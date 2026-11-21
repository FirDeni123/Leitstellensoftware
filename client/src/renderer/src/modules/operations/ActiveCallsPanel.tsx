import type { ReactNode } from 'react';
import { useCalls } from '@/api/queries';
import { EmptyState, ErrorAlert } from '@/components/common';
import { useActiveControlCenter } from '@/state/workContext';
import { CALL_STATUS, elapsed, useNow } from './labels';

/** Laufende Telefonate: who is talking to whom, for how long (audio follows in phase 7). */
export function ActiveCallsPanel(): ReactNode {
  const { active } = useActiveControlCenter();
  const calls = useCalls(active?.id);
  const now = useNow();
  const running = (calls.data ?? []).filter((c) => c.status === 'active' || c.status === 'on_hold');
  return (
    <div className="panel">
      <ErrorAlert error={calls.error} />
      <div className="panel-body">
        {running.length === 0 ? (
          <EmptyState title="Keine laufenden Telefonate">Sprachübertragung (Mikrofon/Lautsprecher) folgt mit Phase 7.</EmptyState>
        ) : (
          <table className="data">
            <thead><tr><th>Status</th><th>Disponent</th><th>Anrufer</th><th>Dauer</th><th>Einsatz</th></tr></thead>
            <tbody>
              {running.map((c) => (
                <tr key={c.id}>
                  <td><span className={`badge ${CALL_STATUS[c.status].cls}`}>{CALL_STATUS[c.status].label}</span></td>
                  <td>{c.handled_by_name}</td>
                  <td>{c.source === 'sim' && <span className="badge sim-badge">SIM</span>}{c.source === 'training' && <span className="badge sim-badge" title="Übungsanruf (Ausbildung)">ÜBUNG</span>} <span className="mono">{c.caller_phone ?? 'unterdrückt'}</span></td>
                  <td className="tabular">{c.answered_at ? elapsed(c.answered_at, now) : '–'}</td>
                  <td className="mono">{c.incident?.number ?? '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
