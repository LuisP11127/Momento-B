// Escaneo robusto: no se congela, aguanta una red inestable y «Detener» responde.
const { test, expect } = require('@playwright/test');
const { Fake, URL, cards, scan } = require('./fake');

test('con GitHub conectado y nada pendiente, el escaneo termina y sube el día', async ({ page, context }) => {
  // Antes la página se congelaba aquí: syncPending se quedaba con una promesa resuelta y se llamaba sin fin.
  const fake = new Fake();
  await fake.install(context);
  await context.addInitScript(() => {
    if (sessionStorage.getItem('pre')) return;
    sessionStorage.setItem('pre', '1');
    localStorage.setItem('momento-b:github', JSON.stringify({ owner: 'LuisP11127', repo: 'Momento-B', branch: 'main', token: 'test-token' }));
  });
  await page.goto(URL);
  await page.waitForTimeout(500);  // la llamada inicial, sin nada que subir
  await scan(page, 'spot');
  await expect(page.locator('#scan-status')).toContainText('y en GitHub.', { timeout: 15000 });
  expect(await cards(page)).toEqual(['AAA/USDT Spot']);
  expect(Object.keys(fake.gh.files).some((f) => /seguimiento\/\d{4}-\d{2}-\d{2}\.json$/.test(f))).toBe(true);
});

test('una red inestable no deja el escaneo colgado', async ({ page, context }) => {
  const fake = new Fake();
  fake.hook = (r) => {
    if (r.tf !== '4h') return undefined;
    if (r.key === 'spot:BBBUSDT:4h' && r.n === 1) return 'hang';  // no responde: se corta a los 20 s y se repite
    if (r.key === 'futures:CCCUSDT:4h' && r.n <= 2) return 'reset';  // se corta la conexión dos veces
    if (r.key === 'futures:AAAUSDT:4h' && r.n === 1) return { status: 429, headers: { 'retry-after': '2', 'access-control-expose-headers': 'retry-after' } };
    if (r.key === 'spot:CCCUSDT:4h') return 'reset';  // nunca responde
    return undefined;
  };
  await fake.install(context);
  await page.goto(URL);
  await scan(page);
  expect((await cards(page)).sort()).toEqual(['AAA/USDT Futuros', 'AAA/USDT Spot', 'TSLAB/USDT Futuros']);
  await expect(page.locator('#notice')).toHaveText('Aviso. Spot: 1 par no respondió (CCCUSDT).');
  expect(fake.count('spot:BBBUSDT:4h')).toBe(2);
  expect(fake.count('futures:CCCUSDT:4h')).toBeGreaterThanOrEqual(3);
  expect(fake.count('spot:CCCUSDT:4h')).toBe(8);  // 4 intentos y otros 4 en la segunda vuelta
});

test('«Detener» corta el escaneo aunque Binance no responda', async ({ page, context }) => {
  const fake = new Fake();
  fake.hook = () => 'hang';
  await fake.install(context);
  await page.goto(URL);
  await page.selectOption('#scan-market', 'spot');
  await page.click('#scan-go');
  await expect(page.locator('#scan-go')).toHaveText('Detener');
  await page.waitForTimeout(2000);
  const t0 = Date.now();
  await page.click('#scan-go');
  await expect(page.locator('#scan-status')).toHaveText('Escaneo detenido.', { timeout: 3000 });
  expect(Date.now() - t0).toBeLessThan(3000);
  await expect(page.locator('#scan-go')).toHaveText('Escanear');
});
