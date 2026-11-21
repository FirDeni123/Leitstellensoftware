/** Sprechwünsche: queue by priority (0 = priorisiert/Notruf first) and time. */
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { describeError } from '@/api/http';
import { useTalkRequests } from '@/api/queries';
import type { TalkRequest } from '@/api/types';
import { EmptyState, ErrorAlert, fmtTime } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';
import { elapsed, useNow } from '../operations/labels';
import { ring, useCallAlert } from '../operations/callAlert';

const STATE: Record<TalkRequest['status'], string> = {
  open: 'offen', accepted: 'Sprechaufforderung erteilt', deferred: 'zurückgestellt', rejected: 'abgelehnt', done: 'erledigt',
};

export function TalkRequestsPanel(): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const { active } = useActiveControlCenter();
  const requests = useTalkRequests(active?.id);
  const now = useNow();
  const muted = useCallAlert((s) => s.muted);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const seenUrgent = useRef(new Set<string>());

  // acoustic signal for new priority requests (status 0)
  useEffect(() => {
    for (const r of requests.data ?? []) {
      if (r.priority === 0 && r.status === 'open' && !seenUrgent.current.has(r.id)) {
        seenUrgent.current.add(r.id);
        if (!muted) ring();
      }
    }
  }, [requests.data, muted]);

  const act = async (r: TalkRequest, action: 'accept' | 'defer' | 'reject' | 'done') => {
    try {
      await api.post(`/talk-requests/${r.id}/${action}`, { note: notes[r.id]?.trim() || null });
      setNotes((n) => ({ ...n, [r.id]: '' }));
      await qc.invalidateQueries({ queryKey: ['talk-requests'] });
      await qc.invalidateQueries({ queryKey: ['fleet'] });
    } catch (e) {
      sysmsg('error', 'Sprechwunsch', describeError(e));
    }
  };

  const items = requests.data ?? [];
  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{items.filter((r) => r.status === 'open').length} offen</span>
      </div>
      <ErrorAlert error={requests.error} />
      <div className="panel-body">
        {items.length === 0 && !requests.isLoading ? <EmptyState title="Keine Sprechwünsche">Status 5 (Sprechwunsch) und 0 (priorisierter Sprechwunsch) erscheinen hier.</EmptyState> : (
          items.map((r) => (
            <div key={r.id} className={`talk-request ${r.priority === 0 ? 'urgent' : ''} state-${r.status}`} data-call-sign={r.call_sign}>
              <span className={`fms ${r.priority === 0 ? 'fms-urgent' : ''}`}>{r.priority}</span>
              <div style={{ flex: 1 }}>
                <div><b>{r.call_sign}</b> <span className="muted">{r.vehicle_type} · {r.station}</span>{r.incident_number && <span className="mono"> · {r.incident_number}</span>}</div>
                <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>
                  {r.priority === 0 ? 'Priorisierter Sprechwunsch (Notruf)' : 'Sprechwunsch'} · {fmtTime(r.created_at)} ({elapsed(r.created_at, now)}) · {STATE[r.status]}
                  {r.handled_by_name && ` von ${r.handled_by_name.replace(/ \(.*\)$/, '')}`}
                </div>
              </div>
              <input className="input" style={{ width: 180 }} aria-label={`Vermerk ${r.call_sign}`} placeholder="Vermerk …" value={notes[r.id] ?? ''} onChange={(e) => setNotes((n) => ({ ...n, [r.id]: e.target.value }))} />
              {r.status !== 'accepted' && <button className="btn primary sm" onClick={() => void act(r, 'accept')}>Sprechaufforderung</button>}
              {r.status === 'open' && <button className="btn sm" onClick={() => void act(r, 'defer')}>Zurückstellen</button>}
              {r.status !== 'accepted' && <button className="btn ghost sm" onClick={() => void act(r, 'reject')}>Ablehnen</button>}
              <button className="btn sm" onClick={() => void act(r, 'done')}>Erledigt</button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
