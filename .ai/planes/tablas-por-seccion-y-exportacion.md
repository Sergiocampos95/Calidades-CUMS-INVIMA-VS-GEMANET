# Tablas por seccion, paginacion real y exportacion de lo filtrado

- **Estado:** terminado
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

- **La descarga baja la SECCION COMPLETA, no la pagina visible ni el filtro.**
  CORREGIDO por el usuario el 2026-09-04: "si estamos en Descripcion
  diferencia vamos a exportar la calidad completa de diferencia en
  descripcion... ya no hace falta exportar solo lo que se muestra en pantalla
  sino todo". O sea: se respeta la SECCION abierta (es el contexto de trabajo)
  y se ignoran los filtros de columna. El endpoint los sigue aceptando como
  opcionales -- no estorban y el frontend simplemente no los manda.
  Medido, ya con el recorte de columnas del paso 1, el coste es bajo hasta en
  la seccion mas grande:

  | seccion | filas | xlsx |
  |---|---|---|
  | Principio activo | 8.865 | 1,3 s · 0,4 MB |
  | Descripcion | 14.630 | 1,8 s · 0,6 MB |
  | Fecha fin | 57.255 | 4,8 s · 2,2 MB |

  El caso lento (24 s / 10,9 MB) es solo la calidad SIN seccion, con las 38
  columnas -- que con esta correccion ya no es lo que descarga el boton.
- **Las columnas por seccion se deciden en el BACKEND.** Asi la tabla, el
  filtro por columna y la descarga ven lo mismo, y no viajan 40 columnas por
  la red para descartarlas al pintar.
- (paso 1) `columnas_de_seccion(clave)` DERIVA las columnas del prefijo de la
  clave (`campo:` / `fecha:`), no de una lista aparte: asi "que secciones
  existen" y "que columnas trae cada una" no pueden discrepar si se agrega o
  quita un campo comparado. Devuelve 8 columnas donde viajaban 38.
- (paso 1) Clave desconocida o vacia -> **tupla vacia**, que el paso 2 debe
  interpretar como "no recortar". Nunca inventar columnas para una seccion
  que no existe.
- (paso 1) `PARES_FECHAS_GEMANET_INVIMA` (coherencia_invima.py) **dejo de ser
  privada**: `columnas_de_seccion` la necesita para saber que par de fechas
  mostrar, y duplicar el mapeo era pedir que discrepen -- ya cambio una vez
  (FECHA_FIN dejo de compararse contra FECHA INACTIVO). Si un modulo hermano
  la necesita, no es privada; importar con guion bajo era saltarse la senal.
- (paso 2) El recorte se aplica SOLO en el endpoint de la tabla, no en el de
  `valores` de una columna: ese ya recibe la columna puntual que el usuario
  eligio entre las que la tabla muestra, y recortar ahi tambien arriesgaria
  dejar el filtro sin opciones si las dos listas discreparan.
- (paso 2) Una columna de la lista que no exista en el DataFrame se OMITE
  (`[c for c in columnas if c in tabla.columns]`), no rompe. Es el mismo
  patron que ya usa `calidades_auditoria()` al armar cada `Calidad`.
- (paso 2) **MEDIDO tras el recorte:** 2,01 MB -> 0,61 MB en Concentracion
  (-70 %) y 0,45 MB en Fecha inicio (-78 %). Pero el TIEMPO no bajo (0,65 s
  en los tres casos): el coste esta en filtrar el DataFrame, no en
  serializar. La ganancia es de ancho de banda y memoria del navegador.
  **Consecuencia para el paso 6: la cache importa mas de lo previsto**, porque
  esos 0,65 s son un coste fijo por pagina que solo se evita no volviendo a
  pedirla.
- (paso 3) 9 pruebas nuevas, verificadas POR MUTACION: se rompio
  `columnas_de_seccion` a proposito (que devolviera el trio de todos los
  campos, el bug que el paso 1 vino a arreglar) y fallaron las dos que tenian
  que fallar -- la unitaria y la del endpoint. Una prueba que pasa no sirve si
  no cae cuando el bug vuelve.
- (paso 3) La degradacion ante columna ausente esta en DOS capas y ninguna
  rompe: `_definiciones` (calidades.py) ya la excluye del `df_tabla` antes de
  llegar al router, y `_con_columnas_de_seccion` la filtra otra vez.
- **OPTIMIZACION (fuera de los pasos, 2026-09-04):** se perfilo de donde
  salian los 0,65 s por peticion. `leer_tabla` ya cacheada: 0 ms;
  `filtrar_por_seccion`: 34 ms; **`calidades_auditoria`: 666 ms**. O sea, el
  100 % del coste era rehacer las 6 mascaras y las columnas derivadas sobre
  199.611 filas para devolver 1.000, en CADA request (tabla, valores,
  secciones y descarga). Se cacheo `_calidades()` por snapshot, mismo patron
  que `_CACHE_TABLAS`. **Medido: 1.177 ms la primera peticion, 54-117 ms las
  siguientes (~10x).** Cubierto por
  `test_un_snapshot_nuevo_invalida_las_calidades_cacheadas`, verificado por
  mutacion: una cache que no se invalida serviria cifras viejas tras un
  refresco, que es el fallo que ya costo una sesion entera aca.
  **Consecuencia para los pasos 6 y 7:** la cache del NAVEGADOR ya no es
  critica para el rendimiento; sigue teniendo sentido para no re-pedir al
  volver a la vista (pedido explicito del usuario), pero el cuello real ya
  esta resuelto en el backend y beneficia a TODAS las vistas, no solo a esta.
