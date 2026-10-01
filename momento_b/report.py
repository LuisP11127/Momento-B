"""Informe HTML interactivo con el gráfico de cada moneda encontrada."""

from __future__ import annotations

import http.server
import json
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import quote

from .scanner import INTERVAL_MINUTES, SORT_KEYS, ScanResult, Signal

TEMPLATE_PATH = Path(__file__).with_name("report_template.html")
BODY_MARKER = "<!--BODY-->"
DATA_MARKER = "__MOMENTO_DATA__"


def signal_to_dict(signal: Signal, interval: str, candles: bool = False, charts: Optional[dict] = None) -> dict:
    data = {
        "mercado": signal.market,
        "intervalo": interval,
        "simbolo": signal.symbol,
        "base": signal.base,
        "quote": signal.quote,
        "precio": signal.price,
        "ma_rapida": signal.ma_fast,
        "ma_media": signal.ma_mid,
        "ma_lenta": signal.ma_slow,
        "dist_ma_lenta_pct": round(signal.dist_to_slow_pct, 4),
        "velas_desde_cruce": signal.bars_since_cross,
        "cruce_visible": signal.cross_seen,
        "var_24h_pct": signal.change_24h_pct,
        "volumen_24h": signal.quote_volume_24h,
    }
    if candles:
        # [apertura ms, open, high, low, close, volumen]
        data["velas"] = [list(c) for c in signal.candles]
    if charts:
        # Las mismas velas en otras temporalidades: {"2h": [[...], ...], "1d": [...]}
        data["graficos"] = {tf: [list(c) for c in rows] for tf, rows in charts.items()}
    return data


def build_payload(
    results: Sequence[ScanResult],
    generated_at: datetime,
    order: str = "distancia",
    example: bool = False,
) -> dict:
    """Resultados del escaneo con las velas de cada moneda: lo que leen el informe y el .json."""
    config = results[0].config
    fast, mid, slow = config.periods
    intervals = {config.interval} | {tf for r in results for charts in r.charts.values() for tf in charts}
    return {
        "generado": generated_at.isoformat(timespec="seconds"),
        "intervalo": config.interval,
        "intervalos_grafico": sorted(intervals, key=lambda tf: INTERVAL_MINUTES.get(tf, 0)),
        "medias": list(config.periods),
        "condicion": f"MA{fast} > MA{mid} y MA{fast} < MA{slow}",
        "solo_cerradas": config.closed_only,
        "orden": order,
        "ejemplo": example,
        "mercados": {
            r.market.key: {
                "nombre": r.market.label,
                "quote": config.quote or "ALL",
                "analizadas": r.analyzed,
                "coincidencias": [
                    signal_to_dict(s, config.interval, candles=True, charts=r.charts.get(s.symbol))
                    for s in sorted(r.signals, key=SORT_KEYS[order])
                ],
            }
            for r in results
        },
    }


def render_report(payload: dict, standalone: bool = True) -> str:
    """HTML del informe. Con ``standalone=False`` devuelve solo el contenido (para publicarlo como artifact)."""
    head, body = TEMPLATE_PATH.read_text(encoding="utf-8").split(BODY_MARKER)
    # "<" solo aparece dentro de cadenas JSON; escaparlo evita cerrar el <script> que lo contiene.
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    body = body.replace(DATA_MARKER, data)
    if not standalone:
        return f"{head.strip()}\n{body.strip()}\n"
    return (
        "<!doctype html>\n<html lang=\"es\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        f"{head.strip()}\n</head>\n<body>\n{body.strip()}\n</body>\n</html>\n"
    )


def write_report(path: Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def make_server(path: Path, port: int) -> http.server.ThreadingHTTPServer:
    """Servidor local que sirve la carpeta del informe; la raíz redirige al informe."""
    path = Path(path).resolve()
    target = "/" + quote(path.name)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(path.parent), **kwargs)

        def do_GET(self):
            if self.path in ("", "/"):
                self.send_response(302)
                self.send_header("Location", target)
                self.end_headers()
                return
            super().do_GET()

        def log_message(self, format, *args):  # sin ruido en la terminal
            pass

    return http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve_report(path: Path, port: int = 8000, open_browser: bool = True) -> None:
    """Sirve el informe por http://localhost hasta Ctrl+C (útil en Codespaces o en un servidor remoto)."""
    with make_server(path, port) as httpd:
        url = f"http://localhost:{httpd.server_address[1]}/{quote(Path(path).name)}"
        print(f"Gráficos en {url}  (Ctrl+C para terminar)")
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print()
