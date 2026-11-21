/**
 * Phase 3 / milestone M3: two dispatchers work in parallel; a second emergency call is
 * linked to the existing incident; the incident history is complete.
 * Requires a server with `ils-admin seed-demo` data in simulation mode.
 */
import { expect, test, type Browser, type Page } from '@playwright/test';

const PASSWORD = process.env['ILS_DEMO_PASSWORD'] ?? 'Demo-Passwort-2026!';
const SHOTS = process.env['E2E_SCREENSHOT_DIR'];
const RUN = Date.now() % 100000;
const ADDRESS = `Teststraße ${RUN}, Demostadt`;

async function session(browser: Browser, user: string): Promise<Page> {
  const page = await (await browser.newContext({ viewport: { width: 1600, height: 900 } })).newPage();
  await page.goto('/');
  await page.getByLabel('Benutzername').fill(user);
  await page.getByLabel('Passwort', { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Anmelden' }).click();
  await expect(page.getByText('Echtzeit verbunden')).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press('F2');
  return page;
}

async function simulateCall(admin: Page) {
  await admin.getByLabel('Szenario').selectOption('pkw_brand');
  await admin.getByRole('button', { name: 'Simulierten Notruf erzeugen' }).click();
}

test('M3: call → new incident, second call by a colleague → existing incident, complete history', async ({ browser }) => {
  const admin = await session(browser, 'admin.demo'); // trainer: injects simulated calls
  const dispo = await session(browser, 'dispo.demo');
  const lead = await session(browser, 'lead.demo');

  // call 1: dispatcher answers with the keyboard and creates the incident
  await simulateCall(admin);
  await expect(dispo.locator('.ringing-indicator')).toBeVisible();
  await dispo.keyboard.press('Control+Space');
  await expect(dispo.getByText('SIMULATION · Gesprächsinhalt des simulierten Anrufers')).toBeVisible();
  await dispo.getByLabel('Einsatzort (Adresse)').fill(ADDRESS);
  await dispo.getByLabel('Einsatzgrund').fill('Pkw brennt auf Parkplatz');
  await dispo.getByRole('button', { name: /Wie viele Personen/ }).click();
  await dispo.getByLabel('Antwort').fill('Niemand im Fahrzeug');
  await dispo.getByLabel('Antwort').press('Enter');
  await dispo.getByRole('button', { name: 'Neuer Einsatz …' }).click();
  await dispo.getByLabel('Einsatzstichwort').selectOption({ label: 'B2 – Mittelbrand (z. B. Pkw, Zimmer)' });
  await dispo.getByRole('button', { name: 'Einsatz anlegen' }).click();
  await expect(dispo.getByText(/^Einsatz \d{4}-\d{6}$/)).toBeVisible();
  await dispo.getByRole('button', { name: 'Gespräch beenden' }).click();

  // call 2: a colleague takes it (the first dispatcher sees it is taken) and links it
  await simulateCall(admin);
  await expect(lead.locator('.ringing-indicator')).toBeVisible();
  await lead.keyboard.press('Control+Space');
  await expect(lead.getByText('SIMULATION · Gesprächsinhalt des simulierten Anrufers')).toBeVisible();
  await expect(dispo.locator('.ringing-indicator')).toHaveCount(0); // taken by the colleague
  await lead.getByRole('button', { name: 'Bestehendem Einsatz zuordnen …' }).click();
  const dialog = lead.getByRole('dialog', { name: 'Notruf einem bestehenden Einsatz zuordnen' });
  await dialog.getByRole('cell', { name: ADDRESS, exact: true }).click();
  await dialog.getByRole('button', { name: 'Zuordnen', exact: true }).click();
  await lead.getByRole('button', { name: 'Gespräch beenden' }).click();

  // in parallel the first dispatcher dispatches a vehicle in the disposition workstation
  await dispo.keyboard.press('F3');
  await dispo.getByRole('cell', { name: ADDRESS, exact: true }).click();
  await dispo.getByLabel('Fahrzeuge hinzufügen').fill('Florian Demo 2/46');
  await dispo.getByRole('option', { name: /Florian Demo 2\/46-1/ }).click();
  await dispo.getByRole('button', { name: 'Zuordnen', exact: true }).click();
  // the demo database persists between runs: the vehicle may still be bound to an older test incident
  const move = dispo.getByRole('dialog', { name: 'Fahrzeug umsetzen?' });
  if (await move.waitFor({ timeout: 1500 }).then(() => true, () => false)) await move.getByRole('button', { name: 'Umsetzen' }).click();

  // the colleague sees the complete, live-updated incident
  await lead.keyboard.press('F3');
  await lead.getByRole('cell', { name: ADDRESS, exact: true }).click();
  await expect(lead.getByText('Notrufe (2)')).toBeVisible();
  const timeline = lead.locator('.timeline');
  await expect(timeline.getByText(/zugeordnet \[Simulation\]/)).toHaveCount(2);
  await expect(timeline.getByText(/Florian Demo 2\/46-1 \(HLF20, .*\) zugeordnet/)).toBeVisible();
  await expect(timeline.getByText(/angelegt mit Stichwort B2/)).toBeVisible();
  if (SHOTS) await lead.screenshot({ path: `${SHOTS}/20-m3-einsatz.png` });

  // the same vehicle cannot be bound to a second incident without explicit reassignment
  await lead.getByRole('button', { name: '+ Einsatz' }).click();
  const create = lead.getByRole('dialog', { name: 'Einsatz anlegen' });
  await create.getByLabel('Einsatzort').fill(`${ADDRESS} (Zweiteinsatz)`);
  await create.getByRole('button', { name: 'Anlegen' }).click();
  await lead.getByRole('cell', { name: `${ADDRESS} (Zweiteinsatz)` }).click();
  await lead.getByLabel('Fahrzeuge hinzufügen').fill('Florian Demo 2/46');
  await lead.getByRole('option', { name: /Florian Demo 2\/46-1/ }).click();
  await lead.getByRole('button', { name: 'Zuordnen', exact: true }).click();
  await expect(lead.getByRole('dialog', { name: 'Fahrzeug umsetzen?' })).toBeVisible();
  await lead.getByRole('button', { name: 'Abbrechen' }).click();
});
