/** Entity configurations for the generic master data panel (one per master data type). */
import type { ReactNode } from 'react';
import type {
  AlarmGroup,
  ControlCenterArea,
  Keyword,
  Organization,
  OrganizationKind,
  RadioGroup,
  Ric,
  Station,
  StatusDefinition,
  Vehicle,
  VehicleType,
} from '@/api/types';
import type { Option } from '@/components/MultiSelect';
import type { EntityConfig, SourceDef } from '../crud/types';

export const KIND_LABEL: Record<OrganizationKind, string> = {
  fire: 'Feuerwehr',
  ems: 'Rettungsdienst',
  civil_protection: 'Katastrophenschutz',
  technical_relief: 'Technische Hilfe (THW)',
  aid: 'Hilfsorganisation',
  police: 'Polizei (nur Information)',
  other: 'Sonstige',
};
const KIND_OPTIONS: Option[] = Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }));

const SOURCES = {
  organizations: { collection: 'organizations', path: '/organizations', scoped: false, label: (o: Organization) => o.name, hint: (o: Organization) => o.key } satisfies SourceDef,
  alarmableOrganizations: { collection: 'organizations', path: '/organizations', scoped: false, label: (o: Organization) => (o.alarmable ? o.name : `${o.name} – nicht disponierbar`) } satisfies SourceDef,
  vehicleTypes: { collection: 'vehicle-types', path: '/vehicle-types', scoped: false, label: (t: VehicleType) => `${t.code} – ${t.name}` } satisfies SourceDef,
  stations: { collection: 'stations', path: '/stations', scoped: true, label: (s: Station) => s.name, hint: (s: Station) => s.short_name ?? '' } satisfies SourceDef,
  radioGroups: { collection: 'radio-groups', path: '/radio-groups', scoped: true, label: (g: RadioGroup) => (g.talkgroup ? `${g.name} (${g.talkgroup})` : g.name) } satisfies SourceDef,
  rics: { collection: 'rics', path: '/rics', scoped: true, label: (r: Ric) => `${r.code}${r.sub_address} – ${r.label}` } satisfies SourceDef,
  vehicles: { collection: 'vehicles', path: '/vehicles', scoped: true, label: (v: Vehicle) => v.call_sign, hint: (v: Vehicle) => v.vehicle_type.code } satisfies SourceDef,
};

const ricLabel = (r: { code: string; sub_address: string }) => `${r.code}${r.sub_address}`;
const ids = (items: { id: string }[]) => items.map((x) => x.id);

function Swatch({ color }: { color: string | null }): ReactNode {
  return <span className="swatch" style={{ background: color ?? 'transparent' }} />;
}

function ActiveBadge({ active }: { active: boolean }): ReactNode {
  return active ? <span className="badge ok">Aktiv</span> : <span className="badge">Inaktiv</span>;
}

function RefList({ title, items }: { title: string; items: string[] }): ReactNode {
  return (
    <>
      <div className="section-title">{title} ({items.length})</div>
      <div className="chips">{items.length ? items.map((x) => <span key={x} className="badge">{x}</span>) : <span className="muted">keine</span>}</div>
    </>
  );
}

// ------------------------------------------------------------------------------ global catalogues
export const ORGANIZATIONS: EntityConfig<Organization> = {
  collection: 'organizations', path: '/organizations', singular: 'Organisation', plural: 'Organisationen', scoped: false,
  writePermission: 'organizations.write', title: (o) => o.name, inactive: (o) => !o.is_active,
  columns: [
    { header: '', width: 24, render: (o) => <Swatch color={o.color} /> },
    { header: 'Name', render: (o) => o.name },
    { header: 'Art', render: (o) => KIND_LABEL[o.kind] },
    { header: 'Alarmierbar', width: 110, render: (o) => (o.alarmable ? <span className="badge ok">Ja</span> : <span className="badge warn">Nein</span>) },
  ],
  fields: [
    { key: 'key', label: 'Schlüssel', type: 'text', required: true, createOnly: true, placeholder: 'z. B. drk', transform: (v) => v.toLowerCase() },
    { key: 'name', label: 'Name', type: 'text', required: true },
    { key: 'kind', label: 'Art', type: 'select', required: true, options: KIND_OPTIONS },
    { key: 'color', label: 'Farbe', type: 'color' },
    { key: 'alarmable', label: 'Alarmierbar', type: 'checkbox', defaultValue: true, disabledWhen: (f) => f['kind'] === 'police',
      hint: 'Die Polizei ist nie alarmierbar – sie erhält nur einen Informationshinweis.' },
    { key: 'is_active', label: 'Aktiv', type: 'checkbox', defaultValue: true },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ],
};

