// Seguimiento: días según la vela de Binance, columnas, «Rumbo al 50», GitHub y estrellas.
const { test, expect } = require('@playwright/test');
const { Fake, URL, scan, sleep } = require('./fake');

const HOUR = 3600000;
const coin = (simbolo, precio, hora, mercado = 'spot') => ({ mercado, simbolo, base: simbolo.replace(/USDT$/, ''), quote: 'USDT', precio, hora, intervalo: '4h' });
const rowTexts = (page) => page.$$eval('.day', (days) => days.map((d) => d.querySelector('h2').textContent + ': ' +
  [...d.querySelectorAll('tbody tr')].map((tr) => (tr.querySelector('.star').getAttribute('aria-pressed') === 'true' ? '★' : '☆') +
    tr.querySelector('.coin').textContent + ' ' + tr.querySelector('.badge').textContent).join(', ')));

test.describe('en la hora de Lima (UTC-5)', () => {
  test.use({ timezoneId: 'America/Lima' });

  test('cada escaneo va al día con que Binance muestra la vela diaria', async ({ page, context }) => {
    const fake = new Fake();
    await fake.install(context);
    // Antes de las 19:00 de Lima la vela diaria en curso es la del 30-09 (abrió el 1 oct a las 00:00 UTC).
    await page.clock.setFixedTime(new Date('2026-10-01T20:30:00Z'));
    await page.goto(URL);
    await scan(page, 'spot');
    await expect(page.locator('#scan-status')).toContainText('Seguimiento 30 de septiembre');
    await page.clock.setFixedTime(new Date('2026-10-02T00:30:00Z'));  // 19:30 en Lima: ya es la vela del 01-10
    await scan(page, 'spot');
    await expect(page.locator('#scan-status')).toContainText('Seguimiento 1 de octubre');
    await page.locator('#views button', { hasText: 'Seguimiento' }).click();
    await expect(page.locator('#track-note')).toContainText('las 19:00 en tu hora');
    await expect(page.locator('.day h2')).toHaveText(['Seguimiento 1 de octubre', 'Seguimiento 30 de septiembre']);
  });

  test('los días guardados con el criterio anterior se corrigen solos', async ({ page, context }) => {
    const fake = new Fake();
    await fake.install(context);
    await context.addInitScript(() => {
      if (sessionStorage.getItem('pre')) return;
      sessionStorage.setItem('pre', '1');
      localStorage.setItem('momento-b:seguimiento', JSON.stringify({ '2026-10-01': { fecha: '2026-10-01', pendiente: false, monedas: [
        { mercado: 'spot', simbolo: 'AAAUSDT', base: 'AAA', quote: 'USDT', precio: 60, hora: '2026-10-01T17:48:22.461Z', intervalo: '4h' }] } }));
    });
    await page.goto(URL + '#seguimiento');
    await expect(page.locator('.day h2')).toHaveText(['Seguimiento 30 de septiembre']);
    const days = await page.evaluate(() => JSON.parse(localStorage.getItem('momento-b:seguimiento')));
    expect(Object.keys(days)).toEqual(['2026-09-30']);
    expect(days['2026-09-30'].pendiente).toBe(true);  // se sube a su archivo correcto al conectar GitHub
  });
});

// Un día publicado con una moneda que llegó a +50 % 30 h y 7 min después del escaneo y otra que no.
function rumboFake() {
  const start = Math.floor((Date.now() - 50 * HOUR) / 1000) * 1000;
  const hit = start + 30 * HOUR + 7 * 60000;
  const fake = new Fake({
    remote: { dias: [{ fecha: '2026-10-05', monedas: [coin('HITUSDT', 10, new Date(start).toISOString()), coin('NOUSDT', 10, new Date(start).toISOString())] }] },
    prices: { spot: { HITUSDT: 10, NOUSDT: 11 }, futures: {} },
    paths: { 'spot:HITUSDT': { base: 10, spikes: [{ at: hit, high: 16 }] }, 'spot:NOUSDT': { base: 11, spikes: [{ at: start + 5 * HOUR, high: 12 }] } },
  });
  return { fake, start, hit };
}

