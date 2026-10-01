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

Al terminar, el scanner abre en el navegador una página con los gráficos de
las monedas encontradas (ver [Gráficos interactivos](#gráficos-interactivos)).

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
| `--incluir-acciones` | no | No descarta las acciones tokenizadas de Binance (bStocks). |
| `-o, --orden` | `distancia` | `distancia` (a la MA99), `cruce` (más reciente), `volumen`, `variacion`, `simbolo`. |
| `--top N` | — | Muestra solo las N primeras de cada mercado. |
| `--csv / --json ARCHIVO` | — | Exporta los resultados (el JSON incluye las velas de cada moneda). |
| `--html ARCHIVO` | `reportes/…` | Ruta del informe con los gráficos. |
| `--graficos INTERVALO…` | `2h 4h 8h 12h 1d` | Temporalidades que se pueden ver en los gráficos. |
| `--sin-grafico` | no | No genera el informe con los gráficos. |
| `--no-abrir` | no | Genera el informe pero no lo abre en el navegador. |
| `--servir` / `--puerto N` | no / `8000` | Abre el informe por `http://localhost` (automático en Codespaces). |
| `--workers N` | `8` | Descargas en paralelo. |
| `--spot-url / --futures-url` | API oficial | URL base alternativa de la API. |

## Gráficos interactivos

Después de cada escaneo se genera `reportes/momento-b_<intervalo>_<fecha>.html`
y se abre en el navegador. Es un solo archivo que puedes guardar o compartir.

- Una tarjeta por moneda con su gráfico de velas y las tres medias, con los
  colores de Binance: MA(7) amarillo, MA(25) rosa y MA(99) morado.
- **Gráfico: 2h / 4h / 8h / 12h / 1D** cambia la temporalidad de todos los gráficos.
  La fila «Cumple en» de cada tarjeta marca en qué temporalidades se cumple
  también MA(7) > MA(25) y MA(7) < MA(99).
- **Tamaño S / M / L** cambia el tamaño de todas las tarjetas.
- Al pulsar una tarjeta, o el botón de ampliar, el gráfico se abre a pantalla completa:
  - rueda del ratón o pellizco para acercar y alejar, y arrastrar para moverse en el tiempo;
  - botones `−` / `+` y «ver todo el historial» (teclas `-`, `+` y `0`);
  - al pasar el ratón se ven apertura, máximo, mínimo, cierre y el valor de cada media en esa vela;
  - selector de temporalidad propio (un punto marca dónde también se cumple la condición);
  - `←` / `→` pasan a la moneda anterior o siguiente y `Esc` cierra;
  - enlace directo al par en Binance.
- Filtros por mercado, búsqueda por símbolo y los mismos órdenes que en la terminal.
- «Cargar informe» (o arrastrar un archivo a la página) abre otro informe `.html`
  o un `.json` generado con `--json`.

Necesita conexión a internet para cargar la librería de gráficos
([TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/)).

## Qué pares se analizan

- **Spot**: pares con estado `TRADING` en la moneda de cotización elegida.
- **Futuros**: contratos USDⓈ-M **perpetuos** en estado `TRADING`. Se excluyen
  los trimestrales, los índices (p. ej. `BTCDOMUSDT`) y los de activos no cripto.
- Se descartan por defecto las stablecoins y monedas fiat como activo base.
- En spot se descartan también las **acciones tokenizadas** de Binance
  (*bStocks*: AAPLB, NVDAB, SPYB…), que cotizan en USDT como si fueran
  criptomonedas. Para saber cuáles son se consulta la lista de productos de la
  web de Binance; si no responde, el scanner avisa y no las descarta.
  `--incluir-acciones` las mantiene.
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

## Ejecutarlo en GitHub

El workflow `.github/workflows/scanner.yml` pasa los tests y hace un escaneo real:

- se ejecuta solo en cada pull request y en cada cambio en `main`;
- en **Actions → Scanner → Run workflow** se lanza a mano eligiendo servidor,
  mercado, temporalidad y volumen mínimo (el botón aparece cuando el workflow está en `main`).

El resultado se ve en el resumen de la ejecución, y el informe con los gráficos
se descarga en **Artifacts → momento-b**.

### Futuros y los servidores de EE. UU.

Los servidores de GitHub Actions están en EE. UU. y Binance rechaza desde allí la
API de futuros (error `451`). En spot se usa `data-api.binance.vision`, que sí
responde. Para escanear futuros, el escaneo tiene que salir desde otro país:

1. **GitHub Codespaces en Europa o Asia** (solo con el navegador, ver abajo).
2. **Tu ordenador**, con `python -m momento_b`, o registrándolo como ejecutor
   de GitHub (**Settings → Actions → Runners → New self-hosted runner**) y
   lanzando el workflow con **Servidor: mi-ordenador**. GitHub recomienda los
   ejecutores propios solo en repositorios privados.
3. **Un servidor propio (VPS) en un país donde Binance opere**, registrado como
   ejecutor igual que en la opción 2, si quieres lanzarlo desde el botón sin
   depender de tu ordenador.

Usar un proxy o una VPN para saltarse el bloqueo va contra las condiciones de
uso de Binance, así que no es una opción recomendada.

## Ejecutarlo en el navegador (GitHub Codespaces)

Codespaces es un ordenador en la nube que se usa desde el navegador (también
desde el móvil), así que no hace falta tener tu ordenador encendido. El plan
gratuito de GitHub incluye horas de uso al mes de sobra para escanear.

**Una sola vez — elegir la región:** en
[github.com/settings/codespaces](https://github.com/settings/codespaces), en
**Region**, elige **Europe West** (o **Southeast Asia**). No dejes "US East" ni
"US West", porque Binance bloquea EE. UU.

**Cada vez que quieras escanear:**

1. En el repositorio, **Code → Codespaces → Create codespace on main** (la
   primera vez tarda un par de minutos; después puedes reabrir el mismo).
2. En la terminal de abajo escribe:

   ```bash
   python -m momento_b
   ```

3. Al terminar, los gráficos se abren en una pestaña nueva. Si no se abre, ve a
   la pestaña **PUERTOS** (*PORTS*), puerto `8000`, y pulsa el icono del globo.
4. Pulsa `Ctrl+C` en la terminal cuando termines. El codespace se detiene solo
   tras 30 minutos sin uso.

Si en futuros sale el error `451`, Binance también bloquea esa región: borra el
codespace y crea otro con **Code → Codespaces → ··· → New with options →
Region** eligiendo la otra (Europe West ↔ Southeast Asia).

## Tests

```bash
pip install pytest
python -m pytest
```
