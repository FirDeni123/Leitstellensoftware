/** Configuration form generated from a plugin's JSON Schema (string, number, boolean, enum). */
import type { ReactNode } from 'react';
import type { JsonObjectSchema } from '@/api/types';
import { coerceValue, fieldError, setConfigValue } from './schemaForm';

export function SchemaForm({ schema, value, onChange, disabled }: {
  schema: JsonObjectSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled?: boolean;
}): ReactNode {
  const entries = Object.entries(schema.properties ?? {});
  if (entries.length === 0) return <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Dieses Plugin hat keine Einstellungen.</div>;
  return (
    <div className="form-grid">
      {entries.map(([key, prop]) => {
        const required = schema.required?.includes(key);
        const label = `${prop.title ?? key}${required ? ' *' : ''}`;
        const current = value[key];
        const error = fieldError(prop, current);
        const set = (raw: string | boolean) => onChange(setConfigValue(value, key, coerceValue(prop, raw)));
        let control: ReactNode;
        if (prop.enum) {
          control = (
            <select className="select" value={current === undefined ? '' : String(current)} disabled={disabled} onChange={(e) => set(e.target.value)}>
              <option value="">{prop.default !== undefined ? `Standard (${String(prop.default)})` : '– auswählen –'}</option>
              {prop.enum.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
            </select>
          );
        } else if (prop.type === 'boolean') {
          control = <input type="checkbox" checked={Boolean(current ?? prop.default)} disabled={disabled} onChange={(e) => set(e.target.checked)} />;
        } else {
          control = (
            <input className={`input ${prop.type === 'integer' || prop.type === 'number' ? 'tabular' : ''}`}
              value={current === undefined ? '' : String(current)} disabled={disabled} maxLength={prop.maxLength}
              placeholder={prop.default !== undefined ? `Standard: ${String(prop.default)}` : prop.format === 'uri' ? 'https://…' : ''}
              onChange={(e) => set(e.target.value)} />
          );
        }
        return (
          <label key={key} className={`field ${prop.type === 'string' && !prop.enum ? 'full' : ''}`}>
            <span className="field-label">{label}</span>
            {control}
            {error && <span className="field-error">{error}</span>}
          </label>
        );
      })}
    </div>
  );
}