export const VEHICLE_TYPES: EntityConfig<VehicleType> = {
  collection: 'vehicle-types', path: '/vehicle-types', singular: 'Fahrzeugtyp', plural: 'Fahrzeugtypen', scoped: false,
  writePermission: 'organizations.write', title: (t) => t.code, inactive: (t) => !t.is_active,
  columns: [
    { header: 'Kürzel', width: 110, className: 'mono', render: (t) => t.code },
    { header: 'Bezeichnung', render: (t) => t.name },
    { header: 'Bereich', render: (t) => KIND_LABEL[t.category] },
    { header: 'km/h', width: 60, className: 'tabular', render: (t) => t.default_speed_kmh },
  ],
  fields: [
    { key: 'code', label: 'Kürzel', type: 'text', required: true, createOnly: true, placeholder: 'HLF20', transform: (v) => v.toUpperCase() },
    { key: 'name', label: 'Bezeichnung', type: 'text', required: true },
    { key: 'category', label: 'Bereich', type: 'select', required: true, options: KIND_OPTIONS },
    { key: 'default_speed_kmh', label: 'Ø Geschwindigkeit (km/h)', type: 'number', min: 5, max: 300, defaultValue: '60', hint: 'Grundwert für die Fahrzeitschätzung und Simulation' },
    { key: 'default_crew', label: 'Regelbesatzung', type: 'number', min: 0, max: 99 },
    { key: 'is_active', label: 'Aktiv', type: 'checkbox', defaultValue: true },
    { key: 'capabilities', label: 'Fähigkeiten', type: 'multiselect',
      options: ['water', 'extinguish', 'rescue_equipment', 'heavy_rescue', 'ladder', 'hazmat', 'logistics', 'transport', 'command',
        'ems', 'patient_transport', 'emergency_physician', 'intensive_care', 'air', 'ems_mass_casualty'].map((c) => ({ value: c, label: c })),
      hint: 'Wird ab Phase 5 für den Einsatzmittelvorschlag genutzt' },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ],
};

export const STATUS_DEFINITIONS: EntityConfig<StatusDefinition> = {
  collection: 'vehicle-status', path: '/vehicle-status-definitions', singular: 'Status', plural: 'Statusbezeichnungen', scoped: false,
  writePermission: 'vehicles.write', title: (d) => `Status ${d.code}`, idOf: (d) => String(d.code), canCreate: false, canDelete: false,
  columns: [
    { header: 'Status', width: 70, render: (d) => <span className="fms" style={{ background: d.color }}>{d.code}</span> },
    { header: 'Bezeichnung', render: (d) => d.label },
    { header: 'Kurz', render: (d) => d.short_label },
    { header: 'Verfügbar', width: 90, render: (d) => (d.counts_as_available ? <span className="badge ok">Ja</span> : <span className="badge">Nein</span>) },
  ],
  fields: [
    { key: 'label', label: 'Bezeichnung', type: 'text', required: true, full: true },
    { key: 'short_label', label: 'Kurzbezeichnung', type: 'text', required: true },
    { key: 'color', label: 'Farbe', type: 'color', required: true },
    { key: 'counts_as_available', label: 'Gilt als verfügbar (für den Einsatzmittelvorschlag)', type: 'checkbox' },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ],
};

