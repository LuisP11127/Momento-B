import json
import time

import pytest

from momento_b import cli, report
from momento_b.binance import FUTURES, SPOT, BinanceError, BinanceFatalError, WeightLimiter
from momento_b.indicators import bars_above, sma
from momento_b.scanner import ScanConfig, evaluate, fetch_charts, scan_market, select_symbols


def kline(close, close_time):
    return [close_time - 1, str(close), str(close), str(close), str(close), "1", close_time, "1", 1, "1", "1", "0"]


def make_klines(closes, last_open=False):
    """Velas con cierre en el pasado; la última queda abierta si ``last_open``."""
    now = int(time.time() * 1000)
    rows = [kline(c, now - (len(closes) - i) * 60_000) for i, c in enumerate(closes)]
    if last_open:
        rows[-1][6] = now + 60_000
    return rows


# Larga caída y rebote reciente: MA7 > MA25 pero MA7 < MA99.
REBOUND = [200 - i for i in range(150)] + [50 + 2 * i for i in range(12)]
# Tendencia alcista limpia: MA7 por encima de todo.
UPTREND = [10 + i for i in range(200)]
# Tendencia bajista limpia: MA7 por debajo de todo.
DOWNTREND = [300 - i for i in range(200)]


def test_sma_matches_manual_average():
    values = [1, 2, 3, 4, 5, 6]
    assert sma(values, 3) == [None, None, 2.0, 3.0, 4.0, 5.0]
    assert sma(values, 1) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


def test_bars_above_counts_streak_from_the_end():
    assert bars_above([1, 3, 3, 3], [2, 2, 2, 2]) == 3
    assert bars_above([3, 3, 1], [2, 2, 2]) == 0
    assert bars_above([None, 3, 3], [None, 2, 2]) == 2


def test_evaluate_detects_rebound_below_slow_ma():
    snap = evaluate(REBOUND)
    assert snap is not None
    assert snap.mid < snap.fast < snap.slow
    assert snap.cross_seen
    assert 1 <= snap.bars_since_cross <= 12


def test_evaluate_rejects_trends_and_short_history():
    assert evaluate(UPTREND) is None
    assert evaluate(DOWNTREND) is None
    assert evaluate(REBOUND[-50:]) is None


def test_evaluate_flags_cross_older_than_history():
    # Con MA(2)/MA(3)/MA(4): la rápida está sobre la media en las 3 velas donde ambas existen,
    # así que el cruce queda fuera del histórico.
    closes = [100, 110, 100, 121, 88]
    snap = evaluate(closes, periods=(2, 3, 4))
    assert snap is not None
    assert snap.bars_since_cross == 3
    assert not snap.cross_seen
    snap = evaluate([130] + closes, periods=(2, 3, 4))
    assert snap is not None and snap.cross_seen


EXCHANGE_INFO_SPOT = {
    "rateLimits": [{"rateLimitType": "REQUEST_WEIGHT", "interval": "MINUTE", "intervalNum": 1, "limit": 6000}],
    "symbols": [
        {"symbol": "AAAUSDT", "status": "TRADING", "baseAsset": "AAA", "quoteAsset": "USDT", "isSpotTradingAllowed": True},
        {"symbol": "BBBUSDT", "status": "TRADING", "baseAsset": "BBB", "quoteAsset": "USDT", "isSpotTradingAllowed": True},
        {"symbol": "CCCUSDT", "status": "TRADING", "baseAsset": "CCC", "quoteAsset": "USDT", "isSpotTradingAllowed": True},
        {"symbol": "NEWUSDT", "status": "TRADING", "baseAsset": "NEW", "quoteAsset": "USDT", "isSpotTradingAllowed": True},
        {"symbol": "AAABTC", "status": "TRADING", "baseAsset": "AAA", "quoteAsset": "BTC", "isSpotTradingAllowed": True},
        {"symbol": "OLDUSDT", "status": "BREAK", "baseAsset": "OLD", "quoteAsset": "USDT", "isSpotTradingAllowed": True},
        {"symbol": "USDCUSDT", "status": "TRADING", "baseAsset": "USDC", "quoteAsset": "USDT", "isSpotTradingAllowed": True},
    ],
}

