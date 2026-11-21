/** Vorschlagsregeln: administrable weights and substitute types per control centre. */
import { useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { useList, useProposalSettings } from '@/api/queries';
import type { ProposalSettings, ProposalSettingsData } from '@/api/types';
import { EmptyState, ErrorAlert, Field, fmtDateTime } from '@/components/common';
import { MultiSelect } from '@/components/MultiSelect';
import { EditNotices, useEditBase } from '@/components/useEditBase';
import { sysmsg } from '@/state/messages';
import { hasPermission, useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';

type NumberKey = Exclude<keyof ProposalSettingsData, 'use_routing' | 'substitutes'>;

const NUMBERS: { key: NumberKey; label: string; step?: number; unit: string; hint: string }[] = [
  { key: 'detour_factor', label: 'Umwegfaktor', step: 0.05, unit: '×', hint: 'Straßenweg ≈ Luftlinie × Faktor (nur bei Schätzung)' },
  { key: 'emergency_speed_factor', label: 'Faktor Sonderrechte', step: 0.05, unit: '×', hint: 'auf die Geschwindigkeit des Fahrzeugtyps' },
  { key: 'turnout_seconds_on_station', label: 'Ausrückzeit bei Status 2', unit: 's', hint: 'wird zur Fahrzeit addiert' },
  { key: 'substitute_penalty_seconds', label: 'Malus Ersatztyp', unit: 's', hint: 'z. B. LF statt HLF' },
  { key: 'preferred_station_bonus_seconds', label: 'Bonus Wache laut AAO', unit: 's', hint: 'Wachen-Einträge der AAO' },
  { key: 'max_travel_minutes', label: 'Maximale Fahrzeit', unit: 'min', hint: 'darüber kein Vorschlag' },
  { key: 'alternatives', label: 'Alternativen je Bedarf', unit: '', hint: 'zur Auswahl im Vorschlag' },
  { key: 'candidates_per_demand', label: 'Vorfilter je Bedarf', unit: '× Anzahl', hint: 'nächste Kandidaten nach Luftlinie für das Routing' },
];

const toForm = (s: ProposalSettings | undefined): ProposalSettingsData | null => (s ? structuredClone(s.settings) : null);

export function ProposalSettingsPanel(): ReactNode {
  const { active } = useActiveControlCenter();
  const query = useProposalSettings(active?.id);
  return (
    <div className="panel">
      <div className="panel-toolbar"><ControlCenterBadge /><span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Regeln des Einsatzmittelvorschlags</span></div>
      <ErrorAlert error={query.error} />
      <div className="panel-body" style={{ padding: 12 }}>
        {!active ? <EmptyState title="Keine Leitstelle ausgewählt" /> : query.data ? <SettingsForm key={active.id} data={query.data} /> : <EmptyState title="Lade …" />}
      </div>
    </div>
  );
}

function SettingsForm({ data }: { data: ProposalSettings }): ReactNode {
  const me = useSession((s) => s.me)!;
  const api = useSession((s) => s.api)!;
  const qc = useQueryClient();
  const types = useList<{ id: string; code: string }>('vehicle-types', '/vehicle-types');
  const edit = useEditBase(data, toForm, (s) => s.version ?? 0);
  const form = edit.form!;
  const [error, setError] = useState<unknown>(null);
  const [newCode, setNewCode] = useState('');
  const canWrite = hasPermission(me, 'proposal_settings.write');
  const codes = (types.data ?? []).map((t) => t.code).sort();
  const set = (patch: Partial<ProposalSettingsData>) => edit.setForm((f) => ({ ...f!, ...patch }));

  const save = async (values: ProposalSettingsData) => {
    setError(null);
    try {
      const saved = await api.put<ProposalSettings>('/proposal-settings', {
        control_center_id: data.control_center_id, settings: values, expected_version: edit.baseVersion || null,
      });
      edit.rebase(saved);
      await qc.invalidateQueries({ queryKey: ['proposal-settings'] });
      sysmsg('success', 'Vorschlagsregeln', 'Gespeichert');
    } catch (e) {
      setError(e);
    }
  };

  return (
    <div>
      <div className="muted" style={{ fontSize: 'var(--fs-sm)', marginBottom: 8 }}>
        Bewertung je Fahrzeug = Fahrzeit + Ausrückzeit (Status 2) + Malus Ersatztyp − Bonus Wache laut AAO. Kleiner ist besser.
        {data.is_default ? ' Es gelten die Standardwerte.' : ` Zuletzt geändert ${fmtDateTime(data.updated_at)} von ${data.updated_by_name ?? '–'}.`}
      </div>
      <div className={`alert ${data.routing_configured ? 'info' : 'warning'}`}>
        {data.routing_configured ? 'Routing-Dienst (OSRM) eingerichtet – Fahrzeiten aus Straßenrouten, bei Ausfall Schätzung.'
          : 'Kein Routing-Dienst eingerichtet (ILS_OSRM_URL) – Fahrzeiten werden geschätzt (Luftlinie × Umwegfaktor).'}
      </div>
      <div className="form-grid">
        {NUMBERS.map((n) => (
          <Field key={n.key} label={`${n.label}${n.unit ? ` (${n.unit})` : ''}`}>
            <input className="input tabular" type="number" step={n.step ?? 1} disabled={!canWrite} value={form[n.key]}
              title={n.hint} onChange={(e) => set({ [n.key]: Number(e.target.value) } as Partial<ProposalSettingsData>)} />
          </Field>
        ))}
        <label className="field"><span className="field-label">Routing-Dienst nutzen</span>
          <input type="checkbox" checked={form.use_routing} disabled={!canWrite} onChange={(e) => set({ use_routing: e.target.checked })} />
        </label>
      </div>

      <div className="section-title">Ersatztypen (Vorrang in Reihenfolge)</div>
      <table className="data compact">
        <thead><tr><th style={{ width: 110 }}>Bedarf</th><th>darf ersetzt werden durch</th><th style={{ width: 30 }} /></tr></thead>
        <tbody>
          {Object.entries(form.substitutes).sort(([a], [b]) => a.localeCompare(b)).map(([code, subs]) => (
            <tr key={code}>
              <td className="mono">{code}</td>
              <td><MultiSelect options={codes.filter((c) => c !== code).map((c) => ({ value: c, label: c }))} value={subs} disabled={!canWrite}
                label={`Ersatz für ${code}`} placeholder="Typ hinzufügen …"
                onChange={(next) => set({ substitutes: { ...form.substitutes, [code]: next } })} /></td>
              <td>{canWrite && <button className="btn ghost sm" aria-label={`Regel ${code} entfernen`} onClick={() => { const next = { ...form.substitutes }; delete next[code]; set({ substitutes: next }); }}>✕</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {canWrite && (
        <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          <select className="select" aria-label="Neue Ersatzregel" style={{ width: 160 }} value={newCode} onChange={(e) => setNewCode(e.target.value)}>
            <option value="">Fahrzeugtyp …</option>
            {codes.filter((c) => !(c in form.substitutes)).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <button className="btn sm" disabled={!newCode} onClick={() => { set({ substitutes: { ...form.substitutes, [newCode]: [] } }); setNewCode(''); }}>+ Regel</button>
        </div>
      )}

      <EditNotices stale={edit.stale} error={error} onReload={() => { edit.reload(); setError(null); }} />
      {canWrite && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button className="btn primary" disabled={!edit.dirty} onClick={() => void save(form)}>Speichern</button>
          <button className="btn" disabled={!edit.dirty} onClick={() => edit.reload()}>Verwerfen</button>
          <button className="btn" style={{ marginLeft: 'auto' }} onClick={() => void save(data.defaults)}>Auf Standardwerte zurücksetzen</button>
        </div>
      )}
    </div>
  );
}
