# Rediseño de navegación, migaja de decisión y ocultamiento de "Archivos de entrada"

- **Estado:** en curso
- **Creado:** 2026-08-25 por Claude Code (diagnóstico de `arquitecto`)
- **Objetivo:** el sidebar es una sola lista de navegación (sin grupos de radio
  duplicados), la barra superior muestra una migaja con la ruta de decisión
  completa (fuente de datos + sección activa) y el panel "Archivos de entrada"
  desaparece de la pantalla tras procesar con éxito, con una vía explícita
  para reabrirlo sin perder la corrida ya calculada.

## Contexto

Pedido del usuario: sidebar solo de navegación y más moderno (no le gustan
los dos grupos de `st.radio` actuales), migajas de pan arriba con la ruta de
decisión completa, y que "Archivos de entrada" deje de ocupar espacio del
todo una vez procesado (el colapso ya hecho en el commit anterior no alcanza).

Diagnóstico completo de `arquitecto` (ver conversación): el diff sin
commitear de Copilot ya cambió las pestañas horizontales por dos `st.radio`
sincronizados a mano con `_activar_seccion` — la causa del problema visual es
que con `index=None` en ambos, uno de los dos grupos se ve siempre vacío. El
bloque "Archivos de entrada" (líneas ~1805-1969) calcula variables
(`usar_detectados`, rutas auxiliares) que se leen también fuera de ese bloque
(líneas ~2066, ~2947, ~2958) y no viven en `session_state["archivos"]`:
ocultarlo sin más produce `NameError`. Además emite 5 avisos de degradación
explícita (regla 2 de `CLAUDE.md`) que no pueden perderse al ocultar el panel.

Documentación desfasada detectada de paso: `README.md` y `CLAUDE.md` siguen
diciendo "5 pestañas"; ya son 6 secciones en sidebar. Se corrige en el paso 7.

Ningún paso de este plan toca reglas de negocio, la cascada de resolución, la
cuarentena ni la fusión de `CODIGO_INTERNO`. Es rediseño de presentación
únicamente en `ui_revision/app_streamlit.py`.

## Pasos

- [ ] 1. (claude/ui-streamlit) `ui_revision/app_streamlit.py` — extraer
      líneas 1805-1969 a `_seleccionar_fuentes() -> EleccionFuentes`
      (dataclass frozen con `usar_api_invima`, `archivo_invima`,
      `archivo_gemma_net`, `archivo_malla_referencia`, `usar_bd_catalogos`,
      `usar_detectados`, `rutas_auxiliares`, `origen_medicamentos`,
      `degradaciones`). Guardar el objeto en `session_state["archivos"]`;
      reemplazar las llamadas sueltas a `descubrir_todo()` (~2066, ~2947) por
      `eleccion.rutas_auxiliares`. Sin cambio visual todavía.
      Criterio de listo: `descubrir_todo()` se llama una sola vez por corrida;
      `usar_detectados` solo aparece dentro de la función y del dataclass;
      `ruff check ui_revision/` limpio; la app procesa igual que antes.
- [ ] 2. (claude/ui-streamlit) `ui_revision/app_streamlit.py` — funciones
      puras de navegación a nivel de módulo (sin llamadas a `st.*`):
      `NAVEGACION`, `SECCIONES`, `_seccion_normalizada`, `_grupo_de_seccion`,
      `_etiqueta_fuente`, `_ruta_navegacion`, `_encabezados_navegacion`,
      `_migaja_html`. **Puede ir en paralelo con el paso 1** si se ubican en
      una zona del archivo distinta (cerca de `_barra_superior`, línea ~410);
      si tocan las mismas líneas que el paso 1, hacerlo después.
      Criterio de listo: importables desde `tests/test_ui_filtros.py` sin
      ejecutar Streamlit; `_ruta_navegacion({})` devuelve
      `["Gemma CUM Loader", "Fuente sin definir"]`.
- [ ] 3. (claude/pruebas) `tests/test_ui_filtros.py` — cubrir las funciones
      puras del paso 2: ruta sin fuente elegida, las 4 combinaciones de
      `_etiqueta_fuente`, origen efectivo vs elegido (caso del fallback de
      base a archivo), sección desconocida cae a la primera, escapado de
      texto en la migaja, estructura de `NAVEGACION` sin huérfanos,
      `_encabezados_navegacion()` apunta a la primera opción de cada grupo,
      degradaciones marcan la miga. **Puede ir en paralelo con el paso 4**
      (no comparte archivo con `app_streamlit.py`) una vez cerrado el paso 2.
      Criterio de listo: `pytest tests/test_ui_filtros.py -q` en verde y las
      pruebas fallan si se invierte el orden de las migas.
