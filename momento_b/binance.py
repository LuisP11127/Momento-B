"""Cliente mínimo de la API pública de Binance (spot y futuros USDⓈ-M).

Solo usa endpoints públicos de datos de mercado, así que no necesita API key.
Respeta el límite de peso por minuto de cada mercado leyendo la cabecera
``X-MBX-USED-WEIGHT-1M`` y reintenta ante 429 / errores de red.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests
from requests.adapters import HTTPAdapter


class BinanceError(RuntimeError):
    """Error al hablar con Binance."""


class BinanceFatalError(BinanceError):
    """Error que impide seguir escaneando el mercado (IP bloqueada, región restringida)."""


@dataclass(frozen=True)
class Market:
    key: str
    label: str
    base_url: str
    exchange_info_path: str
    klines_path: str
    ticker_path: str
    default_weight_limit: int
    exchange_info_weight: int
    ticker_weight: int
    max_klines: int
    klines_weight: Callable[[int], int]


def _futures_klines_weight(limit: int) -> int:
    if limit < 100:
        return 1
    if limit < 500:
        return 2
    if limit <= 1000:
        return 5
    return 10


SPOT = Market(
    key="spot",
    label="Spot",
    base_url="https://api.binance.com",
    exchange_info_path="/api/v3/exchangeInfo",
    klines_path="/api/v3/klines",
    ticker_path="/api/v3/ticker/24hr",
    default_weight_limit=6000,
    exchange_info_weight=20,
    ticker_weight=80,
    max_klines=1000,
    klines_weight=lambda limit: 2,
)

FUTURES = Market(
    key="futures",
    label="Futures USDⓈ-M",
    base_url="https://fapi.binance.com",
    exchange_info_path="/fapi/v1/exchangeInfo",
    klines_path="/fapi/v1/klines",
    ticker_path="/fapi/v1/ticker/24hr",
    default_weight_limit=2400,
    exchange_info_weight=1,
    ticker_weight=40,
    max_klines=1500,
    klines_weight=_futures_klines_weight,
)

MARKETS = {SPOT.key: SPOT, FUTURES.key: FUTURES}

# Lista de productos de la web de Binance: trae las etiquetas de cada par spot (p. ej. "bStocks").
PRODUCTS_URL = "https://www.binance.com/bapi/asset/v2/public/asset-service/product/get-products?includeEtf=true"


class WeightLimiter:
    """Reparte el peso de peticiones por minuto entre varios hilos.

    Binance cuenta el peso en ventanas de un minuto de reloj. Guardamos un
    margen de seguridad y sincronizamos el contador con lo que devuelve el
    servidor en cada respuesta.
    """

    def __init__(self, limit_per_minute: int, safety: float = 0.85) -> None:
        self._lock = threading.Lock()
        self._safety = safety
        self._minute = self._current_minute()
        self._used = 0
        self.set_limit(limit_per_minute)

    @staticmethod
    def _current_minute() -> int:
        return int(time.time() // 60)

    def set_limit(self, limit_per_minute: int) -> None:
        with self._lock:
            self._budget = max(1, int(limit_per_minute * self._safety))

    def acquire(self, weight: int) -> None:
        while True:
            with self._lock:
                now = time.time()
                minute = int(now // 60)
                if minute != self._minute:
                    self._minute = minute
                    self._used = 0
                if self._used + weight <= self._budget or self._used == 0:
                    self._used += weight
                    return
                wait = (minute + 1) * 60 - now + 0.25
            time.sleep(wait)

    def sync(self, used_weight: int) -> None:
        with self._lock:
            if self._current_minute() == self._minute:
                self._used = max(self._used, used_weight)


class BinanceClient:
    def __init__(
        self,
        market: Market,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
        max_retries: int = 4,
        pool_size: int = 16,
    ) -> None:
        self.market = market
        self.base_url = (base_url or market.base_url).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.limiter = WeightLimiter(market.default_weight_limit)
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _get(self, path: str, params: Optional[dict] = None, weight: int = 1) -> Any:
        url = self.base_url + path
        last_error = "sin respuesta"
        for attempt in range(self.max_retries + 1):
            self.limiter.acquire(weight)
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = str(exc)
                time.sleep(min(2 ** attempt, 16))
                continue

            used = resp.headers.get("X-MBX-USED-WEIGHT-1M")
            if used and used.isdigit():
                self.limiter.sync(int(used))

            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After", "")
                time.sleep(int(retry_after) if retry_after.isdigit() else 60)
                last_error = "429 demasiadas peticiones"
                continue
            if resp.status_code == 418:
                raise BinanceFatalError(
                    "Binance ha bloqueado temporalmente esta IP por exceso de peticiones (418). "
                    "Espera unos minutos y reduce --workers."
                )
            if resp.status_code in (403, 451):
                raise BinanceFatalError(
                    f"Binance rechaza las peticiones desde esta ubicación ({resp.status_code}) en "
                    f"{self.base_url}. Prueba desde otra red o cambia la URL base "
                    "(--spot-url / --futures-url)."
                )
            if resp.status_code >= 500:
                last_error = f"{resp.status_code} {resp.text[:200]}"
                time.sleep(min(2 ** attempt, 16))
                continue
            raise BinanceError(f"{resp.status_code} en {path} {params or ''}: {resp.text[:200]}")
        raise BinanceError(f"{path} {params or ''} falló tras {self.max_retries + 1} intentos: {last_error}")

    def exchange_info(self) -> dict:
        info = self._get(self.market.exchange_info_path, weight=self.market.exchange_info_weight)
        for rule in info.get("rateLimits", []):
            if (
                rule.get("rateLimitType") == "REQUEST_WEIGHT"
                and rule.get("interval") == "MINUTE"
                and rule.get("intervalNum") == 1
            ):
                self.limiter.set_limit(int(rule["limit"]))
        return info

    def asset_tags(self) -> Optional[dict[str, list[str]]]:
        """Etiquetas que la web de Binance muestra para cada par spot, o ``None`` si no responde.

        No es un endpoint de la API oficial, así que cualquier fallo se trata como "sin datos".
        """
        try:
            resp = self.session.get(
                PRODUCTS_URL, timeout=self.timeout, headers={"User-Agent": "Mozilla/5.0 (compatible; Momento-B)"}
            )
            resp.raise_for_status()
            products = resp.json().get("data")
            tags = {p["s"]: list(p.get("tags") or []) for p in products if isinstance(p, dict) and "s" in p}
            return tags or None  # una respuesta vacía o con otro formato no sirve para filtrar
        except (requests.RequestException, ValueError, AttributeError, TypeError, KeyError):
            return None

    def tickers_24h(self) -> list[dict]:
        return self._get(self.market.ticker_path, weight=self.market.ticker_weight)

    def klines(self, symbol: str, interval: str, limit: int) -> list[list]:
        limit = min(limit, self.market.max_klines)
        return self._get(
            self.market.klines_path,
            params={"symbol": symbol, "interval": interval, "limit": limit},
            weight=self.market.klines_weight(limit),
        )
