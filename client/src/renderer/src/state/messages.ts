/** System messages (Systemmeldungen): connection changes, server notices, errors. */
import { create } from 'zustand';

export type MessageLevel = 'info' | 'success' | 'warning' | 'error';

export interface SystemMessage {
  id: number;
  ts: Date;
  level: MessageLevel;
  source: string;
  text: string;
}

const MAX_MESSAGES = 500;
let nextId = 1;

interface MessagesState {
  messages: SystemMessage[];
  unread: number;
  push(level: MessageLevel, source: string, text: string): void;
  markRead(): void;
  clear(): void;
}

export const useMessages = create<MessagesState>((set) => ({
  messages: [],
  unread: 0,
  push: (level, source, text) =>
    set((s) => ({
      messages: [{ id: nextId++, ts: new Date(), level, source, text }, ...s.messages].slice(0, MAX_MESSAGES),
      unread: s.unread + 1,
    })),
  markRead: () => set({ unread: 0 }),
  clear: () => set({ messages: [], unread: 0 }),
}));

export const sysmsg = (level: MessageLevel, source: string, text: string): void =>
  useMessages.getState().push(level, source, text);