// ------------------------------------------------------------------------- per control centre
export const STATIONS: EntityConfig<Station> = {
  collection: 'stations', path: '/stations', singular: 'Wache', plural: 'Wachen', scoped: true, writePermission: 'stations.write',
  title: (s) => s.name, inactive: (s) => !s.is_active, emptyHint: 'Wachen anlegen oder über „Datenimport“ einlesen.',
  columns: [
    { header: 'Name', render: (s) => s.name },
    { header: 'Kurz', width: 80, render: (s) => s.short_name ?? '' },
    { header: 'Organisation', render: (s) => <><Swatch color={s.organization.color} /> {s.organization.name}</> },
    { header: 'Standort', className: 'tabular muted', render: (s) => (s.latitude !== null ? `${s.latitude.toFixed(4)}, ${s.longitude?.toFixed(4)}` : '–') },
    { header: 'Status', width: 80, render: (s) => <ActiveBadge active={s.is_active} /> },
  ],
  fields: [
    { key: 'name', label: 'Name', type: 'text', required: true },
    { key: 'short_name', label: 'Kurzname', type: 'text' },
    { key: 'organization_id', label: 'Organisation', type: 'select', required: true, source: SOURCES.organizations, get: (s: Station) => s.organization.id },
    { key: 'phone', label: 'Telefon', type: 'text' },
    { key: 'address', label: 'Anschrift', type: 'text', full: true },
    { key: 'latitude', label: 'Breitengrad (GPS)', type: 'number', min: -90, max: 90, placeholder: '53,5036' },
    { key: 'longitude', label: 'Längengrad (GPS)', type: 'number', min: -180, max: 180, placeholder: '10,4806' },
    { key: 'availability', label: 'Verfügbarkeit', type: 'availability' },
    { key: 'ric_ids', label: 'RICs', type: 'multiselect', source: SOURCES.rics, get: (s: Station) => ids(s.rics) },
    { key: 'is_active', label: 'Aktiv', type: 'checkbox', defaultValue: true },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ],
  details: (s) => (
    <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>
      Schnittstellen dieser Wache (Feuerwehrsoftware, Zusatzalarmierung) werden mit Phase 4 konfigurierbar.
      {s.osm_ref && <> · OSM-Referenz {s.osm_ref}</>}
    </div>
  ),
};

export const VEHICLES: EntityConfig<Vehicle> = {
  collection: 'vehicles', path: '/vehicles', singular: 'Fahrzeug', plural: 'Fahrzeuge', scoped: true, writePermission: 'vehicles.write',
  title: (v) => v.call_sign, inactive: (v) => !v.available, emptyHint: 'Fahrzeuge anlegen oder über „Datenimport“ (Excel/CSV) einlesen.',
  searchText: (v) => [v.call_sign, v.license_plate, v.vehicle_type.code, v.vehicle_type.name, v.station.name, v.organization.name, v.radio_group?.name].join(' '),
  columns: [
    { header: 'Funkrufname', render: (v) => v.call_sign },
    { header: 'Typ', width: 80, className: 'mono', render: (v) => v.vehicle_type.code },
    { header: 'Wache', render: (v) => v.station.name },
    { header: 'Kennzeichen', className: 'mono', render: (v) => v.license_plate ?? '' },
    { header: 'Verfügbar', width: 90, render: (v) => (v.available ? <span className="badge ok">Ja</span> : <span className="badge warn">Nein</span>) },
  ],
  fields: [
    { key: 'call_sign', label: 'Funkrufname', type: 'text', required: true, placeholder: 'Florian Musterstadt 1/46-1' },
    { key: 'license_plate', label: 'Kennzeichen', type: 'text', transform: (v) => v.toUpperCase() },
    { key: 'vehicle_type_id', label: 'Fahrzeugtyp', type: 'select', required: true, source: SOURCES.vehicleTypes, get: (v: Vehicle) => v.vehicle_type.id },
    { key: 'station_id', label: 'Wache', type: 'select', required: true, source: SOURCES.stations, get: (v: Vehicle) => v.station.id },
    { key: 'organization_id', label: 'Organisation', type: 'select', source: SOURCES.alarmableOrganizations, get: (v: Vehicle) => v.organization.id, hint: 'leer = Organisation der Wache', omitWhenEmpty: true },
    { key: 'radio_group_id', label: 'Funkrufgruppe', type: 'select', source: SOURCES.radioGroups, get: (v: Vehicle) => v.radio_group?.id ?? '' },
    { key: 'crew_size', label: 'Besatzung', type: 'number', min: 0, max: 99 },
    { key: 'sim_speed_kmh', label: 'Simulationsgeschwindigkeit (km/h)', type: 'number', min: 5, max: 300, hint: 'leer = Wert des Fahrzeugtyps' },
    { key: 'ric_ids', label: 'RICs', type: 'multiselect', source: SOURCES.rics, get: (v: Vehicle) => ids(v.rics) },
    { key: 'available', label: 'Verfügbar (in Dienst)', type: 'checkbox', defaultValue: true },
    { key: 'availability_note', label: 'Hinweis zur Verfügbarkeit', type: 'text', full: true },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ],
  details: (v) => (
    <dl className="kv" style={{ marginTop: 6 }}>
      <dt>Aktueller Status</dt><dd>{v.status_code} <span className="muted">(Statuswechsel im Betrieb ab Phase 6)</span></dd>
      <dt>Position</dt><dd className="tabular">{v.position.latitude !== null ? `${v.position.latitude.toFixed(5)}, ${v.position.longitude?.toFixed(5)}` : '–'} <span className="muted">({v.position.source === 'station' ? 'Wache' : v.position.source})</span></dd>
      <dt>Geschwindigkeit</dt><dd>{v.effective_speed_kmh} km/h</dd>
      {v.import_job_id && <><dt>Herkunft</dt><dd>Datenimport</dd></>}
    </dl>
  ),
};

