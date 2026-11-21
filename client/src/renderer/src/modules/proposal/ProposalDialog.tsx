/**
 * Einsatzmittelvorschlag: proposal with reasons per vehicle, alternatives, additional demand,
 * recalculation. "Übernehmen" only assigns the vehicles – alarming is the separate, confirmed
 * step in the alarm dialog (optionally opened right afterwards).
 */
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError } from '@/api/http';
import { useList } from '@/api/queries';
import type { Incident, Proposal, ProposalOption, Vehicle } from '@/api/types';
import { ErrorAlert, Modal } from '@/components/common';
import { MultiSelect } from '@/components/MultiSelect';
import { sysmsg } from '@/state/messages';
import { hasPermission, useSession } from '@/state/session';
import { AlarmDialog } from '../alarming/AlarmDialog';
import { fmtDuration, initialSelection, picksByDemand, swapVehicle, TRAVEL_SOURCE } from './labels';

interface Extra { vehicle_type_id: string; count: number }

export function ProposalDialog({ incident, onClose }: { incident: Incident; onClose: () => void }): ReactNode {
  const me = useSession((s) => s.me)!;
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const types = useList<{ id: string; code: string; name: string }>('vehicle-types', '/vehicle-types');
  const vehicles = useList<Vehicle>('vehicles', '/vehicles', { control_center_id: incident.control_center_id });
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [stage, setStage] = useState<number | null>(null);
  const [extra, setExtra] = useState<Extra[]>([]);
  const [selection, setSelection] = useState<string[]>([]);
  const [replacements, setReplacements] = useState<Record<string, ProposalOption>>({});
  const [manual, setManual] = useState<string[]>([]);
  const [newType, setNewType] = useState('');
  const [newCount, setNewCount] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [reassignHint, setReassignHint] = useState<{ message: string; thenAlarm: boolean } | null>(null);
  const [alarming, setAlarming] = useState(false);
  const canAlarm = hasPermission(me, 'alarm.trigger');

  const compute = useCallback(async (nextStage: number | null, nextExtra: Extra[]) => {
    setBusy(true);
    setError(null);
    try {
      const p = await api.post<Proposal>(`/incidents/${incident.id}/proposal`, { stage: nextStage, extra: nextExtra });
      setProposal(p);
      setSelection(initialSelection(p));
      setReplacements({});
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }, [api, incident.id]);

  useEffect(() => { void compute(null, []); }, [compute]);

  const grouped = useMemo(() => (proposal ? picksByDemand(proposal) : new Map()), [proposal]);
  const taken = new Set([...selection, ...manual, ...(proposal?.picks.filter((p) => p.in_incident).map((p) => p.vehicle_id) ?? [])]);
  const addable = (vehicles.data ?? []).filter((v) => v.available && !taken.has(v.id))
    .map((v) => ({ value: v.id, label: v.call_sign, hint: `${v.vehicle_type.code} · ${v.station.name}` }));
  const chosen = [...selection, ...manual];

  const accept = async (thenAlarm: boolean, reassign = false) => {
    if (!proposal) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/proposals/${proposal.id}/accept`, { vehicle_ids: chosen, reassign });
      sysmsg('success', 'Einsatzmittelvorschlag', `${incident.number}: ${chosen.length} Fahrzeug(e) zugeordnet – noch nicht alarmiert`);
      for (const k of ['incidents', 'active-assignments', 'incident-events', 'proposals']) void qc.invalidateQueries({ queryKey: [k] });
      if (thenAlarm) setAlarming(true);
      else onClose();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && !reassign && /bereits Einsatz/.test(e.message)) setReassignHint({ message: e.message, thenAlarm });
      else setError(e);
    } finally {
      setBusy(false);
    }
  };

  if (alarming) return <AlarmDialog incident={incident} onClose={onClose} />;

  return (
    <Modal title={`Einsatzmittelvorschlag – Einsatz ${incident.number}`} onClose={onClose} width={900} footer={<>
      <span className="muted" style={{ marginRight: 'auto', fontSize: 'var(--fs-xs)' }}>Übernehmen ordnet nur zu – alarmiert wird erst nach Bestätigung.</span>
      <button className="btn" disabled={busy} onClick={() => void compute(stage, extra)}>Neu berechnen</button>
      <button className="btn" onClick={onClose}>Abbrechen</button>
      <button className="btn primary" disabled={busy || !proposal || chosen.length === 0} onClick={() => void accept(false)}>Übernehmen ({chosen.length})</button>
      {canAlarm && <button className="btn danger" disabled={busy || !proposal} onClick={() => void accept(true)}>Übernehmen und alarmieren …</button>}
    </>}>
      <ErrorAlert error={error} />
      {!proposal ? <div className="muted">Berechne Vorschlag …</div> : (
        <>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 'var(--fs-sm)' }}>
            <span>{proposal.rule ? `AAO: ${proposal.rule.name ?? ''}${proposal.rule.area ? ` · Bereich ${proposal.rule.area}` : ''}` : 'keine AAO'}</span>
            <span className="badge info">{TRAVEL_SOURCE[proposal.travel_source]}</span>
            <span className="muted">{proposal.candidates} Kandidaten · berechnet in {proposal.duration_ms} ms</span>
            {proposal.max_stage > 0 && (
              <div className="chips" role="group" aria-label="Stufe" style={{ marginLeft: 'auto' }}>
                {Array.from({ length: proposal.max_stage }, (_, i) => i + 1).map((s) => (
                  <button key={s} type="button" className={`chip ${proposal.stage === s ? 'on' : ''}`} onClick={() => { setStage(s); void compute(s, extra); }}>bis Stufe {s}</button>
                ))}
              </div>
            )}
          </div>
          {proposal.warnings.map((w) => <div key={w} className="alert warning">{w}</div>)}
          {proposal.shortfalls.map((s) => <div key={s.demand_key} className="alert error">{s.message}</div>)}

          {proposal.demands.map((d) => (
            <div key={d.key} className="demand">
              <div className="section-title">{d.label} · {d.source} · {d.covered}/{d.count} gedeckt</div>
              {(grouped.get(d.key) ?? []).map((p: Proposal['picks'][number]) => {
                const alt = replacements[p.vehicle_id];
                const shownId = alt?.vehicle_id ?? p.vehicle_id;
                const alternatives = proposal.alternatives[d.key] ?? [];
                return (
                  <div key={p.vehicle_id} className="proposal-row">
                    <input type="checkbox" aria-label={`${alt?.call_sign ?? p.call_sign} übernehmen`} disabled={p.in_incident}
                      checked={p.in_incident || selection.includes(shownId)}
                      onChange={() => setSelection((sel) => (sel.includes(shownId) ? sel.filter((x) => x !== shownId) : [...sel, shownId]))} />
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                        <span style={{ fontWeight: 600 }}>{alt?.call_sign ?? p.call_sign}</span>
                        <span className="badge mono">{alt?.vehicle_type ?? p.vehicle_type}</span>
                        <span className="muted">{alt?.station ?? p.station}</span>
                        {p.in_incident && <span className={`badge ${p.alarmed ? 'danger' : 'accent'}`}>{p.alarmed ? 'alarmiert' : 'im Einsatz'}</span>}
                        {!p.in_incident && <span className="tabular" title="Fahrzeit">{fmtDuration(alt ? alt.travel_seconds : p.travel_seconds)}</span>}
                        {!p.in_incident && alternatives.length > 0 && (
                          <select className="select" aria-label={`Alternative zu ${p.call_sign}`} style={{ marginLeft: 'auto', width: 'auto' }} value={alt?.vehicle_id ?? ''}
                            onChange={(e) => {
                              const option = alternatives.find((o) => o.vehicle_id === e.target.value);
                              setSelection((sel) => swapVehicle(sel, shownId, option?.vehicle_id ?? p.vehicle_id));
                              setReplacements((r) => {
                                const next = { ...r };
                                if (option) next[p.vehicle_id] = option; else delete next[p.vehicle_id];
                                return next;
                              });
                            }}>
                            <option value="">Vorschlag beibehalten</option>
                            {alternatives.map((o) => <option key={o.vehicle_id} value={o.vehicle_id}>statt dessen {o.call_sign} ({o.reason})</option>)}
                          </select>
                        )}
                      </div>
                      <ul className="reasons">
                        {(alt ? [`Alternative gewählt: ${alt.reason}`] : p.reasons).map((r) => <li key={r}>{r}</li>)}
                      </ul>
                    </div>
                  </div>
                );
              })}
              {(grouped.get(d.key) ?? []).length === 0 && <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>kein Fahrzeug verfügbar</div>}
            </div>
          ))}

          <div className="section-title">Zusatzbedarf</div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            {extra.map((e, i) => (
              <span key={i} className="chip on">
                {e.count} × {types.data?.find((t) => t.id === e.vehicle_type_id)?.code ?? '?'}
                <button type="button" className="chip-x" aria-label="Zusatzbedarf entfernen" onClick={() => { const next = extra.filter((_, j) => j !== i); setExtra(next); void compute(stage, next); }}>×</button>
              </span>
            ))}
            <select className="select" aria-label="Fahrzeugtyp für Zusatzbedarf" style={{ width: 220 }} value={newType} onChange={(e) => setNewType(e.target.value)}>
              <option value="">Fahrzeugtyp …</option>
              {(types.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.code} – {t.name}</option>)}
            </select>
            <input className="input tabular" aria-label="Anzahl Zusatzbedarf" type="number" min={1} max={20} style={{ width: 64 }} value={newCount} onChange={(e) => setNewCount(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} />
            <button className="btn sm" disabled={!newType} onClick={() => { const next = [...extra, { vehicle_type_id: newType, count: newCount }]; setExtra(next); setNewType(''); setNewCount(1); void compute(stage, next); }}>+ hinzufügen und neu berechnen</button>
          </div>

          <div className="section-title">Manuell ergänzen</div>
          <MultiSelect options={[...addable, ...(vehicles.data ?? []).filter((v) => manual.includes(v.id)).map((v) => ({ value: v.id, label: v.call_sign }))]}
            value={manual} onChange={setManual} label="Fahrzeug" placeholder="Fahrzeug suchen (Funkrufname, Typ) …" emptyText={null} />
        </>
      )}
      {reassignHint && (
        <div className="alert warning">
          {reassignHint.message}. Fahrzeug dort abziehen und diesem Einsatz zuordnen?
          <div style={{ marginTop: 6, display: 'flex', gap: 6 }}>
            <button className="btn sm" onClick={() => setReassignHint(null)}>Nein</button>
            <button className="btn primary sm" onClick={() => { const next = reassignHint.thenAlarm; setReassignHint(null); void accept(next, true); }}>Umsetzen und übernehmen</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
