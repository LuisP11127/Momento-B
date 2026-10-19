// Binance, GitHub y GitHub Pages simulados: la web se prueba en Chromium sin salir a internet.
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
// MOMENTO_PAGE permite probar otra versión de la página (por ejemplo, una antigua para ver que una prueba detecta su error).
const PAGE = fs.readFileSync(process.env.MOMENTO_PAGE || path.join(ROOT, 'docs', 'index.html'), 'utf8');
const ICON = fs.readFileSync(path.join(ROOT, 'docs', 'icono.png'));
const LIB = fs.readFileSync(path.join(__dirname, 'node_modules', 'lightweight-charts', 'dist', 'lightweight-charts.standalone.production.js'));

const URL = 'https://luisp11127.github.io/Momento-B/';
const MIN = { '1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60, '2h': 120, '4h': 240, '6h': 360, '8h': 480, '12h': 720, '1d': 1440, '1w': 10080 };
const STEP = (tf) => MIN[tf] * 60000;
const CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-headers': 'authorization,content-type,x-github-api-version,accept',
  'access-control-allow-methods': 'GET,PUT,DELETE,OPTIONS',
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Cierres de prueba, de la vela más antigua (i = 0) a la actual (i = n - 1, todavía abierta).
const SHAPES = {
  rebound: (i, n) => (i < n - 12 ? 200 - i * (150 / (n - 12)) : 50 + 2 * (i - (n - 12))),  // cumple MA7 > MA25 y MA7 < MA99
  up: (i) => 10 + i,        // MA7 por encima de MA99: no cumple
  down: (i) => 300 - i,     // MA7 por debajo de MA25: no cumple
  // Cae despacio y solo la vela abierta sube: cumple solo contando esa vela.
  lastCandle: (i, n) => (i === n - 1 ? 150 : 100 + (n - 2 - i) * 0.5),
  // Cae y lleva 45 velas subiendo despacio: el cruce de MA7 sobre MA25 es antiguo.
  slowRebound: (i, n) => (n - 1 - i < 45 ? 90 + (i - (n - 45)) * 0.5 : 90 + (n - 45 - i) * 2),
};

const closesOf = (shape, n) => Array.from({ length: n }, (_, i) => SHAPES[shape](i, n));

// Velas al estilo Binance alineadas para que la última sea la vela en curso (o la que contiene «now»).
// Volumen de 1000 unidades; las compras a mercado (taker) son el 60 % en las velas verdes y el 40 % en las rojas.
function candles(closes, tf, now = Date.now()) {
  const step = STEP(tf), first = Math.floor(now / step) * step - (closes.length - 1) * step;
  return closes.map((c, i) => {
    const o = i ? closes[i - 1] : c, quote = 1000 * c, buy = quote * (c >= o ? 0.6 : 0.4);
    return [first + i * step, String(o), String(Math.max(o, c) * 1.01), String(Math.min(o, c) * 0.99), String(c), '1000',
      first + (i + 1) * step - 1, String(quote), 1, String(buy / c), String(buy), '0'];
  });
}
// Velas a partir del cuerpo de cada una en % (apertura → cierre), la última en curso.
function candlesFromBodies(bodies, tf, start = 100) {
  const closes = [];
  let price = start;
  for (const b of bodies) { price = price * (1 + b / 100); closes.push(price); }
  const rows = candles(closes, tf);
  rows.forEach((r, i) => { r[1] = String(i ? closes[i - 1] : start); });
  return rows;
}
// Velas de un precio fijo con picos en momentos concretos: para el mínimo, el máximo y «Rumbo al 50».
function pathCandles(p, tf, startTime, endTime, limit) {
  const step = STEP(tf), out = [];
  for (let t = Math.ceil(startTime / step) * step; out.length < limit && t <= Date.now() && (endTime == null || t <= endTime); t += step) {
    let hi = p.base, lo = p.base;
    for (const s of p.spikes || []) if (s.at >= t && s.at < t + step) { hi = Math.max(hi, s.high || hi); lo = Math.min(lo, s.low || lo); }
    out.push([t, String(p.base), String(hi), String(lo), String(p.base), '10', t + step - 1, '0', 1, '0', '0', '0']);
  }
  return out;
}

class Fake {
  constructor(opts = {}) {
    this.scanTf = opts.scanTf || '4h';
    this.markets = opts.markets || {
      spot: { AAAUSDT: 'rebound', BBBUSDT: 'up', CCCUSDT: 'down', TSLABUSDT: 'rebound' },
      futures: { AAAUSDT: 'rebound', BBBUSDT: 'up', CCCUSDT: 'down', TSLABUSDT: 'rebound' },
    };
    this.prices = opts.prices || { spot: { AAAUSDT: 80, BBBUSDT: 1 }, futures: { AAAUSDT: 70, TSLABUSDT: 300 } };
    this.remote = opts.remote || { generado: 'x', dias: [] };
    this.stocks = opts.stocks || ['TSLABUSDT'];
    this.futuresBlocked = !!opts.futuresBlocked;
    this.custom = opts.custom || {};   // "mercado:SÍMBOLO:intervalo" -> velas
    this.paths = opts.paths || {};     // "mercado:SÍMBOLO" -> { base, spikes } (consultas con startTime)
    this.history = opts.history || {}; // "mercado:SÍMBOLO:intervalo" -> velas que tiene la moneda (historial con endTime)
    this.full = {};
    this.books = opts.books || {};     // "mercado:SÍMBOLO" -> { bids, asks } (libro de órdenes)
    this.funding = opts.funding || {}; // "SÍMBOLO" -> última financiación de futuros
    this.hook = null;                  // (petición de velas) -> undefined | 'hang' | 'reset' | { status, headers }
    this.requests = [];                // peticiones de velas
    this.calls = [];                   // otras peticiones a Binance: { mk, path, params }
    this.gh = { files: {}, log: [], fail: false };
  }

  async install(context) {
    await context.route('**/*', (route) => this.handle(route));
  }

  count(prefix) { return this.requests.filter((r) => r.key.startsWith(prefix)).length; }

  json(route, body, status = 200, headers = {}) {
    return route.fulfill({ status, body: JSON.stringify(body), contentType: 'application/json', headers: Object.assign({}, CORS, headers) });
  }

  async handle(route) {
    const req = route.request();
    const url = new globalThis.URL(req.url());
    if (url.href.includes('lightweight-charts')) {
      return route.fulfill({ body: LIB, contentType: 'application/javascript', headers: { 'access-control-allow-origin': '*' } });
    }
    if (url.host === 'luisp11127.github.io') {
      if (url.pathname === '/Momento-B/' || url.pathname === '/Momento-B/index.html') return route.fulfill({ body: PAGE, contentType: 'text/html' });
      if (url.pathname === '/Momento-B/icono.png') return route.fulfill({ body: ICON, contentType: 'image/png' });
      if (url.pathname === '/Momento-B/seguimiento.json') return this.json(route, this.remote);
      if (url.pathname === '/Momento-B/bstocks.json') return this.json(route, { simbolos: this.stocks });
      return route.fulfill({ status: 404, body: 'no' });
    }
    if (url.host === 'api.github.com') return this.github(route, req, url);
    if (url.host === 'api.binance.com' || url.host === 'fapi.binance.com') return this.binance(route, url);
    return route.abort();  // fuentes de Google, www.binance.com (sin CORS)…
  }

  github(route, req, url) {
    if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: CORS });
    if (req.headers()['authorization'] !== 'Bearer test-token') return this.json(route, { message: 'Bad credentials' }, 401);
    const file = decodeURIComponent(url.pathname).replace('/repos/LuisP11127/Momento-B/contents/', '');
    this.gh.log.push(req.method() + ' ' + file);
    if (url.pathname.toLowerCase() === '/repos/luisp11127/momento-b') return this.json(route, { full_name: 'LuisP11127/Momento-B', default_branch: 'main' });
    if (!url.pathname.startsWith('/repos/LuisP11127/Momento-B/contents/')) return this.json(route, { message: 'Not Found' }, 404);
    const files = this.gh.files;
    if (req.method() === 'GET') {
      if (!files[file]) return this.json(route, { message: 'Not Found' }, 404);
      return this.json(route, { sha: files[file].sha, content: Buffer.from(files[file].text).toString('base64').replace(/(.{60})/g, '$1\n') });
    }
    const body = JSON.parse(req.postData());
    if (req.method() === 'PUT') {
      if (this.gh.fail) return this.json(route, { message: 'Server Error' }, 500);
      if (files[file] && body.sha !== files[file].sha) return this.json(route, { message: 'sha mismatch' }, 409);
      files[file] = { sha: 'sha' + Math.random().toString(36).slice(2, 8), text: Buffer.from(body.content, 'base64').toString('utf8'), message: body.message };
      return this.json(route, { content: { sha: files[file].sha } }, 201);
    }
    if (req.method() === 'DELETE') { delete files[file]; return this.json(route, { commit: {} }); }
    return this.json(route, { message: 'Not Found' }, 404);
  }

  async binance(route, url) {
    const mk = url.host === 'api.binance.com' ? 'spot' : 'futures';
    if (mk === 'futures' && this.futuresBlocked) return this.json(route, { msg: 'Service unavailable from a restricted location' }, 451);
    const symbols = this.markets[mk] || {};
    if (url.pathname.endsWith('/exchangeInfo')) {
      return this.json(route, { rateLimits: [], symbols: [...Object.keys(symbols), 'USDCUSDT'].map((s) => ({
        symbol: s, status: 'TRADING', baseAsset: s.replace(/USDT$/, ''), quoteAsset: 'USDT', isSpotTradingAllowed: true,
        contractType: 'PERPETUAL', underlyingType: 'COIN' })) });
    }
    if (url.pathname.endsWith('/ticker/24hr')) return this.json(route, Object.keys(symbols).map((s) => ({ symbol: s, quoteVolume: '5000000', priceChangePercent: '2.5' })));
    if (url.pathname.endsWith('/ticker/price')) return this.json(route, Object.entries(this.prices[mk] || {}).map(([symbol, price]) => ({ symbol, price: String(price) })));
    if (!url.pathname.endsWith('/klines')) return this.extra(route, mk, url);

    const q = url.searchParams, symbol = q.get('symbol'), tf = q.get('interval'), limit = +q.get('limit');
    const info = { mk, symbol, tf, limit, startTime: q.has('startTime') ? +q.get('startTime') : null,
      endTime: q.has('endTime') ? +q.get('endTime') : null, key: mk + ':' + symbol + ':' + tf };
    info.n = this.requests.filter((r) => r.key === info.key).length + 1;
    this.requests.push(info);
    const action = this.hook && this.hook(info);
    if (action === 'hang') { await sleep(40000); return route.fulfill({ status: 200, body: '[]' }).catch(() => {}); }
    if (action === 'reset') return route.abort('connectionreset');
    if (action && action.status) return this.json(route, { code: -1, msg: 'error' }, action.status, action.headers || {});

    const pathDef = this.paths[mk + ':' + symbol];
    if (pathDef && info.startTime != null) return this.json(route, pathCandles(pathDef, tf, info.startTime, info.endTime, limit));
    const total = this.history[info.key];
    if (total) {  // como Binance: las últimas «limit» velas que abren antes de endTime
      const full = this.full[info.key] || (this.full[info.key] = candles(closesOf('rebound', total), tf));
      return this.json(route, (info.endTime != null ? full.filter((r) => r[0] <= info.endTime) : full).slice(-limit));
    }
    const custom = this.custom[info.key];
    if (custom) return this.json(route, (info.endTime != null ? custom.filter((r) => r[0] <= info.endTime) : custom).slice(-limit));
    const shape = tf === this.scanTf ? (symbols[symbol] || 'up') : 'rebound';
    return this.json(route, candles(closesOf(shape, limit), tf, info.endTime != null ? info.endTime : undefined));
  }

  // Libro de órdenes, financiación e interés abierto (futuros).
  extra(route, mk, url) {
    const q = url.searchParams, symbol = q.get('symbol'), params = Object.fromEntries(q);
    const path = url.pathname.replace(/^\/(api\/v3|fapi\/v1|futures\/data)\//, '');
    this.calls.push({ mk, path, params });
    if (path === 'depth') {
      const book = this.books[mk + ':' + symbol];
      if (book) return this.json(route, { lastUpdateId: 1, bids: book.bids.map(([p, v]) => [String(p), String(v)]), asks: book.asks.map(([p, v]) => [String(p), String(v)]) });
      const mid = (this.prices[mk] || {})[symbol] || 100, side = (dir) => Array.from({ length: 100 }, (_, i) => [String(mid * (1 + dir * 0.001 * (i + 1))), '10']);
      return this.json(route, { lastUpdateId: 1, bids: side(-1), asks: side(1) });
    }
    if (mk !== 'futures') return route.abort();
    if (path === 'premiumIndex') {
      return this.json(route, Object.keys(this.markets.futures || {}).map((s) => ({ symbol: s, lastFundingRate: String(this.funding[s] ?? 0.0001) })));
    }
    if (path === 'fundingRate') {
      const end = +q.get('endTime') || Date.now();
      return this.json(route, [{ symbol, fundingRate: String(this.funding[symbol] ?? 0.0001), fundingTime: end - 3600000 }]);
    }
    if (path === 'openInterestHist') {  // cada hora: contratos de 1000 a 1100 y precio de 100 a 105
      const end = +q.get('endTime') || Date.now(), start = +q.get('startTime') || end - 25 * 3600000, hour = 3600000;
      const out = [];
      for (let t = Math.ceil(start / hour) * hour; t <= end; t += hour) out.push(t);
      return this.json(route, out.map((t, i) => {
        const oi = 1000 + 100 * i / Math.max(1, out.length - 1), px = 100 + 5 * i / Math.max(1, out.length - 1);
        return { symbol, sumOpenInterest: String(oi), sumOpenInterestValue: String(oi * px), timestamp: t };
      }));
    }
    return route.abort();
  }
}

