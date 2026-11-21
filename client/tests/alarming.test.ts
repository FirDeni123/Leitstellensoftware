import { describe, expect, it } from 'vitest';
import type { JsonObjectSchema } from '@/api/types';
import { coerceValue, fieldError, missingRequired, setConfigValue } from '@/components/schemaFormLogic';
import { deliverySummary, hasTargets, newIdempotencyKey, toggle } from '@/modules/alarming/labels';
import { usePoliceNoticeQueue } from '@/modules/alarming/policeNotices';
import { keysForTopic } from '@/api/queries';

const WEBHOOK: JsonObjectSchema = {
  type: 'object',
  required: ['url'],
  properties: {
    url: { type: 'string', title: 'Ziel-URL', pattern: '^https://' },
    timeout_seconds: { type: 'integer', minimum: 1, maximum: 30 },
  },
};

describe('alarm selection helpers', () => {
  it('toggles ids and detects empty selections', () => {
    expect(toggle(['a', 'b'], 'a')).toEqual(['b']);
    expect(toggle(['a'], 'c')).toEqual(['a', 'c']);
    expect(hasTargets({ vehicle_ids: [], station_ids: [], ric_ids: [], interface_ids: [] })).toBe(false);
    expect(hasTargets({ vehicle_ids: [], station_ids: [], ric_ids: ['r'], interface_ids: [] })).toBe(true);
  });

  it('summarises delivery results', () => {
    const t = (delivery_status: 'simulated' | 'failed') => ({ id: 1, target_type: 'vehicle' as const, target_id: 'x', label: 'x', reason: null, delivery_status, detail: null, delivered_at: null });
    expect(deliverySummary({ targets: [t('simulated'), t('simulated'), t('failed')] })).toBe('2 simuliert · 1 fehlgeschlagen');
  });

  it('creates distinct idempotency keys', () => {
    const keys = new Set(Array.from({ length: 50 }, newIdempotencyKey));
    expect(keys.size).toBe(50);
    for (const k of keys) expect(k.length).toBeGreaterThanOrEqual(8);
  });
});

describe('police notice queue', () => {
  it('shows each open notice once and drops acknowledged ones', () => {
    const notice = { id: 'n1', incident_id: 'i', incident_number: '2026-000001', control_center_id: 'c', keyword_code: 'H2', text: 'Polizei informieren', created_at: '', acknowledged_at: null, acknowledged_by_name: null, note: null };
    const q = usePoliceNoticeQueue.getState();
    q.show(notice);
    q.show(notice);
    q.show({ ...notice, id: 'n2', acknowledged_at: '2026-01-01' });
    expect(usePoliceNoticeQueue.getState().queue.map((n) => n.id)).toEqual(['n1']);
    usePoliceNoticeQueue.getState().done('n1');
    expect(usePoliceNoticeQueue.getState().queue).toEqual([]);
  });
});

describe('plugin configuration forms', () => {
  it('coerces values per JSON schema type', () => {
    expect(coerceValue({ type: 'integer' }, '7')).toBe(7);
    expect(coerceValue({ type: 'number' }, '2,5')).toBe(2.5);
    expect(coerceValue({ type: 'string' }, '  ')).toBeUndefined();
    expect(coerceValue({ type: 'boolean' }, true)).toBe(true);
    expect(setConfigValue({ a: 1, b: 2 }, 'a', undefined)).toEqual({ b: 2 });
  });

  it('reports missing required fields and simple errors', () => {
    expect(missingRequired(WEBHOOK, {})).toEqual(['Ziel-URL']);
    expect(missingRequired(WEBHOOK, { url: 'https://x' })).toEqual([]);
    expect(fieldError(WEBHOOK.properties!['url']!, 'http://x')).toBe('muss mit https:// beginnen');
    expect(fieldError(WEBHOOK.properties!['timeout_seconds']!, 60)).toBe('höchstens 30');
    expect(fieldError(WEBHOOK.properties!['timeout_seconds']!, 'abc')).toBe('Zahl erwartet');
  });
});

describe('realtime invalidation for alarming', () => {
  it('maps alarm and police topics to their queries', () => {
    expect(keysForTopic('alarm.changed')).toContainEqual(['alarms']);
    expect(keysForTopic('police_notice.changed')).toContainEqual(['police-notices']);
    expect(keysForTopic('interface.changed')).toContainEqual(['interfaces']);
  });
});
