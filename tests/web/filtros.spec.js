// Filtros después del escaneo: solo velas cerradas, cruce reciente y acumulación.
const { test, expect } = require('@playwright/test');
const { Fake, URL, closesOf, candlesFromBodies, cards, scan, maInfo } = require('./fake');

// Velas diarias: relleno de velas de ±8 % y al final las que importan (la última, en curso).
const daily = (tail) => candlesFromBodies([...Array.from({ length: 320 - tail.length }, (_, i) => (i % 2 ? 8 : -8)), ...tail], '1d');
const SHAPES = { AAAUSDT: 'rebound', LASTUSDT: 'lastCandle', SLOWUSDT: 'slowRebound', TSLABUSDT: 'rebound' };

function filterFake() {
  return new Fake({
    stocks: ['ZZZUSDT'],
    markets: { spot: { AAAUSDT: 'rebound', LASTUSDT: 'lastCandle', SLOWUSDT: 'slowRebound', BBBUSDT: 'up' }, futures: { TSLABUSDT: 'rebound' } },
    custom: {
      // 6 velas cerradas seguidas dentro de ±4 % (entre −3,5 % y +3 %) tras una de +10 %; la de hoy (+20 %) no cuenta.
      'spot:AAAUSDT:1d': daily([10, -2, 3, -3.5, 1, 0.5, -1, 20]),
      // Una vela de +5 % hace tres días: con ±4 % solo 2 días seguidos, con ±6 % son 4.
      'spot:LASTUSDT:1d': daily([1, 5, -1, 2, 0]),
      'spot:SLOWUSDT:1d': daily([...Array.from({ length: 20 }, (_, i) => (i % 2 ? 1 : -1)), 0]),
      'futures:TSLABUSDT:1d': candlesFromBodies(Array.from({ length: 320 }, (_, i) => (i % 2 ? 0.5 : -0.5)), '1d'),
    },
  });
}
const name = (symbol) => symbol.replace(/USDT$/, '/USDT') + (symbol === 'TSLABUSDT' ? ' Futuros' : ' Spot');
// Lo que debería quedar según las medias calculadas aquí con las mismas velas que recibe la web (299 de 4h).
function expected(test) {
  return Object.entries(SHAPES).filter(([, shape]) => test(closesOf(shape, 299))).map(([s]) => name(s)).sort();
}

test('solo velas cerradas y cruce reciente', async ({ page, context }) => {
  await filterFake().install(context);
  await page.goto(URL);
  await scan(page);
  expect((await cards(page)).sort()).toEqual(['AAA/USDT Spot', 'LAST/USDT Spot', 'SLOW/USDT Spot', 'TSLAB/USDT Futuros']);
  await expect(page.locator('#f-count')).toHaveText('');

  await page.check('#f-closed');
  const closedOk = expected((c) => maInfo(c.slice(0, -1)).ok);
  expect(closedOk).not.toContain('LAST/USDT Spot');  // solo cumple con la vela que aún se forma
  expect((await cards(page)).sort()).toEqual(closedOk);
  await expect(page.locator('#f-count')).toHaveText('Mostrando ' + closedOk.length + ' de 4');

  await page.uncheck('#f-closed');
  await page.fill('#f-cross-n', '10');  // escribir el número activa el filtro y se aplica sin salir del campo
  await expect(page.locator('#f-cross')).toBeChecked();
  const recent = expected((c) => maInfo(c).bars <= 10);
  expect(recent).not.toContain('SLOW/USDT Spot');  // cruzó hace unas 29 velas
  await expect.poll(async () => (await cards(page)).sort()).toEqual(recent);

  await page.check('#f-closed');
  await page.fill('#f-cross-n', '5');
  await expect.poll(async () => (await cards(page)).sort()).toEqual(expected((c) => { const m = maInfo(c.slice(0, -1)); return m.ok && m.bars <= 5; }));
});

test('acumulación: días seguidos con velas diarias dentro de ±X %', async ({ page, context }) => {
  await filterFake().install(context);
  await page.goto(URL);
  await scan(page);
  await page.locator('#tf button', { hasText: /^4h$/ }).click();

  await page.check('#f-acc');  // por defecto: ±4 % durante al menos 5 días
  await expect(page.locator('#tf button[aria-pressed="true"]')).toHaveText('1D');  // se ve en velas diarias
  expect((await cards(page)).sort()).toEqual(['AAA/USDT Spot', 'SLOW/USDT Spot', 'TSLAB/USDT Futuros']);
  const aaa = page.locator('#grid .card').filter({ hasText: 'AAA' });
  await expect(aaa.locator('.acc-row')).toHaveText('Acumulación 6 días · velas entre -3.50% y +3.00%');
  await expect(page.locator('#grid .card').filter({ hasText: 'TSLAB' }).locator('.acc-row')).toContainText('298 días');

  await page.fill('#f-acc-days', '7');
  await expect.poll(async () => (await cards(page)).sort()).toEqual(['SLOW/USDT Spot', 'TSLAB/USDT Futuros']);

  await page.fill('#f-acc-pct', '6');
  await page.fill('#f-acc-days', '4');
  await expect.poll(async () => (await cards(page)).sort()).toEqual(['AAA/USDT Spot', 'LAST/USDT Spot', 'SLOW/USDT Spot', 'TSLAB/USDT Futuros']);
  await expect(page.locator('#grid .card').filter({ hasText: 'LAST' }).locator('.acc-row')).toHaveText('Acumulación 4 días · velas entre -1.00% y +5.00%');

  await page.locator('#grid .card').filter({ hasText: 'LAST' }).click();  // el foco sigue en el campo: el clic no se pierde
  await expect(page.locator('#v-stats')).toContainText('Acumulación 4 días');
  await page.keyboard.press('Escape');

  await page.fill('#f-acc-days', '500');
  await expect(page.locator('#empty')).toHaveText('Ninguna moneda pasa los filtros.');
  await expect(page.locator('#f-count')).toHaveText('Mostrando 0 de 4');

  // Los filtros se recuerdan en este navegador.
  await page.fill('#f-acc-days', '7');
  await expect(page.locator('#f-count')).toHaveText('Mostrando 2 de 4');
  await page.reload();
  await expect(page.locator('#f-acc')).toBeChecked();
  await expect(page.locator('#f-acc-days')).toHaveValue('7');
  await scan(page);
  expect((await cards(page)).sort()).toEqual(['SLOW/USDT Spot', 'TSLAB/USDT Futuros']);
  await page.uncheck('#f-acc');
  expect((await cards(page)).length).toBe(4);
});
