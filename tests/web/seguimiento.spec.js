// Seguimiento: días según la vela de Binance, columnas, «Rumbo al 50», GitHub y estrellas.
const { test, expect } = require('@playwright/test');
const { Fake, URL, scan, sleep, candles } = require('./fake');

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
    // Velas del gráfico con el mismo precio que la moneda (el visor toma de ahí el precio actual).
    custom: { 'spot:HITUSDT:1d': candles(Array(300).fill(10), '1d'), 'spot:NOUSDT:1d': candles(Array(300).fill(11), '1d') },
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
  await noRow.click();
  await expect(page.locator('#v-stats')).toContainText('Precio entonces');
  await expect(page.locator('#v-stats')).not.toContainText('null');  // la que no llegó: sin esa línea
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

test('estrellas: primero en su día y guardadas en GitHub', async ({ page, context }) => {
  const today = new Date().toISOString().slice(0, 10);  // en UTC, el día de la vela de hoy
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
  expect(stars()[today + '|spot:AAAUSDT'].activa).toBe(true);

  // Desde la tabla: la fila sube con las de estrella y el foco se queda en su estrella.
  const futRow = page.locator('.day tbody tr').filter({ hasText: 'AAA' }).filter({ hasText: 'Futuros' });
  await futRow.locator('.star').click();
  await expect.poll(() => rowTexts(page)).toEqual([expect.stringMatching(/★AAA\/USDT Futuros, ★AAA\/USDT Spot, ☆TSLAB\/USDT Futuros$/)]);
  expect(await page.evaluate(() => document.activeElement.dataset.star)).toBe(today + '|futures:AAAUSDT');
  await expect(page.locator('#viewer')).toBeHidden();
  await expect.poll(() => (stars()[today + '|futures:AAAUSDT'] || {}).activa, { timeout: 15000 }).toBe(true);  // se sube a los pocos segundos

  // Si GitHub falla queda pendiente, con su botón.
  fake.gh.fail = true;
  await futRow.locator('.star').click();
  await expect(page.locator('#track-sync')).toContainText('No se pudo subir', { timeout: 15000 });
  fake.gh.fail = false;
  await page.locator('#track-sync button', { hasText: 'Subir las estrellas' }).click();
  await expect(page.locator('#track-sync')).toContainText('Subido');
  expect(stars()[today + '|futures:AAAUSDT'].activa).toBe(false);

  fake.gh.log.length = 0;
  await page.reload();
  await expect.poll(() => rowTexts(page)).toEqual([expect.stringMatching(/★AAA\/USDT Spot, ☆AAA\/USDT Futuros, ☆TSLAB\/USDT Futuros$/)]);
  await sleep(1000);
  expect(fake.gh.log).toEqual([]);  // nada pendiente: no se llama a GitHub
});

// Dos días con las mismas monedas: el 13 y el 15 de octubre.
function twoDays(extra = {}) {
  const day = (fecha, hora) => ({ fecha, monedas: [coin('AAAUSDT', 1, hora), coin('GNSUSDT', 2, hora)] });
  return new Fake(Object.assign({
    remote: { dias: [day('2026-10-15', '2026-10-15T15:00:00.000Z'), day('2026-10-13', '2026-10-13T15:00:00.000Z')] },
    prices: { spot: { AAAUSDT: 1, GNSUSDT: 2 }, futures: {} },
  }, extra));
}
async function openBothDays(page) {
  await page.goto(URL + '#seguimiento');
  await page.selectOption('#track-sort', 'moneda');
  await page.locator('.day[data-fecha="2026-10-13"] .day-toggle').click();  // por defecto solo está abierto el más reciente
  await expect(page.locator('.day[data-fecha="2026-10-13"] tbody tr')).toHaveCount(2);
}