EXCHANGE_INFO_FUTURES = {
    "symbols": [
        {"symbol": "AAAUSDT", "status": "TRADING", "contractType": "PERPETUAL", "underlyingType": "COIN",
         "baseAsset": "AAA", "quoteAsset": "USDT"},
        {"symbol": "AAAUSDT_261225", "status": "TRADING", "contractType": "CURRENT_QUARTER",
         "underlyingType": "COIN", "baseAsset": "AAA", "quoteAsset": "USDT"},
        {"symbol": "BTCDOMUSDT", "status": "TRADING", "contractType": "PERPETUAL", "underlyingType": "INDEX",
         "baseAsset": "BTCDOM", "quoteAsset": "USDT"},
        {"symbol": "XAUUSDT", "status": "TRADING", "contractType": "TRADIFI_PERPETUAL",
         "underlyingType": "COMMODITY", "baseAsset": "XAU", "quoteAsset": "USDT"},
        {"symbol": "DDDUSDT", "status": "SETTLING", "contractType": "PERPETUAL", "underlyingType": "COIN",
         "baseAsset": "DDD", "quoteAsset": "USDT"},
    ],
}


def test_select_symbols_spot_filters_status_quote_and_stables():
    symbols = [s.symbol for s in select_symbols("spot", EXCHANGE_INFO_SPOT, "USDT")]
    assert symbols == ["AAAUSDT", "BBBUSDT", "CCCUSDT", "NEWUSDT"]
    assert "USDCUSDT" in [s.symbol for s in select_symbols("spot", EXCHANGE_INFO_SPOT, "USDT", include_stables=True)]
    assert "AAABTC" in [s.symbol for s in select_symbols("spot", EXCHANGE_INFO_SPOT, None)]


def test_select_symbols_futures_keeps_only_crypto_perpetuals():
    assert [s.symbol for s in select_symbols("futures", EXCHANGE_INFO_FUTURES, "USDT")] == ["AAAUSDT"]


class FakeClient:
    def __init__(self, market, exchange_info, klines, tickers=None, errors=None, tags=None):
        self.market = market
        self.base_url = market.base_url
        self._info = exchange_info
        self._klines = klines
        self._tickers = tickers or []
        self._errors = errors or {}
        self._tags = {} if tags is None else tags
        self.requested = []

    def asset_tags(self):
        return self._tags

    def exchange_info(self):
        return self._info

    def tickers_24h(self):
        return self._tickers

    def klines(self, symbol, interval, limit):
        self.requested.append((symbol, interval, limit))
        if symbol in self._errors:
            raise self._errors[symbol]
        return self._klines[symbol][-limit:]


def spot_client(**kwargs):
    klines = {
        "AAAUSDT": make_klines(REBOUND),
        "BBBUSDT": make_klines(UPTREND),
        "CCCUSDT": make_klines(DOWNTREND),
        "NEWUSDT": make_klines(REBOUND[-40:]),
    }
    tickers = [
        {"symbol": "AAAUSDT", "quoteVolume": "5000000", "priceChangePercent": "4.5"},
        {"symbol": "BBBUSDT", "quoteVolume": "100", "priceChangePercent": "1.0"},
        {"symbol": "CCCUSDT", "quoteVolume": "9000000", "priceChangePercent": "-3.0"},
        {"symbol": "NEWUSDT", "quoteVolume": "9000000", "priceChangePercent": "10.0"},
    ]
    return FakeClient(SPOT, EXCHANGE_INFO_SPOT, klines, tickers, **kwargs)


