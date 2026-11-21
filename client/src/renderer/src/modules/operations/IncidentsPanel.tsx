/** Aktuelle Einsätze: list of incidents and the incident detail (status, data, vehicles, history). */
import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useState, type ReactNode } from 'react';
import { ApiError, describeError } from '@/api/http';
import { useActiveAssignments, useAlarms, useIncident, useIncidentEvents, useIncidents, useList, usePoliceNotices } from '@/api/queries';
import type { Incident, IncidentStatus, IncidentType, Keyword, Vehicle } from '@/api/types';
import { EmptyState, ErrorAlert, Field, fmtDateTime, fmtTime, Modal } from '@/components/common';
import { MultiSelect } from '@/components/MultiSelect';
import { EditNotices, useEditBase } from '@/components/useEditBase';
import { sysmsg } from '@/state/messages';
import { hasPermission, useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { AlarmDialog } from '../alarming/AlarmDialog';
import { AlarmProtocol } from '../alarming/AlarmProtocol';
import { ProposalDialog } from '../proposal/ProposalDialog';
import { usePoliceNoticeQueue } from '../alarming/policeNotices';
import { ControlCenterBadge } from '../crud/CrudPanel';
import { parseNumber } from '../crud/fields';
import { elapsed, INCIDENT_STATUS, INCIDENT_TYPE, PRIORITY, STATUS_BY_KEY, useNow } from './labels';

export function IncidentsPanel(): ReactNode {
  const me = useSession((s) => s.me)!;
  const { active } = useActiveControlCenter();
  const [scope, setScope] = useState<'open' | 'closed' | 'all'>('open');
  const [q, setQ] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const list = useIncidents(active?.id, scope, q.trim());
  const now = useNow();
  const canWrite = hasPermission(me, 'incidents.write');

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <div className="chips">
          {(['open', 'closed', 'all'] as const).map((s) => (
            <button key={s} className={`chip ${scope === s ? 'on' : ''}`} onClick={() => setScope(s)}>{{ open: 'Offen', closed: 'Abgeschlossen', all: 'Alle' }[s]}</button>
          ))}
        </div>
        <input className="input" placeholder="Nr., Ort, Meldender …" aria-label="Einsätze durchsuchen" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 200 }} />
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{list.data?.length ?? 0} Einsätze</span>
        <div className="spacer" />
        {canWrite && active && <button className="btn primary sm" onClick={() => setCreating(true)}>+ Einsatz</button>}
      </div>
      <ErrorAlert error={list.error} />
      <div className="panel-split">
        <div className="master table-wrap">
          {(list.data ?? []).length === 0 && !list.isLoading ? (
            <EmptyState title="Keine Einsätze">Einsätze entstehen in der Notrufannahme oder über „+ Einsatz“.</EmptyState>
          ) : (
            <table className="data">
              <thead><tr><th style={{ width: 82 }}>Stichwort</th><th>Einsatzort</th><th style={{ width: 120 }}>Status</th><th style={{ width: 64 }}>Dauer</th><th>Fahrzeuge</th><th style={{ width: 112 }}>Nr.</th></tr></thead>
              <tbody>
                {(list.data ?? []).map((i) => (
                  <tr key={i.id} className={`clickable prio-${i.priority} ${i.id === selectedId ? 'selected' : ''} ${i.status === 'closed' ? 'inactive' : ''}`} onClick={() => setSelectedId(i.id)}>
                    <td>{i.keyword ? <span className={`kw kw-${i.incident_type}`}>{i.keyword.code}</span> : <span className="muted">–</span>}</td>
                    <td title={i.address ?? ''}>{i.address ?? <span className="muted">Ort offen</span>}</td>
                    <td><span className={`badge ${STATUS_BY_KEY[i.status].cls}`}>{STATUS_BY_KEY[i.status].label}</span></td>
                    <td className="tabular">{elapsed(i.created_at, now)}</td>
                    <td className="muted" title={i.vehicles.join(', ')}>{i.vehicles.join(', ') || '–'}</td>
                    <td className="mono muted">{i.number}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="detail" style={{ flex: 1.2 }}>
          {selectedId ? <IncidentDetail key={selectedId} id={selectedId} /> : <EmptyState title="Einsatz auswählen" />}
        </div>
      </div>
      {creating && active && <CreateIncidentDialog ccId={active.id} onClose={() => setCreating(false)} onCreated={setSelectedId} />}
    </div>
  );
}

interface IncidentForm {
  keyword_id: string;
  incident_type: IncidentType;
  priority: number;
  address: string;
  location_note: string;
  latitude: string;
  longitude: string;
  caller_name: string;
  caller_phone: string;
  description: string;
}

const toIncidentForm = (i: Incident | undefined): IncidentForm => ({
  keyword_id: i?.keyword?.id ?? '', incident_type: i?.incident_type ?? 'other', priority: i?.priority ?? 2,
  address: i?.address ?? '', location_note: i?.location_note ?? '', latitude: i?.latitude?.toString() ?? '',
  longitude: i?.longitude?.toString() ?? '', caller_name: i?.caller_name ?? '', caller_phone: i?.caller_phone ?? '',
  description: i?.description ?? '',
});

function IncidentDetail({ id }: { id: string }): ReactNode {
  const query = useIncident(id);
  if (query.error) return <ErrorAlert error={query.error} />;
  if (!query.data) return <EmptyState title="Lade Einsatz …" />;
  return <IncidentView incident={query.data} />;
}

function IncidentView({ incident }: { incident: Incident }): ReactNode {
  const me = useSession((s) => s.me)!;
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const keywords = useList<Keyword>('keywords', '/keywords');
  const edit = useEditBase(incident, toIncidentForm, (i) => i.version);
  const { form, setForm, initial, dirty } = edit;
  const [error, setError] = useState<unknown>(null);
  const [confirmClose, setConfirmClose] = useState(false);
  const canWrite = hasPermission(me, 'incidents.write') && incident.status !== 'closed';
  const canClose = hasPermission(me, 'incidents.close');
  const set = (patch: Partial<IncidentForm>) => setForm((f) => ({ ...f, ...patch }));
  const refresh = () => qc.invalidateQueries({ queryKey: ['incidents'] });

  const save = async () => {
    setError(null);
    const lat = parseNumber(form.latitude);
    const lon = parseNumber(form.longitude);
    if (Number.isNaN(lat) || Number.isNaN(lon) || (lat === null) !== (lon === null)) {
      setError(new Error('Koordinaten: Breite und Länge als Zahl angeben'));
      return;
    }
    const values: Record<string, unknown> = {
      keyword_id: form.keyword_id || null, incident_type: form.incident_type, priority: form.priority,
      address: form.address || null, location_note: form.location_note || null, latitude: lat, longitude: lon,
      caller_name: form.caller_name || null, caller_phone: form.caller_phone || null, description: form.description || null,
    };
    const changed = Object.fromEntries(Object.entries(values).filter(([k]) => form[k as keyof IncidentForm] !== initial[k as keyof IncidentForm]));
    try {
      const saved = await api.patch<Incident>(`/incidents/${incident.id}`, { ...changed, expected_version: edit.baseVersion });
      edit.rebase(saved);
      await refresh();
    } catch (e) {
      setError(e);
    }
  };

  const setStatus = async (status: IncidentStatus) => {
    setError(null);
    try {
      await api.post(`/incidents/${incident.id}/status`, { status, expected_version: incident.version });
      await refresh();
    } catch (e) {
      setError(e);
    }
  };

  const current = INCIDENT_STATUS.findIndex((s) => s.key === incident.status);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span className="mono" style={{ fontSize: 'var(--fs-xl)', fontWeight: 700 }}>{incident.number}</span>
        {incident.keyword && <span className={`kw kw-${incident.incident_type}`}>{incident.keyword.code}</span>}
        <span className={`badge ${PRIORITY[incident.priority]?.cls}`}>{PRIORITY[incident.priority]?.label}</span>
        {incident.source === 'sim' && <span className="badge sim-badge">SIM</span>}
        <span className="muted" style={{ marginLeft: 'auto', fontSize: 'var(--fs-sm)' }}>angelegt {fmtDateTime(incident.created_at)}</span>
      </div>
      {incident.keyword && <div className="muted" style={{ marginTop: 2 }}>{incident.keyword.name}</div>}

      <div className="status-steps" role="group" aria-label="Einsatzstatus">
        {INCIDENT_STATUS.map((s, idx) => (
          <button key={s.key} type="button" className={`status-step ${idx < current ? 'done' : ''} ${idx === current ? 'current' : ''}`}
            disabled={!hasPermission(me, 'incidents.write') || s.key === incident.status || (incident.status === 'closed' && s.key !== 'finished')}
            onClick={() => (s.key === 'closed' ? setConfirmClose(true) : void setStatus(s.key))}>{s.label}</button>
        ))}
      </div>
      <div className="muted" style={{ fontSize: 'var(--fs-xs)', marginTop: 4 }}>
        „Alarmiert“ setzt die Alarmierung; „Anfahrt“ und „Am Einsatzort“ werden ab Phase 6 aus dem Fahrzeugstatus übernommen.
      </div>
      <PoliceNoticeBanner incident={incident} />

      <div className="section-title">Einsatzdaten</div>
      <div className="form-grid">
        <Field label="Stichwort">
          <select className="select" value={form.keyword_id} disabled={!canWrite} onChange={(e) => {
            const kw = keywords.data?.find((k) => k.id === e.target.value);
            set({ keyword_id: e.target.value, ...(kw ? { incident_type: kw.category } : {}) });
          }}>
            <option value="">– kein Stichwort –</option>
            {(keywords.data ?? []).filter((k) => k.is_active || k.id === form.keyword_id).map((k) => <option key={k.id} value={k.id}>{k.code} – {k.name}</option>)}
          </select>
        </Field>
        <Field label="Einsatzart">
          <select className="select" value={form.incident_type} disabled={!canWrite} onChange={(e) => set({ incident_type: e.target.value as IncidentType })}>
            {Object.entries(INCIDENT_TYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        <div className="field full">
          <label>Priorität</label>
          <div className="chips">{[1, 2, 3].map((p) => <button type="button" key={p} disabled={!canWrite} className={`chip ${form.priority === p ? 'on' : ''}`} onClick={() => set({ priority: p })}>{PRIORITY[p]!.label}</button>)}</div>
        </div>
        <Field label="Einsatzort" className="full"><input className="input" value={form.address} disabled={!canWrite} onChange={(e) => set({ address: e.target.value })} /></Field>
        <Field label="Ortshinweis" className="full"><input className="input" value={form.location_note} disabled={!canWrite} placeholder="z. B. Parkplatz hinter dem Bahnhof" onChange={(e) => set({ location_note: e.target.value })} /></Field>
        <Field label="Breitengrad"><input className="input tabular" value={form.latitude} disabled={!canWrite} onChange={(e) => set({ latitude: e.target.value })} /></Field>
        <Field label="Längengrad"><input className="input tabular" value={form.longitude} disabled={!canWrite} onChange={(e) => set({ longitude: e.target.value })} /></Field>
        <Field label="Meldender"><input className="input" value={form.caller_name} disabled={!canWrite} onChange={(e) => set({ caller_name: e.target.value })} /></Field>
        <Field label="Rückrufnummer"><input className="input mono" value={form.caller_phone} disabled={!canWrite} onChange={(e) => set({ caller_phone: e.target.value })} /></Field>
        <Field label="Beschreibung / Lage" className="full"><textarea className="input" style={{ height: 60, padding: 8 }} value={form.description} disabled={!canWrite} onChange={(e) => set({ description: e.target.value })} /></Field>
      </div>
      <EditNotices stale={edit.stale} error={error} onReload={() => { edit.reload(); setError(null); }} />
      {canWrite && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button className="btn primary" disabled={!dirty} onClick={() => void save()}>Einsatzdaten speichern</button>
          <button className="btn" disabled={!dirty} onClick={() => { edit.reload(); setError(null); }}>Verwerfen</button>
        </div>
      )}

      <VehiclesSection incident={incident} />
      <AlarmSection incident={incident} />

      {incident.calls.length > 0 && (
        <>
          <div className="section-title">Notrufe ({incident.calls.length})</div>
          {incident.calls.map((c) => (
            <div key={c.id} className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
              <span className="tabular">{fmtTime(c.received_at)}</span> · {c.caller_name ?? 'unbekannt'} <span className="mono">{c.caller_phone ?? ''}</span>
            </div>
          ))}
        </>
      )}

      <Timeline incident={incident} canWrite={canWrite} />

      {confirmClose && (
        <Modal title={`Einsatz ${incident.number} abschließen`} onClose={() => setConfirmClose(false)} footer={<>
          <button className="btn" onClick={() => setConfirmClose(false)}>Abbrechen</button>
          <button className="btn primary" disabled={!canClose} onClick={() => { setConfirmClose(false); void setStatus('closed'); }}>Abschließen</button>
        </>}>
          <div>Nach dem Abschluss sind Einsatzdaten und Dokumentation schreibgeschützt. Voraussetzung: Status „Einsatz beendet“ und alle Fahrzeuge freigegeben.</div>
          {!canClose && <div className="alert warning">Abschließen erfordert die Berechtigung „Einsätze abschließen“.</div>}
        </Modal>
      )}
    </div>
  );
}

function VehiclesSection({ incident }: { incident: Incident }): ReactNode {
  const me = useSession((s) => s.me)!;
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const vehicles = useList<Vehicle>('vehicles', '/vehicles', { control_center_id: incident.control_center_id });
  const assignments = useActiveAssignments(incident.control_center_id);
  const [selection, setSelection] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [reassign, setReassign] = useState<{ ids: string[]; message: string } | null>(null);
  const [proposing, setProposing] = useState(false);
  const canWrite = hasPermission(me, 'incidents.write') && !['finished', 'closed'].includes(incident.status);
  const activeAssignments = incident.assignments.filter((a) => a.released_at === null);
  const released = incident.assignments.filter((a) => a.released_at !== null);
  const busy = useMemo(() => new Map((assignments.data ?? []).map((a) => [a.vehicle_id, a])), [assignments.data]);
  const options = useMemo(() => (vehicles.data ?? [])
    .filter((v) => v.available && !activeAssignments.some((a) => a.vehicle.id === v.id))
    .map((v) => {
      const other = busy.get(v.id);
      return { value: v.id, label: v.call_sign, hint: other ? `${v.vehicle_type.code} · in Einsatz ${other.incident_number}` : `${v.vehicle_type.code} · ${v.station.name}` };
    }), [vehicles.data, activeAssignments, busy]);

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ['incidents'] });
    await qc.invalidateQueries({ queryKey: ['active-assignments'] });
    await qc.invalidateQueries({ queryKey: ['incident-events'] });
  };
  const assign = async (ids: string[], withReassign = false) => {
    setError(null);
    try {
      await api.post(`/incidents/${incident.id}/vehicles`, { vehicle_ids: ids, reassign: withReassign });
      setSelection([]);
      await refresh();
    } catch (e) {
      if (e instanceof ApiError && e.isConflict && e.details['incident_number'] && !withReassign) {
        setReassign({ ids, message: e.message });
      } else {
        setError(e);
      }
    }
  };
  const release = async (vehicleId: string) => {
    try {
      await api.delete(`/incidents/${incident.id}/vehicles/${vehicleId}`);
      await refresh();
    } catch (e) {
      sysmsg('error', 'Einsatz', describeError(e));
    }
  };
  const now = useNow(5000);

  return (
    <>
      <div className="section-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span>Fahrzeuge ({activeAssignments.length}){incident.stations.length > 0 && <span className="muted"> · Wachen: {incident.stations.map((s) => s.name).join(', ')}</span>}</span>
        {canWrite && <button className="btn sm" style={{ marginLeft: 'auto' }} onClick={() => setProposing(true)} title="Vorschlag nach AAO, Fahrzeit und Verfügbarkeit – ordnet erst nach Übernahme zu">Vorschlag …</button>}
      </div>
      {proposing && <ProposalDialog incident={incident} onClose={() => setProposing(false)} />}
      {activeAssignments.length === 0 && <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>noch keine Fahrzeuge zugeordnet</div>}
      {activeAssignments.map((a) => (
        <div key={a.id} className="assignment">
          <span style={{ fontWeight: 600 }}>{a.vehicle.call_sign}</span>
          <span className="badge mono">{a.vehicle.vehicle_type}</span>
          <span className="muted">{a.vehicle.station}</span>
          <span className="muted tabular" style={{ marginLeft: 'auto' }}>seit {fmtTime(a.assigned_at)} ({elapsed(a.assigned_at, now)})</span>
          {canWrite && <button className="btn ghost sm" onClick={() => void release(a.vehicle.id)}>Freigeben</button>}
        </div>
      ))}
      {canWrite && (
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start', marginTop: 6 }}>
          <div style={{ flex: 1 }}><MultiSelect options={options} value={selection} onChange={setSelection} label="Fahrzeuge" placeholder="Fahrzeug suchen (Funkrufname, Typ) …" /></div>
          <button className="btn" disabled={!selection.length} onClick={() => void assign(selection)}>Zuordnen</button>
        </div>
      )}
      <ErrorAlert error={error} />
      {released.length > 0 && <div className="muted" style={{ fontSize: 'var(--fs-xs)', marginTop: 4 }}>Freigegeben: {released.map((a) => `${a.vehicle.call_sign} (${a.released_reason === 'reassigned' ? 'umgesetzt' : 'frei'} ${fmtTime(a.released_at!)})`).join(', ')}</div>}
      {reassign && (
        <Modal title="Fahrzeug umsetzen?" onClose={() => setReassign(null)} footer={<>
          <button className="btn" onClick={() => setReassign(null)}>Abbrechen</button>
          <button className="btn primary" onClick={() => { const ids = reassign.ids; setReassign(null); void assign(ids, true); }}>Umsetzen</button>
        </>}>
          <div>{reassign.message}.</div>
          <div>Soll das Fahrzeug dort abgezogen und diesem Einsatz ({incident.number}) zugeordnet werden? Beide Einsatzverläufe werden ergänzt.</div>
        </Modal>
      )}
    </>
  );
}

