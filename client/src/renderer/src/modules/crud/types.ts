import type { ReactNode } from 'react';
import type { Option } from '@/components/MultiSelect';

export type FieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'checkbox'
  | 'select'
  | 'multiselect'
  | 'color'
  | 'availability'
  | 'geojson';

/** Dynamic option source: another REST collection (e.g. stations of the active control centre). */
export interface SourceDef {
  collection: string;
  path: string;
  scoped: boolean;
  label: (item: any) => string; // eslint-disable-line @typescript-eslint/no-explicit-any
  hint?: (item: any) => string; // eslint-disable-line @typescript-eslint/no-explicit-any
  value?: (item: any) => string; // eslint-disable-line @typescript-eslint/no-explicit-any
}

export interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  required?: boolean;
  createOnly?: boolean;
  full?: boolean;
  hint?: string;
  placeholder?: string;
  options?: Option[];
  source?: SourceDef;
  /** Value for the form from a loaded record (default: record[key]). */
  get?: (item: any) => unknown; // eslint-disable-line @typescript-eslint/no-explicit-any
  defaultValue?: unknown;
  min?: number;
  max?: number;
  transform?: (value: string) => string;
  /** Value sent for an empty input (default null). */
  emptyValue?: unknown;
  /** Do not send the field at all when empty (keeps the server-side value / default). */
  omitWhenEmpty?: boolean;
  /** Disable the field depending on the current form values. */
  disabledWhen?: (form: Record<string, unknown>) => boolean;
}

export interface ColumnDef<T> {
  header: string;
  render: (item: T) => ReactNode;
  width?: number;
  className?: string;
  title?: (item: T) => string;
}

export interface EntityConfig<T> {
  collection: string;
  path: string;
  singular: string;
  plural: string;
  scoped: boolean;
  writePermission: string;
  columns: ColumnDef<T>[];
  fields: FieldDef[];
  title: (item: T) => string;
  idOf?: (item: T) => string;
  canCreate?: boolean;
  canDelete?: boolean;
  /** Read-only information shown below the form (e.g. assigned vehicles). */
  details?: (item: T) => ReactNode;
  inactive?: (item: T) => boolean;
  /** Text the search box matches against (default: all field values). */
  searchText?: (item: T) => string;
  emptyHint?: string;
}
