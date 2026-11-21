/**
 * Phase 7 / milestone M7 (without a Claude key: rule-based caller): a trainee takes a training
 * call, talks to the caller, captures the incident in parallel and gets an evaluation with a
 * checklist; an instructor watches live and steers the caller without the trainee seeing it.
 * Requires a server with `ils-admin seed-demo` data (incl. demo scenarios) in simulation mode.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { API, PASSWORD, SHOTS, session } from './helpers';

const SCENARIO = 'Pkw-Brand auf dem Parkplatz (Demo)';

/** Opens (or focuses) a window through the "Fenster" menu – independent of saved layouts. */
async function openWindow(page: Page, title: string): Promise<void> {
  await page.getByRole('button', { name: 'Fenster ▾' }).click();
  await page.getByRole('menuitem', { name: title, exact: true }).click();
}

/** The demo database persists: end exercises left open by earlier (aborted) runs. */
async function endOpenExercises(request: APIRequestContext): Promise<void> {
  const login = await request.post(`${API}/auth/login`, { data: { username: 'admin.demo', password: PASSWORD } });
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const open = (await (await request.get(`${API}/training/sessions?status=open`, { headers })).json()) as { id: string }[];
  for (const s of open) await request.post(`${API}/training/sessions/${s.id}/end`, { headers });
}

test('M7: training call with caller, incident in parallel, instructor steering, evaluation', async ({ browser, request }) => {
  await endOpenExercises(request);
  const trainee = await session(browser, 'dispo.demo', 'F7');
  const trainer = await session(browser, 'ausbilder.demo', 'F7');

  // trainee starts the scenario; the training call rings
  const call = trainee.locator('.exercise').first();
  await trainee.getByRole('row', { name: new RegExp(SCENARIO.replace(/[()]/g, '\\$&')) }).getByRole('button', { name: 'Übung starten' }).click();
  await expect(trainee.getByText('ÜBUNG · SIMULATION').first()).toBeVisible();
  await expect(trainee.getByText('Regelbasierter Anrufer (ohne KI)').first()).toBeVisible();
  await expect(trainee.getByText('Übungsanruf klingelt')).toBeVisible();

  // the instructor sees it live
  await openWindow(trainer, 'Ausbildung (Beobachten)');
  const row = trainer.getByRole('row', { name: /Disponent Demo/ }).first();
  await expect(row).toContainText('klingelt');

  // answering plays the scenario's opening line
  await trainee.getByRole('button', { name: 'Annehmen', exact: true }).click();
  await expect(call.getByText('Ja hallo, hier brennt ein Auto auf dem Parkplatz vom Supermarkt!')).toBeVisible();

  const say = async (text: string) => {
    const input = trainee.getByLabel('Ihre Antwort an den Anrufer');
    await input.fill(text);
    await input.press('Enter');
  };
  await say('Feuerwehr Notruf. Wo genau ist das?');
  await expect(call.locator('[data-role="caller"]').last()).toContainText('Industriestraße 30');

  // instructor steers the caller – the trainee never sees the instruction
  await row.click();
  await trainer.getByLabel('Regieanweisung an den Anrufer').fill('Erwähne, dass das Feuer auf das Nachbarauto übergreift.');
  await trainer.getByRole('button', { name: 'Anweisen' }).click();
  await expect(trainer.getByText(/wartet: Erwähne, dass das Feuer/)).toBeVisible();
  await expect(trainer.locator('.chat').getByText('Industriestraße 30', { exact: false }).first()).toBeVisible();

  // in parallel: incident from the call (the normal call-taking window in the same workstation)
  await trainee.getByLabel('Einsatzort (Adresse)').fill('Industriestraße 30, 21493 Demostadt');
  await trainee.getByLabel('Breitengrad').fill('53.4952');
  await trainee.getByLabel('Längengrad').fill('10.4968');
  await trainee.getByRole('button', { name: 'Neuer Einsatz …' }).click();
  await trainee.getByLabel('Einsatzstichwort').selectOption({ label: 'B2 – Mittelbrand (z. B. Pkw, Zimmer)' });
  await trainee.getByRole('button', { name: 'Einsatz anlegen' }).click();
  await expect(trainee.getByText(/^Einsatz \d{4}-\d{6}$/)).toBeVisible();

  await say('Unter welcher Nummer kann ich Sie zurückrufen?');
  await expect(call.locator('[data-role="caller"]').last()).toContainText('0000 1234567');
  await expect(trainer.locator('.chat').getByText(/^Regie/).first()).toBeVisible(); // delivered with that reply
  await expect(trainee.locator('.chat').getByText(/Regie|Nachbarauto übergreift/)).toHaveCount(0);
  if (SHOTS) await trainee.screenshot({ path: `${SHOTS}/70-m7-uebungsgespraech.png` });
  if (SHOTS) await trainer.screenshot({ path: `${SHOTS}/71-m7-ausbilder.png` });

  // hang up → automatic evaluation with checklist
  await trainee.getByRole('button', { name: 'Auflegen' }).click();
  const report = trainee.getByLabel('Auswertung');
  await expect(report).toBeVisible({ timeout: 15_000 });
  await expect(report.getByText('Regelbasierte Auswertung (Schlüsselwörter, ohne KI)', { exact: false })).toBeVisible();
  await expect(report.locator('tr[data-key="incident_created"]')).toHaveClass(/ok-row/);
  await expect(report.locator('tr[data-key="keyword_correct"]')).toHaveClass(/ok-row/);
  await expect(report.locator('tr[data-key="location_correct"]')).toHaveClass(/ok-row/);
  await expect(report.locator('tr[data-key="ask_location"]')).toHaveClass(/ok-row/);
  await expect(report.locator('tr[data-key="ask_callback"]')).toHaveClass(/ok-row/);
  await expect(report.locator('tr[data-key="alarm_triggered"]')).toHaveClass(/miss-row/);
  await expect(report.getByLabel('Ergebnis')).toHaveText(/\d+ %/);
  await expect(trainee.getByText('Lösung: tatsächliche Lage des Szenarios')).toBeVisible();
  if (SHOTS) await trainee.screenshot({ path: `${SHOTS}/72-m7-auswertung.png` });

  // the instructor sees the evaluated exercise
  await expect(trainer.getByRole('row', { name: /Disponent Demo/ }).first()).toContainText('ausgewertet');
});

test('AI settings: off by default, key never shown, admin only', async ({ browser }) => {
  const admin = await session(browser, 'admin.demo', 'F6');
  await openWindow(admin, 'KI-Einstellungen');
  await expect(admin.getByText('Datenschutz:')).toBeVisible();
  await expect(admin.getByLabel('KI-Anrufer eingeschaltet')).not.toBeChecked();
  await expect(admin.getByText(/API-Schlüssel – keiner|API-Schlüssel – aus Serverkonfiguration/)).toBeVisible();
  if (SHOTS) await admin.screenshot({ path: `${SHOTS}/73-ki-einstellungen.png` });
});
