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

## Versión web (en el navegador)

`docs/index.html` es el scanner completo en una sola página: se abre en el
navegador del móvil o del ordenador, pulsas **Escanear** y aparecen las monedas
con sus gráficos. Las peticiones a Binance salen **desde tu propio navegador y tu
conexión**, así que no hace falta ningún servidor ni tener el ordenador encendido.

Binance bloquea las conexiones que llegan desde servidores en la nube (GitHub
Actions o Codespaces, en cualquier región): esta versión evita ese problema
porque no pasa por ningún servidor.

### Publicarla con GitHub Pages

GitHub Pages es gratis en repositorios públicos (en privados hace falta GitHub Pro).

1. **Settings → General → Danger Zone → Change visibility → Public** (el código no
   contiene claves ni datos personales).
2. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. **Actions → Web → Run workflow**. Al terminar, la web queda en
   `https://<tu-usuario>.github.io/Momento-B/`. Guárdala en favoritos o en la
   pantalla de inicio del móvil.

El workflow `Web` vuelve a publicarla en cada cambio en `main` y una vez al día,
con la lista de acciones tokenizadas (bStocks) actualizada en `bstocks.json`.

Si prefieres mantener el repositorio privado, cualquier alojamiento de páginas
estáticas sirve. Por ejemplo, en Cloudflare Pages conecta el repositorio con el
comando de compilación `pip install -r requirements.txt && python -m momento_b.web site --bstocks`
y la carpeta de salida `site`.

Tras cambiar la plantilla de la página, regenera la web con
`python -m momento_b.web docs`.

### Seguimiento

Cada escaneo de la web (con **Guardar en seguimiento** marcado) guarda las monedas
encontradas, con su precio en ese momento, en un apartado **«Seguimiento 1 de
octubre»**, **«Seguimiento 2 de octubre»**… Si escaneas varias veces el mismo día,
se añaden las monedas nuevas y cada una conserva el primer precio del día.
Cada día del seguimiento es una **vela diaria de Binance**: empieza a las
**00:00 UTC** y lleva la fecha con que Binance la muestra en tu hora. Por ejemplo,
en UTC-5 la vela que empieza el 1 de octubre a las 00:00 UTC aparece en Binance
como la del 30-09 (abre a las 19:00 del 30): un escaneo hecho el 1 de octubre a
mediodía va a «Seguimiento 30 de septiembre», y desde las 19:00 de ese día, a
«Seguimiento 1 de octubre». Los gráficos muestran las velas en tu hora, igual que
Binance.

En la pestaña **Seguimiento** de la web:

- un apartado por día (el más reciente abierto) con las columnas **Moneda**,
  **Precio** del día del seguimiento (el del momento del escaneo), **Precio actual**,
  **Mínimo** y **Máximo** desde la hora del escaneo (con cuánto se alejaron del
  precio del seguimiento), **Rumbo al 50**, **Variación** (del precio del seguimiento
  al actual) y la hora del **Escaneo**, y un resumen: media, cuántas suben y bajan, la mejor y la
  peor. Mínimo, máximo y variación cuentan solo lo que pasó después del escaneo. Los
  precios se piden a Binance desde tu navegador (spot y futuros) y se actualizan
  cada minuto. El mínimo y el máximo salen de las velas de Binance desde ese
  momento (el primer tramo con velas de 1 minuto, empezando en el minuto del
  escaneo); se guardan en el navegador y en cada visita solo se descargan las velas
  nuevas;
- **Rumbo al 50**: cuántos días tardó el máximo en llegar a **+50 %** sobre el precio
  del seguimiento, contados desde la hora del escaneo y redondeando hacia arriba (en
  las primeras 24 horas es «1 día»), y la fecha en que llegó. Esa fila se pinta de
  verde y se queda así aunque luego baje. El momento se busca con velas de 1 o 5
  minutos;
- **estrellas**: la estrella de cada moneda (en las tarjetas del escáner, en el
  gráfico ampliado o en la tabla del seguimiento) la deja fijada, y en el
  seguimiento aparece primero en cada día donde esté. Cuenta el mercado: la de spot
  y la de futuros se marcan por separado;
- filtros **Todos / Spot / Futuros / No repetidas** y orden por subida, bajada,
  moneda u orden del escaneo (las monedas con estrella van siempre primero);
- al pulsar una moneda se abre su gráfico (1D por defecto) con una línea en el
  precio del seguimiento y una flecha en la vela de ese día;
- **Borrar** quita un día.

**Dónde se guarda.** Siempre en el navegador donde escaneas. Para tenerlo también
en el repositorio, y verlo igual en el móvil y en el ordenador, pulsa **Guardar
también en GitHub** y pega una clave de GitHub (*fine-grained token*) creada en
<https://github.com/settings/personal-access-tokens/new> con:

- **Repository access → Only select repositories →** este repositorio;
- **Permissions → Repository permissions → Contents → Read and write**.

La clave se guarda solo en ese navegador y solo se envía a GitHub. Cada día queda
como un archivo `docs/seguimiento/AAAA-MM-DD.json` y las estrellas en
`docs/seguimiento/estrellas.json`; el workflow `Web` los une en `seguimiento.json`
al publicar la página (en otros dispositivos aparece en un minuto). Lo que
escaneas sin conexión con GitHub se sube al conectarlo.

