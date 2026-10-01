"""Versión web: la misma página de gráficos con el escáner incluido, para abrirla en el navegador.

    python -m momento_b.web docs            # escribe docs/index.html
    python -m momento_b.web site --bstocks  # además site/bstocks.json con las acciones tokenizadas
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from .binance import SPOT, BinanceClient
from .report import render_report
from .scanner import is_tokenized_stock


def render_app() -> str:
    """Página sin resultados: se escanea desde el propio navegador."""
    return render_report(None)


def stock_symbols(client: Optional[BinanceClient] = None) -> list[str]:
    """Pares spot que Binance etiqueta como acciones tokenizadas (bStocks)."""
    tags = (client or BinanceClient(SPOT)).asset_tags()
    if tags is None:
        raise RuntimeError("no se pudo consultar la lista de productos de Binance")
    return sorted(symbol for symbol, symbol_tags in tags.items() if is_tokenized_stock(symbol_tags))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m momento_b.web", description=__doc__.splitlines()[0])
    parser.add_argument("carpeta", nargs="?", default="docs", help="carpeta de salida (por defecto: docs)")
    parser.add_argument("--bstocks", action="store_true", help="escribir también bstocks.json")
    args = parser.parse_args(argv)

    out = Path(args.carpeta)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(render_app(), encoding="utf-8")
    print(f"Web escrita en {out / 'index.html'}")
    if args.bstocks:
        try:
            symbols = stock_symbols()
        except RuntimeError as exc:
            print(f"Aviso: {exc}; la web avisará de que pueden aparecer acciones tokenizadas.")
            return 0
        data = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "simbolos": symbols}
        (out / "bstocks.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(symbols)} acciones tokenizadas en {out / 'bstocks.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
