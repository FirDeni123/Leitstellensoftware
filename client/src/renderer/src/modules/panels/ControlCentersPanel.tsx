import { useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { ApiError } from '@/api/http';
import { useControlCenters } from '@/api/queries';
import type { ControlCenter } from '@/api/types';
import { EmptyState, ErrorAlert, Field, fmtDateTime } from '@/components/common';
import { sysmsg } from '@/state/messages';
import { hasPermission, useSession } from '@/state/session';

interface Draft {
  code: string;
  name: string;
  description: string;
  address: string;
  latitude: string;
  longitude: string;
  is_active: boolean;
}

const EMPTY: Draft = { code: '', name: '', description: '', address: '', latitude: '', longitude: '', is_active: true };

function toDraft(cc: ControlCenter): Draft {
  return {
    code: cc.code, name: cc.name, description: cc.description ?? '', address: cc.address ?? '',
    latitude: cc.latitude?.toString() ?? '', longitude: cc.longitude?.toString() ?? '', is_active: cc.is_active,
  };
}

function parseCoord(v: string): number | null {
  if (!v.trim()) return null;
  const n = Number(v.replace(',', '.'));
  return Number.isFinite(n) ? n : NaN;
}

export function ControlCentersPanel(): ReactNode {
  const me = useSession((s) => s.me)!;
  const list = useControlCenters();
  const [selectedId, setSelectedId] = useState<string | 'new' | null>(null);
  const canWrite = hasPermission(me, 'control_centers.write');
  const selected = selectedId && selectedId !== 'new' ? list.data?.find((c) => c.id === selectedId) : undefined;

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{list.data?.length ?? 0} Leitstellen</span>
        <div className="spacer" />
        {canWrite && <button className="btn primary sm" onClick={() => setSelectedId('new')}>+ Leitstelle anlegen</button>}
      </div>
      <ErrorAlert error={list.error} />
      <div className="panel-split">
        <div className="master table-wrap">
          <table className="data">
            <thead><tr><th>Kennung</th><th>Name</th><th>Standort</th><th>Status</th></tr></thead>
            <tbody>
              {(list.data ?? []).map((c) => (
                <tr key={c.id} className={`clickable ${c.id === selectedId ? 'selected' : ''} ${c.is_active ? '' : 'inactive'}`} onClick={() => setSelectedId(c.id)}>
                  <td className="mono">{c.code}</td>
                  <td>{c.name}</td>
                  <td className="tabular muted">{c.latitude != null && c.longitude != null ? `${c.latitude.toFixed(4)}, ${c.longitude.toFixed(4)}` : '–'}</td>
                  <td>{c.is_active ? <span className="badge ok">Aktiv</span> : <span className="badge">Inaktiv</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="detail">
          {selectedId === 'new' ? (
            <ControlCenterEditor key="new" canWrite={canWrite} onSaved={setSelectedId} />
          ) : selected ? (
            <ControlCenterEditor key={`${selected.id}:${selected.version}`} cc={selected} canWrite={canWrite} onSaved={setSelectedId} />
          ) : (
            <EmptyState title="Leitstelle auswählen" />
          )}
        </div>
      </div>
    </div>
  );
}

function ControlCenterEditor(props: { cc?: ControlCenter; canWrite: boolean; onSaved: (id: string | null) => void }): ReactNode {
  const { cc, canWrite } = props;
  const api = useSession((s) => s.api)!;
  const me = useSession((s) => s.me)!;
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Draft>(cc ? toDraft(cc) : EMPTY);
  const [error, setError] = useState<unknown>(null);
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const lat = parseCoord(draft.latitude);
  const lon = parseCoord(draft.longitude);
  const invalid = draft.name.trim().length < 2 || (!cc && !/^[A-Z0-9][A-Z0-9_-]{1,31}$/.test(draft.code)) || Number.isNaN(lat) || Number.isNaN(lon);

  const save = async () => {
    setError(null);
    const body = {
      name: draft.name.trim(), description: draft.description || null, address: draft.address || null,
      latitude: lat, longitude: lon, is_active: draft.is_active,
    };
    try {
      const saved = cc
        ? await api.patch<ControlCenter>(`/control-centers/${cc.id}`, { ...body, expected_version: cc.version })
        : await api.post<ControlCenter>('/control-centers', { ...body, code: draft.code });
      await qc.invalidateQueries({ queryKey: ['control-centers'] });
      sysmsg('success', 'Leitstellen', `Leitstelle ${saved.code} gespeichert`);
      props.onSaved(saved.id);
    } catch (e) {
      setError(e);
    }
  };

  const remove = async () => {
    if (!cc || !window.confirm(`Leitstelle ${cc.code} wirklich löschen?`)) return;
    try {
      await api.delete(`/control-centers/${cc.id}`);
      await qc.invalidateQueries({ queryKey: ['control-centers'] });
      sysmsg('success', 'Leitstellen', `Leitstelle ${cc.code} gelöscht`);
      props.onSaved(null);
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div>
      <div style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>{cc ? cc.name : 'Neue Leitstelle'}</div>
      {error instanceof ApiError && error.isConflict && cc ? (
        <div className="alert error" style={{ marginTop: 10 }}>{error.message} <button className="btn sm" onClick={() => void qc.invalidateQueries({ queryKey: ['control-centers'] })}>Neu laden</button></div>
      ) : (
        <div style={{ marginTop: 10 }}><ErrorAlert error={error} /></div>
      )}
      <div className="form-grid" style={{ marginTop: 10 }}>
        <Field label="Kennung"><input className="input mono" value={draft.code} disabled={!!cc || !canWrite} onChange={(e) => set({ code: e.target.value.toUpperCase() })} placeholder="ILS-NORD" /></Field>
        <Field label="Name"><input className="input" value={draft.name} disabled={!canWrite} onChange={(e) => set({ name: e.target.value })} /></Field>
        <Field label="Anschrift" className="full"><input className="input" value={draft.address} disabled={!canWrite} onChange={(e) => set({ address: e.target.value })} /></Field>
        <Field label="Breitengrad (WGS84)"><input className={`input tabular ${Number.isNaN(lat) ? 'invalid' : ''}`} value={draft.latitude} disabled={!canWrite} onChange={(e) => set({ latitude: e.target.value })} placeholder="53.5036" /></Field>
        <Field label="Längengrad (WGS84)"><input className={`input tabular ${Number.isNaN(lon) ? 'invalid' : ''}`} value={draft.longitude} disabled={!canWrite} onChange={(e) => set({ longitude: e.target.value })} placeholder="10.4806" /></Field>
        <Field label="Beschreibung" className="full"><input className="input" value={draft.description} disabled={!canWrite} onChange={(e) => set({ description: e.target.value })} /></Field>
        <label className="checkbox full"><input type="checkbox" checked={draft.is_active} disabled={!canWrite} onChange={(e) => set({ is_active: e.target.checked })} /> Aktiv</label>
      </div>
      <div className="muted" style={{ fontSize: 'var(--fs-xs)', marginTop: 8 }}>Standortauswahl auf der Karte folgt mit dem Kartenmodul (Phase 6).</div>
      {canWrite && (
        <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
          <button className="btn primary" disabled={invalid} onClick={() => void save()}>{cc ? 'Speichern' : 'Anlegen'}</button>
          {cc && hasPermission(me, 'system.admin') && <button className="btn danger" onClick={() => void remove()}>Löschen</button>}
        </div>
      )}
      {cc && (
        <>
          <div className="section-title">Metadaten</div>
          <dl className="kv">
            <dt>Angelegt</dt><dd>{fmtDateTime(cc.created_at)}</dd>
            <dt>Geändert</dt><dd>{fmtDateTime(cc.updated_at)}</dd>
            <dt>Version</dt><dd className="mono">{cc.version}</dd>
          </dl>
        </>
      )}
    </div>
  );
}
