/** Typed data structures of the server API (mirror of server/app/schemas). */

export type Uuid = string;

export interface ControlCenterRef {
  id: Uuid;
  code: string;
  name: string;
}

export interface Me {
  id: Uuid;
  username: string;
  display_name: string;
  email: string | null;
  must_change_password: boolean;
  roles: string[];
  permissions: string[];
  control_centers: ControlCenterRef[];
  all_control_centers: boolean;
  session_id: Uuid;
}

export interface TokenResponse {
  access_token: string;
  access_token_expires_at: string;
  refresh_token: string;
  token_type: 'bearer';
  user: Me;
}

export interface PermissionOverride {
  permission_code: string;
  effect: 'grant' | 'deny';
}

export interface User {
  id: Uuid;
  username: string;
  display_name: string;
  email: string | null;
  is_active: boolean;
  must_change_password: boolean;
  locked_until: string | null;
  last_login_at: string | null;
  roles: string[];
  control_centers: ControlCenterRef[];
  permission_overrides: PermissionOverride[];
  effective_permissions: string[];
  created_at: string;
  updated_at: string;
  version: number;
}

export interface UserCreatedResponse {
  user: User;
  initial_password: string | null;
}

export interface Role {
  id: Uuid;
  key: string;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: string[];
  version: number;
}

export interface Permission {
  code: string;
  area: string;
  description: string;
}

