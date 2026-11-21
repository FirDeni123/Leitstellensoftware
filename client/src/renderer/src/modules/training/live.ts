/**
 * Live side of training calls:
 * - caller replies arrive sentence by sentence (`training.caller_chunk`) and are shown at once,
 *   before the complete reply is stored;
 * - speech output with the voices of the operating system (Web Speech API, no cloud service);
 * - push-to-talk recording (MediaRecorder, microphone only while the key is held).
 */
import { create } from 'zustand';
import type { RealtimeEvent } from '@/api/realtime';
import { onRealtimeEvent } from '@/state/session';

export interface StreamingReply {
  replyId: string;
  parts: string[];
  /** id of the stored message once the reply is complete (bubble hides when it is shown) */
  finalId: number | null;
}

interface LiveState {
  streaming: Record<string, StreamingReply | undefined>;
}

export const useTrainingLive = create<LiveState>(() => ({ streaming: {} }));

const seen = new Set<string>(); // trainee and instructor copies of the same chunk arrive twice
const spoken = new Set<string>(); // session ids whose caller is spoken aloud on this workstation

export function reduceChunk(state: LiveState, data: Record<string, unknown>): LiveState {
  const sessionId = String(data['session_id']);
  const replyId = String(data['reply_id']);
  const current = state.streaming[sessionId];
  if (data['retract']) {
    if (current?.replyId !== replyId) return state;
    return { streaming: { ...state.streaming, [sessionId]: undefined } };
  }
  const text = String(data['text'] ?? '');
  const parts = current?.replyId === replyId ? [...current.parts, text] : [text];
  return { streaming: { ...state.streaming, [sessionId]: { replyId, parts, finalId: null } } };
}

export function handleTrainingEvent(event: RealtimeEvent): void {
  if (event.topic === 'training.caller_chunk') {
    const key = `${String(event.data['reply_id'])}:${String(event.data['seq'] ?? 'r')}:${event.data['retract'] ? 'x' : ''}`;
    if (seen.has(key)) return;
    seen.add(key);
    if (seen.size > 2000) seen.clear();
    useTrainingLive.setState((s) => reduceChunk(s, event.data));
    const sessionId = String(event.data['session_id']);
    if (event.data['retract']) speaker.stop();
    else if (spoken.has(sessionId)) speaker.say(String(event.data['text'] ?? ''));
  } else if (event.topic === 'training.message' && event.data['role'] === 'caller' && event.data['reply_id']) {
    const sessionId = String(event.data['session_id']);
    useTrainingLive.setState((s) => {
      const current = s.streaming[sessionId];
      if (!current || current.replyId !== event.data['reply_id']) return s;
      return { streaming: { ...s.streaming, [sessionId]: { ...current, finalId: Number(event.data['id']) } } };
    });
  }
}

export function installTrainingLive(): () => void {
  return onRealtimeEvent(handleTrainingEvent);
}

/** The trainee's own exercise is spoken; observers (instructors) read only. */
export function speakSession(sessionId: string | null): () => void {
  if (!sessionId) return () => undefined;
  spoken.add(sessionId);
  return () => {
    spoken.delete(sessionId);
    speaker.stop();
  };
}

// --------------------------------------------------------------------------- speech output
const TTS_KEY = 'ils.training.tts';

function readEnabled(): boolean {
  try {
    return localStorage.getItem(TTS_KEY) !== 'off';
  } catch {
    return true;
  }
}

export const useSpeechOutput = create<{ enabled: boolean; toggle(): void }>((set, get) => ({
  enabled: readEnabled(),
  toggle() {
    const enabled = !get().enabled;
    try {
      localStorage.setItem(TTS_KEY, enabled ? 'on' : 'off');
    } catch {
      /* private mode: setting not remembered */
    }
    if (!enabled) speaker.stop();
    set({ enabled });
  },
}));

export function speechOutputAvailable(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

function germanVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices();
  return voices.find((v) => v.lang === 'de-DE') ?? voices.find((v) => v.lang.startsWith('de')) ?? null;
}

export const speaker = {
  say(text: string): void {
    if (!text.trim() || !speechOutputAvailable() || !useSpeechOutput.getState().enabled) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'de-DE';
    utterance.rate = 1.05;
    const voice = germanVoice();
    if (voice) utterance.voice = voice;
    window.speechSynthesis.speak(utterance); // queued: sentences are spoken in order
  },
  stop(): void {
    if (speechOutputAvailable()) window.speechSynthesis.cancel();
  },
};

// ------------------------------------------------------------------------- push-to-talk
export interface Recording {
  stop(): Promise<Blob>;
  cancel(): void;
}

export function recordingAvailable(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined';
}

export async function startRecording(): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  const type = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : '';
  const recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (e) => {
    if (e.data.size) chunks.push(e.data);
  };
  const release = () => stream.getTracks().forEach((t) => t.stop());
  recorder.start();
  return {
    stop: () =>
      new Promise<Blob>((resolve) => {
        recorder.onstop = () => {
          release();
          resolve(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }));
        };
        recorder.stop();
      }),
    cancel: () => {
      recorder.onstop = release;
      if (recorder.state !== 'inactive') recorder.stop();
      else release();
    },
  };
}
