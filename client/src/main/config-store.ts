/**
 * Local client configuration (per Windows user), stored as JSON in the Electron userData
 * directory (%APPDATA%\ILS-Sim Leitstelle\client-config.json). Contains no secrets:
 * tokens are kept in memory only, so a shared dispatch PC never holds a login on disk.
 */
import { app } from 'electron';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

export interface ClientConfig {
  serverUrl: string;
  workstationName: string;
  lastUsername: string;
  lastWorkstation: string;
}

const DEFAULTS: ClientConfig = {
  serverUrl: 'http://localhost:8000',
  workstationName: '',
  lastUsername: '',
  lastWorkstation: 'dispatch',
};

const ALLOWED_KEYS = new Set(Object.keys(DEFAULTS));

function configPath(): string {
  return join(app.getPath('userData'), 'client-config.json');
}

export function loadConfig(): ClientConfig {
  try {
    const raw = JSON.parse(readFileSync(configPath(), 'utf-8')) as Partial<ClientConfig>;
    return { ...DEFAULTS, ...raw };
  } catch {
    return { ...DEFAULTS };
  }
}

/** Validates and atomically writes the configuration (write temp file + rename). */
export function saveConfig(patch: Record<string, unknown>): ClientConfig {
  const current = loadConfig();
  for (const [key, value] of Object.entries(patch)) {
    if (!ALLOWED_KEYS.has(key) || typeof value !== 'string' || value.length > 500) {
      throw new Error(`Ungültiger Konfigurationswert: ${key}`);
    }
  }
  const next = { ...current, ...(patch as Partial<ClientConfig>) };
  if (next.serverUrl && !/^https?:\/\/[^\s/]+(:\d+)?\/?$/.test(next.serverUrl)) {
    throw new Error('Serveradresse muss die Form http(s)://host[:port] haben');
  }
  const file = configPath();
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(`${file}.tmp`, JSON.stringify(next, null, 2), 'utf-8');
  renameSync(`${file}.tmp`, file);
  return next;
}
