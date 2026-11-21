/**
 * Preload bridge – the only API the renderer gets from the desktop shell.
 * Keep it minimal: every function here is an attack surface.
 */
import { contextBridge, ipcRenderer } from 'electron';

const api = {
  isDesktop: true as const,
  config: {
    get: (): Promise<unknown> => ipcRenderer.invoke('config:get'),
    set: (patch: Record<string, string>): Promise<unknown> => ipcRenderer.invoke('config:set', patch),
  },
  appInfo: (): Promise<unknown> => ipcRenderer.invoke('app:info'),
};

contextBridge.exposeInMainWorld('ils', api);
