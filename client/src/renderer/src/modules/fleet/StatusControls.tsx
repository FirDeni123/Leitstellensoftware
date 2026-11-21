/** Shared fleet widgets: status badge, status selector (FMS), status history. */
import { useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { describeError } from '@/api/http';
import { useStatusDefinitions, useStatusHistory } from '@/api/queries';
import type { FleetVehicle } from '@/api/types';
import { fmtDateTime, Modal } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { useSession } from '@/state/session';
import { statusInfo, textOn } from './live';

const SOURCE: Record<string, string> = { dispatcher: 'Disponent', simulation: 'Simulation', fms: 'FMS', system: 'System' };

export function StatusBadge({ code, title }: { code: number; title?: string }): ReactNode {
  const defs = useStatusDefinitions();
  const info = statusInfo(defs.data, code);
  return <span className="fms" style={{ background: info.color, color: textOn(info.color) }} title={title ?? info.label}>{code}</span>;
}

/** Sets an FMS status. 0 and 5 create a talk request instead of changing the status. */
export function StatusSelect({ vehicle, simulate = false }: { vehicle: FleetVehicle; simulate?: boolean }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const defs = useStatusDefinitions();
  const [busy, setBusy] = useState(false);
  const set = async (code: number) => {
    setBusy(true);
    try {
      await api.post(`/vehicles/${vehicle.id}/status`, { status_code: code, simulate });
      for (const k of ['fleet', 'incidents', 'talk-requests', 'status-history', 'movements']) void qc.invalidateQueries({ queryKey: [k] });
    } catch (e) {
      sysmsg('error', vehicle.call_sign, describeError(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <select className="select status-select" aria-label={`Status ${vehicle.call_sign}`} value="" disabled={busy}
      onChange={(e) => e.target.value !== '' && void set(Number(e.target.value))}>
      <option value="">{simulate ? 'Meldung simulieren …' : 'Status setzen …'}</option>
      {(defs.data ?? []).map((d) => (
        <option key={d.code} value={d.code} disabled={d.code === vehicle.status_code}>
          {d.code} – {d.short_label}{d.code === 0 || d.code === 5 ? ' (Sprechwunsch)' : ''}
        </option>
      ))}
    </select>
  );
}

export function StatusHistoryModal({ vehicle, onClose }: { vehicle: FleetVehicle; onClose: () => void }): ReactNode {
  const history = useStatusHistory(vehicle.id);
  return (
    <Modal title={`Statushistorie ${vehicle.call_sign}`} onClose={onClose} width={640}>
      <table className="data compact">
        <thead><tr><th>Zeit</th><th>Status</th><th>vorher</th><th>Quelle</th><th>Person</th><th>Vermerk</th></tr></thead>
        <tbody>
          {(history.data ?? []).map((h) => (
            <tr key={h.id}>
              <td className="tabular">{fmtDateTime(h.ts)}</td>
              <td><StatusBadge code={h.status_code} /></td>
              <td>{h.previous_code !== null ? <StatusBadge code={h.previous_code} /> : '–'}</td>
              <td>{SOURCE[h.source] ?? h.source}</td>
              <td className="muted">{h.actor_name.replace(/ \(.*\)$/, '')}</td>
              <td className="muted">{h.note ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {history.data?.length === 0 && <div className="muted">Noch keine Statuswechsel.</div>}
      <div className="muted" style={{ fontSize: 'var(--fs-xs)', marginTop: 6 }}>Die Statushistorie ist unveränderbar gespeichert.</div>
    </Modal>
  );
}
