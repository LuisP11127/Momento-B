"""Indicador de giro y libro de órdenes, igual que en la web (momento_b/report_template.html).

La web los calcula al escanear desde el navegador; aquí se calculan igual para el escaneo diario de
GitHub Actions (momento_b/diario.py), de modo que el seguimiento guarde lo mismo venga de donde venga.
Cada vela es [apertura ms, A, M, m, C, volumen, volumen en USDT, compras a mercado (taker) en USDT].
Una prueba (tests/test_giro.py) compara estas funciones con las de la web.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

from .indicators import sma

GIRO_VERSION = 1
GIRO_PARTS = ("estructura", "volumen", "verdes", "obv", "flujo", "momento", "confirmacion", "futuros", "btc")
GIRO_DEFAULT = {"estructura": 1, "volumen": 1, "verdes": 1, "obv": 1, "flujo": 1.5, "momento": 1,
                "confirmacion": 1, "futuros": 1, "btc": 0.5}

BOOK_READS = 3      # lecturas del libro de órdenes de cada moneda
BOOK_GAP = 2.0      # segundos entre vueltas
BOOK_LIMIT = 100    # órdenes de cada lado
BOOK_BANDS = (1, 2, 5)


def js_round(x: float) -> float:
    """Math.round de JavaScript (las mitades hacia arriba), no el redondeo bancario de Python."""
    return math.floor(x + 0.5)


def conf_tf(tf: str) -> str:
    """Temporalidad de la confirmación: 4h si se escanea en 1D; si no, 1D."""
    return "4h" if tf == "1d" else "1d"


def _num(value) -> Optional[float]:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def row(k: Sequence) -> list:
    """Vela de Binance → [apertura ms, A, M, m, C, volumen, volumen en USDT, compras taker en USDT]."""
    return [int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]),
            _num(k[7]) if len(k) > 7 else None, _num(k[10]) if len(k) > 10 else None]


def closed_rows(rows: list, tf_ms: int, now_ms: float) -> list:
    """Las velas sin la última si todavía no ha cerrado."""
    return rows[:-1] if rows and rows[-1][0] + tf_ms > now_ms else rows


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _lin(x: float, a: float, b: float) -> float:
    return _clamp01((x - a) / (b - a))


def _mean(values) -> Optional[float]:
    v = [x for x in values if x is not None and math.isfinite(x)]
    return sum(v) / len(v) if v else None


def _sum(values) -> float:
    total = 0.0
    for x in values:  # en orden, como el reduce de la web
        total += x
    return total


def ema(values: Sequence[float], period: int) -> list[float]:
    k, out, e = 2 / (period + 1), [], None
    for v in values:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def rsi(closes: Sequence[float], period: int = 14) -> list[Optional[float]]:
    """RSI de Wilder."""
    out: list[Optional[float]] = [None] * len(closes)
    gain = loss = 0.0
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        if i <= period:
            gain += max(d, 0) / period
            loss += max(-d, 0) / period
            if i < period:
                continue
        else:
            gain = (gain * (period - 1) + max(d, 0)) / period
            loss = (loss * (period - 1) + max(-d, 0)) / period
        out[i] = 100 - 100 / (1 + gain / loss) if loss else 100
    return out


def _quote_vol(k) -> float:
    return k[6] if k[6] is not None and k[6] > 0 else k[5] * k[4]


def trend_part(rows) -> Optional[float]:
    """Cierre sobre la MA25, MA7 sobre la MA25 y MA7 subiendo (None si faltan velas)."""
    if not rows or len(rows) < 26:
        return None
    c = [k[4] for k in rows]
    i, m7, m25 = len(c) - 1, sma(c, 7), sma(c, 25)
    return _mean([1 if c[i] > m25[i] else 0, 1 if m7[i] > m25[i] else 0, 1 if m7[i] > m7[i - 1] else 0])


def futures_part(fut: Optional[dict]) -> Optional[float]:
    """Interés abierto de 24 h ([contratos, valor en USDT] cada hora) y última financiación."""
    oi = fut and fut.get("oi")
    if not oi or len(oi) < 2 or not oi[0][0] > 0 or not oi[-1][0] > 0:
        return None
    a, b = oi[0], oi[-1]
    oi_chg, px_chg = b[0] / a[0] - 1, (b[1] / b[0]) / (a[1] / a[0]) - 1
    if px_chg >= 0:
        s = 0.6 + 0.4 * _lin(oi_chg, 0, 0.15) if oi_chg >= 0 else 0.55
    else:
        s = 0.4 if oi_chg >= 0 else 0.25
    funding = fut.get("funding")
    if funding is not None:
        s += 0.1 if funding < 0 and px_chg >= 0 else -0.15 if funding > 0.0005 else 0
    return _clamp01(s)


def giro_parts(rows, conf, btc, fut) -> Optional[dict]:
    """Partes del indicador (de 0 a 1, con dos decimales). None si faltan velas."""
    n = len(rows) if rows else 0
    if n < 30:
        return None
    c = [k[4] for k in rows]
    i, m7, m25 = n - 1, sma(c, 7), sma(c, 25)
    vol = [_quote_vol(k) for k in rows]

    def total(a, b):
        return _sum(vol[a:b])

    p = {}
    p["estructura"] = _mean([1 if c[i] > m25[i] else 0, 1 if m7[i] > m7[i - 1] else 0,
                             _lin(m25[i] / m25[i - 5] - 1, -0.03, 0.03)])
    recent, before = total(n - 3, n) / 3, total(n - 23, n - 3) / 20
    p["volumen"] = _lin(math.log2(recent / before), -1, 1.5) if recent > 0 and before > 0 else None
    green = obv = 0.0
    for j in range(n - 10, n):
        if rows[j][4] >= rows[j][1]:
            green += vol[j]
    p["verdes"] = _lin(green / total(n - 10, n), 0.3, 0.8) if total(n - 10, n) > 0 else None
    for j in range(n - 20, n):
        d = c[j] - c[j - 1]
        obv += ((d > 0) - (d < 0)) * vol[j]
    p["obv"] = _lin(obv / total(n - 20, n), -0.3, 0.3) if total(n - 20, n) > 0 else None

    def buys(a, b):
        q = t = 0.0
        for j in range(a, b):
            if rows[j][6] is None or rows[j][7] is None:
                return None
            q += rows[j][6]
            t += rows[j][7]
        return t / q if q > 0 else None

    b6, b14 = buys(n - 6, n), buys(n - 20, n - 6)
    p["flujo"] = None if b6 is None or b14 is None else _mean([_lin(b6, 0.45, 0.6), _lin(b6 - b14, -0.05, 0.05)])
    r = rsi(c)
    ri = r[i]
    zone = _lin(ri, 30, 45) if ri < 45 else 1 if ri <= 65 else 1 - _lin(ri, 65, 80)
    e12, e26 = ema(c, 12), ema(c, 26)
    macd = [e12[j] - e26[j] for j in range(n)]
    signal = ema(macd, 9)

    def hist(j):
        return macd[j] - signal[j]

    p["momento"] = _mean([zone, _lin(ri - r[i - 3], -5, 10),
                          (0.6 if hist(i) > hist(i - 1) else 0) + (0.4 if hist(i) > 0 else 0)])
    p["confirmacion"] = trend_part(conf)
    p["btc"] = trend_part(btc)
    p["futuros"] = futures_part(fut)
    return {k: js_round(p[k] * 100) / 100 for k in GIRO_PARTS if p[k] is not None and math.isfinite(p[k])}


def giro_score(parts: Optional[dict], weights: dict) -> Optional[int]:
    if not parts:
        return None
    sw = s = 0.0
    for k in GIRO_PARTS:
        v, w = parts.get(k), weights.get(k)
        if v is None or not (w is not None and w > 0):
            continue
        sw += w
        s += w * v
    return int(js_round(100 * s / sw)) if sw else None


def giro_weights(saved: Optional[dict]) -> dict:
    """Pesos en uso: los de giro.json (si los hay) sobre los de por defecto."""
    w = dict(GIRO_DEFAULT)
    pesos = (saved or {}).get("pesos") or {}
    for k in GIRO_PARTS:
        v = _num(pesos.get(k)) if k in pesos and not isinstance(pesos.get(k), bool) else None
        if v is not None and v >= 0:
            w[k] = v
    return w


def book_metrics(depth: Optional[dict]) -> Optional[dict]:
    """Una lectura del libro de órdenes (las 100 mejores de cada lado)."""
    def side(levels):
        out = []
        for p, q in levels or []:
            p, q = float(p), float(q)
            if p > 0 and q > 0:
                out.append((p, q))
        return out

    bids, asks = side((depth or {}).get("bids")), side((depth or {}).get("asks"))
    if not bids or not asks:
        return None
    mid = (bids[0][0] + asks[0][0]) / 2

    def dist(p):
        return abs(p - mid) / mid * 100

    def read(levels):
        wall = levels[0]
        for lvl in levels:
            if lvl[0] * lvl[1] > wall[0] * wall[1]:
                wall = lvl
        sizes = sorted(p * q for p, q in levels)
        median = sizes[len(sizes) // 2]
        return {
            "levels": {p: p * q for p, q in levels},
            "bands": [_sum(p * q if dist(p) <= pct + 1e-9 else 0 for p, q in levels) for pct in BOOK_BANDS],
            "reach": dist(levels[-1][0]),
            "wall": {"price": wall[0], "usdt": wall[0] * wall[1], "times": wall[0] * wall[1] / median if median > 0 else None},
        }

    return {"mid": mid, "spread": (asks[0][0] - bids[0][0]) / mid * 100, "compras": read(bids), "ventas": read(asks)}


def book_summary(reads) -> Optional[dict]:
    """Resumen de las lecturas, con el mismo formato que guarda la web."""
    ok = [r for r in reads if r]
    if not ok:
        return None
    last = ok[-1]

    def r2(x):
        return js_round(x * 100) / 100

    def avg(f):
        return _sum(f(r) for r in ok) / len(ok)

    def side(name):
        w = last[name]["wall"]
        return {
            "bandas": {f"{pct}%": int(js_round(avg(lambda r: r[name]["bands"][i]))) for i, pct in enumerate(BOOK_BANDS)},
            "alcance": r2(avg(lambda r: r[name]["reach"])),
            "muro": {"precio": w["price"], "dist": r2((w["price"] - last["mid"]) / last["mid"] * 100),
                     "usdt": int(js_round(w["usdt"])), "veces": None if w["times"] is None else r2(w["times"]),
                     "lecturas": sum(1 for r in ok if r[name]["levels"].get(w["price"], 0) >= w["usdt"] * 0.5)},
        }

    return {"lecturas": len(ok), "spread": js_round(avg(lambda r: r["spread"]) * 1e4) / 1e4,
            "compras": side("compras"), "ventas": side("ventas")}
