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