def test_scan_market_finds_only_matching_symbols():
    client = spot_client()
    result = scan_market(client, ScanConfig(interval="1h", workers=2))
    assert [s.symbol for s in result.signals] == ["AAAUSDT"]
    signal = result.signals[0]
    assert signal.price == REBOUND[-1]
    assert signal.change_24h_pct == 4.5
    assert signal.quote_volume_24h == 5_000_000
    assert signal.dist_to_slow_pct > 0
    assert result.total_symbols == 4
    assert result.analyzed == 3
    assert result.insufficient_data == 1
    assert {r[1:] for r in client.requested} == {("1h", 299)}
    assert len(signal.candles) == len(REBOUND)
    assert signal.candles[-1][1:5] == (REBOUND[-1],) * 4


def test_scan_market_excludes_tokenized_stocks():
    tags = {"AAAUSDT": ["bStocks"], "BBBUSDT": ["Layer1_Layer2", "pos"]}
    client = spot_client(tags=tags)
    result = scan_market(client, ScanConfig(workers=2))
    assert result.skipped_stocks == 1
    assert result.total_symbols == 3
    assert "AAAUSDT" not in [r[0] for r in client.requested]
    assert result.signals == []
    assert [s.symbol for s in scan_market(spot_client(tags=tags), ScanConfig(workers=2, include_stocks=True)).signals] == ["AAAUSDT"]


def test_scan_market_warns_when_tags_are_unavailable():
    result = scan_market(spot_client(tags=None), ScanConfig(workers=2))
    assert result.skipped_stocks == 0
    assert [s.symbol for s in result.signals] == ["AAAUSDT"]
    assert result.warnings == []
    client = spot_client()
    client._tags = None
    result = scan_market(client, ScanConfig(workers=2))
    assert len(result.warnings) == 1 and "bStocks" in result.warnings[0]
    assert [s.symbol for s in result.signals] == ["AAAUSDT"]


def test_fetch_charts_downloads_other_timeframes_for_signals():
    client = spot_client()
    result = scan_market(client, ScanConfig(interval="4h", workers=2))
    client.requested.clear()
    fetch_charts(client, result, ["2h", "4h", "8h", "2h", "1d"])
    assert sorted(r[1] for r in client.requested) == ["1d", "2h", "8h"]  # sin repetir la del escaneo
    assert {r[0] for r in client.requested} == {"AAAUSDT"}
    assert sorted(result.charts["AAAUSDT"]) == ["1d", "2h", "8h"]
    assert len(result.charts["AAAUSDT"]["1d"]) == len(REBOUND)


def test_fetch_charts_survives_errors():
    client = spot_client()
    result = scan_market(client, ScanConfig(workers=1))
    client._errors = {"AAAUSDT": BinanceError("400")}
    fetch_charts(client, result, ["2h", "1d"])
    assert result.charts == {} and result.warnings == []
    client._errors = {"AAAUSDT": BinanceFatalError("451")}
    fetch_charts(client, result, ["2h", "1d"])
    assert result.charts == {} and "451" in result.warnings[0]


def test_scan_market_min_volume_skips_requests():
    client = spot_client()
    result = scan_market(client, ScanConfig(min_quote_volume=1_000_000, workers=2))
    assert result.skipped_volume == 1
    assert "BBBUSDT" not in [r[0] for r in client.requested]


def test_scan_market_closed_only_drops_open_candle():
    # La vela abierta dispara la MA7 por encima de la MA99; sin ella, la señal existe.
    closes = REBOUND + [10_000]
    klines = {"AAAUSDT": make_klines(closes, last_open=True), "BBBUSDT": [], "CCCUSDT": [], "NEWUSDT": []}
    client = FakeClient(SPOT, EXCHANGE_INFO_SPOT, klines)
    assert scan_market(client, ScanConfig(workers=1)).signals == []
    result = scan_market(client, ScanConfig(workers=1, closed_only=True))
    assert [s.symbol for s in result.signals] == ["AAAUSDT"]
    assert result.signals[0].price == 10_000  # el precio mostrado sigue siendo el actual
    assert client.requested[-1][2] == 300  # pide una vela extra para compensar la que descarta