**Cuánto dura.** En GitHub, para siempre: los archivos se quedan en el repositorio
hasta que los borres (cada día ocupa unos 15 KB, unos 5 MB al año). Solo en el
navegador, hasta que borres los datos del sitio; si se llena (unos 2,5 MB), olvida
primero los días más antiguos que ya están en GitHub. La clave de GitHub caduca en
la fecha que elegiste al crearla: cuando pase, la web avisa de que no puede subir y
guarda los días como pendientes en el navegador; crea otra clave y vuelve a
conectar para subirlos.

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
- **Gráfico: 15m … 1D … 1W** cambia la temporalidad de todos los gráficos (por
  defecto **1D**). Cada cambio vuelve a pedir a Binance las velas del momento.
  La fila «Cumple en» de cada tarjeta marca en qué temporalidades (2h, 4h, 8h,
  12h y 1D) se cumple también MA(7) > MA(25) y MA(7) < MA(99).
- **Tamaño S / M / L** cambia el tamaño de todas las tarjetas.
- Al pulsar una tarjeta, o el botón de ampliar, el gráfico se abre a pantalla completa:
  - rueda del ratón o pellizco para acercar y alejar, y arrastrar para moverse en el tiempo;
  - botones `−` / `+` y «ver todo el historial» (teclas `-`, `+` y `0`);
  - al pasar el ratón se ven apertura, máximo, mínimo, cierre y el valor de cada media en esa vela;
  - selector de temporalidad propio, que también descarga velas nuevas al cambiar (un punto
    marca dónde también se cumple la condición);
  - `←` / `→` pasan a la moneda anterior o siguiente y `Esc` cierra;
  - enlace directo al par en Binance.
- Filtros por mercado (**Todos**, **Spot**, **Futuros** y **No repetidas**, que muestra cada
  moneda una sola vez y, si está en los dos mercados, se queda con la de spot), búsqueda
  por símbolo y los mismos órdenes que en la terminal.
- **Filtros** después de escanear (no hace falta volver a escanear; se combinan entre sí,
  se recuerdan en el navegador y el seguimiento guarda siempre todas las monedas):
  - **Solo velas cerradas**: quita las monedas que cumplen la condición solo gracias a la
    vela que todavía se está formando;
  - **Cruce reciente**: la MA rápida cruzó por encima de la media hace como mucho N velas
    (de la temporalidad del escaneo);
  - **Acumulación**: velas diarias seguidas, hasta la última cerrada, con el cuerpo
    (de la apertura al cierre, sin mechas) entre −X % y +X % durante al menos N días.
    La vela de hoy no cuenta. Al activarlo los gráficos pasan a 1D, una franja marca esas
    velas y cada tarjeta dice cuántos días lleva y entre qué variaciones.
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

En la versión web, cada petición tiene un tiempo máximo (20 s; más para las
listas grandes): si Binance no responde se corta y se repite, hasta 4 veces. Los
pares que aun así fallan se vuelven a intentar al final, más despacio, y los que
sigan sin responder se nombran en el aviso. Si fallan muchos seguidos (se cortó la
conexión), el escaneo de ese mercado se detiene y lo dice. El límite de peso se
comparte entre el escáner, los gráficos y el seguimiento.

Binance bloquea su API desde algunos países y desde servidores en la nube
(respuesta `451`/`403`). En spot el scanner pasa entonces a
`data-api.binance.vision`; en futuros lo indica y sigue con el otro mercado.

## Ejecutarlo en GitHub

El workflow `.github/workflows/scanner.yml` pasa los tests y hace un escaneo real:

- se ejecuta solo en cada pull request y en cada cambio en `main`;
- en **Actions → Scanner → Run workflow** se lanza a mano eligiendo mercado,
  temporalidad y volumen mínimo. Desde los servidores de GitHub solo funciona spot.

El resultado se ve en el resumen de la ejecución, y el informe con los gráficos
se descarga en **Artifacts → momento-b**.

### Futuros y los servidores en la nube

Binance rechaza con el error `451` las conexiones que llegan desde servidores en
la nube: GitHub Actions y GitHub Codespaces en cualquier región. Para spot, el
scanner cambia solo a `data-api.binance.vision`, la dirección de Binance para
datos públicos, que sí responde. Para futuros no hay alternativa: usa la
[versión web](#versión-web-en-el-navegador) o ejecuta `python -m momento_b` en tu
ordenador.

Usar un proxy o una VPN para saltarse el bloqueo va contra las condiciones de
uso de Binance, así que no es una opción recomendada.

## Tests

```bash
pip install pytest
python -m pytest
```

Pruebas de la web en el navegador (Chromium con [Playwright](https://playwright.dev/)),
con Binance, GitHub y GitHub Pages simulados, así que no necesitan conexión con ellos:

```bash
cd tests/web
npm ci
npx playwright install chromium
npx playwright test
```

GitHub las corre en cada cambio (workflow `Scanner`, job `web`). Prueban el escáner, el
seguimiento, «Rumbo al 50», los filtros, las estrellas, el guardado en GitHub y que el
escaneo no se cuelgue con una red inestable. Usan `docs/index.html`: tras cambiar la
plantilla, regenérala con `python -m momento_b.web docs`.
