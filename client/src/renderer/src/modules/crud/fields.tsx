/** Form field editors and value conversion for the generic master data panel. */
import { useRef, type ReactNode } from 'react';
import { useList } from '@/api/queries';
import type { Availability } from '@/api/types';
import { MultiSelect, type Option } from '@/components/MultiSelect';
import { useActiveControlCenter } from '@/state/workContext';
import type { FieldDef, SourceDef } from './types';

export type FormValues = Record<string, unknown>;

const DAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];

/** German or English decimal notation -> number; '' -> null; invalid -> NaN. */
export function parseNumber(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  const normalised = t.includes(',') && t.includes('.') ? t.replace(/\./g, '').replace(',', '.') : t.replace(',', '.');
  const n = Number(normalised);
  return Number.isFinite(n) ? n : NaN;
}

export function initialValue(field: FieldDef, item: unknown): unknown {
  if (item) {
    const raw = field.get ? field.get(item) : (item as Record<string, unknown>)[field.key];
    if (field.type === 'number') return raw === null || raw === undefined ? '' : String(raw);
    if (field.type === 'geojson') return raw ? JSON.stringify(raw, null, 2) : '';
    if (field.type === 'text' || field.type === 'textarea' || field.type === 'color' || field.type === 'select') return raw ?? '';
    return raw;
  }
  if (field.defaultValue !== undefined) return field.defaultValue;
  switch (field.type) {
    case 'checkbox': return false;
    case 'multiselect': return [];
    case 'availability': return { mode: 'always', schedule: [] } satisfies Availability;
    default: return '';
  }
}

/** Converts a form value to the API payload value; returns an error text when invalid. */
export function toPayload(field: FieldDef, value: unknown): { value?: unknown; error?: string } {
  switch (field.type) {
    case 'number': {
      const n = parseNumber(String(value ?? ''));
      if (Number.isNaN(n)) return { error: `${field.label}: keine gültige Zahl` };
      if (n !== null && ((field.min !== undefined && n < field.min) || (field.max !== undefined && n > field.max))) {
        return { error: `${field.label}: Wert zwischen ${field.min} und ${field.max}` };
      }
      if (n === null && field.required) return { error: `${field.label} ist erforderlich` };
      return { value: n };
    }
    case 'geojson': {
      const text = String(value ?? '').trim();
      if (!text) return { value: null };
      try {
        return { value: JSON.parse(text) };
      } catch {
        return { error: `${field.label}: kein gültiges JSON` };
      }
    }
    case 'text':
    case 'textarea':
    case 'color':
    case 'select': {
      const text = String(value ?? '').trim();
      if (!text && field.required) return { error: `${field.label} ist erforderlich` };
      return { value: text || (field.emptyValue !== undefined ? field.emptyValue : null) };
    }
    default:
      return { value };
  }
}

function useSourceOptions(source: SourceDef | undefined): Option[] {
  const { active } = useActiveControlCenter();
  const params = source?.scoped && active ? { control_center_id: active.id } : {};
  const list = useList<Record<string, unknown>>(source?.collection ?? 'none', source?.path ?? '/', params, !!source);
  if (!source) return [];
  return (list.data ?? []).map((item) => ({
    value: source.value ? source.value(item) : String(item['id']),
    label: source.label(item),
    hint: source.hint?.(item),
  }));
}

function AvailabilityEditor(props: { value: Availability; onChange: (v: Availability) => void; disabled: boolean }): ReactNode {
  const { value, onChange, disabled } = props;
  const setEntry = (i: number, patch: Partial<Availability['schedule'][number]>) =>
    onChange({ ...value, schedule: value.schedule.map((e, j) => (j === i ? { ...e, ...patch } : e)) });
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <select className="select" value={value.mode} disabled={disabled} aria-label="Verfügbarkeit"
        onChange={(e) => onChange({ ...value, mode: e.target.value as Availability['mode'],
          schedule: e.target.value === 'schedule' && value.schedule.length === 0 ? [{ days: [1, 2, 3, 4, 5], start: '06:00', end: '18:00' }] : value.schedule })}>
        <option value="always">Ständig verfügbar</option>
        <option value="schedule">Nach Zeitplan</option>
        <option value="unavailable">Nicht verfügbar</option>
      </select>
      {value.mode === 'schedule' && value.schedule.map((entry, i) => (
        <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className="chips">
            {DAYS.map((d, idx) => {
              const day = idx + 1;
              const on = entry.days.includes(day);
              return (
                <button type="button" key={d} className={`chip ${on ? 'on' : ''}`} disabled={disabled}
                  onClick={() => setEntry(i, { days: on ? entry.days.filter((x) => x !== day) : [...entry.days, day].sort() })}>{d}</button>
              );
            })}
          </div>
          <input className="input tabular" style={{ width: 70 }} value={entry.start} disabled={disabled} aria-label="von" onChange={(e) => setEntry(i, { start: e.target.value })} />
          <span className="muted">–</span>
          <input className="input tabular" style={{ width: 70 }} value={entry.end} disabled={disabled} aria-label="bis" onChange={(e) => setEntry(i, { end: e.target.value })} />
          {!disabled && <button type="button" className="btn ghost sm" onClick={() => onChange({ ...value, schedule: value.schedule.filter((_, j) => j !== i) })}>Entfernen</button>}
        </div>
      ))}
      {value.mode === 'schedule' && !disabled && (
        <button type="button" className="btn sm" style={{ alignSelf: 'flex-start' }}
          onClick={() => onChange({ ...value, schedule: [...value.schedule, { days: [6, 7], start: '00:00', end: '23:59' }] })}>+ Zeitraum</button>
      )}
      <input className="input" placeholder="Hinweis (optional)" value={value.note ?? ''} disabled={disabled} aria-label="Hinweis zur Verfügbarkeit"
        onChange={(e) => onChange({ ...value, note: e.target.value || null })} />
    </div>
  );
}

