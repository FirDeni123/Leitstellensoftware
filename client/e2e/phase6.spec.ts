/**
 * Phase 6 / milestone M6: alarmed vehicles turn out and drive (simulation, time-lapse),
 * both dispatchers see the same live state, arrival sets status 4 and writes the incident
 * history; talk requests; incident location picked on the map.
 * Requires a server with `ils-admin seed-demo` data in simulation mode.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { API, PASSWORD, releaseDemoVehicles, session, SHOTS } from './helpers';

const RUN = Date.now() % 100000;

async function adminHeaders(request: APIRequestContext): Promise<Record<string, string>> {
  const login = await request.post(`${API}/auth/login`, { data: { username: 'admin.demo', password: PASSWORD } });
  return { Authorization: `Bearer ${(await login.json()).access_token}` };
}

async function setClock(request: APIRequestContext, body: Record<string, unknown>): Promise<void> {
  const r = await request.put(`${API}/simulation/clock`, { headers: await adminHeaders(request), data: body });
  expect(r.ok()).toBeTruthy();
}

async function createIncident(page: Page, keyword: string, address: string, lat?: string, lon?: string): Promise<void> {
  await page.getByRole('button', { name: '+ Einsatz' }).click();
  const dialog = page.getByRole('dialog', { name: 'Einsatz anlegen' });
  await dialog.getByLabel('Einsatzstichwort').selectOption({ label: keyword });
  await dialog.getByLabel('Einsatzort').fill(address);
  await dialog.getByRole('button', { name: 'Anlegen' }).click();
  const detail = page.locator('.detail');
  await expect(detail.getByText(/^\d{4}-\d{6}$/)).toBeVisible();
  if (lat && lon) {
    await detail.getByLabel('Breitengrad').fill(lat);
    await detail.getByLabel('Längengrad').fill(lon);
    await detail.getByRole('button', { name: 'Einsatzdaten speichern' }).click();
    await expect(detail.getByRole('button', { name: 'Einsatzdaten speichern' })).toBeDisabled();
  }
}

test.beforeAll(async ({ request }) => {
  await releaseDemoVehicles(request);
  await setClock(request, { factor: 30, paused: false }); // 30× time-lapse: drives take a few seconds
});

test.afterAll(async ({ request }) => {
  await setClock(request, { factor: 1, paused: false });
});

test('M6: alarmed vehicles drive and arrive, both dispatchers see it live', async ({ browser }) => {
  test.setTimeout(120_000);
  const dispo = await session(browser, 'dispo.demo', 'F3');
  const lead = await session(browser, 'lead.demo', 'F3');
  const address = `Kartenweg ${RUN}, Demostadt`;
  await createIncident(dispo, 'B2 – Mittelbrand (z. B. Pkw, Zimmer)', address, '53.5120', '10.4930');

  // map shows the incident and the vehicles of the control centre – really inside the map area
  const map = dispo.getByTestId('map');
  const mapBox = (await map.boundingBox())!;
  expect(mapBox.height).toBeGreaterThan(150);
  await expect(map.locator('.map-incident').first()).toBeVisible();
  const marker = map.locator('.map-vehicle', { hasText: 'Florian Demo 1/46-1' });
  await expect(marker).toBeVisible();
  const markerBox = (await marker.boundingBox())!;
  expect(markerBox.y).toBeGreaterThanOrEqual(mapBox.y);
  expect(markerBox.y + markerBox.height).toBeLessThanOrEqual(mapBox.y + mapBox.height);

  await dispo.locator('.detail').getByRole('button', { name: 'Alarmieren …' }).click();
  const alarm = dispo.getByRole('dialog', { name: /^Alarmierung – Einsatz/ });
  await alarm.getByRole('button', { name: /^Alarmieren \(\d+\)$/ }).click();
  await expect(alarm).toHaveCount(0);

  // the colleague follows in the vehicle overview: turnout (status 3) …
  await lead.getByRole('tab', { name: 'Fahrzeugübersicht' }).click();
  const row = lead.locator('tr[data-vehicle="Florian Demo 1/46-1"]');
  await expect(row.locator('.fms')).toHaveText('3', { timeout: 20_000 });
  await expect(row).toContainText(/Anfahrt · ETA \d+:\d{2}/);
  // … the dispatcher sees the vehicle moving on the map
  await expect(map.locator('.map-vehicle.moving', { hasText: 'Florian Demo 1/46-1' })).toBeVisible();
  if (SHOTS) await dispo.screenshot({ path: `${SHOTS}/50-m6-karte-anfahrt.png` });

  // arrival: status 4, incident "Am Einsatzort", history entry
  await expect(row.locator('.fms')).toHaveText('4', { timeout: 30_000 });
  const timeline = dispo.locator('.detail .timeline');
  await expect(timeline.getByText(/Florian Demo 1\/46-1: Ankunft am Einsatzort \(Status 4\) \[Simulation\]/)).toBeVisible({ timeout: 10_000 });
  await expect(dispo.locator('.detail .status-step.current')).toHaveText('Am Einsatzort');
  await lead.getByRole('tab', { name: 'Statusübersicht' }).click();
  await expect(lead.locator('.board-tile', { hasText: 'Florian Demo 1/46-1' }).locator('.board-code')).toHaveText('4');
  if (SHOTS) await lead.screenshot({ path: `${SHOTS}/51-m6-statustableau.png` });

  // talk request (status 5) from the vehicle -> dispatcher gives the request to speak
  await lead.getByRole('tab', { name: 'Fahrzeugübersicht' }).click();
  await row.getByLabel('Status Florian Demo 1/46-1').selectOption('5');
  await dispo.getByRole('tab', { name: 'Sprechwünsche' }).click();
  const request = dispo.locator('.talk-request[data-call-sign="Florian Demo 1/46-1"]');
  await expect(request).toBeVisible();
  await request.getByRole('button', { name: 'Sprechaufforderung' }).click();
  await expect(request).toContainText('Sprechaufforderung erteilt von Disponent Demo');
  await request.getByLabel('Vermerk Florian Demo 1/46-1').fill('Lage: Pkw in Vollbrand, 1 Rohr vor');
  await request.getByRole('button', { name: 'Erledigt' }).click();
  await expect(request).toHaveCount(0);
  await expect(timeline.getByText(/Sprechwunsch Florian Demo 1\/46-1: erledigt – Lage: Pkw in Vollbrand/)).toBeVisible();

  // release: the vehicle reports status 1 and drives back to its station (status 2)
  await dispo.locator('.detail .assignment', { hasText: 'Florian Demo 1/46-1' }).getByRole('button', { name: 'Freigeben' }).click();
  await expect(row.locator('.fms')).toHaveText(/^[12]$/, { timeout: 10_000 });
  await expect(row.locator('.fms')).toHaveText('2', { timeout: 30_000 });
});

test('incident location is picked on the map', async ({ browser }) => {
  const dispo = await session(browser, 'dispo.demo', 'F3');
  await createIncident(dispo, 'H1 – Technische Hilfe klein (z. B. Ölspur, Baum auf Fahrbahn)', `Ölspur ${RUN}, Demostadt`);
  const detail = dispo.locator('.detail');
  await detail.getByRole('button', { name: 'Einsatzort auf der Karte wählen' }).click();
  await expect(dispo.getByText(/Einsatzort für \d{4}-\d{6}: in die Karte klicken/)).toBeVisible();
  const map = dispo.getByTestId('map');
  const box = (await map.boundingBox())!;
  await dispo.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(detail.getByLabel('Breitengrad')).toHaveValue(/^53\.\d+$/);
  await expect(detail.getByLabel('Längengrad')).toHaveValue(/^10\.\d+$/);
  await detail.getByRole('button', { name: 'Einsatzdaten speichern' }).click();
  await expect(detail.getByRole('button', { name: 'Einsatzdaten speichern' })).toBeDisabled();
  await expect(dispo.getByTestId('map').locator('.map-incident').first()).toBeVisible();
});
