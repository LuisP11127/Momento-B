"""Lógica del scanner: MA rápida por encima de la media pero aún por debajo de la lenta.

Con los periodos por defecto: MA(7) > MA(25) y MA(7) < MA(99).
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from .binance import BinanceError, BinanceFatalError, Market
from .indicators import bars_above, sma

DEFAULT_PERIODS = (7, 25, 99)

# Bases que no son criptomonedas "de verdad" para este análisis (se mueven en torno a 1).
STABLECOINS = frozenset(
    {
        "USDT", "USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "USDS", "USDE", "PYUSD",
        "USD1", "RLUSD", "XUSD", "BFUSD", "EUR", "EURI", "AEUR", "GBP",
    }
)

# Subyacentes de futuros que no son criptomonedas (índices, materias primas, acciones...).
NON_CRYPTO_UNDERLYING = frozenset({"INDEX", "COMMODITY", "EQUITY", "STOCK", "FOREX"})


@dataclass(frozen=True)
class ScanConfig:
    interval: str = "4h"
    periods: tuple[int, int, int] = DEFAULT_PERIODS
    quote: Optional[str] = "USDT"  # None = todas las monedas de cotización
    min_quote_volume: float = 0.0
    max_bars_since_cross: Optional[int] = None
    closed_only: bool = False
    include_stables: bool = False
    include_stocks: bool = False  # acciones tokenizadas de Binance (bStocks)
    workers: int = 8
    extra_history: int = 200  # velas extra para ver hace cuánto fue el cruce y para el gráfico

    @property
    def klines_limit(self) -> int:
        return max(self.periods) + self.extra_history + (1 if self.closed_only else 0)


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    base: str
    quote: str


@dataclass(frozen=True)
class MASnapshot:
    fast: float
    mid: float
    slow: float
    bars_since_cross: int  # velas con rápida > media (1 = cruzó en la última)
    cross_seen: bool  # False si el cruce es anterior al histórico descargado (bars_since_cross es un mínimo)


@dataclass(frozen=True)
class Signal:
    market: str
    symbol: str
    base: str
    quote: str
    price: float
    ma_fast: float
    ma_mid: float
    ma_slow: float
    dist_to_slow_pct: float  # % que tiene que subir la MA rápida para tocar la lenta
    bars_since_cross: int
    cross_seen: bool
    change_24h_pct: Optional[float]
    quote_volume_24h: Optional[float]
    # (apertura ms, open, high, low, close, volumen) de todas las velas descargadas, para el gráfico
    candles: tuple[tuple[int, float, float, float, float, float], ...] = field(default=(), repr=False, compare=False)


@dataclass
class ScanResult:
    market: Market
    config: ScanConfig
    signals: list[Signal] = field(default_factory=list)
    total_symbols: int = 0
    analyzed: int = 0
    skipped_volume: int = 0
    skipped_stocks: int = 0
    insufficient_data: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Órdenes disponibles para mostrar o exportar las señales.
SORT_KEYS = {
    "distancia": lambda s: s.dist_to_slow_pct,
    "cruce": lambda s: (not s.cross_seen, s.bars_since_cross),
    "volumen": lambda s: -(s.quote_volume_24h or 0.0),
    "variacion": lambda s: -(s.change_24h_pct if s.change_24h_pct is not None else -math.inf),
    "simbolo": lambda s: s.symbol,
}


def evaluate(closes: Sequence[float], periods: tuple[int, int, int] = DEFAULT_PERIODS) -> Optional[MASnapshot]:
    """Devuelve las MA de la última vela si cumple rápida > media y rápida < lenta."""
    fast_p, mid_p, slow_p = periods
    if len(closes) < slow_p:
        return None
    ma_fast = sma(closes, fast_p)
    ma_mid = sma(closes, mid_p)
    ma_slow = sma(closes, slow_p)
    fast, mid, slow = ma_fast[-1], ma_mid[-1], ma_slow[-1]
    if not (fast > mid and fast < slow):
        return None
    bars = bars_above(ma_fast, ma_mid)
    # La media está definida en len - mid_p + 1 velas; si todas están por encima no vemos el cruce.
    return MASnapshot(fast, mid, slow, bars, cross_seen=bars < len(closes) - mid_p + 1)


def select_symbols(
    market_key: str,
    exchange_info: dict,
    quote: Optional[str] = "USDT",
    include_stables: bool = False,
) -> list[SymbolInfo]:
    """Filtra los pares operables del exchangeInfo de spot o futuros."""
    selected = []
    for s in exchange_info.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        if quote and s.get("quoteAsset") != quote:
            continue
        if not include_stables and s.get("baseAsset") in STABLECOINS:
            continue
        if market_key == "spot":
            if not s.get("isSpotTradingAllowed", True):
                continue
        else:
            if s.get("contractType") != "PERPETUAL":
                continue
            if s.get("underlyingType") in NON_CRYPTO_UNDERLYING:
                continue
        selected.append(SymbolInfo(s["symbol"], s["baseAsset"], s["quoteAsset"]))
    return selected


def is_tokenized_stock(tags: Sequence[str]) -> bool:
    """Binance etiqueta sus acciones tokenizadas (AAPLB, NVDAB...) como "bStocks"."""
    return any(isinstance(tag, str) and "stock" in tag.lower() for tag in tags)


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def scan_market(
    client,
    config: ScanConfig,
    progress: Optional[Callable[[int, int], None]] = None,
) -> ScanResult:
    """Descarga velas de todos los pares del mercado y devuelve los que cumplen la condición."""
    result = ScanResult(market=client.market, config=config)
    symbols = select_symbols(client.market.key, client.exchange_info(), config.quote, config.include_stables)
    if client.market.key == "spot" and not config.include_stocks:
        tags = client.asset_tags()
        if tags is None:
            result.warnings.append(
                "no se pudo consultar qué pares son acciones tokenizadas (bStocks); pueden aparecer en la lista"
            )
        else:
            crypto = [info for info in symbols if not is_tokenized_stock(tags.get(info.symbol, ()))]
            result.skipped_stocks = len(symbols) - len(crypto)
            symbols = crypto
    result.total_symbols = len(symbols)

    tickers = {t["symbol"]: t for t in client.tickers_24h()}
    candidates = []
    for info in symbols:
        ticker = tickers.get(info.symbol, {})
        volume = _to_float(ticker.get("quoteVolume"))
        change = _to_float(ticker.get("priceChangePercent"))
        if config.min_quote_volume > 0 and (volume or 0.0) < config.min_quote_volume:
            result.skipped_volume += 1
            continue
        candidates.append((info, change, volume))

    min_closes = max(config.periods)
    pool = ThreadPoolExecutor(max_workers=max(1, config.workers))
    try:
        jobs = {
            pool.submit(client.klines, info.symbol, config.interval, config.klines_limit): (info, change, volume)
            for info, change, volume in candidates
        }
        for done, job in enumerate(as_completed(jobs), 1):
            info, change, volume = jobs[job]
            if progress:
                progress(done, len(jobs))
            try:
                klines = job.result()
            except BinanceFatalError:
                raise
            except BinanceError as exc:
                result.errors.append((info.symbol, str(exc)))
                continue

            closes = [float(k[4]) for k in klines]
            if not closes:
                result.insufficient_data += 1
                continue
            price = closes[-1]
            if config.closed_only and int(klines[-1][6]) >= time.time() * 1000:
                closes.pop()  # la última vela sigue abierta
            if len(closes) < min_closes:
                result.insufficient_data += 1
                continue
            result.analyzed += 1

            snap = evaluate(closes, config.periods)
            if snap is None:
                continue
            if config.max_bars_since_cross is not None and (
                not snap.cross_seen or snap.bars_since_cross > config.max_bars_since_cross
            ):
                continue
            result.signals.append(
                Signal(
                    market=client.market.key,
                    symbol=info.symbol,
                    base=info.base,
                    quote=info.quote,
                    price=price,
                    ma_fast=snap.fast,
                    ma_mid=snap.mid,
                    ma_slow=snap.slow,
                    dist_to_slow_pct=(snap.slow - snap.fast) / snap.fast * 100,
                    bars_since_cross=snap.bars_since_cross,
                    cross_seen=snap.cross_seen,
                    change_24h_pct=change,
                    quote_volume_24h=volume,
                    candles=tuple(
                        (int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in klines
                    ),
                )
            )
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return result