- (paso 5) 8 pruebas del endpoint de descarga, verificadas por DOS mutaciones:
  (a) recortar la descarga a 1.000 filas -> cayo la prueba del alcance;
  (b) escribir el csv/txt sin BOM -> cayeron las dos de formato. Ese BOM no es
  cosmetico: sin el, Excel de Windows muestra "DESCRIPCIÃ“N" y nadie lo nota
  hasta que un usuario abre el reporte.
- (paso 6) El snapshot es **un campo mas de la clave**, no una comprobacion
  aparte como en el backend. Efecto: una consulta contra un snapshot nuevo
  jamas puede leer una entrada del viejo, porque la clave entera es distinta
  -- no hace falta que nadie dispare un "borrar todo" al detectar el refresco.
  `invalidarTodo()` queda como reset explicito, no como parte del flujo.
- (paso 6) Tope **30 paginas** con LRU (Map + borrar-y-reinsertar). Sale de la
  medicion: ~0,6 MB por pagina recortada y ~2,0 MB en el peor caso sin
  seccion, o sea ~60 MB de techo. Sin tope se repetiria el problema que
  reporto el usuario con "cargar todo" ("hasta se trababa el computador").
- (paso 6) `EstadoTabla` (donde estaba parado el usuario) NO lleva snapshot ni
  LRU: es posicion de navegacion, no dato cacheado. Sobrevive a un refresco, y
  las paginas que se repidan ya iran con la clave del snapshot nuevo.
- (paso 6) Usa `offset` y no "numero de pagina" porque es lo que ya viaja entre
  `TablaFiltrable`, `ParametrosTabla` y `PaginaTabla` -- evita una conversion
  al conectarlo en el paso 7.
