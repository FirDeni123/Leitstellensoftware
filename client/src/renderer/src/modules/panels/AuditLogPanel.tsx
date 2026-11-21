import { useState, type ReactNode } from 'react';
import { useAudit } from '@/api/queries';
import type { AuditEntry } from '@/api/types';
import { EmptyState, ErrorAlert, fmtDateTime } from '@/components/common';

const ENTITY_LABEL: Record<string, string> = {
  user: 'Benutzer',
  role: 'Rolle',
  control_center: 'Leitstelle',
  system: 'System',
  permission_catalogue: 'Berechtigungen',
};

const ACTION_LABEL: Record<string, string> = {
  create: 'Angelegt', update: 'Geändert', delete: 'Gelöscht', activate: 'Aktiviert', deactivate: 'Deaktiviert',
  password_reset: 'Passwort zurückgesetzt', password_change: 'Passwort geändert', unlock: 'Entsperrt',
  mode_change: 'Moduswechsel', sync: 'Synchronisiert',
};

function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '–';
  if (Array.isArray(v)) return v.join(', ') || '–';
  return String(v);
}

export function AuditLogPanel(): ReactNode {
  const [entityType, setEntityType] = useState('');
  const [selected, setSelected] = useState<AuditEntry | null>(null);
  const audit = useAudit(entityType);
  const items = audit.data?.items ?? [];

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <select className="select" aria-label="Objekttyp" value={entityType} onChange={(e) => setEntityType(e.target.value)}>
          <option value="">Alle Objekte</option>
          {Object.entries(ENTITY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>{items.length} Einträge · unveränderbar protokolliert</span>
        <div className="spacer" />
        <button className="btn sm" onClick={() => void audit.refetch()}>Aktualisieren</button>
      </div>
      <ErrorAlert error={audit.error} />
      <div className="panel-split">
        <div className="master table-wrap">
          {items.length === 0 && !audit.isLoading ? (
            <EmptyState title="Keine Einträge" />
          ) : (
            <table className="data">
              <thead><tr><th style={{ width: 150 }}>Zeitpunkt</th><th>Benutzer</th><th>Aktion</th><th>Objekt</th><th>Beschreibung</th></tr></thead>
              <tbody>
                {items.map((e) => (
                  <tr key={e.id} className={`clickable ${selected?.id === e.id ? 'selected' : ''}`} onClick={() => setSelected(e)}>
                    <td className="tabular">{fmtDateTime(e.ts)}</td>
                    <td>{e.actor_name}</td>
                    <td>{ACTION_LABEL[e.action] ?? e.action}</td>
                    <td className="muted">{ENTITY_LABEL[e.entity_type] ?? e.entity_type}</td>
                    <td title={e.summary}>{e.summary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {selected && (
          <div className="detail">
            <div className="section-title" style={{ marginTop: 0 }}>Eintrag #{selected.id}</div>
            <dl className="kv">
              <dt>Zeitpunkt</dt><dd className="tabular">{fmtDateTime(selected.ts)}</dd>
              <dt>Benutzer</dt><dd>{selected.actor_name}</dd>
              <dt>Aktion</dt><dd>{ACTION_LABEL[selected.action] ?? selected.action}</dd>
              <dt>Objekt</dt><dd>{ENTITY_LABEL[selected.entity_type] ?? selected.entity_type} <span className="mono muted">{selected.entity_id}</span></dd>
              <dt>Beschreibung</dt><dd>{selected.summary}</dd>
              <dt>Anfrage-ID</dt><dd className="mono">{selected.request_id ?? '–'}</dd>
            </dl>
            {selected.changes && Object.keys(selected.changes).length > 0 && (
              <>
                <div className="section-title">Änderungen</div>
                <table className="data">
                  <thead><tr><th>Feld</th><th>Vorher</th><th>Nachher</th></tr></thead>
                  <tbody>
                    {Object.entries(selected.changes).map(([field, c]) => (
                      <tr key={field}><td className="mono">{field}</td><td className="muted">{formatValue(c.old)}</td><td>{formatValue(c.new)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
