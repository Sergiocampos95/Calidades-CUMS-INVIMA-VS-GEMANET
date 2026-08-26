# Reestructurar títulos y cifras de Auditoría de coherencia

- **Estado:** en curso
- **Creado:** 2026-08-25 por Claude Code
- **Objetivo:** los dos bloques de métricas de Auditoría quedan separados
  visualmente y declaran qué fuentes/campos comparan, las tarjetas de
  hallazgo se agrupan por dimensión colapsadas por defecto, y cada hallazgo
  de dos fuentes muestra su evidencia cruda junto a la tarjeta.

## Contexto

El dueño del producto ve la pantalla de Auditoría de coherencia como una
pared de cifras: dos bloques de métricas ("De los que se pudieron comparar
campo a campo" / "De los que no tienen contraparte en el listado vigente")
seguidos de una grilla de 9+ tarjetas de hallazgo, todo en el mismo scroll.
No queda claro, con solo mirarlo, qué compara cada cifra (¿Gemma Net contra
qué listado de INVIMA?) ni con qué campo. Además reportó un caso donde dudó
de un hallazgo ("activo aquí, sin vigencia en INVIMA — corregir") y al
verificar el Excel de INVIMA a mano confirmó que la app tenía razón — pero
tuvo que ir a buscarlo el mismo por fuera de la aplicación porque la tarjeta
no le mostraba el dato crudo de cada fuente, solo la conclusión. También
reportó que "cada filtro era una eternidad para cargar", pero eso ya se
corrigió hoy (`_filtros_estandar`, ver Decisiones).

Investigación completa (vía agente Explore) en el plan aprobado, guardado
para referencia en `C:\Users\TECNOLGO TIC\.claude\plans\esperemos-a-ver-que-splendid-newt.md`.
Resumen de lo clave:

- Los dos bloques de métricas son código inline en `ui_revision/app_streamlit.py`
  (~línea 3305 y ~3342), sin función dedicada.
- La grilla de tarjetas la arma `_mostrar_tarjetas_alerta` (línea 907); la
  lista de alertas se construye inline (líneas 3385-3436).
- `_calidades(auditoria)` (línea 1078) es un catálogo separado de 11
  hallazgos que alimenta `_panel_prioridades_auditoria` (1329) y
  `_panel_entender_auditoria` (1383) — solapa parcialmente con la grilla de
  tarjetas pero son dos mecanismos distintos.
- **La evidencia cruda ya existe**: `coherencia_invima.py::auditar_coherencia`
  (líneas 1368-1392) guarda columnas `crudos_invima`/`crudos_gemanet` sin
  normalizar, una por campo comparado. El caso de vigencia se calcula en
  `_contrastar_vigencia_invima` (línea 705-894) y termina en
  `NOVEDAD_VIGENCIA_INVIMA`. Hoy solo es visible en la tabla de detalle de
  `_panel_prioridades_auditoria`, no junto a la tarjeta de la grilla.
- Los filtros ya no recalculan nada: `_filtros_estandar` (línea 692) es el
  único patrón desde hoy; `_auditar_coherencia` está cacheada (línea 1909) y
  no se reinvoca al filtrar.

No se toca `src/gemma_cum_loader/` — los datos que hacen falta ya existen,
es 100% presentación en `ui_revision/app_streamlit.py`.

## Pasos

- [x] 1. (claude/implementador — reasignado, el usuario pidió terminar todo
      directo) `ui_revision/app_streamlit.py` — los dos bloques ahora van en
      `st.container(border=True)` separados, con título explícito de fuentes:
      "Comparados campo a campo — Gemma Net vs INVIMA (listado Vigentes)" /
      "Sin contraparte en Vigentes — buscados en INVIMA Vencidos, Otros
      Estados y Trámite de Renovación".
- [x] 2. (claude/implementador) `ui_revision/app_streamlit.py` — las tarjetas
      de hallazgo se separaron en 3 grupos (`alertas_carga`, `alertas_vigencia`,
      `alertas_calidad`) y los dos últimos van dentro de `st.expander(...,
      expanded=False)` con la cuenta de hallazgos en el título — antes eran
      9+ tarjetas sueltas siempre visibles sin importar la sub-vista elegida.
- [x] 3. (claude/implementador) `ui_revision/app_streamlit.py` — títulos y
      `help=` de cada métrica/tarjeta reescritos para nombrar la columna y
      fuente exacta comparada (ej. "Gemma Net (columna ACTIVO) vs INVIMA
      (ESTADO_CUM_INVIMA)"), usando el mapeo confirmado en el paso 6.
- [x] 4. (claude/implementador) `ui_revision/app_streamlit.py` — agregada la
      nota "🔎 Cambiar un filtro más abajo no vuelve a calcular esta
      auditoría ni relee archivos".
- [~] 5. (claude/implementador) Falta la prueba visual en Streamlit corriendo
      — pytest (352/352) y ruff ya se corrieron, pero nadie abrió la app
      todavía para confirmar visualmente. Dejar `[~]` hasta que se abra.
- [x] 12. (claude/implementador, fuera del alcance original — pedido directo
      del usuario tras ver el paso 2 en pantalla) Reemplazo del mecanismo
      compartido `_mostrar_detalle_alerta` (línea ~1129): antes elegía entre
      `st.popover`/`st.expander` según el largo del texto; ahora es siempre
      un botón "❓" con `help=` (tooltip nativo al pasar el mouse, no
      reserva espacio ni empuja la página). Esta función la usan
      `_mensaje_breve` y `_mostrar_tarjetas_alerta` en TODA la app, así que
      el cambio se propaga a cada tarjeta/aviso de las 6 secciones de una
      sola vez. Además se aplanaron los dos `st.expander` de grupo que el
      paso 2 había introducido ("Vigencia frente a INVIMA" / "Calidad de
      los campos del reporte") — ya no hace falta esconder las tarjetas
      detrás de un clic si cada una es compacta. Se agregó `import hashlib`
      para generar la key del botón a partir del contenido. Se dejaron
      SIN tocar los `st.expander`/`st.popover` que esconden contenido
      sustancial (tablas, listas largas) en vez de un aviso corto — ej. los
      popovers de filtros (líneas 991/1002, son funcionales, no avisos), el
      panel "Archivos de entrada", la lista de motivos explicados por IA, y
      los expanders con tablas de "10 dimensiones de calidad" / "Qué hacer
      con cada hallazgo" / "Detalle de sin correspondencia": son
      disclosure de datos reales, no el patrón de "avisos desplegables" que
      motivó el reclamo. No se intentó un relayout a columna lateral
      derecha (pedido también en el mensaje del usuario) — es un cambio de
      layout mucho más grande y transversal a las 6 secciones; se dejó
      pendiente de confirmar si sigue haciendo falta con el icono ya
      resolviendo el problema de espacio.
- [x] 6. (claude/dominio-invima) Confirmar y documentar, dimensión por
      dimensión de `_calidades()`, qué columnas `crudos_invima`/`crudos_gemanet`
      existen y qué representan campo a campo. Solo lectura — corrió en
      paralelo con 1-5. Ver Decisiones.
- [x] 7. (claude/ui-streamlit) Decidir el formato de la evidencia cruda
      dentro de cada tarjeta — decisión: hasta 3 ejemplos "CODIGO_INTERNO:
      DETALLE_VIGENCIA_INVIMA" anexados al `detalle` ya existente de cada
      tarjeta de novedad de vigencia (se apoya en `_mostrar_detalle_alerta`,
      que ya manda a popover si el texto es largo — no hace falta un
      mecanismo nuevo de UI). Alcance acotado a la dimensión de vigencia
      (es la que reportó el usuario); "campos con diferencia" queda para un
      paso futuro si hace falta, no tiene tarjeta de alerta hoy, solo la
      métrica `d2` — evidencia cruda ahí ya vive en la tabla de calidades.
- [x] 8. (claude/implementador) `ui_revision/app_streamlit.py` — implementado:
      `_ejemplos_evidencia_vigencia()` (nueva función, cerca de línea 907) +
      uso en el bucle de `NOVEDAD_VIGENCIA_INVIMA` (~línea 3450) para anexar
      los ejemplos al `detalle` de cada tarjeta. Sin cambios en
      `coherencia_invima.py` — la columna `DETALLE_VIGENCIA_INVIMA` ya
      traía el dato crudo por fila.
- [ ] 9. (claude/ui-streamlit) Validación visual final en Streamlit contra el
      caso real reportado (activo en Gemma Net / vencido en INVIMA).
- [x] 10. (claude/pruebas) `tests/test_ui_filtros.py` — 4 pruebas nuevas:
      ejemplos con dato crudo de cada lado, límite a 3 con aviso del total,
      sin hallazgos no hay texto, y degradación explícita si falta la
      columna `DETALLE_VIGENCIA_INVIMA` (no se inventa evidencia). 17/17
      pruebas del archivo en verde.
- [x] 11. (claude/revisor) Revisión final: `pytest` completo 352/352 en
      verde (348 previas + 4 nuevas). `ruff check ui_revision/app_streamlit.py`
      4 errores, todos preexistentes (baseline confirmado con `git stash`);
      `ruff check tests/test_ui_filtros.py` 1 error preexistente (noqa
      redundante, ya estaba antes de este cambio). La evidencia cruda solo
      se agregó al bucle de `NOVEDAD_VIGENCIA_INVIMA` (dimensión de dos
      fuentes) — no se tocó ninguna tarjeta de duplicados/formato/
      completitud. Sin llamadas de red ni recálculo por fila: `head(limite)`
      antes de `iterrows()`, máximo 3 filas iteradas por tarjeta.

**Orden entre bloques:** los pasos 1-5 (copilot) y 6 (dominio-invima, solo
lectura) van en paralelo. Los pasos 7-11 (claude) escriben en el mismo
`ui_revision/app_streamlit.py` que copilot — esperan a que 1-5 cierren en
`[x]` para no pisarse.

## Decisiones

- Paso 6 (mapeo de columnas crudas por dimensión), confirmado sobre el código
  real de `src/gemma_cum_loader/auditoria/coherencia_invima.py`:
  - **Campos con diferencia** (DESCRIPCION, MARCA_MEDICAMENTO, UNIDAD_MEDIDA):
    `crudos_gemanet["<CAMPO>"]` = valor tal cual en el reporte de Gemma Net;
    `crudos_invima["<CAMPO>"]` = valor tal cual en el listado Vigente de
    INVIMA (o su normalización mínima, ej. TITULAR para MARCA_MEDICAMENTO).
    Solo se llenan para las filas con contraparte en Vigentes
    (`PORCENTAJE_CALIDAD` no vacío) — regla de negocio: vacío, no en blanco
    forzado, cuando no hay con qué comparar.
  - **Vigencia** (`NOVEDAD_VIGENCIA_INVIMA`, de `_contrastar_vigencia_invima`):
    el "crudo" no son columnas `crudos_*` sino el detalle por fila ya
    materializado como texto libre con fechas concretas de ambos lados
    (ACTIVO/FECHA_FIN de Gemma Net vs ESTADO_CUM_INVIMA/FECHA_INACTIVO_INVIMA/
    FECHA_VENCIMIENTO_INVIMA de INVIMA), disponible en la columna de detalle
    que ya usa `_panel_prioridades_auditoria` (`ESTADO_INVIMA_DETALLE`).
  - **Sin aplicar** (una sola fuente, no comparan dos lados): duplicados
    (`CODIGO_DUPLICADO_EN_REPORTE`), formato (`FORMATO_CODIGO_INTERNO_INVALIDO`),
    completitud (`PORCENTAJE_COMPLETITUD_REPORTE`), dominio/catálogos
    (comparan contra una lista de valores válidos, no contra INVIMA). El
    paso 8 NO debe agregar una sección de "evidencia cruda" a estas tarjetas.

## Abierto

-

## Verificación

- [ ] `pytest` en verde
- [ ] `ruff check src/ tests/ ui_revision/` sin errores nuevos
- [ ] Probado en la aplicación corriendo (Streamlit) antes de cerrar el plan
- [ ] Línea agregada a `.ai/bitacora.jsonl`
