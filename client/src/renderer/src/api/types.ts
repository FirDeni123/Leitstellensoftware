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