export const RICS: EntityConfig<Ric> = {
  collection: 'rics', path: '/rics', singular: 'RIC', plural: 'RICs', scoped: true, writePermission: 'rics.write',
  title: (r) => `${ricLabel(r)} ${r.label}`, inactive: (r) => !r.is_active,
  columns: [
    { header: 'RIC', width: 110, className: 'mono', render: (r) => ricLabel(r) },
    { header: 'Bezeichnung', render: (r) => r.label },
    { header: 'Wachen', render: (r) => r.stations.map((s) => s.name).join(', ') },
    { header: 'Fahrzeuge', width: 90, className: 'tabular', render: (r) => r.vehicles.length },
  ],
  fields: [
    { key: 'code', label: 'RIC (Ziffern)', type: 'text', required: true, placeholder: '1234567' },
    { key: 'sub_address', label: 'Subadresse', type: 'select', options: ['A', 'B', 'C', 'D'].map((x) => ({ value: x, label: x })), get: (r: Ric) => r.sub_address, emptyValue: '' },
    { key: 'label', label: 'Bezeichnung', type: 'text', required: true, full: true },
    { key: 'station_ids', label: 'Wachen', type: 'multiselect', source: SOURCES.stations, get: (r: Ric) => ids(r.stations) },
    { key: 'vehicle_ids', label: 'Fahrzeuge', type: 'multiselect', source: SOURCES.vehicles, get: (r: Ric) => ids(r.vehicles) },
    { key: 'is_active', label: 'Aktiv', type: 'checkbox', defaultValue: true },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ],
  details: () => <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>Zuordnung zu Einsatzstichworten und Alarmierungsketten folgt mit Phase 4.</div>,
};

export const ALARM_GROUPS: EntityConfig<AlarmGroup> = {
  collection: 'alarm-groups', path: '/alarm-groups', singular: 'Alarmierungsgruppe', plural: 'Alarmierungsgruppen', scoped: true,
  writePermission: 'rics.write', title: (g) => g.name,
  columns: [
    { header: 'Name', render: (g) => g.name },
    { header: 'RICs', render: (g) => g.rics.map(ricLabel).join(', ') },
  ],
  fields: [
    { key: 'name', label: 'Name', type: 'text', required: true, full: true },
    { key: 'ric_ids', label: 'RICs', type: 'multiselect', source: SOURCES.rics, get: (g: AlarmGroup) => ids(g.rics) },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ],
};

export const RADIO_GROUPS: EntityConfig<RadioGroup> = {
  collection: 'radio-groups', path: '/radio-groups', singular: 'Funkrufgruppe', plural: 'Funkrufgruppen', scoped: true,
  writePermission: 'radio_groups.write', title: (g) => g.name,
  columns: [
    { header: 'Name', render: (g) => g.name },
    { header: 'Kennung', width: 100, className: 'mono', render: (g) => g.talkgroup ?? '' },
    { header: 'Wachen', render: (g) => g.stations.map((s) => s.name).join(', ') },
    { header: 'Fahrzeuge', width: 90, className: 'tabular', render: (g) => g.vehicles.length },
  ],
  fields: [
    { key: 'name', label: 'Name', type: 'text', required: true },
    { key: 'talkgroup', label: 'Kennung (Talkgroup)', type: 'text' },
    { key: 'station_ids', label: 'Wachen', type: 'multiselect', source: SOURCES.stations, get: (g: RadioGroup) => ids(g.stations) },
    { key: 'organization_ids', label: 'Organisationen', type: 'multiselect', source: SOURCES.organizations, get: (g: RadioGroup) => ids(g.organizations) },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ],
  details: (g) => (
    <>
      <RefList title="Fahrzeuge in dieser Gruppe" items={g.vehicles.map((v) => v.call_sign)} />
      <div className="muted" style={{ fontSize: 'var(--fs-xs)', marginTop: 4 }}>Fahrzeuge werden in der Fahrzeugverwaltung einer Funkrufgruppe zugeordnet.</div>
    </>
  ),
};

