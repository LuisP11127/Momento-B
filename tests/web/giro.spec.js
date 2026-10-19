// Indicador de giro: puntuación al escanear, libro de órdenes guardado y análisis del historial.
const { test, expect } = require('@playwright/test');
const { Fake, URL, candles, closesOf, scan } = require('./fake');

const giroOf = (page) => page.$$eval('#grid .card', (els) => Object.fromEntries(els.map((c) =>
  [c.querySelector('.sym').textContent + ' ' + c.querySelector('.badge').textContent, (c.querySelector('.giro') || {}).textContent])));

test('puntuación de giro en las tarjetas, el orden y el visor; se guarda con el libro de órdenes', async ({ page, context }) => {
  // AAA de spot con compras a mercado de justo la mitad del volumen; un libro de órdenes hecho a mano.
  const half = candles(closesOf('rebound', 299), '4h').map((k) => { const r = [...k]; r[10] = String(+r[7] / 2); return r; });
  const fake = new Fake({
    funding: { AAAUSDT: 0.001, TSLABUSDT: -0.0002 },
    custom: { 'spot:AAAUSDT:4h': half },
    books: { 'spot:AAAUSDT': { bids: [[99, 10], [98.5, 100], [97, 5]], asks: [[101, 10], [103, 1000]] } },
  });
  await fake.install(context);
  await page.goto(URL);
  await scan(page);
  const giro = await giroOf(page);
  expect(Object.keys(giro).sort()).toEqual(['AAA/USDT Futuros', 'AAA/USDT Spot', 'TSLAB/USDT Futuros']);
  for (const text of Object.values(giro)) expect(text).toMatch(/^Giro \d+$/);

  const days = await page.evaluate(() => JSON.parse(localStorage.getItem('momento-b:seguimiento')));
  const coins = Object.fromEntries(Object.values(days)[0].monedas.map((c) => [c.mercado + ':' + c.simbolo, c]));
  const spot = coins['spot:AAAUSDT'].giro, aaa = coins['futures:AAAUSDT'].giro, tslab = coins['futures:TSLABUSDT'].giro;
  expect(spot.v).toBe(1);
  expect(spot.partes.futuros).toBeUndefined();  // en spot no hay interés abierto ni financiación
  // Compras al 50 %: 1/3 por el nivel y 1/2 porque no cambian (media 0,42); en futuros, 60 % en las verdes.
  expect(spot.partes.flujo).toBe(0.42);
  expect(aaa.partes.flujo).toBe(1);
  // Interés abierto +10 % con el precio +5 %: 0,87; financiación negativa +0,1, muy positiva −0,15.
  expect(tslab.partes.futuros).toBe(0.97);
  expect(aaa.partes.futuros).toBe(0.72);
  expect(giro['TSLAB/USDT Futuros']).toBe('Giro ' + tslab.puntos);

  // Libro: 3 lecturas por moneda; precio medio 100 y diferencial del 2 %.
  expect(fake.calls.filter((c) => c.path === 'depth').length).toBe(9);
  expect(coins['spot:AAAUSDT'].libro).toEqual({
    lecturas: 3, spread: 2,
    compras: { bandas: { '1%': 990, '2%': 10840, '5%': 11325 }, alcance: 3, muro: { precio: 98.5, dist: -1.5, usdt: 9850, veces: 9.95, lecturas: 3 } },
    ventas: { bandas: { '1%': 1010, '2%': 1010, '5%': 104010 }, alcance: 3, muro: { precio: 103, dist: 3, usdt: 103000, veces: 1, lecturas: 3 } },
  });
  expect(coins['futures:TSLABUSDT'].libro.lecturas).toBe(3);

  await page.selectOption('#sort', 'giro');
  const scores = await page.$$eval('#grid .card .giro', (els) => els.map((e) => +e.textContent.replace('Giro ', '')));
  expect(scores).toEqual([...scores].sort((a, b) => b - a));

  await page.locator('#grid .card').filter({ hasText: 'TSLAB' }).click();
  await expect(page.locator('#v-giro')).toContainText('Giro ' + tslab.puntos);
  await expect(page.locator('#v-giro')).toContainText('Futuros 97');
  await page.keyboard.press('Escape');
  await page.locator('#grid .card').filter({ hasText: 'AAA' }).filter({ hasText: 'Spot' }).click();
  await expect(page.locator('#v-giro')).toContainText('Flujo comprador 42');
  await expect(page.locator('#v-giro')).not.toContainText('Futuros');
});

