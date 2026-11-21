/**
 * Acoustic and visual signal for incoming emergency calls (simulated phone ring via
 * WebAudio – no audio files, no external resources). Muting is a per-workstation setting.
 */
import { create } from 'zustand';
import { sysmsg } from '@/state/messages';
import { hasPermission, onRealtimeEvent, useSession } from '@/state/session';

const STORAGE_KEY = 'ils-call-alert-muted';

function readMuted(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

export const useCallAlert = create<{ muted: boolean; toggle: () => void }>((set, get) => ({
  muted: readMuted(),
  toggle: () => {
    const muted = !get().muted;
    try {
      window.localStorage.setItem(STORAGE_KEY, muted ? '1' : '0');
    } catch {
      /* convenience only */
    }
    set({ muted });
  },
}));

let ctx: AudioContext | null = null;

export function ring(): void {
  try {
    ctx ??= new AudioContext();
    const t0 = ctx.currentTime;
    // two short double tones, similar to a desk phone
    for (const start of [0, 0.25, 0.9, 1.15]) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 880;
      osc.type = 'sine';
      gain.gain.setValueAtTime(0.0001, t0 + start);
      gain.gain.exponentialRampToValueAtTime(0.18, t0 + start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + start + 0.2);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t0 + start);
      osc.stop(t0 + start + 0.22);
    }
  } catch {
    /* audio unavailable (e.g. no output device) – the visual signal remains */
  }
}

export function installCallAlert(): () => void {
  return onRealtimeEvent((event) => {
    if (event.topic !== 'call.changed' || event.data['action'] !== 'ringing') return;
    if (!hasPermission(useSession.getState().me, 'calls.handle')) return;
    sysmsg('warning', 'Notruf', 'Neuer Notruf in der Warteschlange');
    if (!useCallAlert.getState().muted) ring();
  });
}