- [ ] 4. (claude/ui-streamlit) `ui_revision/app_streamlit.py` — sidebar de
      una sola lista: un `st.radio(SECCIONES, key="seccion_activa",
      format_func=...)`, eliminar `_activar_seccion` y las claves
      `navegacion_candidatos`/`navegacion_cargados`; CSS con `::before` de
      encabezado por grupo usando los índices de `_encabezados_navegacion()`.
      Requiere que el paso 2 esté en `[x]`.
      Criterio de listo: una sola opción marcada siempre; los dos encabezados
      de categoría se ven; cambiar de sección no recalcula el pipeline;
      ninguna clave `navegacion_*` queda en el archivo. Si el selector CSS no
      engancha con el DOM real, usar el plan B (lista de `st.button`) y
      anotarlo en `## Decisiones`.
- [ ] 5. (claude/ui-streamlit) `ui_revision/app_streamlit.py` — migaja en la
      barra superior: `_barra_superior(ruta)` recibe la ruta ya construida;
      `st.columns` con la migaja a la izquierda y un `st.popover("Fuente de
      datos")` a la derecha; alto fijo en CSS; texto escapado con
      `html.escape`. Requiere que el paso 2 esté en `[x]`.
      Criterio de listo: cambiar de sección actualiza la migaja en el mismo
      rerun sin parpadeo ni salto de altura; antes de procesar dice "Fuente
      sin definir" sin mostrar sección.
- [ ] 6. (claude/ui-streamlit) `ui_revision/app_streamlit.py` — ocultar el
      bloque de fuentes tras procesar: condicionar `_seleccionar_fuentes()` y
      el botón "Procesar" a `not procesado or editando_fuentes`; botón
      "Cambiar fuente de datos" dentro del popover del paso 5 (enciende
      `editando_fuentes`, NO pone `procesado=False`, para no perder la
      auditoría ya calculada); botón "Cancelar"; sembrar los valores por
      defecto de los widgets desde el `EleccionFuentes` guardado; pintar
      `degradaciones` con `_mostrar_tarjetas_alerta` tras procesar; aviso de
      una línea mientras `editando_fuentes` esté activo ("los resultados de
      abajo son de la corrida anterior"). Requiere que los pasos 1 y 5 estén
      en `[x]`.
      Criterio de listo: con `procesado=True` "Archivos de entrada" no
      aparece en pantalla; "Cambiar fuente de datos" reabre el bloque sin
      borrar la auditoría; los selectores muestran lo elegido antes, no los
      valores por defecto; "Cancelar" no toca nada.
- [ ] 7. (claude/ui-streamlit) `README.md`, `CLAUDE.md`,
      `.claude/agents/ui-streamlit.md` — reemplazar "5 pestañas" por la
      descripción de las 6 secciones agrupadas en sidebar, migaja y popover
      de fuente. Puede ir en paralelo con cualquier otro paso.
      Criterio de listo: no queda ninguna mención a pestañas horizontales.
- [ ] 8. (claude/revisor) — revisión previa al commit: verificar que no se
      perdieron los 5 avisos de degradación explícita, que ninguna llamada de
      red/base/DataFrame completo entró al camino de render de la migaja o el
      popover, que `session_state["archivos"]` como dataclass no rompe
      lectores existentes, y que no se agregaron dependencias. Requiere que
      1-7 estén en `[x]`.

## Decisiones

- Se descarta `st.navigation` + `st.Page` (nativo, sin CSS) por el costo de
  mover ~10 variables locales de `main()` a `session_state`; queda anotado
  como deuda deliberada, no como pendiente de este plan.
- El origen de Gemma Net en la migaja se toma del campo explícito
  `origen_medicamentos` (efecto real), no de `usar_bd_catalogos` (intención),
  por el fallback silencioso detectado en el bloque actual (~1934-1941).
- "Cambiar fuente de datos" apaga `editando_fuentes`, nunca `procesado`: así
  no se pierde `session_state["auditoria_coherencia"]` (corrida de minutos
  sobre ~200.000 filas).

## Abierto

- Confirmar en el paso 4 si el CSS `nth-of-type`/`:has()` engancha con el DOM
  de Streamlit 1.61 instalado, o si hace falta el plan B (lista de botones).

## Verificación

- [ ] `pytest` en verde (261+ pruebas)
- [ ] `ruff check src/ tests/ ui_revision/` limpio
- [ ] Linea agregada a `.ai/bitacora.jsonl`