test('sin «Guardar en seguimiento» no se lee el libro de órdenes', async ({ page, context }) => {
  const fake = new Fake();
  await fake.install(context);
  await page.goto(URL);
  await page.uncheck('#scan-track');
  await scan(page, 'spot');
  await expect(page.locator('#grid .card .giro')).toHaveText(/^Giro \d+$/);
  expect(fake.calls.filter((c) => c.path === 'depth').length).toBe(0);
});

test('analizar el historial: resultado a 7 días, «Rumbo al 50» y pesos propuestos guardados en GitHub', async ({ page, context }) => {
  // 16 monedas que venían rebotando y subieron (+25 %, cuatro hasta +60 %) y 16 que venían cayendo y cayeron −15 %,
  // escaneadas hace 9 y 10 días en velas diarias; y una de futuros.
  const hour = 3600000, now = Date.now();
  const id = (i) => String(i + 1).padStart(2, '0');
  const ups = Array.from({ length: 16 }, (_, i) => 'UP' + id(i) + 'USDT'), downs = Array.from({ length: 16 }, (_, i) => 'DN' + id(i) + 'USDT');
  const markets = { spot: {}, futures: { FUTUSDT: 'rebound' } }, paths = {}, byDay = {};
  [...ups, ...downs, 'FUTUSDT'].forEach((s, i) => {
    const up = !s.startsWith('DN'), mercado = s === 'FUTUSDT' ? 'futures' : 'spot';
    if (mercado === 'spot') markets.spot[s] = up ? 'rebound' : 'down';
    const hora = now - (i % 2 ? 9 : 10) * 24 * hour - 3 * hour;
    const fecha = new Date(hora).toISOString().slice(0, 10);
    paths[mercado + ':' + s] = { base: 100, spikes: [up ? { at: hora + 48 * hour, high: ups.indexOf(s) >= 0 && ups.indexOf(s) < 4 ? 160 : 125 } : { at: hora + 24 * hour, low: 85 }] };
    (byDay[fecha] = byDay[fecha] || []).push({ mercado, simbolo: s, base: s.replace(/USDT$/, ''), quote: 'USDT', precio: 100, hora: new Date(hora).toISOString(), intervalo: '1d' });
  });
  const fake = new Fake({ scanTf: '1d', markets, paths, prices: { spot: {}, futures: {} },
    remote: { dias: Object.entries(byDay).map(([fecha, monedas]) => ({ fecha, monedas })), estrellas: {} } });
  await fake.install(context);
  await context.addInitScript(() => {
    if (sessionStorage.getItem('pre')) return;
    sessionStorage.setItem('pre', '1');
    localStorage.setItem('momento-b:github', JSON.stringify({ owner: 'LuisP11127', repo: 'Momento-B', branch: 'main', token: 'test-token' }));
  });
  await page.goto(URL + '#seguimiento');
  await page.locator('#track-views button', { hasText: 'Indicador de giro' }).click();
  const box = page.locator('.giro-calib');
  await expect(box).toContainText('0 de 33 entradas analizadas');
  await box.locator('button', { hasText: 'Analizar historial' }).click();
  await expect(box.locator('.day-stats')).toContainText('33 de 33 entradas analizadas', { timeout: 30000 });
  await expect(box.locator('.day-stats')).toContainText('33 con resultado');

  // Las puntuaciones se calculan con las velas cerradas antes de cada escaneo (endTime) y el resultado, desde él.
  const scanTimes = new Set(Object.values(byDay).flat().map((c) => Date.parse(c.hora) - 1));
  const daily = fake.requests.filter((r) => r.tf === '1d' && r.symbol !== 'BTCUSDT');
  expect(daily.length).toBe(33);
  for (const r of daily) expect(scanTimes.has(r.endTime)).toBe(true);
  const starts = new Set(Object.values(byDay).flat().map((c) => Math.floor(Date.parse(c.hora) / 900000) * 900000));
  const outcome = fake.requests.filter((r) => r.tf === '15m' && r.limit === 673);  // 7 días de velas de 15 minutos
  expect(outcome.length).toBe(33);
  for (const r of outcome) expect(starts.has(r.startTime)).toBe(true);
  // Futuros: interés abierto y financiación de antes del escaneo.
  const fut = byDay[Object.keys(byDay).find((f) => byDay[f].some((c) => c.simbolo === 'FUTUSDT'))].find((c) => c.simbolo === 'FUTUSDT');
  for (const path of ['openInterestHist', 'fundingRate']) {
    expect(fake.calls.find((c) => c.path === path && c.params.symbol === 'FUTUSDT').params.endTime).toBe(String(Date.parse(fut.hora)));
  }

  await expect(box.locator('.headline').first()).toHaveText('De las 33 entradas con resultado, el 52 % llegó a +20 % en los 7 días siguientes sin caer antes un −10 %.');
  await expect(box.locator('.headline').nth(1)).toHaveText('Con puntuación ≥ 70: el 100 % (17 de 17) llegó a +20 % en una semana, frente al 0 % del resto (0 de 16).');
  const buckets = box.locator('.calib').first().locator('tbody tr');
  await expect(buckets.first()).toContainText('70–100');
  await expect(buckets.first().locator('td').nth(1)).toHaveText('17');
  await expect(buckets.first().locator('td').nth(3)).toHaveText('24 %4/17');  // «Rumbo al 50»: las cuatro de +60 %

  // Partes que separan: peso 2; las que valen igual en todas, sin datos para medirlas.
  const partRow = (name) => box.locator('.calib').nth(1).locator('tbody tr').filter({ hasText: name });
  await expect(partRow('Estructura').locator('td').nth(4)).toHaveText('+100 pts');
  await expect(partRow('Estructura').locator('td').nth(5)).toHaveText('2');
  await expect(partRow('BTC').locator('td').nth(4)).toHaveText('faltan datos');
  await expect(partRow('BTC').locator('td').nth(5)).toHaveText('0,5');

  await box.locator('button', { hasText: 'Aplicar pesos propuestos' }).click();
  await expect(partRow('Estructura').locator('td').nth(1)).toHaveText('2');
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('momento-b:giro-pesos')));
  expect(saved.pesos.estructura).toBe(2);
  await expect.poll(() => fake.gh.files['docs/seguimiento/giro.json'] && JSON.parse(fake.gh.files['docs/seguimiento/giro.json'].text).pesos.estructura).toBe(2);
  expect(fake.gh.files['docs/seguimiento/giro.json'].message).toBe('Pesos del indicador de giro');

  // La columna «Giro» de cada día muestra la puntuación de cada moneda.
  await page.locator('#track-views button', { hasText: 'Por día' }).click();
  const up02 = page.locator('.day tbody tr').filter({ hasText: 'UP02' });  // del día más reciente, el que está abierto
  await expect(up02.locator('.c-giro')).toHaveText(/^\d+$/);
  expect(+(await up02.locator('.c-giro').textContent())).toBeGreaterThanOrEqual(70);

  // Al volver, el análisis está guardado: no se vuelve a pedir nada.
  const before = fake.requests.length;
  await page.reload();
  await page.locator('#track-views button', { hasText: 'Indicador de giro' }).click();
  await expect(box.locator('.day-stats')).toContainText('33 de 33 entradas analizadas');
  await page.waitForTimeout(1000);
  expect(fake.requests.filter((r, i) => i >= before && (r.tf === '15m' || r.endTime != null)).length).toBe(0);
  await expect(box.locator('button', { hasText: 'Volver a los pesos por defecto' })).toBeVisible();
});
