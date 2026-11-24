"""Escaneo diario automático (GitHub Actions): escanea y guarda el día en el seguimiento, como la web.

    python -m momento_b.diario escanear --seguimiento docs/seguimiento --salida dia.json
    python -m momento_b.diario unir dia.json --seguimiento docs/seguimiento

«escanear» usa los filtros del último escaneo de la web (docs/seguimiento/escaneo.json: mercado, velas y
volumen mínimo) y guarda cada moneda encontrada con su precio, su puntuación de giro y su libro de órdenes,
en el mismo formato que la web al pulsar «Escanear» con «Guardar en seguimiento». «unir» la añade al archivo
del día (AAAA-MM-DD.json): las monedas que ya estaban conservan su primer precio del día.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence
from zoneinfo import ZoneInfo

from .binance import MARKETS, BinanceClient, BinanceError
from .giro import (
    BOOK_GAP, BOOK_LIMIT, BOOK_READS, GIRO_VERSION, book_metrics, book_summary, closed_rows, conf_tf, giro_parts,
    giro_score, giro_weights, row,
)
from .scanner import INTERVAL_MINUTES, ScanConfig, scan_market

SETTINGS_FILE = "escaneo.json"  # filtros del último escaneo de la web
GIRO_FILE = "giro.json"         # pesos del indicador de giro
DEFAULTS = {"mercado": "ambos", "intervalo": "1d", "volumen_min": 0, "zona": "America/Lima"}
CHART_LIMIT = 299  # las mismas velas que usa la web para la puntuación
COIN_KEYS = ("mercado", "simbolo", "base", "quote", "precio", "hora", "intervalo", "giro", "libro")


def read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_settings(folder: Path) -> dict:
    """Filtros del último escaneo de la web; los que falten, los de por defecto."""
    saved = read_json(Path(folder) / SETTINGS_FILE) or {}
    out = dict(DEFAULTS)
    if saved.get("mercado") in ("ambos", "spot", "futures"):
        out["mercado"] = saved["mercado"]
    if saved.get("intervalo") in INTERVAL_MINUTES:
        out["intervalo"] = saved["intervalo"]
    if isinstance(saved.get("volumen_min"), (int, float)) and not isinstance(saved["volumen_min"], bool) and saved["volumen_min"] >= 0:
        out["volumen_min"] = saved["volumen_min"]
    if isinstance(saved.get("zona"), str):
        try:
            ZoneInfo(saved["zona"])
            out["zona"] = saved["zona"]
        except (KeyError, ValueError):
            pass
    return out


def day_key(ms: float, zone: str) -> str:
    """Día del seguimiento: la vela diaria de Binance (00:00 UTC) con la fecha que tiene en esa zona horaria.

    Como en la web: en Lima (UTC-5) la vela que abre el 1 oct a las 00:00 UTC es la «30-09».
    """
    t = datetime.fromtimestamp(ms / 1000, timezone.utc)
    opened = datetime(t.year, t.month, t.day, tzinfo=timezone.utc)
    return opened.astimezone(ZoneInfo(zone)).date().isoformat()


def iso_ms(ms: float) -> str:
    """Hora como la escribe la web (toISOString): 2026-11-24T16:00:12.345Z."""
    t = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _plain(value):
    """Números enteros sin «.0», como los escribe la web."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def clean_coin(coin: dict) -> dict:
    return {k: coin[k] for k in COIN_KEYS if coin.get(k) is not None}


def merge_day(existing: Optional[dict], fecha: str, coins: Sequence[dict]) -> tuple[dict, int]:
    """Une las monedas escaneadas con las del día: cada moneda una vez, con el primer precio en que apareció."""
    merged: dict[str, dict] = {}
    for coin in [*((existing or {}).get("monedas") or []), *coins]:
        if not isinstance(coin, dict) or not coin.get("mercado") or not coin.get("simbolo"):
            continue
        key = coin["mercado"] + ":" + coin["simbolo"]
        if key not in merged or str(coin.get("hora")) < str(merged[key].get("hora")):
            merged[key] = coin
    before = len((existing or {}).get("monedas") or [])
    day = {"fecha": fecha, "monedas": [clean_coin(c) for c in merged.values()]}
    return _plain(day), len(day["monedas"]) - before


def day_text(day: dict) -> str:
    return json.dumps(day, ensure_ascii=False, indent=1) + "\n"


def _pool(items, worker: Callable, workers: int = 8) -> list:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(worker, items))


