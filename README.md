# Momento-B

Scanner de criptomonedas de Binance por medias móviles.

Recorre **todos los pares de Binance Spot y Futuros USDⓈ-M (perpetuos)** y lista
las criptomonedas en las que:

```
MA(7) > MA(25)   y   MA(7) < MA(99)
```

Es decir: la media corta ya ha cruzado por encima de la media de 25, pero
todavía no ha alcanzado la de 99. Las medias son simples (SMA) sobre el precio
de cierre, las mismas que dibuja Binance por defecto en sus gráficos.

## Instalación

Requiere Python 3.10 o superior.

```bash
pip install -r requirements.txt
```

No hace falta API key: solo se usan endpoints públicos de datos de mercado.

## Uso

```bash
python -m momento_b                  # spot + futuros, velas de 4h, pares en USDT
python -m momento_b -i 1d            # velas diarias
python -m momento_b -m futures -i 1h # solo futuros, velas de 1h
python -m momento_b --min-volumen 5000000 --top 20
python -m momento_b --max-velas 5    # solo cruces MA7/MA25 de las últimas 5 velas
python -m momento_b --csv senales.csv --json senales.json
```

Ejemplo de salida (datos ilustrativos):

```
Momento-B · MA(7) > MA(25) y MA(7) < MA(99) · velas 4h · 2026-10-01 15:19 UTC

SPOT (USDT) — 57 coincidencias de 402 analizadas
#  Símbolo     Precio     MA7        MA25       MA99       Dist. MA99  Velas 7>25  Var. 24h  Vol. 24h
-  ----------  ---------  ---------  ---------  ---------  ----------  ----------  --------  --------
1  XXXUSDT        1.0204     1.0033    0.97658     1.0069      +0.36%           4    -4.09%   805.70M
...
```

### Columnas

| Columna        | Significado |
|----------------|-------------|
| `Precio`       | Último precio (cierre de la vela en curso). |
| `MA7/MA25/MA99`| Valor de cada media en la última vela evaluada. |
| `Dist. MA99`   | Cuánto (%) tiene que subir la MA7 para tocar la MA99. Cuanto menor, más cerca del cruce. |
| `Velas 7>25`   | Velas seguidas que lleva la MA7 por encima de la MA25 (`1` = cruzó en la última vela). Con `+` el cruce es anterior al histórico descargado. |
| `Var. 24h`     | Variación del precio en 24 h. |
| `Vol. 24h`     | Volumen negociado en 24 h, en la moneda de cotización. |

### Opciones

| Opción | Por defecto | Descripción |
|--------|-------------|-------------|
| `-m, --mercado {spot,futures,ambos}` | `ambos` | Mercado a escanear. |
| `-i, --intervalo` | `4h` | Temporalidad: `1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w 1M`. |
| `-q, --quote` | `USDT` | Moneda de cotización (`USDT`, `USDC`, `BTC`...). `ALL` para todas. |
| `--mas RAPIDA MEDIA LENTA` | `7 25 99` | Periodos de las medias. |
| `--min-volumen N` | `0` | Descarta pares con menos volumen 24 h (se filtran antes de descargar velas). |
| `--max-velas N` | — | Solo señales cuyo cruce MA7/MA25 fue hace N velas o menos. |
| `--solo-cerradas` | no | Ignora la vela en curso. Por defecto se incluye, igual que en el gráfico de Binance. |
| `--incluir-stables` | no | No descarta stablecoins/fiat como base (USDC, FDUSD, EUR...). |
| `-o, --orden` | `distancia` | `distancia` (a la MA99), `cruce` (más reciente), `volumen`, `variacion`, `simbolo`. |
| `--top N` | — | Muestra solo las N primeras de cada mercado. |
| `--csv / --json ARCHIVO` | — | Exporta los resultados. |
| `--workers N` | `8` | Descargas en paralelo. |
| `--spot-url / --futures-url` | API oficial | URL base alternativa de la API. |

## Qué pares se analizan

- **Spot**: pares con estado `TRADING` en la moneda de cotización elegida.
- **Futuros**: contratos USDⓈ-M **perpetuos** en estado `TRADING`. Se excluyen
  los trimestrales, los índices (p. ej. `BTCDOMUSDT`) y los de activos no cripto.
- Se descartan por defecto las stablecoins y monedas fiat como activo base.
- Los pares con menos de 99 velas de historial se cuentan aparte como
  "sin historial suficiente".

Al final se indica qué monedas cumplen la condición en spot y en futuros a la vez.

## Límites de la API

El scanner respeta el límite de peso por minuto de Binance (lo lee de
`exchangeInfo` y de la cabecera `X-MBX-USED-WEIGHT-1M`), espera si se acerca al
límite y reintenta ante errores `429` o de red. Un escaneo de spot + futuros en
USDT supone una petición de velas por par (del orden de 400 en spot y 500 en
futuros), por debajo del límite por minuto de ambos mercados.

Binance bloquea su API desde algunos países (respuesta `451`/`403`). En ese caso
el scanner lo indica y sigue con el otro mercado si puede; para spot puedes
probar `--spot-url https://data-api.binance.vision`.

## Tests

```bash
pip install pytest
python -m pytest
```
