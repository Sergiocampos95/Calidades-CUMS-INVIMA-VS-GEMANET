# Auditoria: universo auditable, fechas de ambas fuentes y consulta de los 4 listados

- **Estado:** en curso
- **Creado:** 2026-09-01 por Claude Code
- **Objetivo:** que la auditoria muestre unicamente CUMs activos (con la unica
  excepcion de inactivo-aqui/vigente-en-INVIMA), que cada fila traiga el estado
  y las fechas de LAS DOS fuentes, y que la consulta puntual encuentre un CUM en
  cualquiera de los 4 listados de INVIMA, no solo en Vigentes.

## Contexto

Pedido del usuario (2026-09-01). Buena parte ya estaba implementada sin
commitear: `ESTADO_LISTADO_INVIMA`, `FECHA_ACTIVO_INVIMA`/`FECHA_INACTIVO_INVIMA`,
`filtrar_universo_auditable()` y la calidad "Inactivo en Gemma Net pero vigente
en INVIMA". Lo que falta son cuatro huecos.

**Caso testigo `20102710-2`** (verificado contra `ListadoCodigoUnicoVencidos2022.xlsx`
y el snapshot de produccion):

| Campo | INVIMA (Vencidos) | Gemma Net | Veredicto |
|---|---|---|---|
| FECHA ACTIVO | `07/23/2016` | FECHA_INICIO `2016-07-23` | coincide |
| FECHA INACTIVO | `10/01/2021` | FECHA_FIN `2999-12-31` | **no coincide** |
| ESTADO CUM | `Inactivo` | ACTIVO `Si` | **contradiccion** |

Confirma la regla de negocio: **INVIMA `FECHA_ACTIVO` ↔ Gemma `FECHA_INICIO`,
INVIMA `FECHA_INACTIVO` ↔ Gemma `FECHA_FIN`**.

Por que "para algunos medicamentos si sirve y para otros no": el merge contra
INVIMA solo se hace contra **Vigentes** (`coherencia_invima.py`, el
`gemanet.merge(invima_reducido, ...)`). Toda fila resuelta por
Vencidos/Otros/Renovacion llegaba **sin ninguna fecha de INVIMA**. Los 4 datasets
comparten las mismas 29 columnas (verificado contra los respaldos reales), asi
que la correccion es estructural.

**Huecos:**

- **A.** `filtrar_universo_auditable()` esta escrita y probada pero **nunca se
  llama**. `pipeline.py:418` dice que aplicarla fue un error; en cambio
  `backend/app/routers/auditoria.py:74` y `tests/test_backend_auditoria.py:120`
  asumen que el snapshot ya viene filtrado. Contradiccion activa.
- **B.** `worker/tareas.py` solo persiste `universo` = Vigentes. Por eso la
  consulta de `20102710-2` no muestra ninguna fila de INVIMA.
- **C.** Las columnas de fecha ya viajan pero **nada las compara**.
- **D.** Bug: `INCONSISTENCIA_FECHAS_ACTIVO` duplica el mensaje (dos `.mask()`
  encadenados; el segundo evalua la Serie ya modificada por el primero).

Reglas del proyecto en juego: **#1** (sin decisiones a ciegas), **#2**
(degradacion explicita), **#5** (`-999` centinela), **#6** (`PORCENTAJE_CALIDAD`
vacio, no 0 %). Y las fechas comodin (`2999-12-31`, `1900-01-01`) son "sin dato",
no una diferencia de fecha.

## Pasos

Un paso, un dueno, los archivos que toca. `[ ]` libre · `[~]` tomado · `[x]` hecho.

- [x] 1. (claude/implementador) `src/gemma_cum_loader/auditoria/coherencia_invima.py`
      + `tests/test_coherencia_invima.py` — arreglar el bug D (mensaje duplicado)
      con un test que lo reproduzca primero.
- [x] 2. (claude/implementador) `src/gemma_cum_loader/auditoria/coherencia_invima.py`
      — hueco C: columna `COHERENCIA_FECHAS_INVIMA` comparando `FECHA_INICIO` vs
      `FECHA_ACTIVO_INVIMA` y `FECHA_FIN` vs `FECHA_INACTIVO_INVIMA`. Reusar
      `_es_fecha_real()` y `FECHAS_CENTINELA`. Vacia si no hay correspondencia.
      Vectorizado, sin `apply` (199.611 filas).