test('una estrella queda solo en el día donde se pone', async ({ page, context }) => {
  await twoDays().install(context);
  await openBothDays(page);
  expect(await rowTexts(page)).toEqual(['Seguimiento 15 de octubre: ☆AAA/USDT Spot, ☆GNS/USDT Spot', 'Seguimiento 13 de octubre: ☆AAA/USDT Spot, ☆GNS/USDT Spot']);
  await page.locator('.day[data-fecha="2026-10-15"] tbody tr', { hasText: 'GNS' }).locator('.star').click();
  // El 15 la moneda sube con su estrella; el 13 sigue igual.
  expect(await rowTexts(page)).toEqual(['Seguimiento 15 de octubre: ★GNS/USDT Spot, ☆AAA/USDT Spot', 'Seguimiento 13 de octubre: ☆AAA/USDT Spot, ☆GNS/USDT Spot']);
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('momento-b:estrellas')));
  expect(Object.keys(saved)).toEqual(['2026-10-15|spot:GNSUSDT']);
  await expect(page.locator('.day[data-fecha="2026-10-15"] tbody tr', { hasText: 'GNS' }).locator('.star')).toHaveAttribute('title', /Seguimiento 15 de octubre/);
  await page.reload();
  await page.locator('.day[data-fecha="2026-10-13"] .day-toggle').waitFor();
  expect((await rowTexts(page))[0]).toBe('Seguimiento 15 de octubre: ★GNS/USDT Spot, ☆AAA/USDT Spot');
});

test('las estrellas de antes (sin día) pasan al día en que se pusieron', async ({ page, context }) => {
  // GNS se marcó el 15; AAA el 14, que no tiene seguimiento: pasa al último día anterior donde estaba, el 13.
  const fake = twoDays({ remote: Object.assign(twoDays().remote, { estrellas: { 'spot:GNSUSDT': { activa: true, hora: '2026-10-15T18:00:00.000Z' } } }) });
  fake.gh.files['docs/seguimiento/estrellas.json'] = { sha: 'viejo', text: JSON.stringify({ estrellas: { 'spot:GNSUSDT': { activa: true, hora: '2026-10-15T18:00:00.000Z' } } }) };
  await fake.install(context);
  await context.addInitScript(() => {
    if (sessionStorage.getItem('pre')) return;
    sessionStorage.setItem('pre', '1');
    localStorage.setItem('momento-b:estrellas', JSON.stringify({ 'spot:AAAUSDT': { activa: true, hora: '2026-10-14T12:00:00.000Z' },
      'spot:XXXUSDT': { activa: false, hora: '2026-10-14T12:00:00.000Z' } }));
  });
  await openBothDays(page);
  expect(await rowTexts(page)).toEqual(['Seguimiento 15 de octubre: ★GNS/USDT Spot, ☆AAA/USDT Spot', 'Seguimiento 13 de octubre: ★AAA/USDT Spot, ☆GNS/USDT Spot']);
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('momento-b:estrellas')));
  expect(Object.keys(saved)).toEqual(['2026-10-13|spot:AAAUSDT']);  // las quitadas de antes ya no se guardan
  expect(await page.evaluate(() => localStorage.getItem('momento-b:estrellas-pendiente'))).toBe('1');

  // Al conectar GitHub el archivo pasa al formato por día.
  await page.locator('#track-sync button', { hasText: 'GitHub' }).click();
  await page.fill('#gh-token', 'test-token');
  await page.locator('#gh-form button[type="submit"]').click();
  await expect(page.locator('#track-sync')).toContainText('Subido');
  expect(Object.keys(JSON.parse(fake.gh.files['docs/seguimiento/estrellas.json'].text).estrellas)).toEqual(['2026-10-13|spot:AAAUSDT', '2026-10-15|spot:GNSUSDT']);
});