export const AREAS: EntityConfig<ControlCenterArea> = {
  collection: 'control-center-areas', path: '/control-center-areas', singular: 'Zuständigkeitsbereich', plural: 'Zuständigkeitsbereiche',
  scoped: true, writePermission: 'control_centers.write', title: (a) => a.name,
  columns: [
    { header: 'Name', render: (a) => a.name },
    { header: 'Gemeindeschlüssel', className: 'mono', render: (a) => a.municipality_key ?? '' },
    { header: 'Geometrie', width: 100, render: (a) => (a.geometry ? <span className="badge info">Polygon</span> : <span className="muted">–</span>) },
    { header: 'Priorität', width: 80, className: 'tabular', render: (a) => a.priority },
  ],
  fields: [
    { key: 'name', label: 'Name', type: 'text', required: true },
    { key: 'municipality_key', label: 'Gemeindeschlüssel (AGS/ARS)', type: 'text', placeholder: '01053112' },
    { key: 'priority', label: 'Priorität', type: 'number', min: 0, max: 1000, defaultValue: '100', hint: 'kleiner = vorrangig bei Überschneidungen' },
    { key: 'geometry', label: 'Gebiet (GeoJSON Polygon/MultiPolygon)', type: 'geojson' },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
  ],
  details: () => <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>Gebiete auf der Karte zeichnen: ab Phase 6 (Kartenmodul).</div>,
};

// ------------------------------------------------------------------------------ keywords (phase 3)
const TYPE_OPTIONS: Option[] = Object.entries({ fire: 'Brand', technical: 'Technische Hilfe', ems: 'Rettungsdienst', hazmat: 'Gefahrstoff', water: 'Wasserrettung', other: 'Sonstiges' })
  .map(([value, label]) => ({ value, label }));

export const KEYWORDS: EntityConfig<Keyword> = {
  collection: 'keywords', path: '/keywords', singular: 'Einsatzstichwort', plural: 'Einsatzstichworte', scoped: false,
  writePermission: 'keywords.write', title: (k) => k.code, inactive: (k) => !k.is_active,
  columns: [
    { header: 'Stichwort', width: 100, render: (k) => <span className={`kw kw-${k.category}`}>{k.code}</span> },
    { header: 'Bezeichnung', render: (k) => k.name },
    { header: 'Einsatzart', render: (k) => TYPE_OPTIONS.find((o) => o.value === k.category)?.label ?? k.category },
    { header: 'Prio', width: 50, className: 'tabular', render: (k) => k.default_priority },
    { header: 'Polizei', width: 64, render: (k) => (k.police_notice ? <span className="badge police-badge" title={k.police_notice_text ?? ''}>Hinweis</span> : '') },
  ],
  fields: [
    { key: 'code', label: 'Kürzel', type: 'text', required: true, createOnly: true, placeholder: 'B2', transform: (v) => v.toUpperCase() },
    { key: 'name', label: 'Bezeichnung', type: 'text', required: true },
    { key: 'category', label: 'Einsatzart', type: 'select', required: true, options: TYPE_OPTIONS },
    { key: 'default_priority', label: 'Standardpriorität (1 = höchste)', type: 'number', min: 1, max: 3, defaultValue: '2', required: true },
    { key: 'is_active', label: 'Aktiv', type: 'checkbox', defaultValue: true },
    { key: 'description', label: 'Beschreibung', type: 'textarea' },
    { key: 'police_notice', label: 'Hinweis „Polizei informieren“ anzeigen (keine Alarmierung)', type: 'checkbox', defaultValue: false },
    { key: 'police_notice_text', label: 'Text des Polizei-Hinweises', type: 'textarea', placeholder: 'z. B. Verkehrsunfall – Polizei informieren (Unfallaufnahme)' },
  ],
  details: () => (
    <div className="muted" style={{ fontSize: 'var(--fs-xs)' }}>
      Die Alarmierungsregeln (AAO) je Leitstelle pflegen Sie im Fenster „Alarmierungsregeln (AAO)“.
      Der Polizei-Hinweis ist ein bestätigungspflichtiges Informationsfenster – das System alarmiert die Polizei nie.
    </div>
  ),
};
