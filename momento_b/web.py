"""Versión web: la misma página de gráficos con el escáner incluido, para abrirla en el navegador.

    python -m momento_b.web docs            # escribe docs/index.html
    python -m momento_b.web site --bstocks  # además site/bstocks.json con las acciones tokenizadas
    python -m momento_b.web site --seguimiento docs/seguimiento  # y site/seguimiento.json con todos los días

Junto a index.html se escribe icono.png (el icono de la pestaña y de la pantalla de inicio del móvil).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from .binance import SPOT, BinanceClient
from .report import render_report
from .scanner import is_tokenized_stock


DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COIN_FIELDS = ("mercado", "simbolo", "base", "quote", "precio", "hora", "intervalo")
STARS_FILE = "estrellas.json"  # monedas con estrella, en la misma carpeta que los días de seguimiento
STAR_KEY_RE = re.compile(r"^[a-z]+:\S+$")
ICON_PATH = Path(__file__).with_name("icono.png")


def collect_tracking(folder: Path) -> list[dict]:
    """Une los archivos de seguimiento (uno por día, AAAA-MM-DD.json), del día más reciente al más antiguo.

    La web los guarda en el repositorio; los que no tengan el formato esperado se ignoran.
    """
    days = {}
    for path in sorted(Path(folder).glob("*.json")):
        if path.name == STARS_FILE:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"Aviso: {path} no es un JSON válido; se ignora.")
            continue
        if not isinstance(data, dict) or not isinstance(data.get("monedas"), list):
            print(f"Aviso: {path} no tiene el formato de seguimiento; se ignora.")
            continue
        fecha = data.get("fecha")
        if not (isinstance(fecha, str) and DAY_RE.match(fecha)):
            fecha = path.stem if DAY_RE.match(path.stem) else None
        if not fecha:
            print(f"Aviso: {path} no indica la fecha; se ignora.")
            continue
        coins = [
            {field: coin.get(field) for field in COIN_FIELDS}
            for coin in data["monedas"]
            if isinstance(coin, dict) and coin.get("mercado") and coin.get("simbolo")
        ]
        days[fecha] = {"fecha": fecha, "monedas": coins}
    return [days[fecha] for fecha in sorted(days, reverse=True)]


def collect_stars(folder: Path) -> dict:
    """Estrellas que la web guarda en estrellas.json: {"spot:BTCUSDT": {"activa": true, "hora": "..."}}.

    Se publican también las quitadas (activa false): con su hora, la web sabe qué cambio es el más reciente.
    """
    path = Path(folder) / STARS_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"Aviso: {path} no es un JSON válido; se ignora.")
        return {}
    stars = data.get("estrellas") if isinstance(data, dict) else None
    if not isinstance(stars, dict):
        print(f"Aviso: {path} no tiene el formato de las estrellas; se ignora.")
        return {}
    return {
        key: {"activa": value["activa"], "hora": str(value.get("hora") or "")}
        for key, value in sorted(stars.items())
        if STAR_KEY_RE.match(key) and isinstance(value, dict) and isinstance(value.get("activa"), bool)
    }


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
    parser.add_argument("--seguimiento", metavar="CARPETA",
                        help="unir los archivos de seguimiento de CARPETA en seguimiento.json")
    args = parser.parse_args(argv)

    out = Path(args.carpeta)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(render_app(), encoding="utf-8")
    shutil.copyfile(ICON_PATH, out / ICON_PATH.name)
    print(f"Web escrita en {out / 'index.html'}")
    if args.seguimiento:
        days = collect_tracking(Path(args.seguimiento))
        data = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dias": days,
                "estrellas": collect_stars(Path(args.seguimiento))}
        (out / "seguimiento.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{len(days)} días de seguimiento en {out / 'seguimiento.json'}")
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