test('columnas del seguimiento y «Rumbo al 50» con su fecha, en verde', async ({ page, context }) => {
  const { fake, hit } = rumboFake();
  await fake.install(context);
  await page.goto(URL + '#seguimiento');
  await expect(page.locator('.day thead th')).toHaveText(['Moneda', 'Precio 5 oct', 'Precio actual', 'Mínimo', 'Máximo', 'Rumbo al 50', 'Variación', 'Escaneo']);
  const hitRow = page.locator('.day tbody tr', { hasText: 'HIT' });
  const noRow = page.locator('.day tbody tr', { hasText: 'NO/' });
  const date = await page.evaluate((ms) => new Date(Math.floor(ms / 60000) * 60000).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' }), hit);

  await expect(hitRow.locator('.c-r50')).toHaveText('2 días' + date);  // 30 h después: segundo día
  await expect(hitRow).toHaveClass(/hit50/);
  await expect(hitRow.locator('.c-high')).toContainText('+60.00%');
  await expect(hitRow.locator('.c-pct')).toContainText('+0.00%');  // ya bajó, pero sigue en verde
  await expect(noRow.locator('.c-r50')).toHaveText('—');
  await expect(noRow).not.toHaveClass(/hit50/);
  // El +50 % cayó en una vela de 5 minutos: se buscó el minuto exacto con velas de 1 minuto.
  expect(fake.requests.some((r) => r.key === 'spot:HITUSDT:1m' && r.startTime > Date.now() - 25 * HOUR)).toBe(true);
  const title = await hitRow.locator('.c-r50').getAttribute('title');
  expect(title).toContain('2 días después del escaneo');

  await hitRow.click();
  await expect(page.locator('#v-stats')).toContainText('Llegó a +50 % el ' + date + ' (2 días)');
  await page.keyboard.press('Escape');

  await page.setViewportSize({ width: 390, height: 800 });
  await expect(hitRow.locator('.c-r50')).toBeVisible();
  await expect(noRow.locator('.c-r50')).toBeHidden();  // en el móvil solo se muestra si llegó
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('los mínimos y máximos guardados antes de «Rumbo al 50» se recalculan', async ({ page, context }) => {
  const { fake, start } = rumboFake();
  await fake.install(context);
  await context.addInitScript((until) => {
    if (sessionStorage.getItem('pre')) return;
    sessionStorage.setItem('pre', '1');
    // Guardado de la versión anterior: ya sabe que el máximo es 16 pero no cuándo llegó a 15.
    localStorage.setItem('momento-b:seguimiento-rangos', JSON.stringify({
      '2026-10-05|spot|HITUSDT': { low: 10, high: 16, until, checked: Date.now() },
      '2026-10-05|spot|NOUSDT': { low: 10, high: 12, until, checked: Date.now() } }));
  }, Date.now() - 10 * 60000);
  await page.goto(URL + '#seguimiento');
  await expect(page.locator('.day tbody tr', { hasText: 'HIT' }).locator('.c-r50')).toContainText('2 días');
  expect(fake.requests.some((r) => r.key.startsWith('spot:HITUSDT:') && r.startTime <= start + 60000)).toBe(true);  // desde el escaneo
  expect(fake.requests.some((r) => r.key.startsWith('spot:NOUSDT:'))).toBe(false);  // la otra sigue guardada
});

test('GitHub: sube el día, no repite subidas sin cambios y borra', async ({ page, context }) => {
  const fake = new Fake();
  await fake.install(context);
  await page.goto(URL);
  await scan(page);
  await expect(page.locator('#scan-status')).toContainText('de este navegador');
  await page.locator('#views button', { hasText: 'Seguimiento' }).click();
  await page.locator('#track-sync button', { hasText: 'GitHub' }).click();
  await expect(page.locator('#gh-repo')).toHaveValue('luisp11127/Momento-B');
  await page.fill('#gh-token', 'test-token');
  await page.locator('#gh-form button[type="submit"]').click();
  await expect(page.locator('#track-sync')).toContainText('Subido');

  const files = Object.keys(fake.gh.files).filter((f) => /seguimiento\/\d{4}-\d{2}-\d{2}\.json$/.test(f));
  expect(files.length).toBe(1);
  const saved = JSON.parse(fake.gh.files[files[0]].text);
  expect(saved.monedas.map((c) => c.mercado + ':' + c.simbolo).sort()).toEqual(['futures:AAAUSDT', 'futures:TSLABUSDT', 'spot:AAAUSDT']);
  expect(Object.keys(saved.monedas[0])).toEqual(['mercado', 'simbolo', 'base', 'quote', 'precio', 'hora', 'intervalo']);

  fake.gh.log.length = 0;
  await page.locator('#views button', { hasText: 'Escáner' }).click();
  await scan(page);
  await expect(page.locator('#scan-status')).toContainText('y en GitHub.');
  expect(fake.gh.log.filter((l) => l.startsWith('PUT'))).toEqual([]);  // mismas monedas: sin commit vacío

  await page.locator('#views button', { hasText: 'Seguimiento' }).click();
  await page.locator('.day .day-actions button', { hasText: 'Borrar' }).click();
  await page.locator('.day .day-actions button', { hasText: 'Sí, borrar' }).click();
  await expect(page.locator('.day')).toHaveCount(0);
  expect(fake.gh.files[files[0]]).toBeUndefined();
});

test('estrellas: primero en cada día y guardadas en GitHub', async ({ page, context }) => {
  const fake = new Fake();
  await fake.install(context);
  await page.goto(URL);
  await scan(page);
  await page.locator('#grid .card').filter({ hasText: 'AAA' }).filter({ hasText: 'Spot' }).locator('.star').click();
  await page.locator('#views button', { hasText: 'Seguimiento' }).click();
  await page.selectOption('#track-sort', 'bajada');
  await expect.poll(() => rowTexts(page)).toEqual([expect.stringMatching(/★AAA\/USDT Spot, ☆AAA\/USDT Futuros, ☆TSLAB\/USDT Futuros$/)]);

  await page.locator('#track-sync button', { hasText: 'GitHub' }).click();
  await page.fill('#gh-token', 'test-token');
  await page.locator('#gh-form button[type="submit"]').click();
  await expect(page.locator('#track-sync')).toContainText('Subido');
  const stars = () => JSON.parse(fake.gh.files['docs/seguimiento/estrellas.json'].text).estrellas;
  expect(stars()['spot:AAAUSDT'].activa).toBe(true);

  // Desde la tabla: la fila sube con las de estrella y el foco se queda en su estrella.
  const futRow = page.locator('.day tbody tr').filter({ hasText: 'AAA' }).filter({ hasText: 'Futuros' });
  await futRow.locator('.star').click();
  await expect.poll(() => rowTexts(page)).toEqual([expect.stringMatching(/★AAA\/USDT Futuros, ★AAA\/USDT Spot, ☆TSLAB\/USDT Futuros$/)]);
  expect(await page.evaluate(() => document.activeElement.dataset.star)).toBe('futures:AAAUSDT');
  await expect(page.locator('#viewer')).toBeHidden();
  await expect.poll(() => (stars()['futures:AAAUSDT'] || {}).activa, { timeout: 15000 }).toBe(true);  // se sube a los pocos segundos

  // Si GitHub falla queda pendiente, con su botón.
  fake.gh.fail = true;
  await futRow.locator('.star').click();
  await expect(page.locator('#track-sync')).toContainText('No se pudo subir', { timeout: 15000 });
  fake.gh.fail = false;
  await page.locator('#track-sync button', { hasText: 'Subir las estrellas' }).click();
  await expect(page.locator('#track-sync')).toContainText('Subido');
  expect(stars()['futures:AAAUSDT'].activa).toBe(false);

  fake.gh.log.length = 0;
  await page.reload();
  await expect.poll(() => rowTexts(page)).toEqual([expect.stringMatching(/★AAA\/USDT Spot, ☆AAA\/USDT Futuros, ☆TSLAB\/USDT Futuros$/)]);
  await sleep(1000);
  expect(fake.gh.log).toEqual([]);  // nada pendiente: no se llama a GitHub
});