function Timeline({ incident, canWrite }: { incident: Incident; canWrite: boolean }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const events = useIncidentEvents(incident.id);
  const [text, setText] = useState('');
  const [error, setError] = useState<unknown>(null);
  const add = async () => {
    if (!text.trim()) return;
    try {
      await api.post(`/incidents/${incident.id}/notes`, { text: text.trim() });
      setText('');
      await qc.invalidateQueries({ queryKey: ['incident-events', incident.id] });
    } catch (e) {
      setError(e);
    }
  };
  return (
    <>
      <div className="section-title">Einsatzverlauf und Dokumentation</div>
      {canWrite && (
        <div style={{ display: 'flex', gap: 6 }}>
          <input className="input" style={{ flex: 1 }} aria-label="Dokumentation ergänzen" placeholder="Lagemeldung / Dokumentation … (Enter)" value={text}
            onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void add()} />
          <button className="btn" disabled={!text.trim()} onClick={() => void add()}>Eintragen</button>
        </div>
      )}
      <ErrorAlert error={error} />
      <div className="timeline">
        {[...(events.data ?? [])].reverse().map((e) => (
          <div key={e.id} className={`timeline-item kind-${e.kind}`}>
            <span className="tabular muted">{fmtTime(e.ts)}</span>
            <span className="selectable">{e.text}</span>
            <span className="muted timeline-actor">{e.actor_name.replace(/ \(.*\)$/, '')}</span>
          </div>
        ))}
      </div>
      <div className="muted" style={{ fontSize: 'var(--fs-xs)', marginTop: 4 }}>Der Einsatzverlauf ist unveränderbar gespeichert.</div>
    </>
  );
}

