# Tablas por seccion, paginacion real y exportacion de lo filtrado

- **Estado:** en curso
- **Creado:** 2026-09-04 por Claude Code
- **Objetivo:** que una tabla de auditoria muestre SOLO las columnas del
  hallazgo que se esta mirando, se navegue por paginas de 1.000 sin recargar
  lo ya visto, y se pueda exportar en XLSX/CSV/TXT exactamente lo que el
  filtro dejo — sin el checkbox de "cargar la tabla completa", que cuelga el
  navegador.

## Contexto

Pedido del usuario (2026-09-04) sobre `Auditoria > Entender la calidad del
catalogo`, seccion "Diferencia de estado o campos":

1. Al abrir la seccion **Concentracion** la tabla sigue mostrando las ~40
   columnas de todas las diferencias (principio activo, ATC, fechas, los
   trios completos). "ES ESTORBOSO, GENERA REDUNDANCIA". Debe mostrar solo:
   codigo, descripcion, el CAMPO VALIDADO (los dos lados) y los dos estados.
2. El checkbox "Cargar la tabla completa" es lento y **traba el equipo** si
   se pulsa al lado de la casilla. Se elimina; en su lugar, paginacion de
   1.000 en 1.000.
3. Las paginas ya cargadas deben quedar precargadas — incluso si el usuario
   sale de la vista y vuelve a entrar.
4. Exportar en XLSX / CSV / TXT **lo que el filtro dejo**, para sacar reportes
   rapido de cualquier vista filtrada.

Lo que YA existe y no hay que construir (verificado en codigo, 2026-09-04):

- El backend **ya pagina y filtra del lado del servidor**: `obtener_calidad`
  acepta `limite`, `offset`, `filtros_json`, y `PaginaTabla` devuelve
  `total` / `visibles` / `limite_aplicado` / `filas`
  (`backend/app/routers/calidades.py`, `backend/app/schemas.py`).
- Las secciones tienen **clave estructurada**: `campo:CONCENTRACION`,
  `fecha:FECHA_INICIO` (`_registro_secciones` en `auditoria/calidades.py`).
  De ahi sale, sin inventar nada, que campo se esta validando.
- Cada campo comparado viaja con su trio `<CAMPO>_GEMANET` / `_INVIMA` /
  `_VALIDACION` (`COLUMNAS_TRIO_CAMPOS_COMPARADOS`).
- Hay un mecanismo de descarga XLSX (`backend/app/routers/descargas.py`),
  pero solo de tablas COMPLETAS y sin filtros.

Reglas del proyecto en juego:

- **Regla de UI:** ninguna tabla se muestra en crudo y el recorte nunca se
  asume en silencio. El tope de 1.000 sigue, cambia como se navega el resto.
- **Regla #2 (degradacion explicita):** si una columna esperada no esta, se
  reporta; no se adivina una lista de columnas.
- **No recalcular en el frontend un veredicto que el backend ya emitio**
  (seccion UI del CLAUDE.md).

## Decisiones ya tomadas con el usuario

- **La descarga baja TODO el resultado del filtro**, no solo la pagina
  visible: si el filtro da 8.865 filas, el archivo trae 8.865 aunque en
  pantalla se vean 1.000. La paginacion es comodidad de pantalla, no debe
  recortar el entregable. El archivo lo arma el servidor.
- **Las columnas por seccion se deciden en el BACKEND.** Asi la tabla, el
  filtro por columna y la descarga ven lo mismo, y no viajan 40 columnas por
  la red para descartarlas al pintar.
