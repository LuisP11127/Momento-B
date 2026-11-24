"""Escaneo diario (momento_b/diario.py): su indicador de giro y su libro de órdenes dan lo mismo que la web.

Se ejecutan las funciones de la propia página (momento_b/report_template.html) con Node y se comparan con
momento_b/giro.py sobre las mismas velas. Sin Node, la comparación se salta.
"""

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from momento_b import diario, giro
from momento_b.binance import BinanceFatalError

TEMPLATE = Path(__file__).resolve().parents[1] / "momento_b" / "report_template.html"


def between(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def run_web(cases):
    node = shutil.which("node")
    if not node:
        pytest.skip("sin Node no se puede ejecutar el código de la web")
    html = TEMPLATE.read_text(encoding="utf-8")
    code = "\n".join([
        between(html, "  function sma(values, period) {", "  function tokens() {"),
        between(html, "  const GIRO_VERSION = 1;", "  const giroLevel"),
        between(html, "  const BOOK_READS = 3", "  async function scanMarket("),
        """
        const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
        const out = input.map((c) => c.depths
          ? bookSummary(c.depths.map(bookMetrics))
          : (() => { const p = giroParts(c.rows, c.conf, c.btc, c.fut); return { partes: p, puntos: giroScore(p, c.weights) }; })());
        process.stdout.write(JSON.stringify(out));
        """,
    ])
    res = subprocess.run([node, "-e", code], input=json.dumps(cases), capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def candles(rnd, n, drift, taker=True, tf=86400000):
    price, rows = 100.0, []
    for i in range(n):
        o = price
        price = max(0.01, price * (1 + rnd.gauss(drift, 0.04)))
        c = price
        vol = rnd.uniform(500, 5000) * (2.5 if i > n - 5 and drift > 0 else 1)
        quote = vol * c
        buy = quote * rnd.uniform(0.35, 0.65)
        rows.append([i * tf, o, max(o, c) * 1.01, min(o, c) * 0.99, c, vol, quote if taker else None, buy if taker else None])
    return rows


def test_giro_matches_the_web():
    rnd = random.Random(7)
    weights = dict(giro.GIRO_DEFAULT)
    cases = []
    for k in range(40):
        drift = [-0.01, 0.0, 0.01, 0.03][k % 4]
        n = [299, 120, 30, 29][k % 7 % 4]
        fut = None
        if k % 3 == 0:
            oi = [[1000 + rnd.uniform(-200, 200), 0] for _ in range(25)]
            for pair in oi:
                pair[1] = pair[0] * rnd.uniform(90, 110)
            fut = {"oi": oi, "funding": [None, -0.0002, 0.0001, 0.001][k % 4]}
        cases.append({"rows": candles(rnd, n, drift, taker=k % 5 != 0), "conf": candles(rnd, 60, drift),
                      "btc": candles(rnd, [120, 20][k % 2], 0.005), "fut": fut,
                      "weights": weights if k % 2 else {**weights, "flujo": 0, "volumen": 2}})
    web = run_web(cases)
    for case, expected in zip(cases, web):
        parts = giro.giro_parts(case["rows"], case["conf"], case["btc"], case["fut"])
        assert parts == expected["partes"]
        assert giro.giro_score(parts, case["weights"]) == expected["puntos"]
    assert sum(1 for e in web if e["partes"]) >= 25  # la mayoría tiene velas suficientes
    assert any(e["partes"] and "futuros" in e["partes"] for e in web)
    assert any(e["partes"] and "flujo" not in e["partes"] for e in web)  # velas sin compras taker


def test_order_book_matches_the_web():
    rnd = random.Random(3)
    cases = []
    for _ in range(10):
        reads = []
        for _ in range(3):
            mid = 100 * rnd.uniform(0.99, 1.01)
            bids = [[f"{mid * (1 - 0.0007 * (i + 1)):.6f}", f"{rnd.uniform(1, 50) * (30 if i == 17 else 1):.3f}"] for i in range(100)]
            asks = [[f"{mid * (1 + 0.0009 * (i + 1)):.6f}", f"{rnd.uniform(1, 50):.3f}"] for i in range(100)]
            reads.append({"bids": bids, "asks": asks})
        cases.append({"depths": reads})
    cases.append({"depths": [{"bids": [["99", "10"], ["98.5", "100"], ["97", "5"]], "asks": [["101", "10"], ["103", "1000"]]}]})
    web = run_web(cases)
    for case, expected in zip(cases, web):
        assert giro.book_summary([giro.book_metrics(d) for d in case["depths"]]) == expected
    assert web[-1]["compras"]["muro"] == {"precio": 98.5, "dist": -1.5, "usdt": 9850, "veces": 9.95, "lecturas": 1}


def test_js_round_rounds_halves_up():
    assert giro.js_round(0.5) == 1 and giro.js_round(2.5) == 3 and giro.js_round(-1.5) == -1


# ---------- escaneo diario (momento_b/diario.py) ----------

DAY = 86400000


def kline(t, o, c, vol=1000.0, buy_share=0.6):
    quote = vol * c
    return [t, str(o), str(max(o, c) * 1.01), str(min(o, c) * 0.99), str(c), str(vol), t + DAY - 1,
            str(quote), 1, "0", str(quote * buy_share), "0"]


def rebound(n, step, now):
    """Cae y las 12 últimas velas suben: cumple MA7 > MA25 y MA7 < MA99. La última sigue abierta."""
    first = (now // step) * step - (n - 1) * step
    closes = [200 - i * (150 / (n - 12)) if i < n - 12 else 50 + 2 * (i - (n - 12)) for i in range(n)]
    return [kline(first + i * step, closes[i - 1] if i else closes[0], closes[i]) for i in range(n)]


class FakeClient:
    def __init__(self, market, now, blocked=False):
        self.market, self.now, self.blocked, self.calls = market, now, blocked, []

    def exchange_info(self):
        if self.blocked:
            raise BinanceFatalError("451 ubicación restringida")
        return {"symbols": [{"symbol": s, "status": "TRADING", "baseAsset": s[:-4], "quoteAsset": "USDT",
                             "contractType": "PERPETUAL", "underlyingType": "COIN"} for s in ("AAAUSDT", "BBBUSDT")]}

    def asset_tags(self):
        return {}

    def tickers_24h(self):
        return [{"symbol": s, "quoteVolume": "5000000", "priceChangePercent": "2"} for s in ("AAAUSDT", "BBBUSDT")]

    def klines(self, symbol, interval, limit):
        step = {"1d": DAY, "4h": DAY // 6}[interval]
        if symbol == "BBBUSDT":  # sube siempre: no cumple
            first = (self.now // step) * step - (limit - 1) * step
            return [kline(first + i * step, 10 + i, 11 + i) for i in range(limit)]
        return rebound(limit, step, self.now)

    def get(self, path, params=None, weight=1):
        self.calls.append(path)
        if path.endswith("/depth"):
            return {"bids": [["99", "10"], ["98.5", "100"], ["97", "5"]], "asks": [["101", "10"], ["103", "1000"]]}
        if path.endswith("premiumIndex"):
            return [{"symbol": "AAAUSDT", "lastFundingRate": "-0.0002"}]
        if path.endswith("openInterestHist"):
            return [{"sumOpenInterest": str(1000 + 4 * i), "sumOpenInterestValue": str((1000 + 4 * i) * (100 + 0.2 * i)),
                     "timestamp": params["endTime"] - (24 - i) * 3600000} for i in range(25)]
        raise AssertionError(path)


def test_load_settings_uses_the_last_web_scan(tmp_path):
    assert diario.load_settings(tmp_path) == diario.DEFAULTS
    (tmp_path / "escaneo.json").write_text(json.dumps(
        {"mercado": "futures", "intervalo": "4h", "volumen_min": 2000000, "zona": "Europe/Madrid"}), encoding="utf-8")
    assert diario.load_settings(tmp_path) == {"mercado": "futures", "intervalo": "4h", "volumen_min": 2000000, "zona": "Europe/Madrid"}
    (tmp_path / "escaneo.json").write_text(json.dumps(
        {"mercado": "x", "intervalo": "9h", "volumen_min": -1, "zona": "Marte/Base"}), encoding="utf-8")
    assert diario.load_settings(tmp_path) == diario.DEFAULTS


def test_day_key_is_the_binance_daily_candle_in_local_time():
    # 16:00 UTC del 25 de noviembre: la vela diaria abrió a las 00:00 UTC, que en Lima son las 19:00 del 24.
    ms = 1795564800000 + 16 * 3600000  # 2026-11-25T16:00:00Z
    assert diario.iso_ms(ms) == "2026-11-25T16:00:00.000Z"
    assert diario.day_key(ms, "America/Lima") == "2026-11-24"
    assert diario.day_key(ms, "UTC") == "2026-11-25"
    assert diario.day_key(ms, "Europe/Madrid") == "2026-11-25"


def test_merge_day_keeps_the_first_price_of_each_coin():
    existing = {"fecha": "2026-11-24", "monedas": [
        {"mercado": "spot", "simbolo": "AAAUSDT", "precio": 1.0, "hora": "2026-11-24T20:00:00.000Z", "libro": {"lecturas": 3}},
        {"mercado": "futures", "simbolo": "AAAUSDT", "precio": 2, "hora": "2026-11-25T18:00:00.000Z"}]}
    scanned = [{"mercado": "spot", "simbolo": "AAAUSDT", "precio": 5, "hora": "2026-11-25T16:00:00.000Z"},
               {"mercado": "futures", "simbolo": "AAAUSDT", "precio": 3, "hora": "2026-11-25T16:00:00.000Z"},
               {"mercado": "spot", "simbolo": "CCCUSDT", "precio": 0.5, "hora": "2026-11-25T16:00:00.000Z"}]
    day, added = diario.merge_day(existing, "2026-11-24", scanned)
    assert added == 1
    assert [(c["mercado"], c["simbolo"], c["precio"]) for c in day["monedas"]] == [
        ("spot", "AAAUSDT", 1), ("futures", "AAAUSDT", 3), ("spot", "CCCUSDT", 0.5)]
    assert day["monedas"][0]["libro"] == {"lecturas": 3}
    assert '"precio": 1,' in diario.day_text(day)  # sin «.0», como la web


def test_scan_day_saves_coins_with_giro_and_order_book(tmp_path, monkeypatch):
    now = 1795564800000 + 16 * 3600000
    clients = {}

    def factory(market):
        clients[market.key] = FakeClient(market, now)
        return clients[market.key]

    settings = dict(diario.DEFAULTS)
    day, notes, failed = diario.scan_day(settings, giro.giro_weights(None), client_factory=factory,
                                         now_ms=lambda: now, sleep=lambda s: None, log=lambda m: None)
    assert failed == [] and notes == []
    assert day["fecha"] == "2026-11-24"
    assert [(c["mercado"], c["simbolo"]) for c in day["monedas"]] == [("spot", "AAAUSDT"), ("futures", "AAAUSDT")]
    spot, fut = day["monedas"]
    assert list(spot) == ["mercado", "simbolo", "base", "quote", "precio", "hora", "intervalo", "giro", "libro"]
    assert spot["hora"] == "2026-11-25T16:00:00.000Z" and spot["intervalo"] == "1d" and spot["precio"] == 72
    assert spot["giro"]["v"] == 1 and "futuros" not in spot["giro"]["partes"]
    # +9,6 % de contratos con el precio subiendo: 0,6 + 0,4 × 0,64 = 0,856; financiación negativa: +0,1.
    assert fut["giro"]["partes"]["futuros"] == 0.96
    assert fut["giro"]["puntos"] == giro.giro_score(fut["giro"]["partes"], giro.GIRO_DEFAULT)
    assert spot["libro"]["lecturas"] == 3 and spot["libro"]["compras"]["muro"]["usdt"] == 9850
    assert clients["spot"].calls.count("/api/v3/depth") == 3
    assert clients["futures"].calls.count("/fapi/v1/depth") == 3

    # Con un mercado bloqueado sigue con el otro; con todos, la ejecución falla.
    blocked = lambda market: FakeClient(market, now, blocked=market.key == "futures")  # noqa: E731
    day, notes, failed = diario.scan_day(settings, giro.GIRO_DEFAULT, client_factory=blocked, now_ms=lambda: now,
                                         sleep=lambda s: None, log=lambda m: None)
    assert failed == ["futures"] and len(day["monedas"]) == 1 and "451" in notes[0]


def test_diario_cli_scans_and_merges(tmp_path, monkeypatch):
    now = 1795564800000 + 16 * 3600000
    monkeypatch.setattr(diario.time, "time", lambda: now / 1000)
    monkeypatch.setattr(diario.time, "sleep", lambda s: None)
    monkeypatch.setattr(diario, "BinanceClient", lambda market: FakeClient(market, now))
    folder = tmp_path / "seguimiento"
    folder.mkdir()
    (folder / "escaneo.json").write_text(json.dumps({"mercado": "spot", "intervalo": "1d", "volumen_min": 0, "zona": "America/Lima"}))
    (folder / "giro.json").write_text(json.dumps({"pesos": {"flujo": 0}}))
    out, summary = tmp_path / "dia.json", tmp_path / "resumen.md"
    assert diario.main(["escanear", "--seguimiento", str(folder), "--salida", str(out), "--resumen", str(summary)]) == 0
    scanned = json.loads(out.read_text())
    assert [c["mercado"] for c in scanned["monedas"]] == ["spot"]
    parts = scanned["monedas"][0]["giro"]["partes"]
    assert scanned["monedas"][0]["giro"]["puntos"] == giro.giro_score(parts, {**giro.GIRO_DEFAULT, "flujo": 0})
    assert "AAAUSDT" in summary.read_text() and "velas 1d" in summary.read_text()
    assert diario.main(["unir", str(out), "--seguimiento", str(folder)]) == 0
    assert diario.main(["unir", str(out), "--seguimiento", str(folder)]) == 0  # dos veces: no repite
    saved = json.loads((folder / "2026-11-24.json").read_text())
    assert len(saved["monedas"]) == 1