- [x] 3. (claude/implementador) `backend/app/routers/auditoria.py`,
      `backend/app/routers/calidades.py`, `auditoria/calidades.py` — hueco A:
      aplicar `filtrar_universo_auditable` en `_tabla_auditoria()` del router
      (NO en `pipeline.py` — ver `## Decisiones`, se cambio de enfoque durante
      la ejecucion por una razon medida), corregir el denominador de los
      porcentajes de las calidades, y reconciliar los comentarios que se
      contradecian.
- [x] 4. (claude/implementador) `worker/tareas.py` — hueco B: persistir tabla
      `invima_listados` = los 4 DataFrames ya en memoria concatenados + columna
      `LISTADO` (`vigente|vencido|renovacion|otros_estados`). Sin lecturas nuevas
      de Socrata. Reusar `escribir_snapshot`.
- [x] 5. (claude/implementador) `backend/app/routers/consulta_detalle.py` —
      buscar en `invima_listados` ademas de `universo`; exponer `LISTADO`,
      `FECHA_ACTIVO`, `FECHA_INACTIVO` por fila de INVIMA.
- [ ] 6. (copilot) `frontend/src/vistas/consulta_detalle.ts` — panel INVIMA:
      mostrar el listado de origen y las fechas de LAS DOS fuentes lado a lado.
      **Bloqueado hasta que 5 este `[x]`.** Ver "Contrato para Copilot".
- [x] 7. (claude/implementador) `src/gemma_cum_loader/auditoria/calidades.py` —
      calidad "Fechas que no cuadran con INVIMA", con las columnas de ambas
      fuentes.
- [x] 8. (claude/pruebas) `tests/test_pipeline.py`, `tests/test_backend_*.py`,
      `tests/test_calidades.py` — ajustar lo que asume el universo sin filtrar.
- [ ] 9. (copilot) `frontend/src/vistas/auditoria.ts` — etiquetas y orden de
      columnas de las tablas de calidades. **Bloqueado hasta que 7 este `[x]`.**
- [ ] 10. (claude/revisor) — revision antes del commit.

## Contrato para Copilot

Copilot toma **solo los pasos 6 y 9**, y **solo cuando sus dependencias esten
`[x]`**. Mientras 1-5 y 7 esten `[~]`, no abras esos archivos: la firma todavia
cambia.

**Regla que no se negocia aqui:** la logica va en `src/`, Copilot solo la
muestra. Si el paso 6 o 9 parece necesitar una regla nueva, **no la inventes en
TypeScript** — dejalo en `## Abierto` y avisa.

### Paso 6 — `frontend/src/vistas/consulta_detalle.ts`

Hoy el panel de INVIMA no aparece cuando el CUM esta en Vencidos/Otros/Renovacion.
Tras el paso 5 el endpoint `GET /consulta-detalle/medicamento?codigo=<CUM>`
devuelve en cada elemento de `invima[]` estas claves (nombres exactos, fijados
por Claude Code — no los renombres):

- `LISTADO` — uno de `vigente` / `vencido` / `renovacion` / `otros_estados`
- `FECHA_ACTIVO`, `FECHA_INACTIVO` — fechas de INVIMA
- `ESTADO_CUM`, `ESTADO_REGISTRO` — estado que reporta INVIMA
- `TITULAR`, `PRODUCTO`, `DESCRIPCION_COMERCIAL` — el registro real
- `_FUENTE_SNAPSHOT` — de que snapshot salio la fila (`invima_listados` o
  `universo`). Es para diagnostico; no lo muestres en pantalla.
- las demas columnas del catalogo, sin cambios

**OJO con el formato de fecha** (verificado en vivo el 2026-09-01): en
`invima[]` las fechas vienen **crudas del catalogo, en MM/DD/YYYY**
(`"07/23/2016"`), porque son la columna original de INVIMA sin normalizar. Las
que YA estan normalizadas a ISO son las de `gemma_net[0]`:
`FECHA_ACTIVO_INVIMA` / `FECHA_INACTIVO_INVIMA` (`"2016-07-23T00:00:00.000"`).

