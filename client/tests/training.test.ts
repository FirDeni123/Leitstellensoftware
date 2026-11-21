import { describe, expect, it } from 'vitest';
import { keysForTopic } from '@/api/queries';
import { handleTrainingEvent, reduceChunk, useTrainingLive } from '@/modules/training/live';
import { toBody } from '@/modules/training/ScenariosPanel';
import { seconds } from '@/modules/training/components';

const chunk = (data: Record<string, unknown>, topic = 'training.caller_chunk') => ({ id: 'e', ts: '', topic, data });

describe('streamed caller replies', () => {
  it('collects sentences of one reply and restarts with a new reply', () => {
    let state = { streaming: {} };
    state = reduceChunk(state, { session_id: 's', reply_id: 'r1', seq: 0, text: 'Hallo.' });
    state = reduceChunk(state, { session_id: 's', reply_id: 'r1', seq: 1, text: 'Bitte kommen Sie!' });
    expect(state.streaming['s' as keyof typeof state.streaming]).toEqual({ replyId: 'r1', parts: ['Hallo.', 'Bitte kommen Sie!'], finalId: null });
    state = reduceChunk(state, { session_id: 's', reply_id: 'r2', seq: 0, text: 'Neu.' });
    expect((state.streaming as Record<string, { parts: string[] }>)['s']!.parts).toEqual(['Neu.']);
  });

  it('a retracted reply disappears, other replies are untouched', () => {
    let state = reduceChunk({ streaming: {} }, { session_id: 's', reply_id: 'r1', seq: 0, text: 'Teil' });
    expect(reduceChunk(state, { session_id: 's', reply_id: 'other', retract: true })).toBe(state);
    state = reduceChunk(state, { session_id: 's', reply_id: 'r1', retract: true });
    expect((state.streaming as Record<string, unknown>)['s']).toBeUndefined();
  });

  it('duplicate chunks (trainee + instructor copy) are applied once; the stored message closes the bubble', () => {
    useTrainingLive.setState({ streaming: {} });
    const data = { session_id: 'x', reply_id: 'dup', seq: 0, text: 'Einmal.' };
    handleTrainingEvent(chunk(data));
    handleTrainingEvent(chunk(data));
    expect(useTrainingLive.getState().streaming['x']!.parts).toEqual(['Einmal.']);
    handleTrainingEvent(chunk({ session_id: 'x', reply_id: 'dup', role: 'caller', id: 42 }, 'training.message'));
    expect(useTrainingLive.getState().streaming['x']!.finalId).toBe(42);
  });

  it('training events refresh the right queries', () => {
    expect(keysForTopic('training.message')).toEqual([['training-session']]);
    expect(keysForTopic('training.session_changed')).toContainEqual(['training-sessions']);
  });
});

describe('scenario editor', () => {
  it('builds the API body: blanks become null, lists split, numbers parsed', () => {
    const body = toBody({
      title: ' Test ', description: '', difficulty: 'hard', keyword_id: '', global: false, is_active: true,
      persona: { name: 'Anna', age: '41', role: '', emotional_state: '', speech_style: '', phone: '' },
      facts: { address: 'Weg 1', lat: '53,5', lon: '10.25', location_hint: '', situation: 'Rauch', persons: '', injuries: '', hazards: '', details: 'a\n\n b ', unknown: '' },
      opening_line: 'Hilfe!',
      checklist: [{ key: 'ask_x', label: 'X', required: false, hints: 'wo, adresse ,' }, { key: '', label: '', required: true, hints: '' }],
    });
    expect(body).toMatchObject({
      title: 'Test', description: null, keyword_id: null,
      persona: { name: 'Anna', age: 41, role: null, phone: null },
      facts: { address: 'Weg 1', lat: 53.5, lon: 10.25, details: ['a', 'b'], unknown: [] },
      checklist: [{ key: 'ask_x', label: 'X', required: false, hints: ['wo', 'adresse'] }],
    });
  });

  it('formats latencies', () => {
    expect(seconds(1234)).toBe('1,2 s');
    expect(seconds(null)).toBe('–');
  });
});