def scan_tracking_market(client, interval: str, min_volume: float, weights: dict, notes: list[str],
                         now_ms: Optional[Callable[[], float]] = None, sleep: Callable[[float], None] = time.sleep,
                         log: Callable[[str], None] = print) -> list[dict]:
    """Escanea un mercado y devuelve sus monedas (sin la hora), con la puntuación de giro y el libro de órdenes."""
    now_ms = now_ms or (lambda: time.time() * 1000)
    market = client.market
    label = market.label
    result = scan_market(client, ScanConfig(interval=interval, min_quote_volume=min_volume, workers=8))
    notes.extend(f"{label}: {w}" for w in result.warnings)
    if result.errors:
        notes.append(f"{label}: {len(result.errors)} pares no respondieron "
                     f"({', '.join(s for s, _ in result.errors[:5])}{'…' if len(result.errors) > 5 else ''})")
    signals = result.signals
    log(f"{label}: {len(signals)} de {result.analyzed} pares cumplen la condición")
    if not signals:
        return []
    tf_ms = INTERVAL_MINUTES[interval] * 60000
    ctf = conf_tf(interval)
    ctf_ms = INTERVAL_MINUTES[ctf] * 60000

    def optional(load, default=None):
        try:
            return load()
        except BinanceError:
            return default

    def candles(symbol, tf, ms, limit=CHART_LIMIT):
        return optional(lambda: closed_rows([row(k) for k in client.klines(symbol, tf, limit)], ms, now_ms()))

    rows = _pool(signals, lambda s: candles(s.symbol, interval, tf_ms))
    conf = _pool(signals, lambda s: candles(s.symbol, ctf, ctf_ms))
    btc = candles("BTCUSDT", interval, tf_ms, 120)
    futs = [None] * len(signals)
    if market.key == "futures":
        funding = {}
        for p in optional(lambda: client.get("/fapi/v1/premiumIndex", weight=10), []) or []:
            try:
                funding[p["symbol"]] = float(p["lastFundingRate"])
            except (KeyError, TypeError, ValueError):
                pass
        end = now_ms()

        def open_interest(symbol):
            data = optional(lambda: client.get("/futures/data/openInterestHist", {
                "symbol": symbol, "period": "1h", "startTime": int(end - 25 * 3600000), "endTime": int(end), "limit": 30}))
            out = [[float(r["sumOpenInterest"]), float(r["sumOpenInterestValue"])]
                   for r in data or [] if int(r["timestamp"]) <= end]
            return out[-25:] if len(out) >= 2 else None

        futs = [{"oi": oi, "funding": funding.get(s.symbol)} for s, oi in
                zip(signals, _pool([s.symbol for s in signals], open_interest, 6))]

    # Libro de órdenes: tres vueltas por todas las monedas, con unos segundos entre una y otra.
    reads: list[list] = [[] for _ in signals]
    for round_ in range(BOOK_READS):
        t0 = time.monotonic()
        books = _pool(signals, lambda s: optional(lambda: client.get(
            market.depth_path, {"symbol": s.symbol, "limit": BOOK_LIMIT}, weight=5)))
        for i, book in enumerate(books):
            reads[i].append(book_metrics(book))
        if round_ < BOOK_READS - 1:
            sleep(max(0.0, BOOK_GAP - (time.monotonic() - t0)))
    missing = 0
    coins = []
    for i, s in enumerate(signals):
        coin = {"mercado": market.key, "simbolo": s.symbol, "base": s.base, "quote": s.quote, "precio": s.price,
                "intervalo": interval}
        partes = giro_parts(rows[i], conf[i], btc, futs[i]) if rows[i] else None
        if partes:
            coin["giro"] = {"v": GIRO_VERSION, "partes": partes, "puntos": giro_score(partes, weights)}
        libro = book_summary(reads[i])
        if libro:
            coin["libro"] = libro
        else:
            missing += 1
        coins.append(coin)
    if missing:
        notes.append(f"{label}: no se pudo leer el libro de órdenes de {missing} monedas")
    return coins