- **Cache de paginas en memoria, y sobrevive a salir y volver a la vista**
  (pedido explicito: "cargo una tabla, me devuelvo, vuelvo a entrar y de
  nuevo la carga"). Se descarta al cambiar filtro/seccion/busqueda **y al
  cambiar el snapshot** — si no, tras un refresco se mostrarian datos viejos.

- (pasos 7-8) El checkbox "Cargar la tabla completa" se ELIMINO. En su lugar
  un pie debajo de la tabla con paginacion (Anterior / "Pagina N de M · filas
  X-Y" / Siguiente) y los tres botones de descarga, que dicen cuantas filas
  trae el archivo -- no son las que se ven, y sin ese rotulo el usuario no
  tiene como saberlo.
- (pasos 7-8) `TablaFiltrable` gano `idTabla`, `seccion` y `urlDescarga`, los
  tres OPCIONALES: una tabla que no los pase funciona igual que antes, solo
  sin cache ni botones. Asi las 8 tablas existentes no habia que tocarlas.
- (pasos 7-8) El snapshot para la clave de cache lo escribe `salud.ts`, que ya
  sondea /salud para el anillo de "hace N min". Un solo sitio sabe cual es el
  snapshot vigente; las tablas solo leen. Evita que cada tabla pregunte por su
  cuenta.
- (pasos 7-8) **Caso borde encontrado al debuggear:** una pagina vacia con
  `offset > 0` no es "no hay hallazgos", es que el conjunto encogio debajo de
  donde estaba parado el usuario (refresco con menos filas, estado restaurado
  de la sesion anterior). Se vuelve solo a la primera pagina en vez de mostrar
  una tabla en blanco, que aca se leeria como un error.
- (pasos 7-8) Cambiar busqueda, orden o filtro devuelve a la pagina 1:
  quedarse en la pagina 7 de un resultado que ahora tiene 3 es otra forma de
  llegar a una tabla vacia que parece rota.

- (paso 9) La revision encontro **cinco cosas reales**, todas corregidas:
  1. **El refresco manual servia datos VIEJOS desde la cache.** `ClavePagina.
     snapshot` sale del sondeo de /salud, que corre cada 60 s: justo despues
     de "Actualizar ahora" esa marca sigue siendo la anterior, la clave calza
     y se pinta la pagina vieja -- sin pasar siquiera por "Cargando…".
     Quedaba el encabezado con cifras nuevas y la tabla con las viejas.
     `main.ts` ahora llama a `invalidarTodo()` antes de repintar.
  2. **El rotulo de descarga mentia con filtro activo:** decia "Descargar las
     37 filas" y bajaba 14.630, porque `pagina.total` es el conteo YA filtrado
     y el archivo ignora los filtros. Con filtro activo ahora lo dice en vez
     de dar un numero falso.
  3. **La descarga sin seccion (24,9 s) no avisaba.** Como es un `<a
     download>` el navegador no muestra progreso y lo natural es volver a
     pulsar, lanzando otra generacion completa. Se avisa a partir de 20.000
     filas.
  4. **`ESTADO_INVIMA` dependia del LOTE:** el criterio por `nunique` hacia
     que una sola fila sucia de Vigentes volcara las 43.312 a "Vigente
     (Vigente)", y que un `otros_estados` homogeneo ESCONDIERA el estado real.
     Sustituido por `DETALLE_REDUNDANTE_POR_LISTADO`, explicito y por fila.
  5. **`_con_estado_listado_invima` era codigo muerto:** su corte temprano
     disparaba siempre, asi que solo copiaba los 6 `df_tabla` para devolverlos
     identicos. Eliminada.
- (paso 9) Lo que la revision descarto explicitamente, para no volver a
  mirarlo: ningun llamador MUTA los `Calidad` cacheados (los cinco consumidores
  solo leen o producen DataFrames nuevos); backend y frontend versionan por la
  MISMA marca (`Snapshot.nombre == generado_utc`, que es lo que expone
  /salud); y el filtrado no quedo duplicado -- pantalla y descarga comparten
  `tabla_calidad_filtrada` -> `filtrar_tabla`.

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

- [x] 1. (claude/implementador) `src/gemma_cum_loader/auditoria/calidades.py`
      — `columnas_de_seccion(clave)`: dada `campo:CONCENTRACION` devuelve
      `[CODIGO_INTERNO, DESCRIPCION, CONCENTRACION_GEMANET,
      CONCENTRACION_INVIMA, CONCENTRACION_VALIDACION, ACTIVO,
      ESTADO_CUM_INVIMA, ESTADO_INVIMA]`; para `fecha:FECHA_INICIO`, el par de
      fechas y su veredicto. Unica fuente de la lista, al lado de
      `_registro_secciones` para que no puedan discrepar.
- [x] 2. (claude/implementador) `backend/app/routers/calidades.py` — cuando
      llega `seccion`, recortar las columnas con lo del paso 1. Degradar
      explicito: si una columna no esta en el DataFrame se omite y se anota,
      nunca se rompe la respuesta.
- [x] 3. (claude/pruebas) `tests/test_calidades.py`,
      `tests/test_backend_calidades.py` — que la seccion de un campo trae su
      trio y NO los de los otros campos; que sin seccion las columnas no
      cambian (no romper las 6 tarjetas).
- [x] 4. (claude/ui-vite) `backend/app/routers/descargas.py` —
      `GET /descargas/calidad/{nombre}` con `formato` (xlsx|csv|txt),
      `seccion`, `filtros_json`, `busqueda`. Reusa el MISMO filtrado del
      endpoint de tabla (extraerlo a una funcion compartida, no duplicarlo:
      duplicar es como la pantalla y el archivo acaban discrepando).
- [x] 5. (claude/pruebas) `tests/test_backend_descargas.py` — que el archivo
      trae la SECCION COMPLETA (no la pagina de 1.000), que respeta las
      columnas de la seccion, y los 3 formatos.
- [x] 6. (claude/ui-vite) `frontend/src/cache_tablas.ts` (NUEVO) — store a
      nivel de MODULO con las paginas ya traidas y el estado de cada tabla
      (pagina actual, filtros, seccion), con clave
      {vista, seccion, filtros, busqueda, snapshot}. Tiene que vivir fuera de
      `TablaFiltrable`: esa instancia muere en cada navegacion (ver la
      seccion "Estructura" arriba).
- [x] 7. (claude/ui-vite) `frontend/src/tabla.ts` — quitar el checkbox
      "Cargar la tabla completa" y `onCargarTodo`; barra de paginacion
      (anterior/siguiente + "pagina N de M"); leer y escribir en el store del
      paso 6 en vez de pedir siempre a la red.
- [x] 8. (claude/ui-vite) `frontend/src/tabla.ts` + vista — botones de
      descarga XLSX/CSV/TXT que llevan el filtro vigente.
- [x] 9. (claude/revisor) — revision antes del commit: que no quede un
      segundo mecanismo de render de tablas ni de descarga.

## Abierto

Nada: el plan quedo cerrado el 2026-09-07.

## Verificacion

- [x] `pytest` en verde (618)
- [x] `ruff check src/ tests/ backend/ worker/` limpio
- [x] `cd frontend && npx tsc --noEmit` limpio + `npm run build`
- [x] Verificado contra la API real: la seccion trae 8 columnas, no 38
- [x] La descarga trae la seccion completa (2.000) con la pantalla en 1.000
- [x] Cache probada ejecutandola (acierto, invalidacion por snapshot, LRU)
- [x] Linea agregada a `.ai/bitacora.jsonl`
