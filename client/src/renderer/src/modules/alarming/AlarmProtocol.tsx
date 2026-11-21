/** Alarm protocol: every alarm of an incident (or of the control centre) with its delivery results. */
import { useState, type ReactNode } from 'react';
import type { Alarm } from '@/api/types';
import { fmtDateTime, fmtTime } from '@/components/common';
import { ALARM_KIND, ALARM_STATUS, DELIVERY, deliverySummary, TARGET_TYPE } from './labels';

export function AlarmCard({ alarm, showIncident = false }: { alarm: Alarm; showIncident?: boolean }): ReactNode {
  const [open, setOpen] = useState(false);
  return (
    <div className="alarm-card">
      <button type="button" className="alarm-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="tabular">{showIncident ? fmtDateTime(alarm.created_at) : fmtTime(alarm.created_at)}</span>
        {showIncident && <span className="mono">{alarm.incident_number}</span>}
        <span style={{ fontWeight: 600 }}>{ALARM_KIND[alarm.kind]}{alarm.stage ? ` · Stufe ${alarm.stage}` : ''}</span>
        <span className={`badge ${alarm.mode === 'real' ? 'danger' : 'sim-badge'}`}>{alarm.mode === 'real' ? 'ECHT' : 'SIM'}</span>
        <span className={`badge ${ALARM_STATUS[alarm.status].cls}`}>{ALARM_STATUS[alarm.status].label}</span>
        <span className="muted">{deliverySummary(alarm)}</span>
        <span className="muted" style={{ marginLeft: 'auto' }}>{alarm.triggered_by_name.replace(/ \(.*\)$/, '')}</span>
      </button>
      {alarm.note && <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Vermerk: {alarm.note}</div>}
      {open && (
        <table className="data compact">
          <tbody>
            {alarm.targets.map((t) => (
              <tr key={t.id}>
                <td style={{ width: 96 }} className="muted">{TARGET_TYPE[t.target_type]}</td>
                <td style={{ fontWeight: 600 }}>{t.label}</td>
                <td><span className={`badge ${DELIVERY[t.delivery_status].cls}`}>{DELIVERY[t.delivery_status].label}</span></td>
                <td className="muted">{t.detail ?? ''}{t.reason ? ` · ${t.reason}` : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function AlarmProtocol({ alarms }: { alarms: Alarm[] }): ReactNode {
  if (alarms.length === 0) return <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>noch keine Alarmierung</div>;
  return <div>{alarms.map((a) => <AlarmCard key={a.id} alarm={a} />)}</div>;
}
