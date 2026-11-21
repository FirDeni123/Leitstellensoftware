/**
 * Alarm dialog: shows the proposal from the AAO (preview) and alarms ONLY after the dispatcher
 * confirms. Every confirmation carries an Idempotency-Key, so a retry after a network error
 * never alarms twice. The dispatcher can remove proposed units and add others.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ApiError } from '@/api/http';
import { useList } from '@/api/queries';
import type { Alarm, AlarmPreview, AlarmSelection, Incident, Vehicle } from '@/api/types';
import { ErrorAlert, Field, Modal } from '@/components/common';
import { MultiSelect } from '@/components/MultiSelect';
import { sysmsg } from '@/state/messages';
import { useSession } from '@/state/session';
import { EFFECT, hasTargets, newIdempotencyKey, toggle } from './labels';
import { usePoliceNoticeQueue } from './policeNotices';

type PreviewVehicle = AlarmPreview['vehicles'][number];

export function AlarmDialog({ incident, onClose }: { incident: Incident; onClose: () => void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const [stage, setStageState] = useState<number | null>(null);
  const [selection, setSelectionState] = useState<AlarmSelection | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [reassignHint, setReassignHint] = useState<string | null>(null);
  const keyRef = useRef(newIdempotencyKey());
  // Units seen in any preview stay visible, so an unchecked unit can be checked again.
  const [known, setKnown] = useState<Map<string, PreviewVehicle>>(new Map());
  const [knownStations, setKnownStations] = useState<Map<string, AlarmPreview['stations'][number]>>(new Map());
  const vehicles = useList<Vehicle>('vehicles', '/vehicles', { control_center_id: incident.control_center_id });

  const preview = useQuery({
    queryKey: ['alarm-preview', incident.id, stage, selection],
    queryFn: () => api.post<AlarmPreview>(`/incidents/${incident.id}/alarm-preview`, { stage, selection }),
    staleTime: 0,
  });
  const data = preview.data;
  const current: AlarmSelection | null = selection ?? data?.selection ?? null;

  useEffect(() => {
    if (!data) return;
    setKnown((m) => new Map([...m, ...data.vehicles.map((v) => [v.id, v] as const)]));
    setKnownStations((m) => new Map([...m, ...data.stations.map((s) => [s.id, s] as const)]));
  }, [data]);

  // Any change of what will be alarmed is a different request -> new idempotency key.
  const setSelection = (next: AlarmSelection) => {
    keyRef.current = newIdempotencyKey();
    setSelectionState(next);
  };
  const setStage = (next: number) => {
    keyRef.current = newIdempotencyKey();
    setSelectionState(null);
    setStageState(next);
  };

  const addable = useMemo(() => (vehicles.data ?? [])
    .filter((v) => v.available && !(current?.vehicle_ids ?? []).includes(v.id))
    .map((v) => ({ value: v.id, label: v.call_sign, hint: `${v.vehicle_type.code} · ${v.station.name}` })), [vehicles.data, current]);

  const submit = async (reassign = false) => {
    if (!current) return;
    setError(null);
    setBusy(true);
    try {
      const alarm = await api.post<Alarm>(
        `/incidents/${incident.id}/alarms`,
        { ...current, stage: data?.stage ?? null, note: note.trim() || null, reassign, confirmed: true },
        { 'Idempotency-Key': keyRef.current },
      );
      sysmsg('success', 'Alarmierung', `${incident.number}: ${alarm.mode === 'real' ? 'ECHTE ' : 'simulierte '}Alarmierung ausgelöst${alarm.replayed ? ' (bereits erfolgt)' : ''}`);
      onClose();
      // The police notice pops up only after the alarm dialog has closed.
      if (alarm.police_notice && !alarm.police_notice.acknowledged_at) usePoliceNoticeQueue.getState().show(alarm.police_notice);
      for (const k of ['incidents', 'alarms', 'incident-events', 'active-assignments']) void qc.invalidateQueries({ queryKey: [k] });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && !reassign && /bereits Einsatz/.test(e.message)) {
        setReassignHint(e.message);
      } else {
        setError(e);
      }
    } finally {
      setBusy(false);
    }
  };

  const vehicleRows = [...known.values()];
  const stationRows = [...knownStations.values()];
  const count = current ? current.vehicle_ids.length + current.station_ids.length : 0;
  const real = data?.mode === 'real';

  return (
    <Modal title={`Alarmierung – Einsatz ${incident.number}`} onClose={onClose} width={820} footer={<>
      <span className="muted" style={{ marginRight: 'auto', fontSize: 'var(--fs-xs)' }}>Es wird erst nach „Alarmieren“ ausgelöst.</span>
      <button className="btn" onClick={onClose}>Abbrechen</button>
      <button className={`btn ${real ? 'danger' : 'primary'}`} disabled={busy || !current || !hasTargets(current) || preview.isFetching}
        onClick={() => void submit()}>{real ? 'REAL alarmieren' : 'Alarmieren'}{count ? ` (${count})` : ''}</button>
    </>}>
      {real ? (
        <div className="alert error" role="alert">ECHTBETRIEB: Aktive reale Schnittstellen übertragen diese Alarmierung an externe Systeme.</div>
      ) : (
        <div className="alert info">Simulationsbetrieb – die Alarmierung wird nur simuliert, reale Schnittstellen werden nicht angesprochen.</div>
      )}
      <ErrorAlert error={preview.error} />
      {data && (
        <>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span>{data.keyword ? <span className={`kw kw-${data.keyword.category}`}>{data.keyword.code}</span> : <span className="muted">ohne Stichwort</span>}</span>
            <span className="muted">{data.rule ? `AAO: ${data.rule.name ?? data.keyword?.code}${data.rule.area ? ` · Bereich ${data.rule.area}` : ''}` : 'keine AAO'}</span>
            <span className="badge accent">{data.next_kind === 'initial' ? 'Erstalarm' : 'Nachalarmierung'}</span>
            {data.max_stage > 0 && (
              <div className="chips" role="group" aria-label="Alarmierungsstufe" style={{ marginLeft: 'auto' }}>
                {Array.from({ length: data.max_stage }, (_, i) => i + 1).map((s) => (
                  <button key={s} type="button" className={`chip ${data.stage === s ? 'on' : ''}`} onClick={() => setStage(s)}>Stufe {s}</button>
                ))}
              </div>
            )}
          </div>
          {data.warnings.map((w) => <div key={w} className="alert warning">{w}</div>)}
          {data.police_notice && <div className="alert info">Nach der Alarmierung erscheint der Hinweis „Polizei informieren“: {data.police_notice} – die Polizei wird nicht durch das System alarmiert.</div>}
          {data.already_alarmed.length > 0 && <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Bereits alarmiert: {data.already_alarmed.join(', ')}</div>}

          <div className="section-title">Fahrzeuge</div>
          {vehicleRows.length === 0 && <div className="muted">Keine Fahrzeuge vorgeschlagen.</div>}
          <table className="data compact">
            <tbody>
              {vehicleRows.map((v) => (
                <tr key={v.id}>
                  <td style={{ width: 28 }}>
                    <input type="checkbox" aria-label={`${v.call_sign} alarmieren`} checked={!!current?.vehicle_ids.includes(v.id)}
                      onChange={() => current && setSelection({ ...current, vehicle_ids: toggle(current.vehicle_ids, v.id) })} />
                  </td>
                  <td style={{ fontWeight: 600 }}>{v.call_sign}</td>
                  <td><span className="badge mono">{v.vehicle_type}</span></td>
                  <td className="muted">{v.station}</td>
                  <td className="tabular muted">{v.distance_km !== null ? `${v.distance_km.toFixed(1)} km` : ''}</td>
                  <td className="muted">{v.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 6 }}>
            <MultiSelect options={addable} value={[]} emptyText={null} label="Fahrzeug" placeholder="weiteres Fahrzeug hinzufügen …"
              onChange={(ids) => current && setSelection({ ...current, vehicle_ids: [...current.vehicle_ids, ...ids.filter((id) => !current.vehicle_ids.includes(id))] })} />
          </div>

          {stationRows.length > 0 && (
            <>
              <div className="section-title">Wachen</div>
              {stationRows.map((s) => (
                <label key={s.id} className="assignment">
                  <input type="checkbox" checked={!!current?.station_ids.includes(s.id)}
                    onChange={() => current && setSelection({ ...current, station_ids: toggle(current.station_ids, s.id) })} />
                  <span style={{ fontWeight: 600 }}>{s.label}</span><span className="muted">{s.reason}</span>
                </label>
              ))}
            </>
          )}

          <div className="section-title">Ausgelöste RICs ({data.rics.length})</div>
          {data.rics.length === 0 ? <div className="muted">keine</div> : data.rics.map((r) => (
            <div key={r.id} className="assignment"><span className="mono">{r.label}</span><span className="muted">{r.reason}</span></div>
          ))}

          <div className="section-title">Schnittstellen ({data.interfaces.length})</div>
          {data.interfaces.length === 0 ? <div className="muted">keine zuständige Schnittstelle</div> : data.interfaces.map((i) => (
            <div key={i.id} className="assignment">
              <span style={{ fontWeight: 600 }}>{i.name}</span>
              <span className={`badge ${EFFECT[i.effect].cls}`}>{EFFECT[i.effect].label}</span>
              <span className="muted">{i.plugin_name} · {i.reason}</span>
            </div>
          ))}

          <Field label="Vermerk zur Alarmierung (optional)">
            <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="z. B. Anfahrt über Hinterhof" />
          </Field>
        </>
      )}
      <ErrorAlert error={error} />
      {reassignHint && (
        <div className="alert warning">
          {reassignHint}. Fahrzeug dort abziehen, in diesen Einsatz umsetzen und alarmieren?
          <div style={{ marginTop: 6, display: 'flex', gap: 6 }}>
            <button className="btn sm" onClick={() => setReassignHint(null)}>Nein</button>
            <button className="btn primary sm" onClick={() => { setReassignHint(null); keyRef.current = newIdempotencyKey(); void submit(true); }}>Umsetzen und alarmieren</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
