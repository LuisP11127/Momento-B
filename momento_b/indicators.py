"""Indicadores técnicos usados por el scanner."""

from __future__ import annotations

from typing import Optional, Sequence


def sma(values: Sequence[float], period: int) -> list[Optional[float]]:
    """Media móvil simple, alineada con ``values``.

    Las posiciones sin suficientes datos (las primeras ``period - 1``) valen
    ``None``. Es la misma MA que dibuja Binance sobre los cierres.
    """
    if period <= 0:
        raise ValueError("el periodo debe ser positivo")
    out: list[Optional[float]] = [None] * len(values)
    window_sum = 0.0
    for i, value in enumerate(values):
        window_sum += value
        if i >= period:
            window_sum -= values[i - period]
        if i >= period - 1:
            out[i] = window_sum / period
    return out


def bars_above(fast: Sequence[Optional[float]], slow: Sequence[Optional[float]]) -> int:
    """Cuántas velas consecutivas, contando la última, lleva ``fast`` por encima de ``slow``.

    1 significa que el cruce se produjo en la última vela; 0 que no está por
    encima. Las velas donde alguna media no está definida cortan la cuenta.
    """
    count = 0
    for f, s in zip(reversed(fast), reversed(slow)):
        if f is None or s is None or f <= s:
            break
        count += 1
    return count