def test_scan_market_max_bars_filter():
    snap = evaluate(REBOUND)
    result = scan_market(spot_client(), ScanConfig(workers=1, max_bars_since_cross=snap.bars_since_cross))
    assert [s.symbol for s in result.signals] == ["AAAUSDT"]
    result = scan_market(spot_client(), ScanConfig(workers=1, max_bars_since_cross=snap.bars_since_cross - 1))
    assert result.signals == []


def test_scan_market_collects_symbol_errors_but_aborts_on_fatal():
    result = scan_market(spot_client(errors={"BBBUSDT": BinanceError("400 símbolo inválido")}), ScanConfig(workers=2))
    assert result.errors == [("BBBUSDT", "400 símbolo inválido")]
    assert [s.symbol for s in result.signals] == ["AAAUSDT"]
    with pytest.raises(BinanceFatalError):
        scan_market(spot_client(errors={"BBBUSDT": BinanceFatalError("418")}), ScanConfig(workers=2))


def test_weight_limiter_blocks_when_budget_is_spent(monkeypatch):
    limiter = WeightLimiter(10, safety=1.0)
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        limiter._minute -= 1  # simula que empieza un minuto nuevo

    monkeypatch.setattr("momento_b.binance.time.sleep", fake_sleep)
    limiter.acquire(6)
    limiter.acquire(4)
    assert sleeps == []
    limiter.acquire(1)
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 60.25


def test_futures_klines_weight():
    assert FUTURES.klines_weight(99) == 1
    assert FUTURES.klines_weight(199) == 2
    assert FUTURES.klines_weight(1000) == 5
    assert SPOT.klines_weight(199) == 2


def test_format_price_keeps_significant_digits():
    assert cli.format_price(65123.456) == "65,123.46"
    assert cli.format_price(1.23456) == "1.2346"
    assert cli.format_price(0.0000123456) == "0.000012346"


def both_clients():
    return {
        "spot": spot_client(),
        "futures": FakeClient(FUTURES, EXCHANGE_INFO_FUTURES, {"AAAUSDT": make_klines(REBOUND)},
                              [{"symbol": "AAAUSDT", "quoteVolume": "1e8", "priceChangePercent": "2"}]),
    }


@pytest.fixture
def opened(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.webbrowser, "open", calls.append)
    monkeypatch.delenv("CODESPACES", raising=False)  # que los tests no dependan de dónde se ejecutan
    return calls


def test_cli_end_to_end(monkeypatch, tmp_path, capsys, opened):
    clients = both_clients()
    monkeypatch.setattr(cli, "BinanceClient", lambda market, **kw: clients[market.key])
    out_json = tmp_path / "res.json"
    out_csv = tmp_path / "res.csv"
    out_html = tmp_path / "graficos.html"

    code = cli.main(["-i", "1d", "--json", str(out_json), "--csv", str(out_csv), "--html", str(out_html), "--no-abrir"])

    assert code == 0
    stdout = capsys.readouterr().out
    assert "SPOT (USDT) — 1 coincidencias de 3 analizadas" in stdout
    assert "FUTURES USDⓈ-M (USDT) — 1 coincidencias de 1 analizadas" in stdout
    assert "En spot y futuros a la vez (1): AAA" in stdout
    assert f"Gráficos interactivos: {out_html}" in stdout
    data = json.loads(out_json.read_text())
    assert data["intervalo"] == "1d"
    futures = data["mercados"]["futures"]["coincidencias"]
    assert [s["simbolo"] for s in futures] == ["AAAUSDT"]
    assert len(futures[0]["velas"]) == len(REBOUND)
    assert data["intervalos_grafico"] == ["2h", "4h", "8h", "12h", "1d"]
    assert sorted(futures[0]["graficos"]) == ["12h", "2h", "4h", "8h"]  # la de 1d va en "velas"
    assert out_csv.read_text().count("AAAUSDT") == 2
    html = out_html.read_text()
    assert html.startswith("<!doctype html>")
    assert "__MOMENTO_DATA__" not in html
    assert opened == []