Para la tabla de comparacion **usa las de `gemma_net[0]`**, que son las mismas
fechas ya normalizadas y comparables. Las crudas de `invima[]` sirven para
mostrar el registro tal cual, no para comparar. No conviertas MM/DD/YYYY a mano
en TypeScript: si hiciera falta normalizarlas, eso se hace en `src/`.

Respuesta real del caso testigo, para que puedas maquetar contra algo concreto:

```json
{"invima": [{"CODIGO_INTERNO": "20102710-2", "LISTADO": "vencido",
             "TITULAR": "JOINPHARM S.A.S", "PRODUCTO": "FINOBES ® 120 MG.",
             "ESTADO_REGISTRO": "Vencido", "ESTADO_CUM": "Inactivo",
             "FECHA_ACTIVO": "07/23/2016", "FECHA_INACTIVO": "10/01/2021"}],
 "gemma_net": [{"ACTIVO": "Si", "ESTADO_LISTADO_INVIMA": "vencido",
                "FECHA_INICIO": "2016-07-23", "FECHA_FIN": "2999-12-31",
                "FECHA_ACTIVO_INVIMA": "2016-07-23T00:00:00.000",
                "FECHA_INACTIVO_INVIMA": "2021-10-01T00:00:00.000"}]}
```

Lo que hay que mostrar:

1. La tabla de INVIMA **siempre** que `invima[]` traiga filas, no solo para
   vigentes. Encabezala con el listado de origen.
2. Una comparacion de fechas **lado a lado**, con las dos fuentes rotuladas:

   | | Gemma Net | INVIMA |
   |---|---|---|
   | Inicio / Activo | `FECHA_INICIO` | `FECHA_ACTIVO` |
   | Fin / Inactivo | `FECHA_FIN` | `FECHA_INACTIVO` |

3. Al lado de "Activo Gemma Net" (que ya existe, linea ~519) agrega **"Estado
   INVIMA"** leyendo `ESTADO_LISTADO_INVIMA` de `gemma_net[0]`.
4. Una fecha comodin de Gemma Net (`2999-12-31`, `1900-01-01`) se muestra como
   **"sin dato"**, no como fecha — es un centinela, no un valor. No la marques
   como diferencia.

Respeta lo que ya rige la UI (CLAUDE.md): tablas con filtros, avisos como
tarjeta corta + icono `?`, nunca parrafos largos en un banner.

### Paso 9 — `frontend/src/vistas/auditoria.ts`

Tras el paso 7 hay una calidad nueva, `"Fechas que no cuadran con INVIMA"`.
Necesita: etiquetas legibles para `FECHA_ACTIVO_INVIMA` ("Fecha activo INVIMA"),
`FECHA_INACTIVO_INVIMA` ("Fecha inactivo INVIMA") y `COHERENCIA_FECHAS_INVIMA`
("Coherencia de fechas"), y que las 4 fechas queden **contiguas** en el orden
Gemma-Gemma-INVIMA-INVIMA para poder compararlas de un vistazo. Reusa
`ETIQUETAS_ACTIVO_VS_INVIMA` (linea ~30) como patron; no crees un segundo
mecanismo de etiquetado.

## Decisiones

- **Exclusion total, no parcial** (confirmado por el usuario): el universo
  auditado es solo `TIPO_CODIGO_INTERNO in {cum, cum_con_sufijo_atc}`, sin
  ancestrales/plantas, y solo activos salvo la excepcion vigente-en-INVIMA. Los
  codigos legados (~33 %) salen de todas las calidades y conteos.
- **Porcentajes sobre el universo auditable** (confirmado por el usuario): el
  denominador deja de ser el catalogo completo. El % responde "de lo que
  auditamos, esto falla".
