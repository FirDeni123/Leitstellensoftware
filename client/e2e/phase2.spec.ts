/**
 * Phase 2: master data administration and Excel/CSV import through the UI.
 * Requires a server with `ils-admin seed-demo` data (see docs/entwicklung.md).
 */
import { expect, test, type Page } from '@playwright/test';

const PASSWORD = process.env['ILS_DEMO_PASSWORD'] ?? 'Demo-Passwort-2026!';
const SHOTS = process.env['E2E_SCREENSHOT_DIR'];
const RUN = Date.now() % 100000;

async function loginAdmin(page: Page) {
  await page.goto('/');
  await page.getByLabel('Benutzername').fill('admin.demo');
  await page.getByLabel('Passwort', { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Anmelden' }).click();
  await expect(page.getByText('Echtzeit verbunden')).toBeVisible({ timeout: 10_000 });
}

test('import vehicles from CSV with row errors, then confirm valid rows', async ({ page }) => {
  await loginAdmin(page);
  await page.keyboard.press('F5');
  await page.getByRole('tab', { name: 'Datenimport' }).click();

  const csv = [
    'Rufname;Typ;Standort;Kennzeichen',
    `Florian E2E ${RUN}/1;HLF20;FW M;E2E-${RUN}1`,
    `Florian E2E ${RUN}/2;Raumschiff;FW M;`,
    `Florian E2E ${RUN}/3;RTW;RW M;E2E-${RUN}3`,
  ].join('\r\n');
  await page.getByLabel('Importdatei').setInputFiles({ name: 'e2e-fahrzeuge.csv', mimeType: 'text/csv', buffer: Buffer.from(csv, 'utf-8') });

  // step 2: suggested mapping from German headers
  await expect(page.getByLabel('Spalte für Funkrufname')).toHaveValue('0');
  await expect(page.getByLabel('Spalte für Wache')).toHaveValue('2');
  await page.getByRole('button', { name: 'Alle Zeilen prüfen' }).click();

  // step 3: row-precise error, commit blocked until errors are explicitly skipped
  await expect(page.getByText('Fahrzeugtyp „Raumschiff“ unbekannt')).toBeVisible();
  const commit = page.getByRole('button', { name: /Datensätze übernehmen/ });
  await expect(commit).toBeDisabled();
  await page.getByText(/fehlerhafte Zeile\(n\) überspringen/).click();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/10-import-fehler.png` });
  await commit.click();
  await page.getByRole('button', { name: 'Jetzt übernehmen' }).click();
  await expect(page.getByText(/wurde am .* übernommen/)).toBeVisible();

  // the imported vehicles appear in the vehicle administration (live via realtime)
  await page.getByRole('tab', { name: 'Fahrzeugverwaltung' }).click();
  await page.getByLabel('Fahrzeuge durchsuchen').fill(`E2E ${RUN}`);
  await expect(page.getByRole('cell', { name: `Florian E2E ${RUN}/1`, exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: `Florian E2E ${RUN}/3`, exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: `Florian E2E ${RUN}/2`, exact: true })).toHaveCount(0);
});

test('concurrent edit: unsaved input is kept, the save is rejected as conflict, reload shows the other change', async ({ browser }) => {
  const a = await (await browser.newContext()).newPage();
  const b = await (await browser.newContext()).newPage();
  for (const p of [a, b]) {
    await loginAdmin(p);
    await p.keyboard.press('F5');
    await p.getByRole('tab', { name: 'Fahrzeugverwaltung' }).click();
    await p.getByRole('cell', { name: 'Florian Demo 3/42-1', exact: true }).click();
    await expect(p.getByLabel('Besatzung')).toBeVisible();
  }
  // always a different value than the current one (the demo database persists between runs)
  const currentCrew = Number(await a.getByLabel('Besatzung').inputValue()) || 0;
  const crew = String((currentCrew % 9) + 1);
  await b.getByLabel('Beschreibung').fill(`Eingabe aus Sitzung B ${RUN}`); // B starts typing …
  await a.getByLabel('Besatzung').fill(crew); // … while A saves another change
  await a.getByRole('tabpanel', { name: 'Fahrzeugverwaltung' }).getByRole('button', { name: 'Speichern' }).click();
  await expect(a.getByText('Dieser Datensatz wurde zwischenzeitlich')).toHaveCount(0); // own save: no warning

  // B is warned live, keeps its input, and cannot silently overwrite A's change
  await expect(b.getByText('Dieser Datensatz wurde zwischenzeitlich von einer anderen Person geändert')).toBeVisible();
  await expect(b.getByLabel('Beschreibung')).toHaveValue(`Eingabe aus Sitzung B ${RUN}`);
  await b.getByRole('tabpanel', { name: 'Fahrzeugverwaltung' }).getByRole('button', { name: 'Speichern' }).click();
  await expect(b.getByText(/wurde zwischenzeitlich von einer anderen Person geändert. Bitte neu laden/)).toBeVisible();
  if (SHOTS) await b.screenshot({ path: `${SHOTS}/11-konflikt.png` });
  await b.getByRole('button', { name: 'Neu laden', exact: true }).click();
  await expect(b.getByLabel('Besatzung')).toHaveValue(crew);
});
