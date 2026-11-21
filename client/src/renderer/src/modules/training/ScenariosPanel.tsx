/** Übungsszenarien (Szenario-Editor for instructors): persona, the truth of the situation,
 *  opening line, difficulty, expected keyword and the checklist for the evaluation. */
import { useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { useList, useTrainingScenarios } from '@/api/queries';
import type { ChecklistItem, Difficulty, TrainingScenario } from '@/api/types';
import { EmptyState, ErrorAlert, Field } from '@/components/common';
import { hasPermission, useSession } from '@/state/session';
import { useActiveControlCenter } from '@/state/workContext';
import { ControlCenterBadge } from '../crud/CrudPanel';
import { DIFFICULTY } from './components';

interface KeywordRef { id: string; code: string; name: string; is_active: boolean }

interface Form {
  title: string;
  description: string;
  difficulty: Difficulty;
  keyword_id: string;
  global: boolean;
  is_active: boolean;
  persona: Record<'name' | 'age' | 'role' | 'emotional_state' | 'speech_style' | 'phone', string>;
  facts: Record<'address' | 'lat' | 'lon' | 'location_hint' | 'situation' | 'persons' | 'injuries' | 'hazards' | 'details' | 'unknown', string>;
  opening_line: string;
  checklist: { key: string; label: string; required: boolean; hints: string }[];
}

const EMPTY: Form = {
  title: '', description: '', difficulty: 'medium', keyword_id: '', global: false, is_active: true,
  persona: { name: '', age: '', role: '', emotional_state: '', speech_style: '', phone: '' },
  facts: { address: '', lat: '', lon: '', location_hint: '', situation: '', persons: '', injuries: '', hazards: '', details: '', unknown: '' },
  opening_line: '', checklist: [],
};

function toForm(s: TrainingScenario): Form {
  const p = s.persona, f = s.facts;
  const str = (v: unknown) => (v === null || v === undefined ? '' : String(v));
  return {
    title: s.title, description: s.description ?? '', difficulty: s.difficulty, keyword_id: s.keyword_id ?? '',
    global: s.control_center_id === null, is_active: s.is_active,
    persona: { name: str(p.name), age: str(p.age), role: str(p.role), emotional_state: str(p.emotional_state), speech_style: str(p.speech_style), phone: str(p.phone) },
    facts: {
      address: str(f.address), lat: str(f.lat), lon: str(f.lon), location_hint: str(f.location_hint), situation: str(f.situation),
      persons: str(f.persons), injuries: str(f.injuries), hazards: str(f.hazards), details: (f.details ?? []).join('\n'), unknown: (f.unknown ?? []).join('\n'),
    },
    opening_line: s.opening_line,
    checklist: s.checklist.map((c) => ({ ...c, hints: c.hints.join(', ') })),
  };
}

function lines(v: string): string[] {
  return v.split('\n').map((l) => l.trim()).filter(Boolean);
}

function num(v: string): number | null {
  const n = Number(v.replace(',', '.'));
  return v.trim() && Number.isFinite(n) ? n : null;
}

export function toBody(form: Form): Record<string, unknown> {
  const blank = (v: string) => v.trim() || null;
  const p = form.persona, f = form.facts;
  return {
    title: form.title.trim(),
    description: blank(form.description),
    difficulty: form.difficulty,
    keyword_id: form.keyword_id || null,
    is_active: form.is_active,
    persona: { name: blank(p.name), age: num(p.age), role: blank(p.role), emotional_state: blank(p.emotional_state), speech_style: blank(p.speech_style), phone: blank(p.phone) },
    facts: {
      address: blank(f.address), lat: num(f.lat), lon: num(f.lon), location_hint: blank(f.location_hint), situation: blank(f.situation),
      persons: blank(f.persons), injuries: blank(f.injuries), hazards: blank(f.hazards), details: lines(f.details), unknown: lines(f.unknown),
    },
    opening_line: form.opening_line.trim(),
    checklist: form.checklist.filter((c) => c.key.trim() && c.label.trim()).map<ChecklistItem>((c) => ({
      key: c.key.trim(), label: c.label.trim(), required: c.required, hints: c.hints.split(',').map((h) => h.trim()).filter(Boolean),
    })),
  };
}

export function ScenariosPanel(): ReactNode {
  const { active } = useActiveControlCenter();
  const scenarios = useTrainingScenarios(active?.id, true);
  const [selected, setSelected] = useState<string | 'new' | null>(null);
  const current = scenarios.data?.find((s) => s.id === selected) ?? null;
  return (
    <div className="panel">
      <div className="panel-toolbar">
        <ControlCenterBadge />
        <span className="muted" style={{ fontSize: 'var(--fs-sm)' }}>Nur fiktive Personen und Lagen verwenden</span>
        <div className="spacer" />
        <button className="btn sm primary" disabled={!active} onClick={() => setSelected('new')}>Neues Szenario</button>
      </div>
      <ErrorAlert error={scenarios.error} />
      <div className="panel-split">
        <div className="master table-wrap">
          {(scenarios.data ?? []).length === 0 ? <EmptyState title="Noch keine Szenarien" /> : (
            <table className="data" aria-label="Szenarien">
              <thead><tr><th>Titel</th><th style={{ width: 70 }}>Stufe</th><th style={{ width: 70 }}>Stichwort</th></tr></thead>
              <tbody>
                {(scenarios.data ?? []).map((s) => (
                  <tr key={s.id} className={`clickable ${s.id === selected ? 'selected' : ''}`} onClick={() => setSelected(s.id)}>
                    <td>{s.title}{!s.is_active && <span className="badge warn" style={{ marginLeft: 4 }}>inaktiv</span>}{s.control_center_id === null && <span className="badge" style={{ marginLeft: 4 }}>alle Leitstellen</span>}</td>
                    <td><span className={`badge ${DIFFICULTY[s.difficulty].cls}`}>{DIFFICULTY[s.difficulty].label}</span></td>
                    <td className="mono">{s.keyword_code ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="detail" style={{ flex: 1.6 }}>
          {selected === 'new' ? <ScenarioEditor key="new" initial={null} onSaved={setSelected} />
            : current ? <ScenarioEditor key={`${current.id}:${current.version}`} initial={current} onSaved={setSelected} />
              : <EmptyState title="Szenario auswählen oder neu anlegen" />}
        </div>
      </div>
    </div>
  );
}

function ScenarioEditor({ initial, onSaved }: { initial: TrainingScenario | null; onSaved(id: string): void }): ReactNode {
  const api = useSession((s) => s.api)!;
  const me = useSession((s) => s.me)!;
  const qc = useQueryClient();
  const { active } = useActiveControlCenter();
  const keywords = useList<KeywordRef>('keywords', '/keywords');
  const [form, setForm] = useState<Form>(initial ? toForm(initial) : EMPTY);
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const isAdmin = hasPermission(me, 'system.admin');
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));
  const setP = (k: keyof Form['persona'], v: string) => setForm((f) => ({ ...f, persona: { ...f.persona, [k]: v } }));
  const setF = (k: keyof Form['facts'], v: string) => setForm((f) => ({ ...f, facts: { ...f.facts, [k]: v } }));
  const setItem = (i: number, patch: Partial<Form['checklist'][number]>) =>
    setForm((f) => ({ ...f, checklist: f.checklist.map((c, j) => (j === i ? { ...c, ...patch } : c)) }));

  const save = async () => {
    setSaving(true);
    try {
      const body = toBody(form);
      const saved = initial
        ? await api.patch<TrainingScenario>(`/training/scenarios/${initial.id}`, { ...body, expected_version: initial.version })
        : await api.post<TrainingScenario>('/training/scenarios', { ...body, control_center_id: form.global && isAdmin ? null : active?.id });
      setError(null);
      await qc.invalidateQueries({ queryKey: ['training-scenarios'] });
      onSaved(saved.id);
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="scenario-editor" onSubmit={(e) => { e.preventDefault(); void save(); }} aria-label="Szenario bearbeiten">
      <ErrorAlert error={error} />
      <div className="form-grid">
        <Field label="Titel" className="full"><input className="input" required value={form.title} onChange={(e) => set({ title: e.target.value })} /></Field>
        <Field label="Beschreibung (für Teilnehmer sichtbar)" className="full"><input className="input" value={form.description} onChange={(e) => set({ description: e.target.value })} /></Field>
        <Field label="Schwierigkeit">
          <select className="select" value={form.difficulty} onChange={(e) => set({ difficulty: e.target.value as Difficulty })}>
            <option value="easy">leicht – Anrufer kooperativ, Standort übermittelt</option>
            <option value="medium">mittel – aufgeregt, Rückfragen nötig</option>
            <option value="hard">schwer – panisch, Rufnummer unterdrückt</option>
          </select>
        </Field>
        <Field label="Erwartetes Stichwort">
          <select className="select" value={form.keyword_id} onChange={(e) => set({ keyword_id: e.target.value })}>
            <option value="">– keins –</option>
            {(keywords.data ?? []).filter((k) => k.is_active || k.id === form.keyword_id).map((k) => <option key={k.id} value={k.id}>{k.code} – {k.name}</option>)}
          </select>
        </Field>
        <label className="field"><span className="field-label">Aktiv</span><input type="checkbox" checked={form.is_active} onChange={(e) => set({ is_active: e.target.checked })} /></label>
        {!initial && isAdmin && <label className="field"><span className="field-label">Für alle Leitstellen</span><input type="checkbox" checked={form.global} onChange={(e) => set({ global: e.target.checked })} /></label>}
      </div>
      <h4>Anrufer (Persona)</h4>
      <div className="form-grid">
        <Field label="Name"><input className="input" value={form.persona.name} onChange={(e) => setP('name', e.target.value)} /></Field>
        <Field label="Alter"><input className="input tabular" value={form.persona.age} onChange={(e) => setP('age', e.target.value)} /></Field>
        <Field label="Rolle"><input className="input" placeholder="z. B. Passant, Ehefrau" value={form.persona.role} onChange={(e) => setP('role', e.target.value)} /></Field>
        <Field label="Gemütszustand"><input className="input" value={form.persona.emotional_state} onChange={(e) => setP('emotional_state', e.target.value)} /></Field>
        <Field label="Sprechweise"><input className="input" value={form.persona.speech_style} onChange={(e) => setP('speech_style', e.target.value)} /></Field>
        <Field label="Rufnummer"><input className="input mono" value={form.persona.phone} onChange={(e) => setP('phone', e.target.value)} /></Field>
      </div>
      <h4>Tatsächliche Lage (weiß der Anrufer, nennt sie nur auf Nachfrage)</h4>
      <div className="form-grid">
        <Field label="Einsatzort (Adresse)" className="full"><input className="input" value={form.facts.address} onChange={(e) => setF('address', e.target.value)} /></Field>
        <Field label="Breitengrad"><input className="input tabular" value={form.facts.lat} onChange={(e) => setF('lat', e.target.value)} /></Field>
        <Field label="Längengrad"><input className="input tabular" value={form.facts.lon} onChange={(e) => setF('lon', e.target.value)} /></Field>
        <Field label="Ortsbeschreibung"><input className="input" value={form.facts.location_hint} onChange={(e) => setF('location_hint', e.target.value)} /></Field>
        <Field label="Was ist passiert" className="full"><textarea className="input" rows={2} value={form.facts.situation} onChange={(e) => setF('situation', e.target.value)} /></Field>
        <Field label="Beteiligte Personen"><input className="input" value={form.facts.persons} onChange={(e) => setF('persons', e.target.value)} /></Field>
        <Field label="Verletzungen / Zustand"><input className="input" value={form.facts.injuries} onChange={(e) => setF('injuries', e.target.value)} /></Field>
        <Field label="Gefahren"><input className="input" value={form.facts.hazards} onChange={(e) => setF('hazards', e.target.value)} /></Field>
        <Field label="Weitere Details (je Zeile eins)" className="full"><textarea className="input" rows={2} value={form.facts.details} onChange={(e) => setF('details', e.target.value)} /></Field>
        <Field label="Weiß der Anrufer nicht (je Zeile eins)" className="full"><textarea className="input" rows={2} value={form.facts.unknown} onChange={(e) => setF('unknown', e.target.value)} /></Field>
        <Field label="Erster Satz des Anrufers" className="full"><input className="input" required value={form.opening_line} onChange={(e) => set({ opening_line: e.target.value })} /></Field>
      </div>
      <h4>Checkliste für die Gesprächsauswertung</h4>
      <div className="muted" style={{ fontSize: 'var(--fs-sm)' }}>
        Leer = Standard (Einsatzort, Ereignis, Betroffene, Rückrufnummer, Name, Verhaltenshinweise). Einsatzanlage, Stichwort, Ort und Alarmierung werden immer automatisch geprüft.
        Schlüsselwörter dienen der Auswertung ohne KI.
      </div>
      <table className="data" aria-label="Checkliste">
        <thead><tr><th style={{ width: 120 }}>Schlüssel</th><th>Prüfpunkt</th><th style={{ width: 50 }}>Pflicht</th><th>Schlüsselwörter</th><th style={{ width: 30 }} /></tr></thead>
        <tbody>
          {form.checklist.map((c, i) => (
            <tr key={i}>
              <td><input className="input mono" aria-label="Schlüssel" value={c.key} onChange={(e) => setItem(i, { key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })} /></td>
              <td><input className="input" aria-label="Prüfpunkt" value={c.label} onChange={(e) => setItem(i, { label: e.target.value })} /></td>
              <td><input type="checkbox" aria-label="Pflicht" checked={c.required} onChange={(e) => setItem(i, { required: e.target.checked })} /></td>
              <td><input className="input" aria-label="Schlüsselwörter" placeholder="wo, adresse" value={c.hints} onChange={(e) => setItem(i, { hints: e.target.value })} /></td>
              <td><button type="button" className="btn ghost sm" aria-label="Entfernen" onClick={() => setForm((f) => ({ ...f, checklist: f.checklist.filter((_, j) => j !== i) }))}>✕</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <button type="button" className="btn sm" onClick={() => setForm((f) => ({ ...f, checklist: [...f.checklist, { key: '', label: '', required: true, hints: '' }] }))}>Prüfpunkt hinzufügen</button>
        <div className="spacer" />
        <button type="submit" className="btn primary" disabled={saving || !form.title.trim() || !form.opening_line.trim()}>Speichern</button>
      </div>
    </form>
  );
}