def test_cli_writes_report_in_reportes_and_opens_it(monkeypatch, tmp_path, opened):
    clients = both_clients()
    monkeypatch.setattr(cli, "BinanceClient", lambda market, **kw: clients[market.key])
    monkeypatch.chdir(tmp_path)

    assert cli.main(["-i", "1h"]) == 0

    reports = list((tmp_path / "reportes").glob("momento-b_1h_*.html"))
    assert len(reports) == 1
    assert opened == [reports[0].resolve().as_uri()]


def test_cli_without_chart(monkeypatch, tmp_path, opened):
    clients = both_clients()
    monkeypatch.setattr(cli, "BinanceClient", lambda market, **kw: clients[market.key])
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--sin-grafico"]) == 0
    assert not (tmp_path / "reportes").exists()
    assert opened == []
    assert {r[1] for c in clients.values() for r in c.requested} == {"4h"}  # sin gráficos no hay descargas extra


def test_cli_custom_chart_timeframes(monkeypatch, tmp_path, opened):
    clients = both_clients()
    monkeypatch.setattr(cli, "BinanceClient", lambda market, **kw: clients[market.key])
    out_json = tmp_path / "r.json"
    assert cli.main(["-i", "1h", "--graficos", "1h", "1d", "--json", str(out_json), "--sin-grafico"]) == 0
    data = json.loads(out_json.read_text())
    assert data["intervalos_grafico"] == ["1h", "1d"]


def test_cli_reports_blocked_market(monkeypatch, capsys, opened):
    class Blocked(FakeClient):
        def exchange_info(self):
            raise BinanceFatalError("451 ubicación restringida")

    clients = {"spot": spot_client(), "futures": Blocked(FUTURES, {}, {})}
    monkeypatch.setattr(cli, "BinanceClient", lambda market, **kw: clients[market.key])
    assert cli.main(["--sin-grafico"]) == 1
    captured = capsys.readouterr()
    assert "451 ubicación restringida" in captured.err
    assert "SPOT (USDT)" in captured.out


def test_cli_validates_periods():
    with pytest.raises(SystemExit):
        cli.main(["--mas", "25", "7", "99"])


def embedded_payload(html):
    start = html.index('<script id="momento-data" type="application/json">') + len('<script id="momento-data" type="application/json">')
    return json.loads(html[start:html.index("</script>", start)])


def test_report_embeds_payload_safely():
    result = scan_market(spot_client(), ScanConfig(workers=1))
    from datetime import datetime, timezone

    payload = report.build_payload([result], datetime(2026, 10, 1, 12, tzinfo=timezone.utc))
    payload["mercados"]["spot"]["coincidencias"][0]["simbolo"] = "</script><b>X"

    html = report.render_report(payload)
    assert "</script><b>" not in html
    assert embedded_payload(html) == payload
    assert payload["mercados"]["spot"]["coincidencias"][0]["velas"][0][0] > 0

    fragment = report.render_report(payload, standalone=False)
    assert fragment.startswith("<title>Momento-B Scanner</title>")
    assert "<!doctype" not in fragment and "<body>" not in fragment
    assert embedded_payload(fragment) == payload


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


def test_asset_tags_parses_binance_products(monkeypatch):
    from momento_b.binance import BinanceClient

    client = BinanceClient(SPOT)
    payload = {"code": "000000", "data": [
        {"s": "AAOIBUSDT", "b": "AAOIB", "an": "Applied Optoelectronics (bStocks)", "tags": ["bStocks"]},
        {"s": "TRXUSDT", "b": "TRX", "tags": ["Layer1_Layer2", "pos"]},
        {"s": "NEWUSDT", "tags": None},
    ]}
    monkeypatch.setattr(client.session, "get", lambda *a, **kw: FakeResponse(payload))
    assert client.asset_tags() == {"AAOIBUSDT": ["bStocks"], "TRXUSDT": ["Layer1_Layer2", "pos"], "NEWUSDT": []}
    monkeypatch.setattr(client.session, "get", lambda *a, **kw: FakeResponse({}, status=403))
    assert client.asset_tags() is None
    monkeypatch.setattr(client.session, "get", lambda *a, **kw: FakeResponse({"data": "raro"}))
    assert client.asset_tags() is None


