/** Queue of police notices the current dispatcher has to acknowledge (information only). */
import { create } from 'zustand';
import type { PoliceNotice } from '@/api/types';

interface PoliceNoticeState {
  queue: PoliceNotice[];
  show(notice: PoliceNotice): void;
  done(id: string): void;
}

export const usePoliceNoticeQueue = create<PoliceNoticeState>((set) => ({
  queue: [],
  show: (notice) => set((s) => (s.queue.some((n) => n.id === notice.id) || notice.acknowledged_at ? s : { queue: [...s.queue, notice] })),
  done: (id) => set((s) => ({ queue: s.queue.filter((n) => n.id !== id) })),
}));
