/**
 * Access to the desktop shell (Electron preload bridge). When the renderer runs in a
 * plain browser (development, end-to-end tests) a localStorage fallback is used.
 */

export interface ClientConfig {
  serverUrl: string;
  workstationName: string;
  lastUsername: string;
  lastWorkstation: string;
}

export interface AppInfo {
  version: string;
  platform: string;
  electron?: string;
}

interface DesktopBridge {
  isDesktop: true;
  config: { get(): Promise<ClientConfig>; set(patch: Partial<ClientConfig>): Promise<ClientConfig> };
  appInfo(): Promise<AppInfo>;
}

declare global {
  interface Window {
    ils?: DesktopBridge;
  }
}

const STORAGE_KEY = 'ils-client-config';
const DEFAULTS: ClientConfig = {
  serverUrl: 'http://localhost:8000',
  workstationName: 'Browser',
  lastUsername: '',
  lastWorkstation: 'dispatch',
};

function readLocal(): ClientConfig {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? { ...DEFAULTS, ...(JSON.parse(raw) as Partial<ClientConfig>) } : { ...DEFAULTS };
  } catch {
    return { ...DEFAULTS };
  }
}

export const platform = {
  isDesktop: (): boolean => window.ils?.isDesktop === true,

  async loadConfig(): Promise<ClientConfig> {
    return window.ils ? window.ils.config.get() : readLocal();
  },

  async saveConfig(patch: Partial<ClientConfig>): Promise<ClientConfig> {
    if (window.ils) return window.ils.config.set(patch);
    const next = { ...readLocal(), ...patch };
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* storage unavailable (private mode) – keep in memory only */
    }
    return next;
  },

  async appInfo(): Promise<AppInfo> {
    return window.ils ? window.ils.appInfo() : { version: __APP_VERSION__, platform: 'browser' };
  },
};

declare const __APP_VERSION__: string;