- **El recorte NO se aplica en `pipeline.py`** -- se cambio de opinion durante
  la ejecucion, y por una razon buena. El comentario de `pipeline.py:418` tenia
  razon: las dimensiones de auto-consistencia (formato invalido, duplicados)
  tienen que ver TODAS las filas, y recortar antes las deja ciegas (medido:
  `formato_invalido` pasaba de 1 a 0 porque la fila con el problema
  desaparecia, no porque se arreglara). Se aplica en `_tabla_auditoria()` del
  router (`backend/app/routers/auditoria.py`), **un solo lugar**, que cubre la
  tabla, `/valores` y `/resumen` a la vez. Antes solo `/resumen` filtraba: la
  misma pantalla daba tres respuestas distintas al mismo criterio.
- `filtrar_universo_auditable` ahora **degrada explicitamente** si al snapshot
  le faltan columnas (TIPO_CODIGO_INTERNO, ESTADO_LISTADO_INVIMA): aplica las
  mascaras que puede y deja las omitidas en `attrs["recorte_omitido"]`. Antes
  reventaba con `KeyError`, lo que habria dejado la seccion de auditoria en 500
  cada vez que el codigo se adelantara al ultimo snapshot.
- `n_total_auditado` de `/auditoria/dimensiones` pasa a ser el universo
  auditable (67.524), mientras los contadores de auto-consistencia de ese mismo
  endpoint siguen contando sobre las 199.611. Responden preguntas distintas a
  proposito y esta documentado en el docstring: el total es "lo que auditamos",
  los contadores son "cuanta basura hay en el reporte".

### Medido tras el refresco real (2026-09-01)

- Universo auditable: **67.524 de 199.611 (33,8 %)**. Solo `cum` (67.445) y
  `cum_con_sufijo_atc` (79). Ningun criterio quedo sin aplicar.
- De esos, 55.620 activos + **11.904 inactivos**, y los 11.904 son
  exactamente la excepcion pedida (`ESTADO_LISTADO_INVIMA == vigente`).
- `invima_listados`: 385.891 filas (vigente 101.183 · vencido 149.224 ·
  otros_estados 77.760 · renovacion 57.724).
- Calidad nueva "Fechas que no cuadran con INVIMA": **3.683 hallazgos reales**.
- Caso testigo `20102710-2`: el panel de INVIMA ya trae el registro autentico
  (JOINPHARM S.A.S, Vencido, 07/23/2016 → 10/01/2021) y
  `INCONSISTENCIA_FECHAS_ACTIVO` ya no repite el texto.
- `COHERENCIA_FECHAS_INVIMA` queda **vacia** en el caso testigo, y esta bien:
  su `FECHA_FIN` es el comodin `2999-12-31` ("sin dato"), no una fecha
  distinta. Ese caso ya lo cubre el aviso de vencido-y-activo.

## Abierto

- **Suplementos:** el usuario pidio excluirlos, pero no hay campo estructural que
  los identifique (ni `CLASIFICADO` ni `TIPO_CODIGO_INTERNO`). Buscar
  "SUPLEMENTO" en `DESCRIPCION` seria una decision a ciegas (regla #1). Los
  filtros de CUM + ancestrales ya sacan la mayoria. Pendiente de una señal
  verificable; ya reportado al usuario.
- Socrata esta devolviendo 0 filas otra vez (mismo outage conocido). El refresco
  cae al respaldo local de `data/`, que es de 2022 — suficiente para verificar
  esta tarea, pero las fechas no son las de hoy.

## Verificacion

- [x] `pytest` en verde -- 566 pruebas, incluidas 12 nuevas de esta tarea
- [x] `ruff check` limpio en todo lo tocado (los 29 hallazgos que quedan en
      `src/`+`tests/` son preexistentes, en archivos que esta tarea no toca)
- [x] `GET /consulta-detalle/medicamento?codigo=20102710-2` trae la fila de
      INVIMA con `LISTADO=vencido`, `FECHA_ACTIVO=07/23/2016`,
      `FECHA_INACTIVO=10/01/2021` (crudas del catalogo, ver el contrato de
      Copilot), y `INCONSISTENCIA_FECHAS_ACTIVO` sin el texto repetido
- [x] En el universo auditable: los 11.904 inactivos son TODOS
      `ESTADO_LISTADO_INVIMA == 'vigente'`; solo hay `cum` y `cum_con_sufijo_atc`
- [ ] Linea agregada a `.ai/bitacora.jsonl` (al cerrar, tras los pasos 6 y 9)
