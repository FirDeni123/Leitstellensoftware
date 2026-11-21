/** Shared E2E helpers (login, cleanup of the persistent demo database). */
import { expect, type APIRequestContext, type Browser, type Page } from '@playwright/test';

export const PASSWORD = process.env['ILS_DEMO_PASSWORD'] ?? 'Demo-Passwort-2026!';
export const API = process.env['ILS_API_URL'] ?? 'http://localhost:8000/api/v1';
export const SHOTS = process.env['E2E_SCREENSHOT_DIR'];

export async function session(browser: Browser, user: string, workstationKey: string): Promise<Page> {
  const page = await (await browser.newContext({ viewport: { width: 1600, height: 900 } })).newPage();
  await page.goto('/');
  await page.getByLabel('Benutzername').fill(user);
  await page.getByLabel('Passwort', { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Anmelden' }).click();
  await expect(page.getByText('Echtzeit verbunden')).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press(workstationKey);
  return page;
}

/** The demo database persists between runs: release vehicles still bound to older test incidents. */
export async function releaseDemoVehicles(request: APIRequestContext): Promise<void> {
  const login = await request.post(`${API}/auth/login`, { data: { username: 'admin.demo', password: PASSWORD } });
  expect(login.ok()).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const centres = (await (await request.get(`${API}/control-centers`, { headers })).json()) as { id: string }[];
  for (const cc of centres) {
    const active = (await (await request.get(`${API}/incidents/active-assignments?control_center_id=${cc.id}`, { headers })).json()) as
      { vehicle_id: string; incident_id: string }[];
    for (const a of active) await request.delete(`${API}/incidents/${a.incident_id}/vehicles/${a.vehicle_id}`, { headers });
  }
}
