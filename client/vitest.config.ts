import { resolve } from 'node:path';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import pkg from './package.json';

const define = { __APP_VERSION__: JSON.stringify(pkg.version) };

export default defineConfig({
  plugins: [react()],
  define,
  resolve: { alias: { '@': resolve('src/renderer/src') } },
  test: { environment: 'jsdom', include: ['tests/**/*.test.{ts,tsx}'], setupFiles: ['tests/setup.ts'] },
});
