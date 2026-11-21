import { useMemo, useState, type ReactNode } from 'react';

export interface Option {
  value: string;
  label: string;
  hint?: string;
}

/** Searchable multi selection – scales to hundreds of options (e.g. RICs). */
export function MultiSelect(props: {
  options: Option[];
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
  placeholder?: string;
  label?: string;
}): ReactNode {
  const { options, value, onChange, disabled } = props;
  const [filter, setFilter] = useState('');
  const byValue = useMemo(() => new Map(options.map((o) => [o.value, o])), [options]);
  const matches = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return options
      .filter((o) => !value.includes(o.value))
      .filter((o) => !f || o.label.toLowerCase().includes(f) || (o.hint ?? '').toLowerCase().includes(f))
      .slice(0, 40);
  }, [options, value, filter]);

  return (
    <div className="multiselect">
      <div className="chips">
        {value.map((v) => (
          <span key={v} className="chip on">
            {byValue.get(v)?.label ?? v}
            {!disabled && (
              <button type="button" className="chip-x" aria-label={`${byValue.get(v)?.label ?? v} entfernen`} onClick={() => onChange(value.filter((x) => x !== v))}>
                ×
              </button>
            )}
          </span>
        ))}
        {value.length === 0 && <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>keine</span>}
      </div>
      {!disabled && (
        <div className="multiselect-add">
          <input
            className="input"
            aria-label={props.label ? `${props.label} hinzufügen` : 'Eintrag hinzufügen'}
            placeholder={props.placeholder ?? 'Suchen und hinzufügen …'}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          {filter && (
            <div className="multiselect-list" role="listbox">
              {matches.length === 0 && <div className="muted" style={{ padding: 6 }}>Keine Treffer</div>}
              {matches.map((o) => (
                <button type="button" role="option" aria-selected={false} key={o.value} className="menu-item" onClick={() => { onChange([...value, o.value]); setFilter(''); }}>
                  <span>{o.label}</span>
                  {o.hint && <span className="muted" style={{ fontSize: 'var(--fs-xs)' }}>{o.hint}</span>}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
