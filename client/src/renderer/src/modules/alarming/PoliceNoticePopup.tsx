/**
 * Police notice (Polizei-Hinweis): an information popup that must be acknowledged.
 * Nothing is transmitted to the police – informing them is the dispatcher's task.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { ApiError } from '@/api/http';
import type { PoliceNotice } from '@/api/types';
import { ErrorAlert, Field, fmtTime, Modal } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { onRealtimeEvent, useSession } from '@/state/session';
import { usePoliceNoticeQueue } from './policeNotices';

/** Mounted once in the shell. */
export function PoliceNoticePopup(): ReactNode {
  const me = useSession((s) => s.me);
  const api = useSession((s) => s.api);
  const queue = usePoliceNoticeQueue((s) => s.queue);

  // A notice created for me on another workstation PC (same user) pops up here as well.
  useEffect(() => onRealtimeEvent((e) => {
    if (e.topic !== 'police_notice.changed' || !api || !me) return;
    const id = String(e.data['id']);
    if (e.data['action'] === 'acknowledged') {
      usePoliceNoticeQueue.getState().done(id);
      return;
    }
    if (e.data['action'] === 'created' && e.data['for_user'] === me.id) {
      void api.get<PoliceNotice[]>('/police-notices', { only_open: true }).then((list) => {
        const notice = list.find((n) => n.id === id);
        if (notice) usePoliceNoticeQueue.getState().show(notice);
      }).catch(() => undefined);
    }
  }), [api, me]);

  const notice = queue[0];
  return notice ? <PoliceNoticeModal key={notice.id} notice={notice} /> : null;
}

function PoliceNoticeModal({ notice }: { notice: PoliceNotice }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const [note, setNote] = useState('');
  const [error, setError] = useState<unknown>(null);
  const done = usePoliceNoticeQueue((s) => s.done);
  const acknowledge = async () => {
    try {
      await api.post(`/police-notices/${notice.id}/acknowledge`, { note: note.trim() || null });
      done(notice.id);
      await qc.invalidateQueries({ queryKey: ['police-notices'] });
      await qc.invalidateQueries({ queryKey: ['incident-events'] });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        sysmsg('info', 'Polizei-Hinweis', e.message);
        done(notice.id);
      } else {
        setError(e);
      }
    }
  };
  return (
    <Modal title="Hinweis: Polizei informieren" width={520} footer={
      <button className="btn primary" autoFocus onClick={() => void acknowledge()}>Zur Kenntnis genommen</button>
    }>
      <div className="police-notice">
        <div className="mono">Einsatz {notice.incident_number} · Stichwort {notice.keyword_code} · {fmtTime(notice.created_at)}</div>
        <div style={{ fontSize: 'var(--fs-lg)', fontWeight: 600, margin: '8px 0' }}>{notice.text}</div>
      </div>
      <div className="alert warning">
        Das System alarmiert und benachrichtigt die Polizei <strong>nicht</strong>. Bitte informieren Sie die Polizei
        selbst auf dem vorgesehenen Weg. Ihre Bestätigung wird im Einsatzverlauf dokumentiert.
      </div>
      <Field label="Vermerk (optional)">
        <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="z. B. Polizei über 110 informiert, Streife unterwegs" />
      </Field>
      <ErrorAlert error={error} />
    </Modal>
  );
}