def scan_day(settings: dict, weights: dict, client_factory: Optional[Callable] = None,
             now_ms: Optional[Callable[[], float]] = None, sleep: Optional[Callable[[float], None]] = None,
             log: Callable[[str], None] = print) -> tuple[Optional[dict], list[str], list[str]]:
    """Escanea los mercados elegidos. Devuelve (día con las monedas o None, avisos, mercados que fallaron)."""
    client_factory = client_factory or BinanceClient
    now_ms = now_ms or (lambda: time.time() * 1000)
    sleep = sleep or time.sleep
    keys = ["spot", "futures"] if settings["mercado"] == "ambos" else [settings["mercado"]]
    coins, notes, failed = [], [], []
    for key in keys:
        client = client_factory(MARKETS[key])
        try:
            coins += scan_tracking_market(client, settings["intervalo"], float(settings["volumen_min"]), weights,
                                          notes, now_ms=now_ms, sleep=sleep, log=log)
        except BinanceError as exc:  # el otro mercado sigue
            failed.append(key)
            notes.append(f"{MARKETS[key].label}: {exc}")
    if not coins:
        return None, notes, failed
    hora = now_ms()  # como la web: la hora en que termina el escaneo
    for coin in coins:
        coin["hora"] = iso_ms(hora)
    return {"fecha": day_key(hora, settings["zona"]), "monedas": [clean_coin(c) for c in coins]}, notes, failed


def summary_markdown(settings: dict, day: Optional[dict], notes: Sequence[str]) -> str:
    vol = settings["volumen_min"]
    lines = [f"## Escaneo diario: {'spot y futuros' if settings['mercado'] == 'ambos' else settings['mercado']}, "
             f"velas {settings['intervalo']}, volumen mínimo {vol:g} USDT", ""]
    if day:
        lines += [f"**{len(day['monedas'])} monedas** para «Seguimiento {day['fecha']}».", "",
                  "| Moneda | Mercado | Precio | Giro |", "| --- | --- | ---: | ---: |"]
        for c in sorted(day["monedas"], key=lambda c: -((c.get("giro") or {}).get("puntos") or -1)):
            lines.append(f"| {c['simbolo']} | {c['mercado']} | {c['precio']:g} | {(c.get('giro') or {}).get('puntos', '—')} |")
    else:
        lines.append("Ninguna moneda cumple la condición.")
    if notes:
        lines += ["", "**Avisos**", ""] + [f"- {n}" for n in notes]
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m momento_b.diario", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="orden", required=True)
    esc = sub.add_parser("escanear", help="escanear y escribir las monedas del día en --salida")
    esc.add_argument("--seguimiento", default="docs/seguimiento", help="carpeta del seguimiento (filtros y pesos)")
    esc.add_argument("--salida", required=True, help="archivo JSON con el día escaneado")
    esc.add_argument("--mercado", choices=["ambos", "spot", "futures"], help="en vez del del último escaneo de la web")
    esc.add_argument("--intervalo", choices=list(INTERVAL_MINUTES), help="en vez del del último escaneo de la web")
    esc.add_argument("--volumen-min", type=float, help="en vez del del último escaneo de la web")
    esc.add_argument("--resumen", help="añadir un resumen en Markdown a este archivo ($GITHUB_STEP_SUMMARY)")
    uni = sub.add_parser("unir", help="añadir el día escaneado a su archivo del seguimiento")
    uni.add_argument("dia", help="archivo escrito por «escanear»")
    uni.add_argument("--seguimiento", default="docs/seguimiento")
    args = parser.parse_args(argv)

    folder = Path(args.seguimiento)
    if args.orden == "unir":
        scanned = read_json(Path(args.dia))
        if not scanned or not scanned.get("monedas"):
            print("No hay monedas que guardar.")
            return 0
        path = folder / f"{scanned['fecha']}.json"
        day, added = merge_day(read_json(path), scanned["fecha"], scanned["monedas"])
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(day_text(day), encoding="utf-8")
        print(f"{added} monedas nuevas en {path.name} ({len(day['monedas'])} en el día)")
        return 0

    settings = load_settings(folder)
    for key, value in (("mercado", args.mercado), ("intervalo", args.intervalo), ("volumen_min", args.volumen_min)):
        if value is not None:
            settings[key] = value
    print(f"Filtros: {settings}")
    day, notes, failed = scan_day(settings, giro_weights(read_json(folder / GIRO_FILE)))
    for note in notes:
        print(f"Aviso: {note}")
    Path(args.salida).write_text(day_text(day or {"fecha": None, "monedas": []}), encoding="utf-8")
    if args.resumen:
        with open(args.resumen, "a", encoding="utf-8") as fh:
            fh.write(summary_markdown(settings, day, notes))
    keys = ["spot", "futures"] if settings["mercado"] == "ambos" else [settings["mercado"]]
    if len(failed) == len(keys):  # ningún mercado respondió: que la ejecución salga en rojo
        print("Error: no se pudo escanear ningún mercado.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
