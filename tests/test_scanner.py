import json
import time

import pytest

from momento_b import cli
from momento_b.binance import FUTURES, SPOT, BinanceError, BinanceFatalError, WeightLimiter
from momento_b.indicators import bars_above, sma
from momento_b.scanner import ScanConfig, evaluate, scan_market, select_symbols


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
    def __init__(self, market, exchange_info, klines, tickers=None, errors=None):
        self.market = market
        self._info = exchange_info
        self._klines = klines
        self._tickers = tickers or []
        self._errors = errors or {}
        self.requested = []

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
    assert {r[1:] for r in client.requested} == {("1h", 199)}


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
    assert client.requested[-1][2] == 200  # pide una vela extra para compensar la que descarta


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


def test_cli_end_to_end(monkeypatch, tmp_path, capsys):
    futures_klines = {"AAAUSDT": make_klines(REBOUND)}
    clients = {
        "spot": spot_client(),
        "futures": FakeClient(FUTURES, EXCHANGE_INFO_FUTURES, futures_klines,
                              [{"symbol": "AAAUSDT", "quoteVolume": "1e8", "priceChangePercent": "2"}]),
    }
    monkeypatch.setattr(cli, "BinanceClient", lambda market, **kw: clients[market.key])
    out_json = tmp_path / "res.json"
    out_csv = tmp_path / "res.csv"

    code = cli.main(["-i", "1d", "--json", str(out_json), "--csv", str(out_csv)])

    assert code == 0
    stdout = capsys.readouterr().out
    assert "SPOT (USDT) — 1 coincidencias de 3 analizadas" in stdout
    assert "FUTURES USDⓈ-M (USDT) — 1 coincidencias de 1 analizadas" in stdout
    assert "En spot y futuros a la vez (1): AAA" in stdout
    data = json.loads(out_json.read_text())
    assert data["intervalo"] == "1d"
    assert [s["simbolo"] for s in data["mercados"]["futures"]["coincidencias"]] == ["AAAUSDT"]
    assert out_csv.read_text().count("AAAUSDT") == 2


def test_cli_reports_blocked_market(monkeypatch, capsys):
    class Blocked(FakeClient):
        def exchange_info(self):
            raise BinanceFatalError("451 ubicación restringida")

    clients = {"spot": spot_client(), "futures": Blocked(FUTURES, {}, {})}
    monkeypatch.setattr(cli, "BinanceClient", lambda market, **kw: clients[market.key])
    assert cli.main([]) == 1
    captured = capsys.readouterr()
    assert "451 ubicación restringida" in captured.err
    assert "SPOT (USDT)" in captured.out


def test_cli_validates_periods():
    with pytest.raises(SystemExit):
        cli.main(["--mas", "25", "7", "99"])
