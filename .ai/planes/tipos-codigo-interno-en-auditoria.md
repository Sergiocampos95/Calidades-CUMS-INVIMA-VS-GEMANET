# Tipos de estructura de CODIGO_INTERNO en la auditoría + filtro

- **Estado:** terminado (2026-08-26) — pendiente solo de fusionar
  `feature/tipos-codigo-interno` a `master` cuando el usuario lo confirme
- **Creado:** 2026-08-26 por Claude Code (diagnóstico de `arquitecto`)
- **Objetivo:** el catálogo de tipos de `CODIGO_INTERNO` investigado contra
  producción (`design/tipos_codigo_interno.md`) se refleja como columna
  informativa en la auditoría y se puede filtrar en las tablas donde
  `CODIGO_INTERNO` viene de Gemma Net, sin tocar ninguna decisión de negocio
  existente.

## Contexto

Investigación previa: `design/tipos_codigo_interno.md` (dominio-invima,
2026-08-26, contra 199.611 filas reales de `tb_medicamento`). El usuario
pidió que esta información "sea tratada... afectando de alguna forma" los
apartados relevantes y que se pueda filtrar por ella.

Diagnóstico completo de `arquitecto` (ver conversación). Puntos clave:

- `clasificar_codigo()` (`normaliza/codigos.py:26-27`) hoy no tiene ningún
  consumidor en `src/` ni en `ui_revision/` — solo lo usa
  `tests/test_codigos.py`. Ampliarlo no puede romper producción.
- `es_cum()` **no se toca**: es el predicado estricto del que depende el
  resto del sistema (comentario histórico sobre cifras contradictorias
  66.231 vs 199.463).
- El patrón `^\d+-\d+$` está copiado a mano en 3 sitios más
  (`coherencia_invima.py:1521`, `app_streamlit.py:1387,3928`) — se unifican
  para importar desde `codigos.py`.
