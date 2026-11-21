import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createInvalidationScheduler } from '@/api/queries';

describe('realtime invalidation scheduler', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('merges a burst of events into one refetch per key', async () => {
    const calls: string[] = [];
    const s = createInvalidationScheduler(async (key) => { calls.push(key.join('/')); }, 200);
    for (let i = 0; i < 20; i++) s.request(['fleet']);
    s.request(['incidents']);
    await vi.advanceTimersByTimeAsync(250);
    expect(calls.sort()).toEqual(['fleet', 'incidents']);
  });

  it('never runs two refetches of a key at once and catches up afterwards', async () => {
    let release!: () => void;
    let running = 0;
    let maxRunning = 0;
    let count = 0;
    const s = createInvalidationScheduler(() => {
      count++;
      running++;
      maxRunning = Math.max(maxRunning, running);
      return new Promise<void>((r) => { release = () => { running--; r(); }; });
    }, 100);
    s.request(['fleet']);
    await vi.advanceTimersByTimeAsync(150); // first refetch starts and hangs
    for (let i = 0; i < 10; i++) { s.request(['fleet']); await vi.advanceTimersByTimeAsync(50); } // events keep coming
    expect(count).toBe(1);
    release();
    await vi.advanceTimersByTimeAsync(150); // exactly one catch-up refetch
    expect(count).toBe(2);
    release();
    await vi.advanceTimersByTimeAsync(500);
    expect(count).toBe(2);
    expect(maxRunning).toBe(1);
  });
});