test('sección «Llegaron a +50 %»: todas las que llegaron, primero las de estrella', async ({ page, context }) => {
  const now = Math.floor(Date.now() / 1000) * 1000;
  const d5 = now - 50 * HOUR, d3 = now - 100 * HOUR;  // horas de escaneo del 5 y del 3 de octubre
  const flat = (p) => candles(Array(300).fill(p), '1d');
  const fake = new Fake({
    remote: {
      dias: [
        { fecha: '2026-10-05', monedas: [coin('HITUSDT', 10, new Date(d5).toISOString()), coin('NOUSDT', 10, new Date(d5).toISOString())] },
        { fecha: '2026-10-03', monedas: [coin('AAAUSDT', 10, new Date(d3).toISOString()), coin('GNSUSDT', 10, new Date(d3).toISOString())] },
      ],
      estrellas: { '2026-10-03|spot:GNSUSDT': { activa: true, hora: new Date(d3).toISOString() } },
    },
    prices: { spot: { HITUSDT: 10, NOUSDT: 11, AAAUSDT: 10, GNSUSDT: 10 }, futures: {} },
    paths: {
      'spot:HITUSDT': { base: 10, spikes: [{ at: now - 20 * HOUR, high: 16 }] },   // llegó hace 20 h (30 h tras su escaneo)
      'spot:NOUSDT': { base: 11, spikes: [{ at: now - 30 * HOUR, high: 12 }] },    // +20 %: no llegó
      'spot:AAAUSDT': { base: 10, spikes: [{ at: now - 10 * HOUR, high: 15.5 }] }, // la más reciente
      'spot:GNSUSDT': { base: 10, spikes: [{ at: d3 + 10 * HOUR, high: 20 }] },    // la más antigua, pero con estrella
    },
    custom: { 'spot:HITUSDT:1d': flat(10), 'spot:NOUSDT:1d': flat(11), 'spot:AAAUSDT:1d': flat(10), 'spot:GNSUSDT:1d': flat(10) },
  });
  await fake.install(context);
  await page.goto(URL + '#seguimiento');
  await expect(page.locator('#track-views button')).toHaveText(['Por día', /^Llegaron a \+50 %/]);
  await expect(page.locator('#track-views button').first()).toHaveAttribute('aria-pressed', 'true');

  await page.locator('#track-views button', { hasText: 'Llegaron' }).click();
  const hits = page.locator('.day.hits');
  await expect(hits.locator('.hits-title')).toHaveText('Llegaron a +50 %');
  await expect(page.locator('.day-toggle')).toHaveCount(0);  // los días siguen ahí, en «Por día»
  await expect(page.locator('#track-sort-label')).toBeHidden();
  const rows = () => page.$$eval('.day.hits tbody tr', (trs) => trs.map((tr) => (tr.querySelector('.star').getAttribute('aria-pressed') === 'true' ? '★' : '☆') +
    tr.querySelector('.coin').textContent + ' ' + tr.querySelector('.c-day').textContent + ' ' + tr.querySelector('.c-r50').firstChild.textContent));
  await expect.poll(rows).toEqual(['★GNS/USDT 3 oct 1 día', '☆AAA/USDT 3 oct 4 días', '☆HIT/USDT 5 oct 2 días']);
  await expect(hits.locator('.day-stats')).toContainText('3 de 4 monedas del seguimiento');
  await expect(hits.locator('.day-stats')).toContainText('★ 1 con estrella');
  await expect(hits.locator('.day-stats')).not.toContainText('Revisando');
  await expect(hits.locator('thead th')).toHaveText(['Moneda', 'Seguimiento', 'Precio seguimiento', 'Precio actual', 'Mínimo', 'Máximo', 'Rumbo al 50', 'Variación', 'Escaneo']);
  await expect(page.locator('#track-views button', { hasText: 'Llegaron' }).locator('.count')).toHaveText('3');

  // Estrella desde esta sección: se guarda en el día de esa moneda y sube arriba.
  await hits.locator('tbody tr', { hasText: 'AAA' }).locator('.star').click();
  await expect.poll(rows).toEqual(['★AAA/USDT 3 oct 4 días', '★GNS/USDT 3 oct 1 día', '☆HIT/USDT 5 oct 2 días']);
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('momento-b:estrellas')));
  expect(Object.keys(saved)).toEqual(['2026-10-03|spot:AAAUSDT']);

  // El gráfico se abre con el día de esa moneda.
  await hits.locator('tbody tr', { hasText: 'HIT' }).click();
  await expect(page.locator('#v-stats')).toContainText('Seguimiento 5 de octubre');
  await page.keyboard.press('Escape');

  await page.locator('#track-market button', { hasText: 'Futuros' }).click();
  await expect(hits.locator('.gh-note')).toHaveText('Ninguna moneda del seguimiento ha llegado todavía a +50 %.');
  await page.locator('#track-market button', { hasText: 'Todos' }).click();

  // La vista elegida se recuerda; «Por día» vuelve a los días como siempre.
  await page.reload();
  await expect(page.locator('.day.hits')).toBeVisible();
  await page.locator('#track-views button', { hasText: 'Por día' }).click();
  await expect(page.locator('.day h2')).toHaveText(['Seguimiento 5 de octubre', 'Seguimiento 3 de octubre']);
  await expect(page.locator('#track-sort-label')).toBeVisible();

  await page.setViewportSize({ width: 390, height: 800 });
  await page.locator('#track-views button', { hasText: 'Llegaron' }).click();
  await expect(page.locator('.day.hits tbody tr').first().locator('.c-day')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
