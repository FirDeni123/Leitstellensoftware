import type { ReactNode } from 'react';
import { useSystemInfo } from '@/api/queries';
import type { ModuleState } from '@/api/types';
import { ErrorAlert } from '@/components/common';

const STATE: Record<ModuleState, { label: string; cls: string }> = {
  available: { label: 'Verfügbar', cls: 'ok' },
  partial: { label: 'Teilweise', cls: 'info' },
  planned: { label: 'Geplant', cls: 'warn' },
};

/** Transparent overview of what is implemented and what is still planned. */
export function ModuleStatusPanel(): ReactNode {
  const info = useSystemInfo();
  const modules = [...(info.data?.modules ?? [])].sort((a, b) => a.phase - b.phase);
  return (
    <div className="panel">
      <ErrorAlert error={info.error} />
      <div className="panel-body">
        <table className="data">
          <thead><tr><th style={{ width: 70 }}>Phase</th><th>Modul</th><th style={{ width: 110 }}>Status</th><th>Hinweis</th></tr></thead>
          <tbody>
            {modules.map((m) => (
              <tr key={m.key}>
                <td className="tabular">{m.phase}</td>
                <td>{m.name}</td>
                <td><span className={`badge ${STATE[m.status].cls}`}>{STATE[m.status].label}</span></td>
                <td className="muted" title={m.note ?? undefined}>{m.note ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