export interface ControlCenter {
  id: Uuid;
  code: string;
  name: string;
  description: string | null;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export type ModuleState = 'available' | 'partial' | 'planned';

export interface ModuleStatus {
  key: string;
  name: string;
  phase: number;
  status: ModuleState;
  note: string | null;
}

export type OperationMode = 'simulation' | 'real';

export interface SystemInfo {
  product: string;
  version: string;
  environment: string;
  server_time: string;
  operation_mode: OperationMode;
  realtime_backend: 'memory' | 'redis';
  modules: ModuleStatus[];
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor_user_id: Uuid | null;
  actor_name: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  control_center_id: Uuid | null;
  summary: string;
  changes: Record<string, { old: unknown; new: unknown }> | null;
  request_id: string | null;
}

export interface AuditPage {
  items: AuditEntry[];
  next_before_id: number | null;
}

export interface LayoutDoc {
  workstation: string;
  layout: Record<string, unknown>;
  version: number;
  updated_at: string;
}

export interface LoginEvent {
  id: number;
  ts: string;
  username: string;
  success: boolean;
  event: string;
  reason: string | null;
  ip_address: string | null;
  client_name: string | null;
  workstation: string | null;
}

// ------------------------------------------------------------------ Phase 2: master data
export type OrganizationKind = 'fire' | 'ems' | 'civil_protection' | 'technical_relief' | 'aid' | 'police' | 'other';

export interface Versioned {
  id: Uuid;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface OrganizationRef {
  id: Uuid;
  key: string;
  name: string;
  kind: OrganizationKind;
  color: string | null;
  alarmable: boolean;
}

export interface Organization extends OrganizationRef, Versioned {
  description: string | null;
  is_active: boolean;
}

export interface VehicleTypeRef {
  id: Uuid;
  code: string;
  name: string;
  category: OrganizationKind;
}

export interface VehicleType extends VehicleTypeRef, Versioned {
  default_speed_kmh: number;
  default_crew: number | null;
  capabilities: string[];
  description: string | null;
  is_active: boolean;
}

export interface StatusDefinition {
  code: number;
  label: string;
  short_label: string;
  color: string;
  counts_as_available: boolean;
  description: string | null;
  version: number;
}

export interface RicRef {
  id: Uuid;
  code: string;
  sub_address: string;
  label: string;
}

export interface StationRef {
  id: Uuid;
  name: string;
  short_name: string | null;
}

export interface Availability {
  mode: 'always' | 'schedule' | 'unavailable';
  schedule: { days: number[]; start: string; end: string }[];
  note?: string | null;
}

export interface Station extends StationRef, Versioned {
  control_center_id: Uuid;
  organization: OrganizationRef;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  phone: string | null;
  availability: Availability;
  description: string | null;
  osm_ref: string | null;
  is_active: boolean;
  rics: RicRef[];
}

export interface RadioGroupRef {
  id: Uuid;
  name: string;
  talkgroup: string | null;
}

export interface Vehicle extends Versioned {
  control_center_id: Uuid;
  call_sign: string;
  license_plate: string | null;
  station: StationRef;
  vehicle_type: VehicleTypeRef;
  organization: OrganizationRef;
  radio_group: RadioGroupRef | null;
  rics: RicRef[];
  status_code: number;
  status_changed_at: string | null;
  position: { latitude: number | null; longitude: number | null; source: string };
  available: boolean;
  availability_note: string | null;
  crew_size: number | null;
  description: string | null;
  sim_speed_kmh: number | null;
  effective_speed_kmh: number;
  import_job_id: Uuid | null;
}

export interface Ric extends RicRef, Versioned {
  control_center_id: Uuid;
  description: string | null;
  is_active: boolean;
  stations: StationRef[];
  vehicles: { id: Uuid; call_sign: string }[];
}

export interface AlarmGroup extends Versioned {
  control_center_id: Uuid;
  name: string;
  description: string | null;
  rics: RicRef[];
}

export interface RadioGroup extends RadioGroupRef, Versioned {
  control_center_id: Uuid;
  description: string | null;
  stations: StationRef[];
  organizations: OrganizationRef[];
  vehicles: { id: Uuid; call_sign: string }[];
}

export interface ControlCenterArea extends Versioned {
  control_center_id: Uuid;
  name: string;
  municipality_key: string | null;
  geometry: { type: string; coordinates: unknown } | null;
  priority: number;
  description: string | null;
}

export interface ControlCenterLink {
  id: Uuid;
  from_control_center: ControlCenterRef;
  to_control_center: ControlCenterRef;
  kind: 'neighbor' | 'backup' | 'cooperation';
  note: string | null;
  created_at: string;
}

// ------------------------------------------------------------------ Phase 2: import
export type ImportKind = 'vehicles' | 'stations';
export type ImportAction = 'create' | 'update' | 'unchanged' | 'error' | 'skip';

export interface ImportRowResult {
  row: number;
  action: ImportAction;
  values: Record<string, string>;
  errors: string[];
  warnings: string[];
  changes: string[];
}

export interface ImportJob {
  id: Uuid;
  control_center_id: Uuid;
  kind: ImportKind;
  status: 'uploaded' | 'validated' | 'committed' | 'discarded';
  file_name: string;
  sheet_name: string | null;
  row_count: number;
  summary: Record<ImportAction | 'total', number> | null;
  created_at: string;
  committed_at: string | null;
  version: number;
  headers: string[];
  sample_rows: string[][];
  sheets: string[];
  fields: { key: string; label: string; required: boolean; hint: string }[];
  column_mapping: Record<string, number | null> | null;
  options: { update_existing?: boolean };
  validation: ImportRowResult[] | null;
}

export type ImportJobSummary = Omit<ImportJob, 'headers' | 'sample_rows' | 'sheets' | 'fields' | 'column_mapping' | 'options' | 'validation'>;

// ------------------------------------------------------------------ Phase 3: operations
export type IncidentStatus = 'new' | 'in_progress' | 'alarmed' | 'en_route' | 'on_scene' | 'finished' | 'closed';
export type IncidentType = 'fire' | 'technical' | 'ems' | 'hazmat' | 'water' | 'other';
export type CallStatus = 'ringing' | 'active' | 'on_hold' | 'ended';

export interface KeywordRef {
  id: Uuid;
  code: string;
  name: string;
  category: IncidentType;
}

export interface Keyword extends KeywordRef, Versioned {
  default_priority: number;
  description: string | null;
  is_active: boolean;
  police_notice: boolean;
  police_notice_text: string | null;
}

export interface CallNote {
  id: number;
  kind: 'note' | 'question';
  question: string | null;
  text: string;
  author_name: string;
  ts: string;
}

export interface Call {
  id: Uuid;
  control_center_id: Uuid;
  status: CallStatus;
  priority: number;
  source: 'sim' | 'manual' | 'voip' | 'training';
  line: string | null;
  caller_name: string | null;
  caller_phone: string | null;
  caller_location: string | null;
  caller_latitude: number | null;
  caller_longitude: number | null;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  reason: string | null;
  sim_transcript: string | null;
  incident: { id: Uuid; number: string; status: IncidentStatus } | null;
  handled_by: Uuid | null;
  handled_by_name: string | null;
  received_at: string;
  answered_at: string | null;
  ended_at: string | null;
  notes: CallNote[];
  version: number;
}

export interface IncidentSummary {
  id: Uuid;
  control_center_id: Uuid;
  number: string;
  keyword: KeywordRef | null;
  incident_type: IncidentType;
  status: IncidentStatus;
  priority: number;
  address: string | null;
  created_at: string;
  status_changed_at: string;
  vehicles: string[];
  version: number;
}

export interface Assignment {
  id: number;
  vehicle: { id: Uuid; call_sign: string; vehicle_type: string; station: string };
  assigned_at: string;
  alarmed_at: string | null;
  s3_at: string | null;
  s4_at: string | null;
  released_at: string | null;
  released_reason: string | null;
}

export interface Incident extends IncidentSummary {
  year: number;
  sequence: number;
  location_note: string | null;
  latitude: number | null;
  longitude: number | null;
  caller_name: string | null;
  caller_phone: string | null;
  description: string | null;
  source: string;
  updated_at: string;
  finished_at: string | null;
  closed_at: string | null;
  assignments: Assignment[];
  stations: StationRef[];
  calls: { id: Uuid; status: CallStatus; caller_name: string | null; caller_phone: string | null; received_at: string }[];
}

export interface IncidentEvent {
  id: number;
  ts: string;
  kind: string;
  text: string;
  data: Record<string, unknown> | null;
  actor_name: string;
}

export interface ActiveAssignment {
  vehicle_id: Uuid;
  incident_id: Uuid;
  incident_number: string;
  assigned_at: string;
}

export interface CallScenario {
  key: string;
  title: string;
  expected_keyword: string;
}

// ---------------------------------------------------------------------------- Phase 4: alarming
export type RuleItemKind = 'vehicle_type' | 'vehicle' | 'station' | 'ric' | 'alarm_group' | 'interface';

export interface AlarmRuleItem {
  id?: number;
  stage: number;
  kind: RuleItemKind;
  count: number;
  target_id: Uuid;
  target_label?: string;
  note: string | null;
}

export interface AlarmRule extends Versioned {
  control_center_id: Uuid;
  keyword: KeywordRef;
  area: { id: Uuid; name: string } | null;
  name: string | null;
  is_active: boolean;
  items: Required<AlarmRuleItem>[];
  max_stage: number;
}

export interface AlarmSelection {
  vehicle_ids: Uuid[];
  station_ids: Uuid[];
  ric_ids: Uuid[];
  interface_ids: Uuid[];
}

export interface PreviewTarget {
  id: Uuid;
  label: string;
  reason: string;
}

export interface AlarmPreview {
  incident_id: Uuid;
  incident_number: string;
  incident_version: number;
  keyword: KeywordRef | null;
  rule: { id: Uuid; name: string | null; area: string | null } | null;
  stage: number | null;
  max_stage: number;
  next_kind: 'initial' | 'follow_up';
  mode: OperationMode;
  vehicles: {
    id: Uuid; call_sign: string; vehicle_type: string; station_id: Uuid; station: string; status_code: number;
    distance_km: number | null; travel_seconds: number | null; travel_source: TravelSource | null; reason: string; assigned: boolean;
  }[];
  stations: PreviewTarget[];
  rics: PreviewTarget[];
  interfaces: { id: Uuid; name: string; plugin_name: string; is_real: boolean; effect: 'deliver' | 'simulate' | 'redirect' | 'skip'; reason: string }[];
  already_alarmed: string[];
  police_notice: string | null;
  warnings: string[];
  selection: AlarmSelection;
}

export type DeliveryStatus = 'simulated' | 'sent' | 'failed' | 'skipped' | 'not_delivered' | 'pending';

export interface AlarmTarget {
  id: number;
  target_type: 'vehicle' | 'station' | 'ric' | 'interface';
  target_id: string;
  label: string;
  reason: string | null;
  delivery_status: DeliveryStatus;
  detail: string | null;
  delivered_at: string | null;
}

export interface PoliceNotice {
  id: Uuid;
  incident_id: Uuid;
  incident_number: string;
  control_center_id: Uuid;
  keyword_code: string;
  text: string;
  created_at: string;
  acknowledged_at: string | null;
  acknowledged_by_name: string | null;
  note: string | null;
}

export interface Alarm {
  id: Uuid;
  incident_id: Uuid;
  incident_number: string;
  control_center_id: Uuid;
  kind: 'initial' | 'follow_up' | 'manual';
  stage: number | null;
  mode: OperationMode;
  status: 'pending' | 'completed' | 'partial';
  note: string | null;
  triggered_by_name: string;
  created_at: string;
  targets: AlarmTarget[];
  replayed: boolean;
  police_notice: PoliceNotice | null;
}

/** Subset of JSON Schema used by plugin configuration forms. */
export interface JsonSchemaProperty {
  type?: 'string' | 'integer' | 'number' | 'boolean';
  title?: string;
  description?: string;
  enum?: (string | number)[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  maxLength?: number;
  pattern?: string;
  format?: string;
}

export interface JsonObjectSchema {
  type: 'object';
  required?: string[];
  properties?: Record<string, JsonSchemaProperty>;
  additionalProperties?: boolean;
}

export type InterfaceScope = 'global' | 'control_center' | 'station';

export interface PluginInfo {
  key: string;
  name: string;
  description: string;
  is_real: boolean;
  scopes: InterfaceScope[];
  config_schema: JsonObjectSchema;
  secret_label: string | null;
  secret_required: boolean;
  capabilities: string[];
}

export interface InterfaceItem extends Versioned {
  plugin_key: string;
  plugin_name: string;
  is_real: boolean;
  name: string;
  scope: InterfaceScope;
  control_center_id: Uuid | null;
  station_id: Uuid | null;
  station_name: string | null;
  enabled: boolean;
  effective: boolean;
  config: Record<string, unknown>;
  has_secret: boolean;
  secret_hint: string | null;
  status: 'unknown' | 'ok' | 'error';
  last_ok_at: string | null;
  last_error: string | null;
  last_checked_at: string | null;
}

export interface InterfaceEventItem {
  id: number;
  ts: string;
  level: 'info' | 'warning' | 'error';
  kind: string;
  message: string;
}

// ---------------------------------------------------------------------- Phase 5: proposal
export type TravelSource = 'osrm' | 'estimate' | 'none';

export interface ProposalPick {
  demand_key: string;
  vehicle_id: Uuid;
  call_sign: string;
  vehicle_type: string;
  station_id: Uuid;
  station: string;
  status_code: number;
  slot: number;
  match: 'exact' | 'substitute' | 'vehicle' | 'covered';
  score_seconds: number | null;
  travel_seconds: number | null;
  distance_m: number | null;
  travel_source: TravelSource;
  in_incident: boolean;
  alarmed: boolean;
  reasons: string[];
}

export interface ProposalOption {
  vehicle_id: Uuid;
  call_sign: string;
  vehicle_type: string;
  station: string;
  status_code: number;
  match: string;
  score_seconds: number;
  travel_seconds: number | null;
  reason: string;
}

export interface Proposal {
  id: Uuid;
  incident_id: Uuid;
  control_center_id: Uuid;
  computed_at: string;
  computed_by_name: string;
  duration_ms: number;
  rule: { id: Uuid; name: string | null; area: string | null } | null;
  stage: number | null;
  max_stage: number;
  next_kind: 'initial' | 'follow_up';
  travel_source: TravelSource | 'mixed';
  demands: { key: string; label: string; source: string; count: number; stage: number | null; covered: number }[];
  picks: ProposalPick[];
  alternatives: Record<string, ProposalOption[]>;
  shortfalls: { demand_key: string; label: string; missing: number; message: string }[];
  warnings: string[];
  candidates: number;
  accepted_vehicle_ids: Uuid[] | null;
  accepted_at: string | null;
  accepted_by_name: string | null;
}

export interface ProposalSettingsData {
  detour_factor: number;
  emergency_speed_factor: number;
  turnout_seconds_on_station: number;
  substitute_penalty_seconds: number;
  preferred_station_bonus_seconds: number;
  max_travel_minutes: number;
  alternatives: number;
  candidates_per_demand: number;
  use_routing: boolean;
  substitutes: Record<string, string[]>;
}

export interface ProposalSettings {
  control_center_id: Uuid;
  settings: ProposalSettingsData;
  defaults: ProposalSettingsData;
  is_default: boolean;
  version: number | null;
  updated_at: string | null;
  updated_by_name: string | null;
  routing_configured: boolean;
}
