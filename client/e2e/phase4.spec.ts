/**
 * Phase 4 / milestone M4: alarm preview from the AAO, alarm only after confirmation, alarm
 * protocol and delivery via the (simulated) interface, police notice popup with acknowledgement,
 * real interfaces cannot be enabled in simulation mode.
 * Requires a server with `ils-admin seed-demo` data in simulation mode.
 */
import { expect, test, type APIRequestContext, type Browser, type Page } from '@playwright/test';

const PASSWORD = process.env['ILS_DEMO_PASSWORD'] ?? 'Demo-Passwort-2026!';
const API = process.env['ILS_API_URL'] ?? 'http://localhost:8000/api/v1';
const SHOTS = process.env['E2E_SCREENSHOT_DIR'];
const RUN = Date.now() % 100000;

async function session(browser: Browser, user: string, workstationKey: string): Promise<Page> {
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
async function releaseDemoVehicles(request: APIRequestContext): Promise<void> {
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

async function createIncident(page: Page, keyword: string, address: string): Promise<void> {
  await page.getByRole('button', { name: '+ Einsatz' }).click();
  const dialog = page.getByRole('dialog', { name: 'Einsatz anlegen' });
  await dialog.getByLabel('Einsatzstichwort').selectOption({ label: keyword });
  await dialog.getByLabel('Einsatzort').fill(address);
  await dialog.getByRole('button', { name: 'Anlegen' }).click();
  await expect(page.locator('.detail').getByText(/^\d{4}-\d{6}$/)).toBeVisible();
}

test.beforeAll(async ({ request }) => {
  await releaseDemoVehicles(request);
});

test('M4: AAO preview for B2, alarm only after confirmation, protocol and simulated delivery', async ({ browser }) => {
  const dispo = await session(browser, 'dispo.demo', 'F3');
  const lead = await session(browser, 'lead.demo', 'F3');
  const address = `Brandweg ${RUN}, Demostadt`;
  await createIncident(dispo, 'B2 – Mittelbrand (z. B. Pkw, Zimmer)', address);

  await dispo.getByRole('button', { name: 'Alarmieren …' }).click();
  const dialog = dispo.getByRole('dialog', { name: /^Alarmierung – Einsatz/ });
  await expect(dialog.getByText('AAO: B2 (Demo)')).toBeVisible();
  await expect(dialog.getByText('Simulationsbetrieb – die Alarmierung wird nur simuliert')).toBeVisible();
  for (const unit of ['Florian Demo 1/46-1', 'Florian Demo 1/33-1', 'Florian Demo 1/11-1']) {
    await expect(dialog.getByLabel(`${unit} alarmieren`)).toBeChecked();
  }
  await expect(dialog.getByText('Simulations-Empfänger (Demo)')).toBeVisible();
  if (SHOTS) await dispo.screenshot({ path: `${SHOTS}/30-m4-alarmierungsvorschau.png` });

  // The preview alone alarms nothing.
  await expect(dispo.getByText('noch keine Alarmierung')).toBeVisible();
  // The dispatcher removes the command vehicle and confirms.
  await dialog.getByLabel('Florian Demo 1/11-1 alarmieren').uncheck();
  await expect(dialog.getByRole('button', { name: 'Alarmieren (2)' })).toBeEnabled();
  await dialog.getByRole('button', { name: 'Alarmieren (2)' }).click();
  await expect(dialog).toHaveCount(0);

  const detail = dispo.locator('.detail');
  await expect(detail.getByText('Erstalarm · Stufe 1')).toBeVisible();
  const timeline = detail.locator('.timeline');
  await expect(timeline.getByText(/Erstalarm \(Stufe 1, AAO B2\) \[Simulation\]: Fahrzeuge Florian Demo 1\/46-1, Florian Demo 1\/33-1/)).toBeVisible();
  await expect(timeline.getByText(/Zustellung über Schnittstellen – Simulations-Empfänger \(Demo\): simuliert/)).toBeVisible();
  await expect(detail.locator('.status-step.current')).toHaveText('Alarmiert');
  await detail.getByRole('button', { name: /Erstalarm · Stufe 1/ }).click();
  await expect(detail.getByRole('cell', { name: 'Florian Demo 1/46-1 (HLF20)', exact: true })).toBeVisible();

  // The colleague sees the alarm live in the overview.
  await lead.getByRole('tab', { name: 'Alarmierungsübersicht' }).click();
  await expect(lead.locator('.alarm-card').filter({ hasText: 'Erstalarm · Stufe 1' }).first()).toBeVisible();
  if (SHOTS) await dispo.screenshot({ path: `${SHOTS}/31-m4-alarmprotokoll.png` });

  // Follow-up alarm proposes stage 2 (2nd HLF + RTW) only.
  await dispo.getByRole('button', { name: 'Nachalarmieren …' }).click();
  const follow = dispo.getByRole('dialog', { name: /^Alarmierung – Einsatz/ });
  await expect(follow.getByText('Nachalarmierung')).toBeVisible();
  await expect(follow.getByText('Bereits alarmiert: Florian Demo 1/46-1, Florian Demo 1/33-1')).toBeVisible();
  await expect(follow.getByLabel('Florian Demo 2/46-1 alarmieren')).toBeChecked();
  await follow.getByRole('button', { name: 'Abbrechen' }).click();
});

test('M4: police notice popup must be acknowledged and is documented – nothing is sent to the police', async ({ browser }) => {
  const dispo = await session(browser, 'dispo.demo', 'F3');
  await createIncident(dispo, 'H2 – Technische Hilfe mittel (z. B. Verkehrsunfall mit Verletzten)', `Unfallkreuzung ${RUN}, Demostadt`);
  await dispo.getByRole('button', { name: 'Alarmieren …' }).click();
  const dialog = dispo.getByRole('dialog', { name: /^Alarmierung – Einsatz/ });
  await expect(dialog.getByText(/Nach der Alarmierung erscheint der Hinweis „Polizei informieren“/)).toBeVisible();
  await dialog.getByRole('button', { name: /^Alarmieren/ }).click();

  const popup = dispo.getByRole('dialog', { name: 'Hinweis: Polizei informieren' });
  await expect(popup).toBeVisible();
  await expect(popup.getByText('Das System alarmiert und benachrichtigt die Polizei')).toBeVisible();
  if (SHOTS) await dispo.screenshot({ path: `${SHOTS}/32-m4-polizei-hinweis.png` });
  await popup.getByLabel('Vermerk (optional)').fill('Polizei über 110 informiert');
  await popup.getByRole('button', { name: 'Zur Kenntnis genommen' }).click();
  await expect(popup).toHaveCount(0);
  const timeline = dispo.locator('.detail .timeline');
  await expect(timeline.getByText(/Polizei-Hinweis zur Kenntnis genommen \(H2\)\. Vermerk: Polizei über 110 informiert/)).toBeVisible();
  await expect(timeline.getByText(/Hinweis „Polizei informieren“ \(H2\)/)).toBeVisible();
});

test('real interfaces cannot be enabled in simulation mode', async ({ browser }) => {
  const admin = await session(browser, 'admin.demo', 'F6');
  await admin.getByRole('tab', { name: 'Schnittstellen' }).click();
  await admin.getByRole('button', { name: '+ Schnittstelle' }).click();
  const dialog = admin.getByRole('dialog', { name: 'Schnittstelle anlegen' });
  await dialog.getByLabel('Plugin').selectOption({ label: 'Webhook (HTTP POST, real) – REAL' });
  await expect(dialog.getByText(/Reale Schnittstelle: Aktivieren und Testen nur im Echtbetrieb/)).toBeVisible();
  await dialog.getByLabel('Name').fill(`Webhook E2E ${RUN}`);
  await dialog.getByLabel('Ziel-URL *').fill('https://alarm.example.invalid/hook');
  await dialog.getByLabel(/Token \/ API-Schlüssel/).fill('geheim-e2e-1234');
  await dialog.getByRole('button', { name: 'Anlegen (deaktiviert)' }).click();
  await expect(dialog).toHaveCount(0);

  const detail = admin.locator('.detail');
  await expect(detail.getByText('deaktiviert', { exact: true })).toBeVisible();
  await expect(detail.getByLabel(/Token \/ API-Schlüssel/)).toHaveAttribute('placeholder', /gesetzt \(••••1234\)/);
  await detail.getByRole('button', { name: 'Aktivieren' }).click();
  const confirm = admin.getByRole('dialog', { name: /Reale Schnittstelle .* aktivieren/ });
  await confirm.getByLabel('Begründung (wird protokolliert)').fill('E2E-Test der Sperre');
  await confirm.getByRole('button', { name: 'Aktivieren' }).click();
  await expect(confirm.getByText(/nur im Echtbetrieb aktiviert werden/)).toBeVisible();
  await confirm.getByRole('button', { name: 'Abbrechen' }).click();
  await expect(detail.getByText('deaktiviert', { exact: true })).toBeVisible();
  // clean up
  await detail.getByRole('button', { name: 'Löschen' }).click();
});