def test_report_server_redirects_root_to_report(tmp_path):
    import threading
    import urllib.request

    page = tmp_path / "momento-b_4h.html"
    page.write_text("<p>hola</p>", encoding="utf-8")
    server = report.make_server(page, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:  # sigue la redirección
            assert resp.geturl().endswith("/momento-b_4h.html")
            assert resp.read() == b"<p>hola</p>"
    finally:
        server.shutdown()
        server.server_close()


def test_cli_serves_report_in_codespaces(monkeypatch, tmp_path, opened):
    clients = both_clients()
    monkeypatch.setattr(cli, "BinanceClient", lambda market, **kw: clients[market.key])
    served = []
    monkeypatch.setattr(cli, "serve_report", lambda path, port, open_browser: served.append((path.name, port, open_browser)))
    monkeypatch.setenv("CODESPACES", "true")
    assert cli.main(["--html", str(tmp_path / "g.html")]) == 0
    assert served == [("g.html", 8000, False)]  # la pestaña la abre el reenvío de puertos
    assert opened == []
    served.clear()
    assert cli.main(["--html", str(tmp_path / "g.html"), "--no-abrir"]) == 0
    assert served == []


def test_cli_servir_outside_codespaces(monkeypatch, tmp_path, opened):
    clients = both_clients()
    monkeypatch.setattr(cli, "BinanceClient", lambda market, **kw: clients[market.key])
    served = []
    monkeypatch.setattr(cli, "serve_report", lambda path, port, open_browser: served.append((port, open_browser)))
    monkeypatch.delenv("CODESPACES", raising=False)
    assert cli.main(["--html", str(tmp_path / "g.html"), "--servir", "--puerto", "9100"]) == 0
    assert served == [(9100, True)]
    assert opened == []


class StatusResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload
        self.headers = {}
        self.text = ""

    def json(self):
        return self._payload


def test_spot_falls_back_to_data_api_on_451(monkeypatch):
    from momento_b.binance import BinanceClient

    client = BinanceClient(SPOT)
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return StatusResponse(451) if url.startswith("https://api.binance.com") else StatusResponse(200, {"ok": 1})

    monkeypatch.setattr(client.session, "get", fake_get)
    assert client._get("/api/v3/ping") == {"ok": 1}
    assert calls == ["https://api.binance.com/api/v3/ping", "https://data-api.binance.vision/api/v3/ping"]
    assert client.base_url == "https://data-api.binance.vision"


def test_futures_and_explicit_urls_do_not_fall_back(monkeypatch):
    from momento_b.binance import BinanceClient

    for client in (BinanceClient(FUTURES), BinanceClient(SPOT, base_url="https://api.binance.com")):
        monkeypatch.setattr(client.session, "get", lambda url, params=None, timeout=None: StatusResponse(451))
        with pytest.raises(BinanceFatalError):
            client._get("/x")


def test_web_app_has_no_data_and_scan_form():
    from momento_b import web

    html = web.render_app()
    assert embedded_payload(html) is None
    assert 'id="scan-form"' in html


def test_committed_web_page_is_up_to_date():
    from pathlib import Path

    from momento_b import web

    page = Path(__file__).resolve().parents[1] / "docs" / "index.html"
    assert page.read_text(encoding="utf-8") == web.render_app(), "regenera con: python -m momento_b.web docs"


def test_stock_symbols_lists_bstocks():
    from momento_b import web

    class Client:
        def asset_tags(self):
            return {"TSLABUSDT": ["bStocks"], "BTCUSDT": ["pow"], "NVDABUSDT": ["bStocks"]}

    assert web.stock_symbols(Client()) == ["NVDABUSDT", "TSLABUSDT"]

    class Down:
        def asset_tags(self):
            return None

    with pytest.raises(RuntimeError):
        web.stock_symbols(Down())


def test_collect_tracking_orders_days_and_skips_bad_files(tmp_path, capsys):
    from momento_b import web

    coin = {"mercado": "spot", "simbolo": "AAAUSDT", "base": "AAA", "quote": "USDT", "precio": 1.5,
            "hora": "2026-10-01T15:00:00.000Z", "intervalo": "4h", "extra": "se descarta"}
    (tmp_path / "2026-10-01.json").write_text(json.dumps({"fecha": "2026-10-01", "monedas": [coin]}), encoding="utf-8")
    (tmp_path / "2026-10-03.json").write_text(json.dumps({"monedas": [coin, {"simbolo": "SIN_MERCADO"}]}), encoding="utf-8")
    (tmp_path / "roto.json").write_text("{no es json", encoding="utf-8")
    (tmp_path / "otro.json").write_text(json.dumps({"monedas": []}), encoding="utf-8")  # sin fecha
    (tmp_path / "README.md").write_text("no es un día", encoding="utf-8")
    (tmp_path / "estrellas.json").write_text(json.dumps({"estrellas": {}}), encoding="utf-8")  # no es un día

    days = web.collect_tracking(tmp_path)

    assert [d["fecha"] for d in days] == ["2026-10-03", "2026-10-01"]  # más reciente primero; fecha del nombre
    assert days[1]["monedas"] == [{k: coin[k] for k in web.COIN_FIELDS}]
    assert len(days[0]["monedas"]) == 1
    out = capsys.readouterr().out
    assert "roto.json" in out and "otro.json" in out
    assert "estrellas.json" not in out
    assert web.collect_tracking(tmp_path / "no-existe") == []


def test_collect_stars_keeps_valid_entries(tmp_path, capsys):
    from momento_b import web

    assert web.collect_stars(tmp_path) == {}  # sin archivo
    (tmp_path / "estrellas.json").write_text(json.dumps({"estrellas": {
        "spot:BTCUSDT": {"activa": True, "hora": "2026-10-06T15:00:00.000Z"},
        "futures:ETHUSDT": {"activa": False, "hora": "2026-10-06T16:00:00.000Z", "otro": 1},
        "sin-mercado": {"activa": True, "hora": "x"},
        "spot:XUSDT": {"activa": "sí"},
    }}), encoding="utf-8")
    assert web.collect_stars(tmp_path) == {
        "futures:ETHUSDT": {"activa": False, "hora": "2026-10-06T16:00:00.000Z"},
        "spot:BTCUSDT": {"activa": True, "hora": "2026-10-06T15:00:00.000Z"},
    }
    (tmp_path / "estrellas.json").write_text("[]", encoding="utf-8")
    assert web.collect_stars(tmp_path) == {}
    assert "estrellas.json" in capsys.readouterr().out


def test_web_cli_writes_tracking_aggregate(tmp_path):
    from momento_b import web

    folder = tmp_path / "seguimiento"
    folder.mkdir()
    (folder / "2026-10-02.json").write_text(json.dumps({"fecha": "2026-10-02", "monedas": [
        {"mercado": "futures", "simbolo": "BBBUSDT", "base": "BBB", "quote": "USDT", "precio": 2, "hora": "x", "intervalo": "1d"}]}),
        encoding="utf-8")
    (folder / "estrellas.json").write_text(json.dumps({"estrellas": {
        "futures:BBBUSDT": {"activa": True, "hora": "2026-10-06T15:00:00.000Z"}}}), encoding="utf-8")
    out = tmp_path / "site"
    assert web.main([str(out), "--seguimiento", str(folder)]) == 0
    data = json.loads((out / "seguimiento.json").read_text(encoding="utf-8"))
    assert [d["fecha"] for d in data["dias"]] == ["2026-10-02"]
    assert data["estrellas"] == {"futures:BBBUSDT": {"activa": True, "hora": "2026-10-06T15:00:00.000Z"}}
    assert (out / "index.html").exists()
    assert (out / "icono.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    # Sin --seguimiento no se escribe (docs/ no debe llevar una copia que se quede vieja)
    assert web.main([str(tmp_path / "otra")]) == 0
    assert not (tmp_path / "otra" / "seguimiento.json").exists()