- **Cache de paginas en memoria, y sobrevive a salir y volver a la vista**
  (pedido explicito: "cargo una tabla, me devuelvo, vuelvo a entrar y de
  nuevo la carga"). Se descarta al cambiar filtro/seccion/busqueda **y al
  cambiar el snapshot** — si no, tras un refresco se mostrarian datos viejos.

## Estructura: NO hay que cambiarla (medido, 2026-09-04)

La app corre sobre una sola vista: `render()` en `main.ts` llama a
`subActual.montar(vista)` y cada vista hace `contenedor.innerHTML = ...`, asi
que **cada navegacion destruye y recrea el DOM** (23 sitios lo hacen). La
pregunta era si eso obliga a rehacer la arquitectura para poder cachear.

No obliga. Medido contra el backend real:

| | |
|---|---|
| Pagina de 1.000 filas | **0,63 s · 2,0 MB · 38 columnas** |
| Columnas utiles en la seccion Concentracion | **8** |
| Datos de mas que viajan hoy | **79 %** |

Lo caro es la RED, no el DOM: recrear 1.000 filas en el navegador son
milisegundos, pedirlas son 0,6 s. Basta con que la cache y el estado de tabla
vivan en un MODULO y no en la instancia de `TablaFiltrable`, que si muere al
navegar. Al volver, la vista se remonta pero pinta desde memoria sin tocar la
red. Ya hay precedente: `_codigoPendiente` en `consulta_detalle.ts`.

Se descarta la alternativa de no destruir las vistas (ocultarlas con
`hidden`): daria scroll y filtros conservados gratis, pero obliga a revisar
los 23 sitios que asumen "monto desde cero", con riesgo de listeners
duplicados y fugas, para ganar milisegundos de DOM cuando el cuello esta en
la red.

**Consecuencia para el orden de los pasos:** se midio la seccion
`Concentracion` y pesa lo MISMO que sin seccion (2,2 MB) — las 38 columnas
viajan siempre y el frontend solo las esconde. El paso 1 no es estetica: es
la mayor ganancia de rendimiento de todo el trabajo (79 % menos datos por
pagina) y por si solo ya agiliza la app. Va primero.

## Pasos

- [ ] 1. (claude/implementador) `src/gemma_cum_loader/auditoria/calidades.py`
      — `columnas_de_seccion(clave)`: dada `campo:CONCENTRACION` devuelve
      `[CODIGO_INTERNO, DESCRIPCION, CONCENTRACION_GEMANET,
      CONCENTRACION_INVIMA, CONCENTRACION_VALIDACION, ACTIVO,
      ESTADO_CUM_INVIMA, ESTADO_INVIMA]`; para `fecha:FECHA_INICIO`, el par de
      fechas y su veredicto. Unica fuente de la lista, al lado de
      `_registro_secciones` para que no puedan discrepar.
- [ ] 2. (claude/implementador) `backend/app/routers/calidades.py` — cuando
      llega `seccion`, recortar las columnas con lo del paso 1. Degradar
      explicito: si una columna no esta en el DataFrame se omite y se anota,
      nunca se rompe la respuesta.
- [ ] 3. (claude/pruebas) `tests/test_calidades.py`,
      `tests/test_backend_calidades.py` — que la seccion de un campo trae su
      trio y NO los de los otros campos; que sin seccion las columnas no
      cambian (no romper las 6 tarjetas).
- [ ] 4. (claude/ui-vite) `backend/app/routers/descargas.py` —
      `GET /descargas/calidad/{nombre}` con `formato` (xlsx|csv|txt),
      `seccion`, `filtros_json`, `busqueda`. Reusa el MISMO filtrado del
      endpoint de tabla (extraerlo a una funcion compartida, no duplicarlo:
      duplicar es como la pantalla y el archivo acaban discrepando).
- [ ] 5. (claude/pruebas) `tests/test_backend_descargas.py` — que el archivo
      trae las filas del filtro (no la pagina), que respeta las columnas de
      la seccion, y los 3 formatos.
- [ ] 6. (claude/ui-vite) `frontend/src/cache_tablas.ts` (NUEVO) — store a
      nivel de MODULO con las paginas ya traidas y el estado de cada tabla
      (pagina actual, filtros, seccion), con clave
      {vista, seccion, filtros, busqueda, snapshot}. Tiene que vivir fuera de
      `TablaFiltrable`: esa instancia muere en cada navegacion (ver la
      seccion "Estructura" arriba).
- [ ] 7. (claude/ui-vite) `frontend/src/tabla.ts` — quitar el checkbox
      "Cargar la tabla completa" y `onCargarTodo`; barra de paginacion
      (anterior/siguiente + "pagina N de M"); leer y escribir en el store del
      paso 6 en vez de pedir siempre a la red.
- [ ] 8. (claude/ui-vite) `frontend/src/tabla.ts` + vista — botones de
      descarga XLSX/CSV/TXT que llevan el filtro vigente.
- [ ] 9. (claude/revisor) — revision antes del commit: que no quede un
      segundo mecanismo de render de tablas ni de descarga.

## Abierto

- La cache necesita saber cuando cambio el snapshot. `GET /salud` ya expone
  `ultima_actualizacion_utc`; usarlo como parte de la clave evita inventar un
  mecanismo nuevo. **Confirmar al implementar el paso 6.**
- Tope de la descarga: 59.005 filas x ~40 columnas en XLSX puede tardar. Con
  las columnas recortadas del paso 1 baja mucho, pero conviene medirlo antes
  de decidir si hace falta streaming o un aviso de espera.

## Verificacion

- [ ] `pytest` en verde
- [ ] `ruff check src/ tests/` limpio
- [ ] `cd frontend && npx tsc --noEmit` limpio
- [ ] Probado en pantalla: seccion Concentracion muestra 8 columnas, no 40
- [ ] Descarga de un filtro reducido trae exactamente esas filas
- [ ] Salir de la vista y volver NO vuelve a pedir la pagina ya cargada
- [ ] Linea agregada a `.ai/bitacora.jsonl`
