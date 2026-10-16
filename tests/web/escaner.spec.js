// Escáner: resultados, mercados, gráficos, visor y estrellas.
const { test, expect } = require('@playwright/test');
const { Fake, URL, cards, scan } = require('./fake');

test('escanea spot y futuros y deja fuera las acciones tokenizadas de spot', async ({ page, context }) => {
  const fake = new Fake();
  await fake.install(context);
  await page.goto(URL);
  await expect(page.locator('link[rel="apple-touch-icon"]')).toHaveAttribute('href', 'icono.png');
  await expect(page.locator('.brand .logo')).toBeVisible();
  await expect(page.locator('#toolbar')).toBeHidden();
  await expect(page.locator('#filters')).toBeHidden();

  await scan(page);
  await expect(page.locator('#scan-status')).toContainText('Guardado en «Seguimiento');
  expect((await cards(page)).sort()).toEqual(['AAA/USDT Futuros', 'AAA/USDT Spot', 'TSLAB/USDT Futuros']);
  await expect(page.locator('#notice')).toBeHidden();
  expect(fake.count('spot:TSLABUSDT')).toBe(0);  // en spot es una acción tokenizada: ni se piden sus velas

  await page.locator('#market button', { hasText: 'No repetidas' }).click();
  expect((await cards(page)).sort()).toEqual(['AAA/USDT Spot', 'TSLAB/USDT Futuros']);
  await page.locator('#market button', { hasText: 'Futuros' }).click();
  expect((await cards(page)).sort()).toEqual(['AAA/USDT Futuros', 'TSLAB/USDT Futuros']);
});

test('si Binance bloquea futuros (451) lo avisa y sigue con spot', async ({ page, context }) => {
  const fake = new Fake({ futuresBlocked: true });
  await fake.install(context);
  await page.goto(URL);
  await scan(page);
  expect(await cards(page)).toEqual(['AAA/USDT Spot']);
  await expect(page.locator('#notice')).toContainText('451');
});

test('cada cambio de temporalidad vuelve a pedir las velas y el visor también', async ({ page, context }) => {
  const fake = new Fake();
  await fake.install(context);
  await page.goto(URL);
  await scan(page, 'spot');
  await expect(page.locator('#tf button[aria-pressed="true"]')).toHaveText('1D');
  await expect(page.locator('.card .mini canvas').first()).toBeVisible();

  const before = fake.count('spot:AAAUSDT:1h');
  await page.locator('#tf button', { hasText: /^1h$/ }).click();
  await expect.poll(() => fake.count('spot:AAAUSDT:1h')).toBe(before + 1);
  await page.locator('#tf button', { hasText: '1D' }).click();
  await expect.poll(() => fake.count('spot:AAAUSDT:1d')).toBeGreaterThan(1);

  await page.locator('#grid .card').first().click();
  await expect(page.locator('#viewer')).toBeVisible();
  await expect(page.locator('#big canvas').first()).toBeVisible();
  await expect(page.locator('#v-stats')).not.toContainText('null');  // sin filtro de acumulación esa línea no aparece
  const n15 = fake.count('spot:AAAUSDT:15m');
  await page.locator('#v-tf button', { hasText: '15m' }).click();
  await expect.poll(() => fake.count('spot:AAAUSDT:15m')).toBe(n15 + 1);
  await page.keyboard.press('Escape');
  await expect(page.locator('#viewer')).toBeHidden();
});

test('estrellas en las tarjetas y en el visor, en el día del escaneo', async ({ page, context }) => {
  const today = new Date().toISOString().slice(0, 10);  // las pruebas corren en UTC: el día de la vela es el de hoy
  const fake = new Fake({ remote: { dias: [], estrellas: { [today + '|futures:TSLABUSDT']: { activa: true, hora: new Date().toISOString() } } } });
  await fake.install(context);
  await page.goto(URL);
  await scan(page);
  const star = (name, market) => page.locator('#grid .card').filter({ hasText: name }).filter({ hasText: market }).locator('.star');

  await expect(star('TSLAB', 'Futuros')).toHaveAttribute('aria-pressed', 'true');  // guardada en GitHub
  await star('AAA', 'Spot').click();
  await expect(star('AAA', 'Spot')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#viewer')).toBeHidden();  // la estrella no abre el gráfico

  await star('AAA', 'Futuros').focus();
  await page.keyboard.press('Enter');
  await expect(star('AAA', 'Futuros')).toHaveAttribute('aria-pressed', 'true');
  await page.keyboard.press('Enter');
  await expect(star('AAA', 'Futuros')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('#viewer')).toBeHidden();

  await page.locator('#grid .card').filter({ hasText: 'TSLAB' }).click();
  await expect(page.locator('#v-star')).toHaveAttribute('aria-pressed', 'true');
  await page.locator('#v-star').click();
  await expect(page.locator('#v-star')).toHaveAttribute('aria-pressed', 'false');
  await page.locator('#v-star').focus();
  await page.keyboard.press('Escape');  // Esc cierra el visor aunque el foco esté en la estrella
  await expect(page.locator('#viewer')).toBeHidden();
  await expect(star('TSLAB', 'Futuros')).toHaveAttribute('aria-pressed', 'false');

  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('momento-b:estrellas')));
  expect(saved[today + '|spot:AAAUSDT'].activa).toBe(true);
  expect(saved[today + '|futures:AAAUSDT'].activa).toBe(false);
  expect(saved[today + '|futures:TSLABUSDT'].activa).toBe(false);
  await page.reload();
  await scan(page);
  await expect(star('AAA', 'Spot')).toHaveAttribute('aria-pressed', 'true');
});

test('el gráfico ampliado carga el máximo de velas y, hacia atrás, todo el historial', async ({ page, context }) => {
  const fake = new Fake({ history: { 'spot:AAAUSDT:1d': 2600, 'futures:TSLABUSDT:1d': 3200 } });
  await fake.install(context);
  await page.goto(URL);
  await scan(page);
  const reqs = (key) => fake.requests.filter((r) => r.key === key);
  expect(reqs('spot:AAAUSDT:1d').map((r) => r.limit)).toEqual([299]);  // las tarjetas, con las del escaneo

  await page.locator('#grid .card').filter({ hasText: 'AAA' }).filter({ hasText: 'Spot' }).click();
  await expect(page.locator('#v-hist')).toContainText('1000 velas');  // spot: 1000 por petición
  expect(reqs('spot:AAAUSDT:1d').map((r) => r.limit)).toEqual([299, 1000]);
  await page.locator('#v-fit').click();  // «Ver todo el historial»
  await expect(page.locator('#v-hist')).toContainText('Todo el historial: 2600 velas');
  expect(reqs('spot:AAAUSDT:1d').filter((r) => r.endTime != null).length).toBe(2);  // 1000 + 600 anteriores
  await page.keyboard.press('Escape');

  await page.locator('#grid .card').filter({ hasText: 'TSLAB' }).click();
  await expect(page.locator('#v-hist')).toContainText('1500 velas');  // futuros: 1500 por petición
  for (let i = 0; i < 14 && !reqs('futures:TSLABUSDT:1d').some((r) => r.endTime != null); i++) {
    await page.keyboard.press('-');  // alejar hasta el borde izquierdo carga las anteriores
    await page.waitForTimeout(150);
  }
  await expect(page.locator('#v-hist')).toContainText('3000 velas');
  await expect(page.locator('#big canvas').first()).toBeVisible();
});