function GeoJsonEditor(props: { value: string; onChange: (v: string) => void; disabled: boolean }): ReactNode {
  const fileRef = useRef<HTMLInputElement>(null);
  let info = 'keine Geometrie';
  if (props.value.trim()) {
    try {
      const parsed = JSON.parse(props.value) as { type?: string; geometry?: { type?: string } };
      info = `GeoJSON ${parsed.type === 'Feature' ? parsed.geometry?.type : parsed.type}, ${props.value.length.toLocaleString('de-DE')} Zeichen`;
    } catch {
      info = 'kein gültiges JSON';
    }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <textarea className="input mono" style={{ height: 110, padding: 8, fontSize: 'var(--fs-xs)' }} value={props.value} disabled={props.disabled}
        aria-label="GeoJSON" placeholder='{"type":"Polygon","coordinates":[[[10.40,53.45],[10.56,53.45],[10.56,53.56],[10.40,53.45]]]}'
        onChange={(e) => props.onChange(e.target.value)} />
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {!props.disabled && <button type="button" className="btn sm" onClick={() => fileRef.current?.click()}>GeoJSON-Datei laden</button>}
        <span className="muted" style={{ fontSize: 'var(--fs-xs)' }}>{info} · Reihenfolge [Länge, Breite]</span>
        <input ref={fileRef} type="file" accept=".geojson,.json,application/geo+json,application/json" hidden
          onChange={async (e) => { const f = e.target.files?.[0]; if (f) props.onChange(await f.text()); e.target.value = ''; }} />
      </div>
    </div>
  );
}

export function FieldEditor(props: { field: FieldDef; value: unknown; onChange: (v: unknown) => void; disabled: boolean }): ReactNode {
  const { field, value, onChange } = props;
  const disabled = props.disabled;
  const sourceOptions = useSourceOptions(field.source);
  const options = field.options ?? sourceOptions;
  const id = `fld-${field.key}`;

  switch (field.type) {
    case 'checkbox':
      return (
        <label className="checkbox">
          <input type="checkbox" checked={Boolean(value)} disabled={disabled} onChange={(e) => onChange(e.target.checked)} /> {field.label}
        </label>
      );
    case 'textarea':
      return <textarea id={id} className="input" style={{ height: 64, padding: 8 }} value={String(value ?? '')} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
    case 'select':
      return (
        <select id={id} className="select" value={String(value ?? '')} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
          {!field.required && <option value="">– keine –</option>}
          {field.required && !value && <option value="">– bitte wählen –</option>}
          {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      );
    case 'multiselect':
      return <MultiSelect options={options} value={(value as string[]) ?? []} onChange={onChange} disabled={disabled} label={field.label} />;
    case 'color':
      return (
        <div style={{ display: 'flex', gap: 6 }}>
          <input type="color" aria-label={`${field.label} wählen`} value={String(value || '#888888')} disabled={disabled} onChange={(e) => onChange(e.target.value)} style={{ width: 36, height: 30, padding: 0, border: 'none', background: 'none' }} />
          <input id={id} className="input mono" value={String(value ?? '')} disabled={disabled} placeholder="#RRGGBB" onChange={(e) => onChange(e.target.value)} />
        </div>
      );
    case 'availability':
      return <AvailabilityEditor value={value as Availability} onChange={onChange} disabled={disabled} />;
    case 'geojson':
      return <GeoJsonEditor value={String(value ?? '')} onChange={onChange} disabled={disabled} />;
    default:
      return (
        <input id={id} className={`input ${field.type === 'number' ? 'tabular' : ''}`} value={String(value ?? '')} disabled={disabled}
          placeholder={field.placeholder} inputMode={field.type === 'number' ? 'decimal' : undefined}
          onChange={(e) => onChange(field.transform ? field.transform(e.target.value) : e.target.value)} />
      );
  }
}
