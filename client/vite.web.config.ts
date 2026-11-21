// Browser build of the renderer (development without Electron and end-to-end tests).
// The production client is always the Electron build.
import { resolve } from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import pkg from './package.json';

const define = { __APP_VERSION__: JSON.stringify(pkg.version) };

export default defineConfig({
  root: 'src/renderer',
  resolve: { alias: { '@': resolve('src/renderer/src') } },
  plugins: [react()],
  define,
  build: { outDir: resolve('dist/web'), emptyOutDir: true },
  server: { port: 5173, strictPort: true },
});
