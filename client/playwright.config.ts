/**
 * End-to-end tests: the renderer (web build) against a real running server.
 * Prerequisites: server on http://localhost:8000 with bootstrap + seed-demo data
 * (see docs/entwicklung.md). Start with: npm run build:web && npm run e2e
 */
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'e2e',
  timeout: 60_000,
  retries: 0,
  // The tests share one running server, demo database and demo users – run them serially
  // so that sessions and simulated calls of different tests cannot interfere.
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: 'http://localhost:4173',
    viewport: { width: 1600, height: 900 },
    trace: 'off',
    launchOptions: process.env['PW_CHROMIUM'] ? { executablePath: process.env['PW_CHROMIUM'] } : {},
  },
  webServer: {
    command: 'npm run preview:web',
    url: 'http://localhost:4173',
    reuseExistingServer: true,
  },
});
