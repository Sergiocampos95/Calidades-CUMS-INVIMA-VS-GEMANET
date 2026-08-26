# Tipos de estructura de CODIGO_INTERNO en la auditoría + filtro

- **Estado:** en curso
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
- [ ] 5. (bloqueado — requiere aprobación de negocio, NO implementar sin
      confirmación puntual) `cum_con_sufijo_atc` recuperable: columna
      informativa con el CUM reconstruido + calidad nueva en `_calidades()`
      listando esos códigos. **No cambia la llave del merge de la línea
      1336** — esas 147 filas siguen en `sin_correspondencia_invima` hasta
      que negocio decida activar el cruce.
- [x] 6. (claude/implementador) `ui_revision/app_streamlit.py`,
      `design/tipos_codigo_interno.md` — `_mostrar_distribucion_tipo_codigo_interno()`
      nueva en "Entender la calidad del catálogo": tabla de conteos por tipo
      + aviso explícito de por qué no hay categoría "paquete"/"insumo".
      Documento de diseño actualizado con un bloque de estado de
      implementación al inicio. `README.md` sin tocar todavía (queda para
      el cierre, cuando se confirme el alcance con el usuario).
- [ ] 7. (claude/pruebas) `tests/test_codigos.py` (ampliar/reemplazar
      `test_clasificar_codigo_ium` — cambio de contrato consciente: "ZIAL"
      pasa a `codigo_propio`), `tests/test_coherencia_invima.py`,
      `tests/test_ui_filtros.py` — casos listados en el diagnóstico del
      arquitecto, incluyendo el test de no-fusión y el de que ningún valor
      contenga `", "` (rompería `_valores_de_columna_lista`).
- [ ] 8. (claude/revisor) Revisión final: `pytest`, `ruff check`, confirmar
      que `es_cum()` da lo mismo que antes, que `PORCENTAJE_CALIDAD`/
      `ESTADO_COHERENCIA`/`NATURALEZA_HALLAZGO` no cambiaron para ningún
      caso existente, que la clasificación usa `np.select` vectorizado (no
      `apply`/`map` por fila) y sin llamadas de red.

## Decisiones

- Paquetes/insumos/CUPS-por-cruce quedan fuera de esta ronda (paso 6 lo
  declara en pantalla). Si se quieren después: dos `SELECT` de una sola
  columna contra `tb_cup`/`tb_insumo`, materializados en `set` y cruzados
  con `.isin()` — nunca `JOIN` ni `LATERAL` contra `tb_medicamento` en
  Postgres (ver el `statement_timeout` real que ya documenta
  `gemanet_sql.py`).
- `cum_con_sufijo_atc` (paso 5) no se implementa sin aprobación explícita:
  cambia resultados de auditoría reales (147 filas moverían de estado).

## Abierto

- Confirmar con el usuario si el alcance de 6 categorías + residual (sin
  paquetes/insumos/CUPS) es lo que esperaba, o si quiere que se sume el
  cruce contra `tb_cup`/`tb_insumo` en esta misma ronda.
- Paso 5 (`cum_con_sufijo_atc` recuperable) espera aprobación puntual.

## Verificación

- [ ] `pytest` en verde
- [ ] `ruff check src/ tests/ ui_revision/` sin errores nuevos
- [ ] `es_cum()`/`partir_cum()` sin cambio de comportamiento
- [ ] Ningún resultado de auditoría existente (PORCENTAJE_CALIDAD,
      ESTADO_COHERENCIA, NATURALEZA_HALLAZGO, duplicados) cambia
- [ ] Línea agregada a `.ai/bitacora.jsonl`
