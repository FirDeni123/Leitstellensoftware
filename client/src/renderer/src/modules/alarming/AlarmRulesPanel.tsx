/**
 * AAO editor (Alarm- und Ausrückeordnung): per keyword and control centre (optionally per area)
 * which units are proposed in which stage. The AAO only produces a proposal – the dispatcher
 * always confirms the alarm.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useState, type ReactNode } from 'react';
import { useAlarmRules, useList } from '@/api/queries';
import type { AlarmRule, AlarmRuleItem, InterfaceItem, Keyword, RuleItemKind } from '@/api/types';
import { EmptyState, ErrorAlert, Field, Modal } from '@/components/common';
import { EditNotices, useEditBase } from '@/components/useEditBase';
import { sysmsg } from '@/state/messages';
import { hasPermission, useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';
import { RULE_KIND } from './labels';

interface Named { id: string; name?: string; code?: string; call_sign?: string; label?: string; sub_address?: string }

type Selected = { kind: 'rule'; id: string } | { kind: 'new'; keywordId: string } | null;

export function AlarmRulesPanel(): ReactNode {
  const me = useSession((s) => s.me)!;
  const { active } = useActiveControlCenter();
  const rules = useAlarmRules(active?.id);
  const keywords = useList<Keyword>('keywords', '/keywords');
  const [selected, setSelected] = useState<Selected>(null);
  const [q, setQ] = useState('');
  const canWrite = hasPermission(me, 'alarm_rules.write');
  const byKeyword = useMemo(() => {
    const map = new Map<string, AlarmRule[]>();
    for (const r of rules.data ?? []) map.set(r.keyword.id, [...(map.get(r.keyword.id) ?? []), r]);
    return map;
  }, [rules.data]);
  const visible = (keywords.data ?? []).filter((k) => `${k.code} ${k.name}`.toLowerCase().includes(q.toLowerCase()));
  const rule = selected?.kind === 'rule' ? rules.data?.find((r) => r.id === selected.id) : undefined;

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <input className="input" placeholder="Stichwort suchen …" aria-label="Stichwort suchen" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 180 }} />
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{rules.data?.length ?? 0} AAO-Einträge</span>
      </div>
      <ErrorAlert error={rules.error ?? keywords.error} />
      <div className="panel-split">
        <div className="master table-wrap" style={{ flex: 0.7 }}>
          <table className="data">
            <thead><tr><th style={{ width: 90 }}>Stichwort</th><th>Bezeichnung</th><th style={{ width: 130 }}>AAO</th></tr></thead>
            <tbody>
              {visible.map((k) => {
                const list = byKeyword.get(k.id) ?? [];
                return list.length === 0 ? (
                  <tr key={k.id} className={`clickable ${selected?.kind === 'new' && selected.keywordId === k.id ? 'selected' : ''} ${k.is_active ? '' : 'inactive'}`}
                    onClick={() => setSelected({ kind: 'new', keywordId: k.id })}>
                    <td><span className={`kw kw-${k.category}`}>{k.code}</span></td><td>{k.name}</td><td className="muted">keine</td>
                  </tr>
                ) : list.map((r) => (
                  <tr key={r.id} className={`clickable ${rule?.id === r.id ? 'selected' : ''} ${r.is_active ? '' : 'inactive'}`} onClick={() => setSelected({ kind: 'rule', id: r.id })}>
                    <td><span className={`kw kw-${k.category}`}>{k.code}</span></td>
                    <td>{r.name ?? k.name}{r.area && <span className="muted"> · {r.area.name}</span>}</td>
                    <td className="muted">{r.items.length} Einträge · {r.max_stage} Stufe{r.max_stage === 1 ? '' : 'n'}</td>
                  </tr>
                ));
              })}
            </tbody>
          </table>
        </div>
        <div className="detail" style={{ flex: 1.5, minWidth: 420 }}>
          {!active ? <EmptyState title="Keine Leitstelle ausgewählt" />
            : rule ? <RuleEditor key={rule.id} rule={rule} ccId={active.id} canWrite={canWrite} onDeleted={() => setSelected(null)} />
              : selected?.kind === 'new' ? (
                <NewRule key={selected.keywordId} keyword={keywords.data?.find((k) => k.id === selected.keywordId)} ccId={active.id} canWrite={canWrite}
                  onCreated={(id) => setSelected({ kind: 'rule', id })} />
              ) : <EmptyState title="Stichwort auswählen">AAO je Stichwort: welche Fahrzeugtypen, Fahrzeuge, Wachen, RICs, Alarmierungsgruppen und Schnittstellen in welcher Stufe vorgeschlagen werden.</EmptyState>}
        </div>
      </div>
    </div>
  );
}

function useTargets(ccId: string) {
  const me = useSession((s) => s.me)!;
  const p = { control_center_id: ccId };
  const types = useList<Named>('vehicle-types', '/vehicle-types');
  const vehicles = useList<Named>('vehicles', '/vehicles', p);
  const stations = useList<Named>('stations', '/stations', p);
  const rics = useList<Named>('rics', '/rics', p);
  const groups = useList<Named>('alarm-groups', '/alarm-groups', p);
  const interfaces = useList<InterfaceItem>('interfaces', '/interfaces', p, hasPermission(me, 'interfaces.read'));
  return useMemo(() => {
    const label = (n: Named) => n.call_sign ?? (n.code && n.label ? `${n.code}${n.sub_address ? `/${n.sub_address}` : ''} ${n.label}` : n.code && n.name ? `${n.code} – ${n.name}` : n.name ?? n.id);
    const opts = (rows: Named[] | undefined) => (rows ?? []).map((r) => ({ value: r.id, label: label(r) })).sort((a, b) => a.label.localeCompare(b.label, 'de'));
    return {
      vehicle_type: opts(types.data), vehicle: opts(vehicles.data), station: opts(stations.data), ric: opts(rics.data),
      alarm_group: opts(groups.data), interface: (interfaces.data ?? []).map((i) => ({ value: i.id, label: `${i.name}${i.is_real ? ' (real)' : ''}` })),
    } satisfies Record<RuleItemKind, { value: string; label: string }[]>;
  }, [types.data, vehicles.data, stations.data, rics.data, groups.data, interfaces.data]);
}

interface RuleForm { name: string; is_active: boolean; items: AlarmRuleItem[] }
const toForm = (r: AlarmRule | undefined): RuleForm => ({
  name: r?.name ?? '', is_active: r?.is_active ?? true,
  items: (r?.items ?? []).map((i) => ({ stage: i.stage, kind: i.kind, count: i.count, target_id: i.target_id, note: i.note })),
});

function ItemsEditor({ items, onChange, ccId, disabled }: { items: AlarmRuleItem[]; onChange: (items: AlarmRuleItem[]) => void; ccId: string; disabled: boolean }): ReactNode {
  const targets = useTargets(ccId);
  const update = (idx: number, patch: Partial<AlarmRuleItem>) => onChange(items.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  const stages = [...new Set(items.map((i) => i.stage))].sort();
  return (
    <>
      <table className="data compact">
        <thead><tr><th style={{ width: 70 }}>Stufe</th><th style={{ width: 150 }}>Art</th><th>Ziel</th><th style={{ width: 64 }}>Anzahl</th><th>Hinweis</th><th style={{ width: 30 }} /></tr></thead>
        <tbody>
          {items.map((it, idx) => (
            <tr key={idx}>
              <td><select className="select" aria-label="Stufe" value={it.stage} disabled={disabled} onChange={(e) => update(idx, { stage: Number(e.target.value) })}>
                {Array.from({ length: 9 }, (_, i) => i + 1).map((s) => <option key={s} value={s}>{s}</option>)}
              </select></td>
              <td><select className="select" aria-label="Art" value={it.kind} disabled={disabled} onChange={(e) => update(idx, { kind: e.target.value as RuleItemKind, target_id: '' })}>
                {Object.entries(RULE_KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select></td>
              <td><select className="select" aria-label="Ziel" value={it.target_id} disabled={disabled} onChange={(e) => update(idx, { target_id: e.target.value })}>
                <option value="">– auswählen –</option>
                {targets[it.kind].map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select></td>
              <td>{it.kind === 'vehicle_type' ? <input className="input tabular" aria-label="Anzahl" type="number" min={1} max={20} value={it.count} disabled={disabled} onChange={(e) => update(idx, { count: Math.max(1, Math.min(20, Number(e.target.value) || 1)) })} /> : <span className="muted">1</span>}</td>
              <td><input className="input" aria-label="Hinweis" value={it.note ?? ''} disabled={disabled} onChange={(e) => update(idx, { note: e.target.value || null })} /></td>
              <td>{!disabled && <button className="btn ghost sm" aria-label="Zeile entfernen" onClick={() => onChange(items.filter((_, i) => i !== idx))}>✕</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!disabled && (
        <button className="btn sm" style={{ marginTop: 6 }} onClick={() => onChange([...items, { stage: stages.at(-1) ?? 1, kind: 'vehicle_type', count: 1, target_id: '', note: null }])}>+ Zeile</button>
      )}
    </>
  );
}

const cleanItems = (items: AlarmRuleItem[]) => items.filter((i) => i.target_id).map((i) => ({ stage: i.stage, kind: i.kind, count: i.count, target_id: i.target_id, note: i.note }));

function RuleEditor({ rule, ccId, canWrite, onDeleted }: { rule: AlarmRule; ccId: string; canWrite: boolean; onDeleted: () => void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const edit = useEditBase(rule, toForm, (r) => r.version);
  const { form, setForm, dirty } = edit;
  const [error, setError] = useState<unknown>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const incomplete = form.items.some((i) => !i.target_id);
  const save = async () => {
    setError(null);
    try {
      const saved = await api.patch<AlarmRule>(`/alarm-rules/${rule.id}`, {
        name: form.name || null, is_active: form.is_active, items: cleanItems(form.items), expected_version: edit.baseVersion,
      });
      edit.rebase(saved);
      await qc.invalidateQueries({ queryKey: ['alarm-rules'] });
      sysmsg('success', 'AAO', `AAO ${rule.keyword.code} gespeichert`);
    } catch (e) {
      setError(e);
    }
  };
  const remove = async () => {
    try {
      await api.delete(`/alarm-rules/${rule.id}?expected_version=${rule.version}`);
      await qc.invalidateQueries({ queryKey: ['alarm-rules'] });
      onDeleted();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className={`kw kw-${rule.keyword.category}`}>{rule.keyword.code}</span>
        <span style={{ fontWeight: 600 }}>{rule.keyword.name}</span>
        {rule.area && <span className="badge info">Bereich {rule.area.name}</span>}
      </div>
      <div className="form-grid" style={{ marginTop: 8 }}>
        <Field label="Bezeichnung"><input className="input" value={form.name} disabled={!canWrite} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} /></Field>
        <label className="field"><span className="field-label">Aktiv</span><input type="checkbox" checked={form.is_active} disabled={!canWrite} onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} /></label>
      </div>
      <div className="section-title">Einträge</div>
      <ItemsEditor items={form.items} onChange={(items) => setForm((f) => ({ ...f, items }))} ccId={ccId} disabled={!canWrite} />
      {incomplete && <div className="alert warning">Zeilen ohne Ziel werden beim Speichern nicht übernommen.</div>}
      <EditNotices stale={edit.stale} error={error} onReload={() => { edit.reload(); setError(null); }} />
      {canWrite && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button className="btn primary" disabled={!dirty} onClick={() => void save()}>Speichern</button>
          <button className="btn" disabled={!dirty} onClick={() => edit.reload()}>Verwerfen</button>
          <button className="btn danger" style={{ marginLeft: 'auto' }} onClick={() => setConfirmDelete(true)}>Löschen</button>
        </div>
      )}
      <div className="muted" style={{ fontSize: 'var(--fs-xs)', marginTop: 8 }}>
        Stufe 1 = Erstalarm. Die Vorschau bei „Alarmieren“ zieht bereits im Einsatz befindliche Fahrzeuge ab und schlägt freie
        Fahrzeuge nach Luftlinie vor (Einsatzmittelvorschlag mit Fahrzeit folgt in Phase 5).
      </div>
      {confirmDelete && (
        <Modal title={`AAO ${rule.keyword.code} löschen`} onClose={() => setConfirmDelete(false)} footer={<>
          <button className="btn" onClick={() => setConfirmDelete(false)}>Abbrechen</button>
          <button className="btn danger" onClick={() => { setConfirmDelete(false); void remove(); }}>Löschen</button>
        </>}>Für dieses Stichwort gibt es danach keinen Alarmierungsvorschlag mehr.</Modal>
      )}
    </div>
  );
}

function NewRule({ keyword, ccId, canWrite, onCreated }: { keyword: Keyword | undefined; ccId: string; canWrite: boolean; onCreated: (id: string) => void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const areas = useList<Named>('control-center-areas', '/control-center-areas', { control_center_id: ccId });
  const [items, setItems] = useState<AlarmRuleItem[]>([{ stage: 1, kind: 'vehicle_type', count: 1, target_id: '', note: null }]);
  const [areaId, setAreaId] = useState('');
  const [error, setError] = useState<unknown>(null);
  if (!keyword) return null;
  const create = async () => {
    setError(null);
    try {
      const rule = await api.post<AlarmRule>('/alarm-rules', {
        control_center_id: ccId, keyword_id: keyword.id, area_id: areaId || null, name: `${keyword.code}${areaId ? '' : ' Standard'}`, items: cleanItems(items),
      });
      await qc.invalidateQueries({ queryKey: ['alarm-rules'] });
      onCreated(rule.id);
    } catch (e) {
      setError(e);
    }
  };
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className={`kw kw-${keyword.category}`}>{keyword.code}</span><span style={{ fontWeight: 600 }}>{keyword.name}</span>
      </div>
      {!canWrite ? <EmptyState title="Keine AAO hinterlegt">Zum Anlegen fehlt die Berechtigung „Alarmierungsregeln (AAO) verwalten“.</EmptyState> : (
        <>
          <Field label="Gilt für">
            <select className="select" value={areaId} onChange={(e) => setAreaId(e.target.value)}>
              <option value="">gesamte Leitstelle</option>
              {(areas.data ?? []).map((a) => <option key={a.id} value={a.id}>Bereich {a.name}</option>)}
            </select>
          </Field>
          <div className="section-title">Einträge</div>
          <ItemsEditor items={items} onChange={setItems} ccId={ccId} disabled={false} />
          <ErrorAlert error={error} />
          <button className="btn primary" style={{ marginTop: 10 }} onClick={() => void create()}>AAO anlegen</button>
        </>
      )}
    </div>
  );
}