- `armado/malla.py` y `validacion/reglas.py` **no se tocan**: confirmado que
  no hay nada ahí que deba cambiar (malla trabaja sobre CODIGO_INTERNO de
  INVIMA, siempre CUM por construcción; reglas.py solo valida "es un valor
  real", no el tipo estructural).
- La columna nueva (`TIPO_CODIGO_INTERNO`) es **informativa**, no una
  dimensión de calidad #11 (no hay veredicto bien/mal) y **nunca** puede
  derivar en fusión o deduplicado de `CODIGO_INTERNO` — regla no negociable
  del proyecto.
- Alcance de esta ronda: 6 valores por regex (prioridad alta+media del
  documento) + `sin_clasificar` como residual honesto. Paquetes/insumos/CUPS
  por cruce contra `tb_cup`/`tb_insumo` quedan **fuera** (no hay patrón de
  código, requieren consulta a la base) — se declara explícitamente en
  pantalla, no se omite en silencio.
- El filtro se implementa como **tercer parámetro opcional** de
  `_filtros_estandar` (los 2 popovers existentes ya están ocupados), sin
  crear un segundo mecanismo de filtro.
- **`cum_con_sufijo_atc` (paso 5) requiere aprobación de negocio explícita**
  antes de implementarse: recuperar esas 147 filas contra INVIMA cambiaría
  la llave del merge y movería filas entre estados de la auditoría. No se
  implementa en este plan sin luz verde puntual.

## Pasos

- [x] 1. (claude/implementador) `src/gemma_cum_loader/normaliza/codigos.py`
      — ampliado `CodigoTipo`/`clasificar_codigo()` con los 6 valores nuevos
      + `sin_clasificar`, en el orden de correctitud del diagnóstico
      (`cum` → `cum_con_sufijo_atc` → `atc_expediente_consecutivo` → `ium`
      → `registro_sanitario` → `forma_cups` → `codigo_propio` →
      `sin_clasificar`). Agregado `clasificar_codigos(serie)` vectorizada
      (`np.select`, sin `apply`/`map` por fila) y `TIPOS_CODIGO_INTERNO`
      exportado. `es_cum()`/`partir_cum()` sin tocar. `PATRON_CUM` pasó a
      público (antes `_PATRON_CUM`) para que el paso 2 lo importe. 28/28
      pruebas en verde (commit `f41b036`).
- [x] 2. (claude/implementador) `src/gemma_cum_loader/auditoria/coherencia_invima.py:1521`
      — reemplazado el patrón `^\d+-\d+$` copiado a mano por `PATRON_CUM`
      importado. `ui_revision/app_streamlit.py:1387,3928` quedan
      pendientes (se hacen junto con el paso 4, mismo archivo).
- [x] 3. (claude/implementador) `src/gemma_cum_loader/auditoria/coherencia_invima.py`
      — nueva columna `TIPO_CODIGO_INTERNO` (vectorizada, vía
      `clasificar_codigos`), agregada junto al resto del resultado, antes de
      `NATURALEZA_HALLAZGO` para dejar claro que no participa en él. Nueva
      `_detectar_capa_legada_atc()`: advertencia agregada (una frase, no por fila) cuando la capa
      `atc_expediente_consecutivo` supera el umbral de reporte, dejando
      explícito que es una capa legada apagada y que **no se fusiona con su
      gemelo CUM**. Comentario nuevo junto a las 9 dimensiones explicando
      por qué esta columna no es una dimensión #10.
- [x] 4. (claude/implementador) `ui_revision/app_streamlit.py` — tercer
      parámetro opcional (`columna_tipo`/`opciones_tipo`/`clave_tipo`) en
      `_filtros_estandar`, `_tabla_filtrable`, `_tabla_auditoria_esencial`
      (esta última con AUTODETECCIÓN: se activa sola cuando la columna está
      presente). Activo en Explorar y Priorizar (vía autodetección),
      tabla de calidades (explícito) y "Por qué no se cargó → Ya cargados"
      (autodetección dentro de `_diagnostico_por_campo`, compartida con
      Cargue → candidatos pendientes, que no tiene la columna y por tanto no
      la muestra). NO se agregó en Detalle por registro ni Casos que
      requieren decisión (datos de INVIMA, siempre CUM). Etiquetas de los 8
      valores + nombre de columna en
      `_ETIQUETA_VALOR_INTERNO`/`_ETIQUETA_COLUMNA_FILTRO`/`_ETIQUETA_COLUMNA_TABLA`.
      Se unificó también el segundo sitio con el patrón CUM copiado a mano
      (`_calidades()`, quedaba pendiente del paso 2) via `PATRON_CUM`
      importado. 25/25 pruebas de `test_ui_filtros.py`, 379/379 en toda la
      suite.
- [x] 5. (aprobado por el usuario 2026-08-26: "Recuperar los 147, pero
      priorizar solo los activos") `src/gemma_cum_loader/auditoria/coherencia_invima.py`
      — **SÍ se cambió la llave de cruce contra INVIMA** (a diferencia de lo
      que decía este plan originalmente): se calcula `clave_cruce_invima`
      (EXPEDIENTE-CONSECUTIVO reconstruido, sin ceros a la izquierda, SOLO
      para los `cum_con_sufijo_atc`) y se usa en el merge contra Vigentes y
      en los tres datasets auxiliares (Vencidos/Otros Estados/Renovación) en
      vez de `CODIGO_INTERNO` crudo. `resultado["CODIGO_INTERNO"]` (la
      identidad real del medicamento) nunca se toca — el reconstruido queda
      aparte en la nueva columna informativa `CUM_RECONSTRUIDO`. La
      priorización "solo los activos" no necesitó código nuevo: los 48
      activos con diferencias caen solos en las tarjetas de prioridad
      existentes (ya filtran por ACTIVO), los 99 inactivos quedan con su
      `ESTADO_COHERENCIA` real pero fuera de esas tarjetas, igual que
      cualquier otro código inactivo. 6 pruebas nuevas (incluye el caso de
      Vencidos), 112/112 en `test_coherencia_invima.py`.
- [x] 6. (claude/implementador) `ui_revision/app_streamlit.py`,
      `design/tipos_codigo_interno.md` — `_mostrar_distribucion_tipo_codigo_interno()`
      nueva en "Entender la calidad del catálogo": tabla de conteos por tipo
      + aviso explícito de por qué no hay categoría "paquete"/"insumo".
      Documento de diseño actualizado con un bloque de estado de
      implementación al inicio. `README.md` sin tocar todavía (queda para
      el cierre, cuando se confirme el alcance con el usuario).
- [x] 7. (claude/pruebas) Cubierto de forma incremental junto con cada paso
      (28 en `test_codigos.py` incl. el reemplazo consciente de
      `test_clasificar_codigo_ium`, 112 en `test_coherencia_invima.py` incl.
      no-fusión y el cruce real del paso 5, 25 en `test_ui_filtros.py` incl.
      que ningún valor de tipo se trate como columna-lista).
- [x] 8. (claude/revisor) `pytest` completo: **385/385 en verde**. `ruff
      check src/ tests/ ui_revision/`: sin errores nuevos (mismo baseline
      preexistente de siempre). `es_cum()`/`partir_cum()` sin cambio de
      comportamiento (prueba dedicada). `PORCENTAJE_CALIDAD`/
      `ESTADO_COHERENCIA`/`NATURALEZA_HALLAZGO` no cambiaron para ningún
      caso preexistente — las 106 pruebas originales de
      `test_coherencia_invima.py` pasan sin modificar ninguna aserción.
      Clasificación vectorizada con `np.select` (no `apply`/`map` por fila,
      confirmado con prueba de equivalencia). Sin llamadas de red en
      ninguna parte de `codigos.py`/la reconstrucción del paso 5.

## Decisiones

- Paquetes/insumos/CUPS-por-cruce quedan fuera de esta ronda (paso 6 lo
  declara en pantalla). Si se quieren después: dos `SELECT` de una sola
  columna contra `tb_cup`/`tb_insumo`, materializados en `set` y cruzados
  con `.isin()` — nunca `JOIN` ni `LATERAL` contra `tb_medicamento` en
  Postgres (ver el `statement_timeout` real que ya documenta
  `gemanet_sql.py`).
- `cum_con_sufijo_atc` (paso 5) no se implementa sin aprobación explícita:
  cambia resultados de auditoría reales (147 filas moverían de estado). →
  **Aprobado 2026-08-26**, implementado (ver paso 5).
- Pedido de negocio (2026-08-26, confirmado explícitamente): los resultados
  se priorizan por ESTADO + VIGENCIA — lo que no está vigente/activo se
  conserva por trazabilidad pero no debe estorbar el flujo de trabajo. Dos
  consecuencias directas: (a) el paso 5 recupera los 147 códigos pero la
  prioridad natural ya separa los 48 activos de los 99 inactivos sin código
  nuevo (los masks existentes de "Priorizar" ya filtran por ACTIVO); (b) la
  capa legada `atc_expediente_consecutivo` (0% activa) se colapsa por
  defecto en "Entender la calidad del catálogo" (`_TIPO_CAPA_LEGADA`,
  expander cerrado) — sigue filtrable a mano en cualquier tabla.

## Abierto

- Alcance confirmado por el usuario para esta ronda: 6 categorías + residual
  + el paso 5 recuperado. Paquetes/insumos/CUPS por cruce contra
  `tb_cup`/`tb_insumo` siguen fuera (ver Decisiones) — no se pidió sumarlos.
- Paso 5 (`cum_con_sufijo_atc` recuperable) espera aprobación puntual.

## Verificación

- [ ] `pytest` en verde
- [ ] `ruff check src/ tests/ ui_revision/` sin errores nuevos
- [ ] `es_cum()`/`partir_cum()` sin cambio de comportamiento
- [ ] Ningún resultado de auditoría existente (PORCENTAJE_CALIDAD,
      ESTADO_COHERENCIA, NATURALEZA_HALLAZGO, duplicados) cambia
- [ ] Línea agregada a `.ai/bitacora.jsonl`
