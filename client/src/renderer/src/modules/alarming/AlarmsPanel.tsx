/** Alarmierungsübersicht: recent alarms of the control centre and open police notices. */
import type { ReactNode } from 'react';
import { useAlarms, usePoliceNotices } from '@/api/queries';
import { EmptyState, ErrorAlert, fmtTime } from '@/components/common';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';
import { AlarmCard } from './AlarmProtocol';
import { usePoliceNoticeQueue } from './policeNotices';

export function AlarmsPanel(): ReactNode {
  const { active } = useActiveControlCenter();
  const alarms = useAlarms(active?.id);
  const notices = usePoliceNotices(active?.id);
  const show = usePoliceNoticeQueue((s) => s.show);
  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{alarms.data?.length ?? 0} Alarmierungen</span>
      </div>
      <ErrorAlert error={alarms.error ?? notices.error} />
      <div className="panel-body">
        {(notices.data ?? []).length > 0 && (
          <>
            <div className="section-title">Offene Polizei-Hinweise ({notices.data!.length})</div>
            {notices.data!.map((n) => (
              <div key={n.id} className="assignment">
                <span className="badge police-badge">Polizei informieren</span>
                <span className="mono">{n.incident_number}</span>
                <span>{n.text}</span>
                <span className="muted tabular" style={{ marginLeft: 'auto' }}>{fmtTime(n.created_at)}</span>
                <button className="btn sm" onClick={() => show(n)}>Bestätigen …</button>
              </div>
            ))}
          </>
        )}
        <div className="section-title">Alarmierungsprotokoll</div>
        {(alarms.data ?? []).length === 0 && !alarms.isLoading
          ? <EmptyState title="Noch keine Alarmierungen">Alarmierungen werden im Einsatz über „Alarmieren“ ausgelöst.</EmptyState>
          : (alarms.data ?? []).map((a) => <AlarmCard key={a.id} alarm={a} showIncident />)}
      </div>
    </div>
  );
}
