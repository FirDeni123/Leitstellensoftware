/**
 * Phase 5 / milestone M5: Einsatzmittelvorschlag for B2 with travel time and reasons per
 * vehicle, alternatives, accepting only assigns (no alarm), then the confirmed alarm.
 * Requires a server with `ils-admin seed-demo` data in simulation mode.
 */
import { expect, test } from '@playwright/test';
import { releaseDemoVehicles, session, SHOTS } from './helpers';

const RUN = Date.now() % 100000;

test.beforeAll(async ({ request }) => {
  await releaseDemoVehicles(request);
});

test('M5: proposal with reasons, alternative, accept without alarm, then alarm', async ({ browser }) => {
  const dispo = await session(browser, 'dispo.demo', 'F3');
  await dispo.getByRole('button', { name: '+ Einsatz' }).click();
  const create = dispo.getByRole('dialog', { name: 'Einsatz anlegen' });
  await create.getByLabel('Einsatzstichwort').selectOption({ label: 'B2 – Mittelbrand (z. B. Pkw, Zimmer)' });
  await create.getByLabel('Einsatzort').fill(`Nordstraße ${RUN}, Demostadt`);
  await create.getByRole('button', { name: 'Anlegen' }).click();
  const detail = dispo.locator('.detail');
  // incident location next to the northern fire station
  await detail.getByLabel('Breitengrad').fill('53.5275');
  await detail.getByLabel('Längengrad').fill('10.4725');
  await detail.getByRole('button', { name: 'Einsatzdaten speichern' }).click();
  await expect(detail.getByRole('button', { name: 'Einsatzdaten speichern' })).toBeDisabled();

  await detail.getByRole('button', { name: 'Vorschlag …' }).click();
  const dialog = dispo.getByRole('dialog', { name: /^Einsatzmittelvorschlag – Einsatz/ });
  await expect(dialog.getByText('AAO: B2 (Demo)')).toBeVisible();
  await expect(dialog.getByText('Schätzung (Luftlinie × Umwegfaktor)')).toBeVisible();
  await expect(dialog.getByText(/berechnet in \d+ ms/)).toBeVisible();
  // nearest HLF is the northern one; the central HLF is offered as alternative
  await expect(dialog.getByLabel('Florian Demo 2/46-1 übernehmen')).toBeChecked();
  await expect(dialog.getByText('AAO B2, Stufe 1: HLF20 (Bedarf 1/1)').first()).toBeVisible();
  await expect(dialog.getByText(/^Fahrzeit ca\. \d+:\d{2} min ab Wache/).first()).toBeVisible();
  if (SHOTS) await dispo.screenshot({ path: `${SHOTS}/40-m5-einsatzmittelvorschlag.png` });

  const alternative = dialog.getByLabel('Alternative zu Florian Demo 2/46-1');
  const value = await alternative.locator('option', { hasText: 'statt dessen Florian Demo 1/46-1' }).getAttribute('value');
  await alternative.selectOption(value!);
  await expect(dialog.getByLabel('Florian Demo 1/46-1 übernehmen')).toBeChecked();
  await dialog.getByLabel('Florian Demo 1/11-1 übernehmen').uncheck();
  await dialog.getByRole('button', { name: 'Übernehmen (2)' }).click();
  await expect(dialog).toHaveCount(0);

  // assigned, not alarmed
  await expect(detail.locator('.assignment').filter({ hasText: 'Florian Demo 1/46-1' })).toBeVisible();
  await expect(detail.locator('.assignment').filter({ hasText: 'Florian Demo 1/33-1' })).toBeVisible();
  await expect(detail.getByText('noch keine Alarmierung')).toBeVisible();
  await expect(detail.locator('.timeline').getByText(
    'Einsatzmittelvorschlag übernommen – zugeordnet, nicht alarmiert: Florian Demo 1/46-1, Florian Demo 1/33-1; '
    + 'abgewählt: Florian Demo 2/46-1, Florian Demo 1/11-1; Alternative gewählt: Florian Demo 1/46-1',
  )).toBeVisible();

  // second proposal: what is in the incident counts, only the ELW is still missing
  await detail.getByRole('button', { name: 'Vorschlag …' }).click();
  const second = dispo.getByRole('dialog', { name: /^Einsatzmittelvorschlag – Einsatz/ });
  await expect(second.getByText('im Einsatz')).toHaveCount(2);
  await expect(second.getByLabel('Florian Demo 1/11-1 übernehmen')).toBeChecked();
  await second.getByRole('button', { name: 'Übernehmen und alarmieren …' }).click();
  const alarm = dispo.getByRole('dialog', { name: /^Alarmierung – Einsatz/ });
  for (const unit of ['Florian Demo 1/46-1', 'Florian Demo 1/33-1', 'Florian Demo 1/11-1']) {
    await expect(alarm.getByLabel(`${unit} alarmieren`)).toBeChecked();
  }
  await alarm.getByRole('button', { name: 'Alarmieren (3)' }).click();
  await expect(alarm).toHaveCount(0);
  await expect(detail.getByText('Erstalarm · Stufe 1')).toBeVisible();
});

test('proposal settings can be changed and reset by the administration', async ({ browser }) => {
  const admin = await session(browser, 'admin.demo', 'F5');
  await admin.getByRole('tab', { name: 'Vorschlagsregeln' }).click();
  const panel = admin.getByRole('tabpanel', { name: 'Vorschlagsregeln' });
  const turnout = panel.getByLabel('Ausrückzeit bei Status 2 (s)');
  await turnout.fill('120');
  await panel.getByRole('button', { name: 'Speichern' }).click();
  await expect(panel.getByText(/Zuletzt geändert .* von Administrator Demo/)).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Speichern' })).toBeDisabled(); // own save adopted, no conflict
  await expect(panel.getByText('von einer anderen Person geändert')).toHaveCount(0);
  if (SHOTS) await admin.screenshot({ path: `${SHOTS}/41-vorschlagsregeln.png` });
  await panel.getByRole('button', { name: 'Auf Standardwerte zurücksetzen' }).click();
  await expect(turnout).toHaveValue('90');
  // leave the default tab active again (layouts are stored per user)
  await admin.getByRole('tab', { name: 'Alarmierungsregeln (AAO)' }).click();
});
