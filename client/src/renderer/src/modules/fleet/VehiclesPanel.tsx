/** Fahrzeugübersicht: all vehicles with status, station, incident, position/ETA; status setting. */
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { describeError } from '@/api/http';
import { useFleet, useSimulationClock, useStatusDefinitions } from '@/api/queries';
import type { FleetVehicle } from '@/api/types';
import { EmptyState, ErrorAlert } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { hasPermission, useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';
import { fmtEta, shownPosition, staleLiveIds, statusInfo, useLivePositions } from './live';
import { StatusBadge, StatusHistoryModal, StatusSelect } from './StatusControls';

export function VehiclesPanel(): ReactNode {
  const me = useSession((s) => s.me)!;
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const { active } = useActiveControlCenter();
  const fleet = useFleet(active?.id);
  const defs = useStatusDefinitions();
  const clock = useSimulationClock();
  const live = useLivePositions((s) => s.byId);
  const drop = useLivePositions((s) => s.drop);
  const [q, setQ] = useState('');
  const [onlyBusy, setOnlyBusy] = useState(false);
  const [history, setHistory] = useState<FleetVehicle | null>(null);
  const canSet = hasPermission(me, 'vehicles.status.set');
  const canSim = hasPermission(me, 'simulation.control') && !!clock.data?.simulation_mode;

  useEffect(() => {
    if (fleet.data) drop(staleLiveIds(fleet.data, useLivePositions.getState().byId));
  }, [fleet.data, drop]);

  const filter = q.trim().toLowerCase();
  const rows = (fleet.data ?? []).filter((v) => (!onlyBusy || v.incident || v.position?.moving)
    && (!filter || `${v.call_sign} ${v.vehicle_type} ${v.station} ${v.organization}`.toLowerCase().includes(filter)));

  const breakdown = async (v: FleetVehicle) => {
    try {
      await api.post(`/simulation/vehicles/${v.id}/breakdown`, {});
      await qc.invalidateQueries({ queryKey: ['fleet'] });
    } catch (e) {
      sysmsg('error', v.call_sign, describeError(e));
    }
  };

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <input className="input" placeholder="Funkrufname, Typ, Wache …" aria-label="Fahrzeuge filtern" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 220 }} />
        <button type="button" className={`chip ${onlyBusy ? 'on' : ''}`} onClick={() => setOnlyBusy((b) => !b)}>nur im Einsatz / unterwegs</button>
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{rows.length} Fahrzeuge</span>
        {clock.data?.simulation_mode && clock.data.factor !== 1 && <span className="badge sim-badge">Zeitraffer {clock.data.factor}×</span>}
        {clock.data?.paused && <span className="badge warn">Simulation pausiert</span>}
      </div>
      <ErrorAlert error={fleet.error} />
      <div className="panel-body table-wrap">
        {rows.length === 0 && !fleet.isLoading ? <EmptyState title="Keine Fahrzeuge" /> : (
          <table className="data">
            <thead><tr><th style={{ width: 54 }}>Status</th><th>Funkrufname</th><th>Typ</th><th>Wache</th><th>Einsatz</th><th>Lage</th><th style={{ width: 170 }} /></tr></thead>
            <tbody>
              {rows.map((v) => {
                const pos = shownPosition(v, live[v.id]);
                const info = statusInfo(defs.data, v.status_code);
                return (
                  <tr key={v.id} className={v.available ? '' : 'inactive'} data-vehicle={v.call_sign}>
                    <td><StatusBadge code={v.status_code} /></td>
                    <td style={{ fontWeight: 600 }}>
                      {v.call_sign}
                      {v.talk_request && <span className={`badge ${v.talk_request.priority === 0 ? 'danger blink' : 'info'}`} style={{ marginLeft: 6 }}>SW {v.talk_request.priority}</span>}
                    </td>
                    <td className="mono">{v.vehicle_type}</td>
                    <td className="muted">{v.station}</td>
                    <td className="mono">{v.incident?.number ?? ''}</td>
                    <td className="muted" title={info.label}>
                      {pos?.moving ? `${live[v.id]?.kind === 'to_station' ? 'Rückfahrt' : 'Anfahrt'} · ETA ${fmtEta(pos.eta_s)}`
                        : v.planned_departure_s !== null ? `rückt aus in ${fmtEta(v.planned_departure_s)}`
                          : pos?.source === 'station' ? 'auf Wache' : pos ? 'vor Ort / unterwegs gestoppt' : 'Position unbekannt'}
                    </td>
                    <td style={{ display: 'flex', gap: 4 }}>
                      {canSet && <StatusSelect vehicle={v} />}
                      <button className="btn ghost sm" title="Statushistorie" aria-label={`Statushistorie ${v.call_sign}`} onClick={() => setHistory(v)}>⏱</button>
                      {canSim && v.status_code !== 6 && <button className="btn ghost sm" title="Ausfall simulieren" aria-label={`Ausfall ${v.call_sign}`} onClick={() => void breakdown(v)}>⚠</button>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {history && <StatusHistoryModal vehicle={history} onClose={() => setHistory(null)} />}
    </div>
  );
}
