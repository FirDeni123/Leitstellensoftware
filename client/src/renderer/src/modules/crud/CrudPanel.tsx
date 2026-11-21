/**
 * Generic master data panel: list with search, detail form, create/update/delete with
 * optimistic locking and conflict handling. Each entity only supplies an EntityConfig.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useState, type ReactNode } from 'react';
import { useList } from '@/api/queries';
import { EmptyState, ErrorAlert } from '@/components/common';
import { EditNotices, useEditBase } from '@/components/useEditBase';
import { sysmsg } from '@/state/messages';
import { hasPermission, useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { FieldEditor, initialValue, toPayload, type FormValues } from './fields';
import type { EntityConfig } from './types';

const field = (item: object, key: string): unknown => (item as Record<string, unknown>)[key];
const versionOf = (item: object): number | undefined => field(item, 'version') as number | undefined;
const defaultId = (item: object): string => String(field(item, 'id'));

export function ControlCenterBadge(): ReactNode {
  const { active, all } = useActiveControlCenter();
  if (!active) return <span className="badge warn">Keine Leitstelle</span>;
  return <span className="badge accent" title={all.length > 1 ? 'Umschalten in der Kopfzeile' : undefined}>{active.code}</span>;
}

export function CrudPanel<T extends object>({ config }: { config: EntityConfig<T> }): ReactNode {
  const me = useSession((s) => s.me)!;
  const { active } = useActiveControlCenter();
  const [q, setQ] = useState('');
  const [selectedId, setSelectedId] = useState<string | 'new' | null>(null);
  const params = useMemo(() => ({
    ...(config.scoped && active ? { control_center_id: active.id } : {}),
  }), [config.scoped, active]);
  const list = useList<T>(config.collection, config.path, params, !config.scoped || !!active);
  const idOf = config.idOf ?? defaultId;
  const canWrite = hasPermission(me, config.writePermission);

  const items = useMemo(() => {
    const f = q.trim().toLowerCase();
    const all = list.data ?? [];
    if (!f) return all;
    const text = config.searchText ?? ((item: T) => JSON.stringify(item));
    return all.filter((item) => text(item).toLowerCase().includes(f));
  }, [list.data, q, config.searchText]);
  const selected = selectedId && selectedId !== 'new' ? (list.data ?? []).find((x) => idOf(x) === selectedId) : undefined;

  return (
    <div className="panel">
      <div className="panel-toolbar">
        {config.scoped && <ControlCenterBadge />}
        <input className="input" placeholder="Suchen" aria-label={`${config.plural} durchsuchen`} value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 220 }} />
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{items.length} {config.plural}</span>
        <div className="spacer" />
        {canWrite && config.canCreate !== false && (!config.scoped || active) && (
          <button className="btn primary sm" onClick={() => setSelectedId('new')}>+ {config.singular}</button>
        )}
      </div>
      <ErrorAlert error={list.error} />
      <div className="panel-split">
        <div className="master table-wrap">
          {items.length === 0 && !list.isLoading ? (
            <EmptyState title={`Keine ${config.plural}`}>{config.emptyHint}</EmptyState>
          ) : (
            <table className="data">
              <thead>
                <tr>{config.columns.map((c) => <th key={c.header} style={c.width ? { width: c.width } : undefined}>{c.header}</th>)}</tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={idOf(item)} onClick={() => setSelectedId(idOf(item))}
                    className={`clickable ${idOf(item) === selectedId ? 'selected' : ''} ${config.inactive?.(item) ? 'inactive' : ''}`}>
                    {config.columns.map((c) => <td key={c.header} className={c.className} title={c.title?.(item)}>{c.render(item)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="detail">
          {selectedId === 'new' ? (
            <CrudEditor key="new" config={config} canWrite={canWrite} onDone={setSelectedId} />
          ) : selected ? (
            <CrudEditor key={idOf(selected)} config={config} item={selected} canWrite={canWrite} onDone={setSelectedId} />
          ) : (
            <EmptyState title={`${config.singular} auswählen`} />
          )}
        </div>
      </div>
    </div>
  );
}

function CrudEditor<T extends object>(props: { config: EntityConfig<T>; item?: T; canWrite: boolean; onDone: (id: string | null) => void }): ReactNode {
  const { config, item, canWrite } = props;
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const { active } = useActiveControlCenter();
  const toForm = (record: T | undefined) => Object.fromEntries(config.fields.map((f) => [f.key, initialValue(f, record)])) as FormValues;
  const edit = useEditBase(item, toForm, versionOf);
  const { form, setForm, initial, dirty, stale } = edit;
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const idOf = config.idOf ?? defaultId;
  const reload = () => {
    edit.reload();
    setError(null);
  };

  const save = async () => {
    setError(null);
    const payload: Record<string, unknown> = {};
    for (const field of config.fields) {
      if (item && field.createOnly) continue;
      if (item && JSON.stringify(form[field.key]) === JSON.stringify(initial[field.key])) continue;
      const converted = toPayload(field, form[field.key]);
      if (converted.error) {
        setError(new Error(converted.error));
        return;
      }
      if (converted.value === null && (!item || field.omitWhenEmpty)) continue; // keep server value / default
      payload[field.key] = converted.value;
    }
    setBusy(true);
    try {
      const saved = item
        ? await api.patch<T>(`${config.path}/${idOf(item)}`, { ...payload, expected_version: edit.baseVersion })
        : await api.post<T>(config.path, { ...payload, ...(config.scoped ? { control_center_id: active?.id } : {}) });
      if (item) edit.rebase(saved); // own change: the server response is the new editing base
      await qc.invalidateQueries({ queryKey: [config.collection] });
      sysmsg('success', config.plural, `${config.singular} „${config.title(saved)}“ gespeichert`);
      props.onDone(idOf(saved));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!item || !window.confirm(`${config.singular} „${config.title(item)}“ wirklich löschen?`)) return;
    try {
      await api.delete(`${config.path}/${idOf(item)}`);
      await qc.invalidateQueries({ queryKey: [config.collection] });
      sysmsg('success', config.plural, `${config.singular} „${config.title(item)}“ gelöscht`);
      props.onDone(null);
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>{item ? config.title(item) : `Neue(r) ${config.singular}`}</div>
        {item && versionOf(item) !== undefined && <span className="muted mono" style={{ marginLeft: 'auto', fontSize: 'var(--fs-xs)' }}>v{versionOf(item)}</span>}
      </div>
      <div className="form-grid" style={{ marginTop: 6 }}>
        {config.fields.map((field) => {
          const disabled = !canWrite || (!!item && !!field.createOnly) || !!field.disabledWhen?.(form);
          const editor = <FieldEditor field={field} value={form[field.key]} disabled={disabled} onChange={(v) => setForm((f) => ({ ...f, [field.key]: v }))} />;
          const full = field.full || ['textarea', 'multiselect', 'availability', 'geojson'].includes(field.type);
          if (field.type === 'checkbox') return <div key={field.key} className={full ? 'full' : undefined}>{editor}</div>;
          return (
            <div key={field.key} className={`field ${full ? 'full' : ''}`}>
              <label htmlFor={`fld-${field.key}`}>{field.label}{field.required ? ' *' : ''}</label>
              {editor}
              {field.hint && <span className="muted" style={{ fontSize: 'var(--fs-xs)' }}>{field.hint}</span>}
            </div>
          );
        })}
      </div>
      <EditNotices stale={stale} error={error} onReload={reload} />
      {canWrite && (
        <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
          <button className="btn primary" disabled={busy || (!!item && !dirty)} onClick={() => void save()}>{item ? 'Speichern' : 'Anlegen'}</button>
          {item && <button className="btn" disabled={!dirty || busy} onClick={reload}>Verwerfen</button>}
          {item && config.canDelete !== false && <button className="btn danger" style={{ marginLeft: 'auto' }} onClick={() => void remove()}>Löschen</button>}
          {!item && <button className="btn" onClick={() => props.onDone(null)}>Abbrechen</button>}
        </div>
      )}
      {item && config.details && <div style={{ marginTop: 8 }}>{config.details(item)}</div>}
    </div>
  );
}
