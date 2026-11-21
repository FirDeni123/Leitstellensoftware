/** Helpers for plugin configuration forms generated from a (small) JSON Schema subset. */
import type { JsonObjectSchema, JsonSchemaProperty } from '@/api/types';

/** Convert the raw input of one field to the JSON value the server expects ('' = not set). */
export function coerceValue(prop: JsonSchemaProperty, raw: string | boolean): unknown {
  if (prop.type === 'boolean') return Boolean(raw);
  if (typeof raw !== 'string' || raw.trim() === '') return undefined;
  if (prop.type === 'integer' || prop.type === 'number') {
    const n = Number(raw.replace(',', '.'));
    if (Number.isNaN(n)) return raw; // the server reports the error
    return prop.type === 'integer' ? Math.trunc(n) : n;
  }
  return raw.trim();
}

/** Apply one field change to a configuration object (removes unset values). */
export function setConfigValue(config: Record<string, unknown>, key: string, value: unknown): Record<string, unknown> {
  const next = { ...config };
  if (value === undefined) delete next[key];
  else next[key] = value;
  return next;
}

/** Labels of required fields that are still empty. */
export function missingRequired(schema: JsonObjectSchema, config: Record<string, unknown>): string[] {
  return (schema.required ?? []).filter((k) => config[k] === undefined || config[k] === '').map((k) => schema.properties?.[k]?.title ?? k);
}

/** Client-side pre-check (pattern, range); the server validates authoritatively. */
export function fieldError(prop: JsonSchemaProperty, value: unknown): string | null {
  if (value === undefined) return null;
  if ((prop.type === 'integer' || prop.type === 'number') && typeof value !== 'number') return 'Zahl erwartet';
  if (typeof value === 'number') {
    if (prop.minimum !== undefined && value < prop.minimum) return `mindestens ${prop.minimum}`;
    if (prop.maximum !== undefined && value > prop.maximum) return `höchstens ${prop.maximum}`;
  }
  if (typeof value === 'string' && prop.pattern && !new RegExp(prop.pattern).test(value)) {
    return prop.pattern === '^https://' ? 'muss mit https:// beginnen' : 'ungültiges Format';
  }
  return null;
}
