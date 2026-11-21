import { resolve } from 'node:path';
import { defineConfig } from 'electron-vite';
import react from '@vitejs/plugin-react';
import pkg from './package.json';

const define = { __APP_VERSION__: JSON.stringify(pkg.version) };

export default defineConfig({
  main: { build: { outDir: 'out/main' } },
  preload: { build: { outDir: 'out/preload' } },
  renderer: {
    root: 'src/renderer',
    resolve: { alias: { '@': resolve('src/renderer/src') } },
    plugins: [react()],
    define,
    build: { outDir: 'out/renderer' },
  },
});