function CreateIncidentDialog({ ccId, onClose, onCreated }: { ccId: string; onClose: () => void; onCreated: (id: string) => void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const keywords = useList<Keyword>('keywords', '/keywords');
  const [keywordId, setKeywordId] = useState('');
  const [address, setAddress] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState<unknown>(null);
  const submit = async () => {
    try {
      const incident = await api.post<Incident>('/incidents', { control_center_id: ccId, keyword_id: keywordId || null, address: address || null, description: description || null });
      await qc.invalidateQueries({ queryKey: ['incidents'] });
      sysmsg('success', 'Einsatz', `Einsatz ${incident.number} angelegt`);
      onCreated(incident.id);
      onClose();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Modal title="Einsatz anlegen" onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Abbrechen</button>
      <button className="btn primary" onClick={() => void submit()}>Anlegen</button>
    </>}>
      <Field label="Einsatzstichwort">
        <select className="select" autoFocus value={keywordId} onChange={(e) => setKeywordId(e.target.value)}>
          <option value="">– später festlegen –</option>
          {(keywords.data ?? []).filter((k) => k.is_active).map((k) => <option key={k.id} value={k.id}>{k.code} – {k.name}</option>)}
        </select>
      </Field>
      <Field label="Einsatzort"><input className="input" value={address} onChange={(e) => setAddress(e.target.value)} /></Field>
      <Field label="Beschreibung"><textarea className="input" style={{ height: 60, padding: 8 }} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      <ErrorAlert error={error} />
    </Modal>
  );
}

function AlarmSection({ incident }: { incident: Incident }): ReactNode {
  const me = useSession((s) => s.me)!;
  const alarms = useAlarms(undefined, incident.id);
  const [open, setOpen] = useState(false);
  const canAlarm = hasPermission(me, 'alarm.trigger') && !['finished', 'closed'].includes(incident.status);
  const count = alarms.data?.length ?? 0;
  return (
    <>
      <div className="section-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span>Alarmierungen ({count})</span>
        {canAlarm && (
          <button className="btn danger sm" style={{ marginLeft: 'auto' }} onClick={() => setOpen(true)} title="Vorschau öffnen – ausgelöst wird erst nach Bestätigung">
            {count ? 'Nachalarmieren …' : 'Alarmieren …'}
          </button>
        )}
      </div>
      <ErrorAlert error={alarms.error} />
      <AlarmProtocol alarms={alarms.data ?? []} />
      {open && <AlarmDialog incident={incident} onClose={() => setOpen(false)} />}
    </>
  );
}

function PoliceNoticeBanner({ incident }: { incident: Incident }): ReactNode {
  const notices = usePoliceNotices(incident.control_center_id);
  const show = usePoliceNoticeQueue((s) => s.show);
  const open = (notices.data ?? []).filter((n) => n.incident_id === incident.id);
  if (open.length === 0) return null;
  return (
    <div className="alert warning" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span className="badge police-badge">Polizei informieren</span>
      <span>{open[0]!.text} – noch nicht bestätigt (keine Übermittlung durch das System).</span>
      <button className="btn sm" style={{ marginLeft: 'auto' }} onClick={() => show(open[0]!)}>Bestätigen …</button>
    </div>
  );
}
