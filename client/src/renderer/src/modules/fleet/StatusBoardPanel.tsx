/** Statusübersicht (Statustableau): vehicles grouped by station, radio group or organisation. */
import { useState, type ReactNode } from 'react';
import { useFleet, useStatusDefinitions } from '@/api/queries';
import type { FleetVehicle } from '@/api/types';
import { EmptyState, ErrorAlert } from '@/components/common';
import { hasPermission, useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';
import { groupVehicles, statusInfo, textOn, type Grouping } from './live';
import { StatusSelect } from './StatusControls';

const GROUPING: Record<Grouping, string> = { station: 'Wache', radio_group: 'Funkrufgruppe', organization: 'Organisation' };

export function StatusBoardPanel({ defaultGrouping = 'station' }: { defaultGrouping?: Grouping }): ReactNode {
  const me = useSession((s) => s.me)!;
  const { active } = useActiveControlCenter();
  const fleet = useFleet(active?.id);
  const defs = useStatusDefinitions();
  const [by, setBy] = useState<Grouping>(defaultGrouping);
  const [selected, setSelected] = useState<FleetVehicle | null>(null);
  const canSet = hasPermission(me, 'vehicles.status.set');
  const counts = new Map<number, number>();
  for (const v of fleet.data ?? []) counts.set(v.status_code, (counts.get(v.status_code) ?? 0) + 1);
  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <div className="chips" role="group" aria-label="Gruppierung">
          {(Object.keys(GROUPING) as Grouping[]).map((g) => <button key={g} type="button" className={`chip ${by === g ? 'on' : ''}`} onClick={() => setBy(g)}>{GROUPING[g]}</button>)}
        </div>
        <div className="status-summary">
          {(defs.data ?? []).filter((d) => counts.get(d.code)).map((d) => (
            <span key={d.code} className="fms wide" style={{ background: d.color, color: textOn(d.color) }} title={d.label}>{d.code}: {counts.get(d.code)}</span>
          ))}
        </div>
      </div>
      <ErrorAlert error={fleet.error} />
      <div className="panel-body" style={{ padding: 8 }}>
        {(fleet.data ?? []).length === 0 && !fleet.isLoading && <EmptyState title="Keine Fahrzeuge" />}
        {groupVehicles(fleet.data ?? [], by).map(([group, vehicles]) => (
          <div key={group} className="board-group">
            <div className="board-title">{group}</div>
            <div className="board-tiles">
              {vehicles.map((v) => {
                const info = statusInfo(defs.data, v.status_code);
                return (
                  <button key={v.id} type="button" className={`board-tile ${selected?.id === v.id ? 'selected' : ''}`}
                    style={{ borderColor: info.color }} title={`${v.call_sign} – ${info.label}${v.incident ? ` – Einsatz ${v.incident.number}` : ''}`}
                    onClick={() => setSelected(v)}>
                    <span className="board-code" style={{ background: info.color, color: textOn(info.color) }}>{v.status_code}</span>
                    <span className="board-name">{v.call_sign}</span>
                    {v.talk_request && <span className={`board-talk ${v.talk_request.priority === 0 ? 'urgent' : ''}`}>SW</span>}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      {selected && canSet && (
        <div className="board-action">
          <b>{selected.call_sign}</b>
          <StatusSelect vehicle={(fleet.data ?? []).find((v) => v.id === selected.id) ?? selected} />
          <button className="btn ghost sm" onClick={() => setSelected(null)}>Schließen</button>
        </div>
      )}
    </div>
  );
}
