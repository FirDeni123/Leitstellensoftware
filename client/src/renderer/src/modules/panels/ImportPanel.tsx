/**
 * Import wizard (Excel/CSV): 1 file → 2 column mapping → 3 validation preview → 4 result.
 * Nothing is written to master data before the administrator confirms in step 3.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useRef, useState, type ReactNode } from 'react';
import type { ImportAction, ImportJob, ImportJobSummary, ImportKind } from '@/api/types';
import { ErrorAlert, fmtDateTime, Modal } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { hasPermission, useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';

const ACTION: Record<ImportAction, { label: string; cls: string }> = {
  create: { label: 'Neu', cls: 'ok' },
  update: { label: 'Aktualisieren', cls: 'info' },
  unchanged: { label: 'Unverändert', cls: '' },
  error: { label: 'Fehler', cls: 'danger' },
  skip: { label: 'Leer', cls: '' },
};

const KIND_LABEL: Record<ImportKind, string> = { vehicles: 'Fahrzeuge', stations: 'Wachen' };

export function ImportPanel(): ReactNode {
  const api = useSession((s) => s.api)!;
  const me = useSession((s) => s.me)!;
  const qc = useQueryClient();
  const { active } = useActiveControlCenter();
  const [job, setJob] = useState<ImportJob | null>(null);
  const [kind, setKind] = useState<ImportKind>('vehicles');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const history = useQuery({
    queryKey: ['import-jobs', active?.id],
    queryFn: () => api.get<ImportJobSummary[]>('/imports', { control_center_id: active?.id }),
    enabled: !!active,
  });

  const run = async (fn: () => Promise<ImportJob | void>) => {
    setBusy(true);
    setError(null);
    try {
      const result = await fn();
      if (result) setJob(result);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const upload = (file: File) => run(async () => {
    const form = new FormData();
    form.append('file', file);
    form.append('kind', kind);
    form.append('control_center_id', active!.id);
    const created = await api.upload<ImportJob>('/imports', form);
    void qc.invalidateQueries({ queryKey: ['import-jobs'] });
    return created;
  });

  const permitted = hasPermission(me, kind === 'vehicles' ? 'vehicles.write' : 'stations.write');
  const step = !job ? 1 : job.status === 'uploaded' ? 2 : job.status === 'validated' ? 3 : 4;

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <ol className="steps" aria-label="Importschritte">
          {['Datei', 'Spalten zuordnen', 'Prüfen', 'Ergebnis'].map((label, i) => (
            <li key={label} className={step === i + 1 ? 'current' : step > i + 1 ? 'done' : ''}>{i + 1}. {label}</li>
          ))}
        </ol>
        <div className="spacer" />
        {job && <button className="btn sm" onClick={() => { setJob(null); setError(null); }}>Neuer Import</button>}
      </div>
      <div className="panel-body" style={{ padding: 12 }}>
        <ErrorAlert error={error} />
        {!job && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 640 }}>
            <div className="field">
              <label>Was soll importiert werden?</label>
              <div className="chips">
                {(['vehicles', 'stations'] as const).map((k) => (
                  <button key={k} className={`chip ${kind === k ? 'on' : ''}`} onClick={() => setKind(k)}>{KIND_LABEL[k]}</button>
                ))}
              </div>
            </div>
            <div className="dropzone" onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f && active && permitted) void upload(f); }}>
              <div style={{ fontWeight: 600 }}>Excel- oder CSV-Datei hierher ziehen</div>
              <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>.xlsx oder .csv (Trennzeichen ; oder ,), max. 5 MB / 5000 Zeilen. Die erste Zeile enthält die Spaltennamen.</div>
              <button className="btn primary" disabled={!active || busy || !permitted} onClick={() => fileRef.current?.click()}>Datei auswählen …</button>
              <input ref={fileRef} type="file" hidden aria-label="Importdatei" accept=".xlsx,.csv,.txt,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ''; }} />
              {!permitted && <div className="alert warning">Für den Import von {KIND_LABEL[kind]} fehlt die Berechtigung {kind === 'vehicles' ? 'vehicles.write' : 'stations.write'}.</div>}
            </div>
            <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>
              Hinweis: Fahrzeuge verweisen auf bestehende Wachen, Fahrzeugtypen, Funkrufgruppen und RICs – diese zuerst anlegen bzw. Wachen zuerst importieren.
              OpenStreetMap liefert nur Standorte, keine verlässlichen Fahrzeugbestände.
            </div>
            <ImportHistory jobs={history.data ?? []} onOpen={(id) => void run(() => api.get<ImportJob>(`/imports/${id}`))} />
          </div>
        )}
        {job && step === 2 && <MappingStep job={job} busy={busy} onValidate={(mapping, updateExisting) => run(() => api.put<ImportJob>(`/imports/${job.id}/mapping`, { mapping, update_existing: updateExisting, expected_version: job.version }))} onDiscard={() => run(async () => { await api.delete(`/imports/${job.id}`); setJob(null); sysmsg('info', 'Datenimport', 'Import verworfen'); })} />}
        {job && step === 3 && (
          <PreviewStep job={job} busy={busy}
            onBack={() => setJob({ ...job, status: 'uploaded' })}
            onDiscard={() => run(async () => { await api.delete(`/imports/${job.id}`); setJob(null); sysmsg('info', 'Datenimport', 'Import verworfen'); })}
            onCommit={(skipInvalid) => run(async () => {
              const done = await api.post<ImportJob>(`/imports/${job.id}/commit`, { expected_version: job.version, skip_invalid: skipInvalid });
              await qc.invalidateQueries({ queryKey: [job.kind] });
              void qc.invalidateQueries({ queryKey: ['import-jobs'] });
              sysmsg('success', 'Datenimport', `Import „${job.file_name}“ übernommen (${done.summary?.create ?? 0} neu, ${done.summary?.update ?? 0} aktualisiert)`);
              return done;
            })} />
        )}
        {job && step === 4 && <ResultStep job={job} />}
      </div>
    </div>
  );
}

function ImportHistory({ jobs, onOpen }: { jobs: ImportJobSummary[]; onOpen: (id: string) => void }): ReactNode {
  if (!jobs.length) return null;
  const STATUS = { uploaded: 'Hochgeladen', validated: 'Geprüft', committed: 'Übernommen', discarded: 'Verworfen' } as const;
  return (
    <div>
      <div className="section-title">Letzte Importe</div>
      <table className="data">
        <thead><tr><th>Zeitpunkt</th><th>Datei</th><th>Art</th><th>Zeilen</th><th>Status</th></tr></thead>
        <tbody>
          {jobs.slice(0, 10).map((j) => (
            <tr key={j.id} className={j.status === 'uploaded' || j.status === 'validated' ? 'clickable' : ''} onClick={() => (j.status === 'uploaded' || j.status === 'validated') && onOpen(j.id)}>
              <td className="tabular">{fmtDateTime(j.created_at)}</td>
              <td>{j.file_name}</td>
              <td>{KIND_LABEL[j.kind]}</td>
              <td className="tabular">{j.row_count}</td>
              <td><span className={`badge ${j.status === 'committed' ? 'ok' : j.status === 'discarded' ? '' : 'warn'}`}>{STATUS[j.status]}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MappingStep(props: { job: ImportJob; busy: boolean; onValidate: (m: Record<string, number | null>, u: boolean) => void; onDiscard: () => void }): ReactNode {
  const { job } = props;
  const [mapping, setMapping] = useState<Record<string, number | null>>(job.column_mapping ?? {});
  const [updateExisting, setUpdateExisting] = useState(Boolean(job.options.update_existing));
  const missing = job.fields.filter((f) => f.required && (mapping[f.key] === null || mapping[f.key] === undefined));
  const used = Object.values(mapping).filter((v): v is number => v !== null && v !== undefined);
  const duplicate = used.length !== new Set(used).size;
  const unmapped = job.headers.filter((_, i) => !used.includes(i));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div><b>{job.file_name}</b> <span className="muted">· {job.row_count} Zeilen{job.sheet_name ? ` · Blatt „${job.sheet_name}“` : ''} · {KIND_LABEL[job.kind]}</span></div>
      <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Die Zuordnung wurde anhand der Spaltennamen vorgeschlagen. Bitte prüfen und bei Bedarf anpassen.</div>
      <table className="data mapping">
        <thead><tr><th style={{ width: 220 }}>Zielfeld</th><th style={{ width: 240 }}>Spalte der Datei</th><th>Beispielwerte</th></tr></thead>
        <tbody>
          {job.fields.map((f) => {
            const idx = mapping[f.key];
            const samples = idx === null || idx === undefined ? [] : job.sample_rows.map((r) => r[idx]).filter(Boolean).slice(0, 3);
            return (
              <tr key={f.key}>
                <td title={f.hint}>{f.label}{f.required && <span style={{ color: 'var(--danger)' }}> *</span>}{f.hint && <div className="muted" style={{ fontSize: 'var(--fs-xs)', whiteSpace: 'normal' }}>{f.hint}</div>}</td>
                <td>
                  <select className="select" style={{ width: '100%' }} aria-label={`Spalte für ${f.label}`} value={idx ?? ''} onChange={(e) => setMapping({ ...mapping, [f.key]: e.target.value === '' ? null : Number(e.target.value) })}>
                    <option value="">– nicht importieren –</option>
                    {job.headers.map((h, i) => <option key={i} value={i}>{h}</option>)}
                  </select>
                </td>
                <td className="muted">{samples.join(' · ')}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {unmapped.length > 0 && <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>Nicht verwendete Spalten: {unmapped.join(', ')}</div>}
      <label className="checkbox"><input type="checkbox" checked={updateExisting} onChange={(e) => setUpdateExisting(e.target.checked)} /> Vorhandene {KIND_LABEL[job.kind]} aktualisieren (Abgleich über {job.kind === 'vehicles' ? 'Funkrufname' : 'Name'}; leere Zellen ändern nichts)</label>
      {missing.length > 0 && <div className="alert warning">Pflichtfelder ohne Spalte: {missing.map((f) => f.label).join(', ')}</div>}
      {duplicate && <div className="alert warning">Eine Spalte ist mehreren Zielfeldern zugeordnet.</div>}
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn primary" disabled={props.busy || missing.length > 0 || duplicate} onClick={() => props.onValidate(mapping, updateExisting)}>{props.busy ? 'Prüfe …' : 'Alle Zeilen prüfen'}</button>
        <button className="btn" onClick={props.onDiscard}>Verwerfen</button>
      </div>
    </div>
  );
}

function PreviewStep(props: { job: ImportJob; busy: boolean; onBack: () => void; onDiscard: () => void; onCommit: (skipInvalid: boolean) => void }): ReactNode {
  const { job } = props;
  const [filter, setFilter] = useState<ImportAction | 'all'>('all');
  const [skipInvalid, setSkipInvalid] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const summary = job.summary ?? { create: 0, update: 0, unchanged: 0, error: 0, skip: 0, total: 0 };
  const keyField = job.kind === 'vehicles' ? 'call_sign' : 'name';
  const rows = useMemo(() => (job.validation ?? []).filter((r) => filter === 'all' || r.action === filter), [job.validation, filter]);
  const writes = summary.create + summary.update;
  const blocked = summary.error > 0 && !skipInvalid;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, height: '100%' }}>
      <div className="chips" role="group" aria-label="Filter">
        <button className={`chip ${filter === 'all' ? 'on' : ''}`} onClick={() => setFilter('all')}>Alle {summary.total}</button>
        {(['create', 'update', 'unchanged', 'error', 'skip'] as const).map((a) => summary[a] > 0 && (
          <button key={a} className={`chip ${filter === a ? 'on' : ''}`} onClick={() => setFilter(a)}><span className={`badge ${ACTION[a].cls}`}>{ACTION[a].label}</span> {summary[a]}</button>
        ))}
      </div>
      <div className="table-wrap" style={{ maxHeight: 420, border: '1px solid var(--line)' }}>
        <table className="data">
          <thead><tr><th style={{ width: 60 }}>Zeile</th><th style={{ width: 120 }}>Aktion</th><th style={{ width: 240 }}>{job.kind === 'vehicles' ? 'Funkrufname' : 'Name'}</th><th>Meldungen</th></tr></thead>
          <tbody>
            {rows.slice(0, 1000).map((r) => (
              <tr key={r.row}>
                <td className="tabular">{r.row}</td>
                <td><span className={`badge ${ACTION[r.action].cls}`}>{ACTION[r.action].label}</span></td>
                <td>{r.values[keyField] ?? ''}</td>
                <td style={{ whiteSpace: 'normal' }} className="selectable">
                  {r.errors.map((e) => <div key={e} style={{ color: '#ff9da1' }}>{e}</div>)}
                  {r.warnings.map((w) => <div key={w} style={{ color: '#ffd291' }}>{w}</div>)}
                  {r.changes.length > 0 && <div className="muted">Ändert: {r.changes.join(', ')}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {summary.error > 0 && (
        <label className="checkbox"><input type="checkbox" checked={skipInvalid} onChange={(e) => setSkipInvalid(e.target.checked)} /> {summary.error} fehlerhafte Zeile(n) überspringen und nur die übrigen übernehmen</label>
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn primary" disabled={props.busy || blocked || writes === 0} onClick={() => setConfirm(true)}>{writes} Datensätze übernehmen …</button>
        <button className="btn" onClick={props.onBack}>Zurück zur Zuordnung</button>
        <button className="btn" onClick={props.onDiscard}>Verwerfen</button>
      </div>
      {confirm && (
        <Modal title="Import übernehmen" onClose={() => setConfirm(false)} footer={<>
          <button className="btn" onClick={() => setConfirm(false)}>Abbrechen</button>
          <button className="btn primary" onClick={() => { setConfirm(false); props.onCommit(skipInvalid); }}>Jetzt übernehmen</button>
        </>}>
          <div>Es werden <b>{summary.create}</b> {KIND_LABEL[job.kind]} neu angelegt und <b>{summary.update}</b> aktualisiert{summary.error ? <>, <b>{summary.error}</b> fehlerhafte Zeilen übersprungen</> : ''}.</div>
          <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Die Übernahme erfolgt in einem Schritt (ganz oder gar nicht) und jeder Datensatz wird im Änderungsprotokoll vermerkt.</div>
        </Modal>
      )}
    </div>
  );
}

function ResultStep({ job }: { job: ImportJob }): ReactNode {
  const s = job.summary;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 560 }}>
      <div className="alert success">Import „{job.file_name}“ wurde am {fmtDateTime(job.committed_at)} übernommen.</div>
      <dl className="kv">
        <dt>Neu angelegt</dt><dd>{s?.create ?? 0}</dd>
        <dt>Aktualisiert</dt><dd>{s?.update ?? 0}</dd>
        <dt>Unverändert</dt><dd>{s?.unchanged ?? 0}</dd>
        <dt>Übersprungen (Fehler)</dt><dd>{s?.error ?? 0}</dd>
      </dl>
      <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Die Rohdaten der Datei wurden nach der Übernahme gelöscht; Prüfergebnis und Protokoll bleiben erhalten.</div>
    </div>
  );
}
