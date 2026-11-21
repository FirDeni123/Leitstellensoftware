import { expect, test, type Page } from '@playwright/test';

const PASSWORD = process.env['ILS_DEMO_PASSWORD'] ?? 'Demo-Passwort-2026!';
const SHOTS = process.env['E2E_SCREENSHOT_DIR'];

const workstation = (page: Page, name: RegExp) =>
  page.getByRole('navigation', { name: 'Arbeitsplätze' }).getByRole('button', { name });

async function login(page: Page, username: string, password = PASSWORD) {
  await page.goto('/');
  await page.getByLabel('Benutzername').fill(username);
  await page.getByLabel('Passwort', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Anmelden' }).click();
}

test('login page clearly shows simulation mode and rejects wrong passwords', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('SIMULATION · Training und Entwicklung')).toBeVisible();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/01-login.png` });
  await login(page, 'dispo.demo', 'falsches-Passwort-1');
  await expect(page.getByRole('alert')).toContainText('Benutzername oder Passwort falsch');
});

test('dispatcher workstation with map and live connection', async ({ page }) => {
  await login(page, 'dispo.demo');
  await expect(page.getByRole('status').filter({ hasText: 'SIMULATIONSBETRIEB' })).toBeVisible();
  await expect(page.getByText('Echtzeit verbunden')).toBeVisible({ timeout: 10_000 });
  await expect(workstation(page, /Disposition/)).toBeVisible();
  // Dispatchers must not see the administrator workstation.
  await expect(workstation(page, /Administrator/)).toHaveCount(0);
  // all windows of the dispatcher workstation are implemented (phase 6): the map is there
  await expect(page.getByTestId('map')).toBeVisible();
  await expect(page.getByText('Noch nicht implementiert')).toHaveCount(0);
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/02-disposition.png` });
  await page.keyboard.press('F2');
  await expect(workstation(page, /Einsatzannahme/)).toHaveClass(/active/);
});

test('admin changes a user – second session sees it live', async ({ browser }) => {
  const adminCtx = await browser.newContext();
  const leadCtx = await browser.newContext();
  const admin = await adminCtx.newPage();
  const lead = await leadCtx.newPage();

  await login(lead, 'lead.demo');
  await expect(lead.getByText('Echtzeit verbunden')).toBeVisible({ timeout: 10_000 });
  await workstation(lead, /Verwaltung/).click();
  await expect(lead.getByRole('tab', { name: 'Ereignisprotokoll' })).toBeVisible();

  await login(admin, 'admin.demo');
  await workstation(admin, /Administrator/).click();
  await admin.getByRole('cell', { name: 'beobachter.demo', exact: true }).click();
  const nameField = admin.getByLabel('Anzeigename');
  const newName = `Beobachter Demo ${Date.now() % 10000}`;
  await nameField.fill(newName);
  await admin.getByRole('tabpanel', { name: 'Benutzerverwaltung' }).getByRole('button', { name: 'Speichern' }).click();
  await expect(admin.getByRole('cell', { name: newName })).toBeVisible();
  if (SHOTS) await admin.screenshot({ path: `${SHOTS}/03-admin-benutzer.png` });

  // The audit entry appears in the lead's open protocol without reload (WebSocket push).
  await expect(lead.getByText('Benutzer beobachter.demo geändert').first()).toBeVisible({ timeout: 10_000 });
  if (SHOTS) await lead.screenshot({ path: `${SHOTS}/04-verwaltung-live.png` });
  await adminCtx.close();
  await leadCtx.close();
});
