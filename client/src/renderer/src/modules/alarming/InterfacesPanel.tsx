/**
 * Schnittstellen: plugin instances per system, control centre or station.
 * New interfaces are always disabled. Real interfaces can only be enabled and tested in real
 * operation and with `interfaces.activate_real`; the server enforces this – the UI explains it.
 * Secrets are write-only: the server stores them encrypted and only returns a masked hint.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { useInterfaceEvents, useInterfaces, useList, usePlugins } from '@/api/queries';
import type { InterfaceItem, InterfaceScope, PluginInfo } from '@/api/types';
import { EmptyState, ErrorAlert, Field, fmtDateTime, fmtTime, Modal } from '@/components/common';
import { SchemaForm } from '@/components/SchemaForm';
import { missingRequired } from '@/components/schemaFormLogic';
import { EditNotices, useEditBase } from '@/components/useEditBase';
import { sysmsg } from '@/state/messages';
import { hasPermission, useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';

const SCOPE: Record<InterfaceScope, string> = { global: 'systemweit', control_center: 'Leitstelle', station: 'Wache' };
const STATUS: Record<InterfaceItem['status'], { label: string; cls: string }> = {
  unknown: { label: 'ungeprüft', cls: '' }, ok: { label: 'OK', cls: 'ok' }, error: { label: 'Fehler', cls: 'danger' },
};

function stateBadge(i: InterfaceItem): ReactNode {
  if (!i.enabled) return <span className="badge">deaktiviert</span>;
  if (!i.effective) return <span className="badge warn" title="Reale Schnittstelle im Simulationsbetrieb – Zustellungen werden umgeleitet">umgeleitet</span>;
  return <span className={`badge ${i.is_real ? 'danger' : 'ok'}`}>{i.is_real ? 'AKTIV (real)' : 'aktiv'}</span>;
}

export function InterfacesPanel(): ReactNode {
  const me = useSession((s) => s.me)!;
  const { active } = useActiveControlCenter();
  const list = useInterfaces(active?.id);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const canWrite = hasPermission(me, 'interfaces.write');
  const selected = list.data?.find((i) => i.id === selectedId);
  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{list.data?.length ?? 0} Schnittstellen</span>
        <div className="spacer" />
        {canWrite && <button className="btn primary sm" onClick={() => setCreating(true)}>+ Schnittstelle</button>}
      </div>
      <ErrorAlert error={list.error} />
      <div className="panel-split">
        <div className="master table-wrap">
          {(list.data ?? []).length === 0 && !list.isLoading ? (
            <EmptyState title="Keine Schnittstellen">Schnittstellen leiten Alarmierungen an weitere Systeme weiter (z. B. Alarmierungs-App, Feuerwehrsoftware).</EmptyState>
          ) : (
            <table className="data">
              <thead><tr><th>Name</th><th>Plugin</th><th>Gültig für</th><th style={{ width: 110 }}>Zustand</th><th style={{ width: 80 }}>Prüfung</th></tr></thead>
              <tbody>
                {(list.data ?? []).map((i) => (
                  <tr key={i.id} className={`clickable ${i.id === selectedId ? 'selected' : ''} ${i.enabled ? '' : 'inactive'}`} onClick={() => setSelectedId(i.id)}>
                    <td style={{ fontWeight: 600 }}>{i.name}</td>
                    <td>{i.plugin_name}{i.is_real && <span className="badge danger" style={{ marginLeft: 4 }}>REAL</span>}</td>
                    <td className="muted">{SCOPE[i.scope]}{i.station_name ? `: ${i.station_name}` : ''}</td>
                    <td>{stateBadge(i)}</td>
                    <td><span className={`badge ${STATUS[i.status].cls}`} title={i.last_error ?? ''}>{STATUS[i.status].label}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="detail" style={{ flex: 1.2 }}>
          {selected ? <InterfaceDetail key={selected.id} item={selected} onDeleted={() => setSelectedId(null)} /> : <EmptyState title="Schnittstelle auswählen" />}
        </div>
      </div>
      {creating && <CreateInterfaceDialog ccId={active?.id} onClose={() => setCreating(false)} onCreated={setSelectedId} />}
    </div>
  );
}

function RealHint({ plugin }: { plugin: Pick<PluginInfo, 'is_real'> }): ReactNode {
  if (!plugin.is_real) return <div className="alert info">Simulations-Plugin: es wird kein externes System angesprochen.</div>;
  return (
    <div className="alert warning">
      Reale Schnittstelle: Aktivieren und Testen nur im Echtbetrieb und mit der Berechtigung „Reale Schnittstellen aktivieren“.
      Im Simulationsbetrieb wird nichts übertragen; beim Wechsel in den Simulationsbetrieb wird sie automatisch deaktiviert.
    </div>
  );
}

interface IfaceForm { name: string; config: Record<string, unknown>; secret: string; clearSecret: boolean }
const toForm = (i: InterfaceItem | undefined): IfaceForm => ({ name: i?.name ?? '', config: i?.config ?? {}, secret: '', clearSecret: false });

function InterfaceDetail({ item, onDeleted }: { item: InterfaceItem; onDeleted: () => void }): ReactNode {
  const me = useSession((s) => s.me)!;
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const plugins = usePlugins();
  const events = useInterfaceEvents(item.id);
  const plugin = plugins.data?.find((p) => p.key === item.plugin_key);
  const edit = useEditBase(item, toForm, (i) => i.version);
  const { form, setForm, dirty } = edit;
  const [error, setError] = useState<unknown>(null);
  const [toggle, setToggle] = useState(false);
  const [reason, setReason] = useState('');
  const [testing, setTesting] = useState(false);
  const canWrite = hasPermission(me, 'interfaces.write') && (item.scope !== 'global' || hasPermission(me, 'system.admin'));
  const canReal = hasPermission(me, 'interfaces.activate_real');
  const locked = item.is_real && item.enabled && !canReal;
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ['interfaces'] }), qc.invalidateQueries({ queryKey: ['interface-events'] })]);

  const save = async () => {
    setError(null);
    try {
      const body: Record<string, unknown> = { expected_version: edit.baseVersion };
      if (form.name !== edit.initial.name) body['name'] = form.name;
      if (JSON.stringify(form.config) !== JSON.stringify(edit.initial.config)) body['config'] = form.config;
      if (form.secret) body['secret'] = form.secret;
      if (form.clearSecret) body['clear_secret'] = true;
      const saved = await api.patch<InterfaceItem>(`/interfaces/${item.id}`, body);
      edit.rebase(saved);
      await refresh();
    } catch (e) {
      setError(e);
    }
  };
  const setEnabled = async (enabled: boolean) => {
    setError(null);
    try {
      await api.post(`/interfaces/${item.id}/enabled`, { enabled, expected_version: item.version, reason: reason.trim() || null });
      setToggle(false);
      setReason('');
      await refresh();
    } catch (e) {
      setError(e);
    }
  };
  const test = async () => {
    setError(null);
    setTesting(true);
    try {
      const r = await api.post<{ ok: boolean; detail: string }>(`/interfaces/${item.id}/test`);
      sysmsg(r.ok ? 'success' : 'error', 'Schnittstelle', `${item.name}: ${r.detail}`);
      await refresh();
    } catch (e) {
      setError(e);
    } finally {
      setTesting(false);
    }
  };
  const remove = async () => {
    try {
      await api.delete(`/interfaces/${item.id}?expected_version=${item.version}`);
      await refresh();
      onDeleted();
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 'var(--fs-lg)', fontWeight: 700 }}>{item.name}</span>
        {stateBadge(item)}
        <span className={`badge ${STATUS[item.status].cls}`}>{STATUS[item.status].label}</span>
      </div>
      <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
        {item.plugin_name} · {SCOPE[item.scope]}{item.station_name ? `: ${item.station_name}` : ''}
        {item.last_checked_at && ` · zuletzt geprüft ${fmtDateTime(item.last_checked_at)}`}
      </div>
      {item.last_error && item.status === 'error' && <div className="alert error">Letzter Fehler: {item.last_error}</div>}
      {plugin && <RealHint plugin={plugin} />}

      {canWrite && (
        <div style={{ display: 'flex', gap: 8, margin: '8px 0' }}>
          <button className={`btn ${item.enabled ? '' : item.is_real ? 'danger' : 'primary'}`} disabled={item.is_real && !canReal}
            onClick={() => (item.enabled || !item.is_real ? void setEnabled(!item.enabled) : setToggle(true))}>
            {item.enabled ? 'Deaktivieren' : 'Aktivieren'}
          </button>
          <button className="btn" disabled={testing || (item.is_real && !canReal)} onClick={() => void test()}>{testing ? 'Teste …' : 'Verbindung testen'}</button>
          <button className="btn danger" style={{ marginLeft: 'auto' }} disabled={item.enabled} title={item.enabled ? 'Zuerst deaktivieren' : ''} onClick={() => void remove()}>Löschen</button>
        </div>
      )}

      <div className="section-title">Einstellungen</div>
      <Field label="Name"><input className="input" value={form.name} disabled={!canWrite || locked} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} /></Field>
      {plugin && <SchemaForm schema={plugin.config_schema} value={form.config} disabled={!canWrite || locked} onChange={(config) => setForm((f) => ({ ...f, config }))} />}
      {plugin?.secret_label && (
        <Field label={`${plugin.secret_label} (verschlüsselt gespeichert)`}>
          <input className="input mono" type="password" autoComplete="new-password" value={form.secret} disabled={!canWrite || locked}
            placeholder={item.has_secret ? `gesetzt (${item.secret_hint}) – leer lassen = unverändert` : 'nicht gesetzt'}
            onChange={(e) => setForm((f) => ({ ...f, secret: e.target.value, clearSecret: false }))} />
        </Field>
      )}
      {item.has_secret && canWrite && !locked && (
        <label className="assignment"><input type="checkbox" checked={form.clearSecret} onChange={(e) => setForm((f) => ({ ...f, clearSecret: e.target.checked, secret: '' }))} /> Schlüssel entfernen</label>
      )}
      {locked && <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>Änderungen an einer aktiven realen Schnittstelle erfordern „Reale Schnittstellen aktivieren“.</div>}
      <EditNotices stale={edit.stale} error={error} onReload={() => { edit.reload(); setError(null); }} />
      {canWrite && !locked && (
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <button className="btn primary" disabled={!dirty} onClick={() => void save()}>Speichern</button>
          <button className="btn" disabled={!dirty} onClick={() => edit.reload()}>Verwerfen</button>
        </div>
      )}

      <div className="section-title">Protokoll</div>
      <div className="timeline">
        {(events.data ?? []).map((e) => (
          <div key={e.id} className={`timeline-item level-${e.level}`}>
            <span className="tabular muted">{fmtTime(e.ts)}</span>
            <span className="selectable">{e.message}</span>
            <span className="muted">{e.kind}</span>
          </div>
        ))}
      </div>

      {toggle && (
        <Modal title={`Reale Schnittstelle „${item.name}“ aktivieren`} onClose={() => setToggle(false)} footer={<>
          <button className="btn" onClick={() => setToggle(false)}>Abbrechen</button>
          <button className="btn danger" disabled={reason.trim().length < 5} onClick={() => void setEnabled(true)}>Aktivieren</button>
        </>}>
          <div className="alert error">Nach der Aktivierung überträgt diese Schnittstelle Alarmierungen an ein reales externes System.</div>
          <Field label="Begründung (wird protokolliert)"><input className="input" autoFocus value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <ErrorAlert error={error} />
        </Modal>
      )}
    </div>
  );
}

function CreateInterfaceDialog({ ccId, onClose, onCreated }: { ccId: string | undefined; onClose: () => void; onCreated: (id: string) => void }): ReactNode {
  const me = useSession((s) => s.me)!;
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const plugins = usePlugins();
  const stations = useList<{ id: string; name: string }>('stations', '/stations', { control_center_id: ccId }, !!ccId);
  const [pluginKey, setPluginKey] = useState('');
  const [name, setName] = useState('');
  const [scope, setScope] = useState<InterfaceScope>('control_center');
  const [stationId, setStationId] = useState('');
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [secret, setSecret] = useState('');
  const [error, setError] = useState<unknown>(null);
  const plugin = plugins.data?.find((p) => p.key === pluginKey);
  const scopes = (plugin?.scopes ?? []).filter((s) => s !== 'global' || hasPermission(me, 'system.admin'));
  const missing = plugin ? missingRequired(plugin.config_schema, config) : [];
  const submit = async () => {
    setError(null);
    try {
      const created = await api.post<InterfaceItem>('/interfaces', {
        plugin_key: pluginKey, name, scope, config, secret: secret || null,
        control_center_id: scope === 'global' ? null : ccId, station_id: scope === 'station' ? stationId || null : null,
      });
      await qc.invalidateQueries({ queryKey: ['interfaces'] });
      sysmsg('success', 'Schnittstelle', `„${created.name}“ angelegt (deaktiviert)`);
      onCreated(created.id);
      onClose();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Modal title="Schnittstelle anlegen" width={640} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Abbrechen</button>
      <button className="btn primary" disabled={!plugin || name.trim().length < 2 || missing.length > 0 || (scope === 'station' && !stationId)} onClick={() => void submit()}>Anlegen (deaktiviert)</button>
    </>}>
      <Field label="Plugin">
        <select className="select" autoFocus value={pluginKey} onChange={(e) => { setPluginKey(e.target.value); setConfig({}); }}>
          <option value="">– auswählen –</option>
          {(plugins.data ?? []).map((p) => <option key={p.key} value={p.key}>{p.name}{p.is_real ? ' – REAL' : ''}</option>)}
        </select>
      </Field>
      {plugin && (
        <>
          <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{plugin.description}</div>
          <RealHint plugin={plugin} />
          <div className="form-grid">
            <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Gültig für">
              <select className="select" value={scope} onChange={(e) => setScope(e.target.value as InterfaceScope)}>
                {scopes.map((s) => <option key={s} value={s}>{SCOPE[s]}</option>)}
              </select>
            </Field>
            {scope === 'station' && (
              <Field label="Wache" className="full">
                <select className="select" value={stationId} onChange={(e) => setStationId(e.target.value)}>
                  <option value="">– auswählen –</option>
                  {(stations.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </Field>
            )}
          </div>
          <div className="section-title">Einstellungen</div>
          <SchemaForm schema={plugin.config_schema} value={config} onChange={setConfig} />
          {plugin.secret_label && (
            <Field label={`${plugin.secret_label} (wird verschlüsselt gespeichert, nie wieder angezeigt)`}>
              <input className="input mono" type="password" autoComplete="new-password" value={secret} onChange={(e) => setSecret(e.target.value)} />
            </Field>
          )}
          {missing.length > 0 && <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>Pflichtfelder: {missing.join(', ')}</div>}
        </>
      )}
      <ErrorAlert error={error} />
    </Modal>
  );
}
