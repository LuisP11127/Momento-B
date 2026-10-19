# Seguimiento

La web guarda aquí un archivo por día (`AAAA-MM-DD.json`) con las monedas que encontró el
escáner ese día y su precio en ese momento, cuando está conectada con GitHub (apartado
**Seguimiento → Guardar también en GitHub**). `estrellas.json` guarda las estrellas de cada día
(`"AAAA-MM-DD|mercado:SÍMBOLO"`), también las quitadas, con la hora del cambio, para que cada
dispositivo sepa cuál es el último. Desde el indicador de giro, cada moneda guarda también
`giro` (la puntuación al escanear y sus partes) y `libro` (el resumen del libro de órdenes), y
`giro.json` guarda los pesos del indicador que se aplicaron en **Seguimiento → Indicador de giro**.
El workflow `Web` los une en `seguimiento.json` al publicar la página. Para borrar un día, usa el
botón **Borrar** de la web o elimina su archivo.