// Lo que se ve en la página.
const cards = (page) => page.$$eval('#grid .card', (els) => els.map((c) => c.querySelector('.sym').textContent + ' ' + c.querySelector('.badge').textContent));
async function scan(page, market) {
  if (market) await page.selectOption('#scan-market', market);
  await page.click('#scan-go');
  await page.waitForFunction(() => /terminado/.test(document.getElementById('scan-status').textContent), null, { timeout: 60000 });
}

// Medias simples y velas con MA rápida sobre la media, calculadas aquí por separado para comparar con la web.
function sma(values, p) {
  return values.map((_, i) => (i < p - 1 ? null : values.slice(i - p + 1, i + 1).reduce((a, b) => a + b, 0) / p));
}
function maInfo(closes, [fp, mp, sp] = [7, 25, 99]) {
  const f = sma(closes, fp), m = sma(closes, mp), s = sma(closes, sp), i = closes.length - 1;
  let bars = 0;
  for (let j = i; j >= 0 && f[j] != null && m[j] != null && f[j] > m[j]; j--) bars++;
  return { ok: f[i] > m[i] && f[i] < s[i], bars };
}

module.exports = { Fake, URL, STEP, SHAPES, closesOf, candles, candlesFromBodies, cards, scan, maInfo, sleep };
