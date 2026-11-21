/**
 * Electron main process.
 *
 * Security baseline (Electron security checklist):
 *  - contextIsolation + sandbox, no nodeIntegration in the renderer
 *  - the renderer only talks to the main process through the narrow preload bridge
 *  - navigation and new windows are blocked; external links open in the system browser
 *  - permission requests are denied by default (microphone will be allowed explicitly in
 *    phase 7 for the voice simulation, nothing else)
 */
import { app, BrowserWindow, ipcMain, net, protocol, session, shell } from 'electron';
import { hostname } from 'node:os';
import { join, normalize, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import { loadConfig, saveConfig } from './config-store';

const isDev = !app.isPackaged && process.env['ELECTRON_RENDERER_URL'] !== undefined;

// The renderer is served from a private, secure custom scheme instead of file://.
// This gives it a stable origin ("app://ils") that the server's CORS policy can allow
// explicitly – file:// pages would send "Origin: null".
const APP_ORIGIN = 'app://ils';
const RENDERER_DIR = join(__dirname, '../renderer');
protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } },
]);

function registerAppProtocol(): void {
  protocol.handle('app', (request) => {
    const { pathname } = new URL(request.url);
    const file = normalize(join(RENDERER_DIR, decodeURIComponent(pathname)));
    if (!file.startsWith(RENDERER_DIR + sep)) return new Response('Forbidden', { status: 403 });
    return net.fetch(pathToFileURL(file).toString());
  });
}

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1680,
    height: 1000,
    minWidth: 1280,
    minHeight: 760,
    show: false,
    backgroundColor: '#0b0f14',
    title: 'ILS-Sim Leitstelle',
    // Custom dark title bar; Windows draws the native window buttons on top of it.
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#0e131a', symbolColor: '#a9b4c0', height: 40 },
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false,
    },
  });

  win.once('ready-to-show', () => {
    win.maximize();
    win.show();
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//.test(url)) void shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    const allowed = isDev ? url.startsWith(process.env['ELECTRON_RENDERER_URL'] ?? '') : url.startsWith(`${APP_ORIGIN}/`);
    if (!allowed) event.preventDefault();
  });

  if (isDev) {
    void win.loadURL(process.env['ELECTRON_RENDERER_URL']!);
  } else {
    void win.loadURL(`${APP_ORIGIN}/index.html`);
  }
  return win;
}

function registerIpc(): void {
  ipcMain.handle('config:get', () => {
    const cfg = loadConfig();
    return { ...cfg, workstationName: cfg.workstationName || hostname() };
  });
  ipcMain.handle('config:set', (_event, patch: unknown) => {
    if (typeof patch !== 'object' || patch === null) throw new Error('Ungültige Konfiguration');
    return saveConfig(patch as Record<string, unknown>);
  });
  ipcMain.handle('app:info', () => ({
    version: app.getVersion(),
    platform: process.platform,
    electron: process.versions.electron,
  }));
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    const [win] = BrowserWindow.getAllWindows();
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  void app.whenReady().then(() => {
    session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
    registerAppProtocol();
    registerIpc();
    createWindow();
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });
}
