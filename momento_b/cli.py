"""Interfaz de línea de comandos del scanner."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from .binance import MARKETS, BinanceClient, BinanceError
from .report import build_payload, signal_to_dict, write_report
from .scanner import SORT_KEYS, ScanConfig, ScanResult, Signal, scan_market

INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"]
REPORTS_DIR = Path("reportes")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="momento-b",
        description=(
            "Scanner de Binance (spot y futuros): lista las criptomonedas con la MA(7) "
            "por encima de la MA(25) pero todavía por debajo de la MA(99)."
        ),
    )
    p.add_argument("-m", "--mercado", choices=["spot", "futures", "ambos"], default="ambos",
                   help="mercado a escanear (por defecto: ambos)")
    p.add_argument("-i", "--intervalo", choices=INTERVALS, default="4h",
                   help="temporalidad de las velas (por defecto: 4h)")
    p.add_argument("-q", "--quote", default="USDT",
                   help="moneda de cotización: USDT, USDC, BTC... o ALL para todas (por defecto: USDT)")
    p.add_argument("--mas", nargs=3, type=int, default=[7, 25, 99], metavar=("RAPIDA", "MEDIA", "LENTA"),
                   help="periodos de las medias (por defecto: 7 25 99)")
    p.add_argument("--min-volumen", type=float, default=0.0, metavar="N",
                   help="volumen mínimo en 24h, en la moneda de cotización (ej. 1000000)")
    p.add_argument("--max-velas", type=int, metavar="N",
                   help="solo señales cuyo cruce de la MA rápida sobre la media fue hace N velas o menos")
    p.add_argument("--solo-cerradas", action="store_true",
                   help="ignorar la vela en curso (por defecto se incluye, como en el gráfico de Binance)")
    p.add_argument("--incluir-stables", action="store_true",
                   help="no descartar stablecoins/fiat como base (USDC, FDUSD, EUR...)")
    p.add_argument("-o", "--orden", choices=list(SORT_KEYS), default="distancia",
                   help="orden de la tabla: distancia a la MA lenta (por defecto), cruce más reciente, "
                        "volumen, variación 24h o símbolo")
    p.add_argument("--top", type=int, metavar="N", help="mostrar solo las N primeras de cada mercado")
    p.add_argument("--csv", metavar="ARCHIVO", help="guardar los resultados en CSV")
    p.add_argument("--json", metavar="ARCHIVO", help="guardar los resultados en JSON (incluye las velas)")
    p.add_argument("--html", metavar="ARCHIVO",
                   help="ruta del informe con los gráficos (por defecto: reportes/momento-b_<intervalo>_<fecha>.html)")
    p.add_argument("--sin-grafico", action="store_true", help="no generar el informe con los gráficos")
    p.add_argument("--no-abrir", action="store_true", help="generar el informe pero no abrirlo en el navegador")
    p.add_argument("--workers", type=int, default=8, help="descargas en paralelo (por defecto: 8)")
    p.add_argument("--spot-url", help="URL base de la API spot (por defecto: https://api.binance.com)")
    p.add_argument("--futures-url", help="URL base de la API de futuros (por defecto: https://fapi.binance.com)")
    return p


def format_price(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if value == 0:
        return "0"
    decimals = max(2, min(10, 4 - math.floor(math.log10(abs(value)))))
    return f"{value:,.{decimals}f}"


def format_volume(value: Optional[float]) -> str:
    if value is None:
        return "-"
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= limit:
            return f"{value / limit:.2f}{suffix}"
    return f"{value:.0f}"


def format_pct(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:+.2f}%"


def format_bars(signal: Signal) -> str:
    return str(signal.bars_since_cross) if signal.cross_seen else f"{signal.bars_since_cross}+"


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]], right_align: set[int]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(cell)) for w, cell in zip(widths, row)]

    def line(cells: Sequence[str]) -> str:
        return "  ".join(
            cell.rjust(w) if i in right_align else cell.ljust(w)
            for i, (cell, w) in enumerate(zip(cells, widths))
        ).rstrip()

    out = [line(headers), line(["-" * w for w in widths])]
    out.extend(line(row) for row in rows)
    return "\n".join(out)


def render_result(result: ScanResult, order: str, top: Optional[int]) -> str:
    config = result.config
    fast, mid, slow = config.periods
    quote = config.quote or "todas"
    signals = sorted(result.signals, key=SORT_KEYS[order])
    shown = signals[:top] if top else signals

    title = (
        f"{result.market.label.upper()} ({quote}) — {len(signals)} coincidencias "
        f"de {result.analyzed} analizadas"
    )
    notes = []
    if result.skipped_volume:
        notes.append(f"{result.skipped_volume} descartadas por volumen")
    if result.insufficient_data:
        notes.append(f"{result.insufficient_data} sin historial suficiente")
    if result.errors:
        notes.append(f"{len(result.errors)} con error")
    if notes:
        title += f" ({', '.join(notes)})"

    if not shown:
        return f"{title}\n  Ninguna moneda cumple la condición."

    headers = ["#", "Símbolo", "Precio", f"MA{fast}", f"MA{mid}", f"MA{slow}",
               f"Dist. MA{slow}", f"Velas {fast}>{mid}", "Var. 24h", "Vol. 24h"]
    rows = [
        [
            str(n),
            s.symbol,
            format_price(s.price),
            format_price(s.ma_fast),
            format_price(s.ma_mid),
            format_price(s.ma_slow),
            format_pct(s.dist_to_slow_pct),
            format_bars(s),
            format_pct(s.change_24h_pct),
            format_volume(s.quote_volume_24h),
        ]
        for n, s in enumerate(shown, 1)
    ]
    table = render_table(headers, rows, right_align={0, 2, 3, 4, 5, 6, 7, 8, 9})
    footer = f"\n  … y {len(signals) - len(shown)} más (quita --top para verlas todas)" if len(shown) < len(signals) else ""
    return f"{title}\n{table}{footer}"


CSV_FIELDS = [
    "mercado", "intervalo", "simbolo", "base", "quote", "precio", "ma_rapida", "ma_media", "ma_lenta",
    "dist_ma_lenta_pct", "velas_desde_cruce", "cruce_visible", "var_24h_pct", "volumen_24h",
]


def export_csv(path: str, results: Sequence[ScanResult], order: str) -> None:
    rows = [signal_to_dict(s, r.config.interval) for r in results for s in sorted(r.signals, key=SORT_KEYS[order])]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def export_json(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))


def _progress_printer(label: str):
    if not sys.stderr.isatty():
        return None

    def report(done: int, total: int) -> None:
        end = "\n" if done == total else ""
        print(f"\r  {label}: {done}/{total} pares descargados", end=end, file=sys.stderr, flush=True)

    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    fast, mid, slow = args.mas
    if not 0 < fast < mid < slow:
        parser.error("--mas debe cumplir 0 < RAPIDA < MEDIA < LENTA")
    if args.workers < 1:
        parser.error("--workers debe ser al menos 1")

    quote = None if args.quote.upper() == "ALL" else args.quote.upper()
    config = ScanConfig(
        interval=args.intervalo,
        periods=(fast, mid, slow),
        quote=quote,
        min_quote_volume=args.min_volumen,
        max_bars_since_cross=args.max_velas,
        closed_only=args.solo_cerradas,
        include_stables=args.incluir_stables,
        workers=args.workers,
    )
    market_keys = ["spot", "futures"] if args.mercado == "ambos" else [args.mercado]
    base_urls = {"spot": args.spot_url, "futures": args.futures_url}

    started = datetime.now(timezone.utc)
    print(
        f"Momento-B · MA({fast}) > MA({mid}) y MA({fast}) < MA({slow}) · velas {config.interval}"
        f"{' cerradas' if config.closed_only else ''} · {started:%Y-%m-%d %H:%M} UTC\n"
    )

    results: list[ScanResult] = []
    failed = False
    for key in market_keys:
        market = MARKETS[key]
        client = BinanceClient(market, base_url=base_urls[key], pool_size=max(config.workers, 10))
        try:
            result = scan_market(client, config, progress=_progress_printer(market.label))
        except BinanceError as exc:
            failed = True
            print(f"{market.label.upper()}: error — {exc}\n", file=sys.stderr)
            continue
        results.append(result)
        print(render_result(result, args.orden, args.top) + "\n")
        for symbol, error in result.errors[:5]:
            print(f"  ! {symbol}: {error}", file=sys.stderr)

    if len(results) == 2:
        common = sorted({s.base for s in results[0].signals} & {s.base for s in results[1].signals})
        if common:
            print(f"En spot y futuros a la vez ({len(common)}): {', '.join(common)}\n")

    if not results:
        return 1

    payload = build_payload(results, started, args.orden)
    if args.csv:
        export_csv(args.csv, results, args.orden)
        print(f"Resultados guardados en {args.csv}")
    if args.json:
        export_json(args.json, payload)
        print(f"Resultados guardados en {args.json}")
    if not args.sin_grafico:
        default_name = f"momento-b_{config.interval}_{started.astimezone():%Y%m%d-%H%M}.html"
        path = write_report(Path(args.html) if args.html else REPORTS_DIR / default_name, payload)
        print(f"Gráficos interactivos: {path}")
        if not args.no_abrir:
            webbrowser.open(path.resolve().as_uri())

    return 1 if failed else 0
