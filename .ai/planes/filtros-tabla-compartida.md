# Estandarizar y optimizar el filtro compartido de tablas

- **Estado:** en curso
- **Creado:** 2026-08-25 por Claude Code
- **Objetivo:** `_filtros_avanzados()` / `_tabla_filtrable()` (`ui_revision/app_streamlit.py:484-750`,
  usadas por las 6 secciones) quedan más compactas visualmente y sin trabajo
  evitable sobre DataFrames grandes, verificado con la app corriendo antes de
  cerrar.

## Contexto

Captura de referencia del usuario (sub-vista "Detalle por registro" de Resumen
de resolución, pero el patrón es el mismo en toda la app): el panel "Filtros
— busca por cualquier campo del medicamento" se ve como varias cajas
apiladas de ancho completo (selector de campos, panel de valores, botón
"Aplicar filtros") antes de llegar a la tabla. No es un caso puntual: es
`_filtros_avanzados()`, un componente compartido — mejorarlo una vez se
refleja en las 6 secciones.

Pedido explícito: dos frentes en paralelo — **diseño** (más compacto, menos
cajas apiladas, consistente con el azul y el estilo de tablas ya aplicado en
esta sesión) y **optimización** (que filtrar sobre tablas de hasta ~200.000
filas no relentice la interacción; revisar si hay copias o recómputos
evitables por rerun). Como tocan la misma función compartida, no pueden ir
literalmente en paralelo sin pisarse — la optimización va primero porque
cambia la forma en que se calculan los filtros; el diseño se construye sobre
esa base ya estable. Sí hay paralelismo real entre pruebas (archivo distinto)
y la optimización.

Reglas del proyecto en juego: toda tabla de medicamentos sigue con búsqueda
libre y filtros (no se le quita nada al reorganizar), sin dependencias
nuevas, sin tocar `src/gemma_cum_loader/`.

## Pasos

- [ ] 1. (claude/ui-streamlit) `ui_revision/app_streamlit.py` — optimización:
      medir `_filtros_avanzados()`/`_tabla_filtrable()` con un DataFrame de
      referencia grande (miles de filas, no hace falta producción) y eliminar
      recómputo evitable por rerun: el split de celdas por fila del filtro
      tipo "lista" (línea ~739, `texto.map(lambda celda: {...})`) y la
      búsqueda de texto libre sobre columnas completas
      (`.astype(str).str.lower().str.contains(...)`, línea ~533) son los dos
      puntos a revisar primero. Mismo resultado observable, sin copias del
      DataFrame completo que no aporten. **Puede ir en paralelo con el paso
      2** (no comparte archivo).
      Criterio de listo: los mismos filtros devuelven las mismas filas que
      antes; ninguna operación se repite sin que haya cambiado el criterio
      que la origina.
- [ ] 2. (claude/pruebas) `tests/test_ui_filtros.py` — pruebas de regresión
      para el comportamiento actual de `_filtros_avanzados`/`_tabla_filtrable`
      (fecha, número, categoría, lista, "contiene") ANTES de que cambie la
      implementación interna, para que el paso 1 tenga que dejarlas en verde.
      **Puede ir en paralelo con el paso 1.**
      Criterio de listo: `pytest tests/test_ui_filtros.py -q` en verde contra
      el código actual, y sigue en verde después del paso 1.
- [ ] 3. (claude/ui-streamlit) `ui_revision/app_streamlit.py` — diseño:
      layout compacto de `_filtros_avanzados()` — los controles por campo en
      columnas en vez de apilados a ancho completo, el multiselect de "Campos
      por los que filtrar" y el botón "Aplicar filtros" con menos espacio
      vertical, expander colapsado por defecto salvo que ya haya campos
      elegidos (conserva `expanded=bool(sugeridos)`). Mismos `key` de
      `session_state` que hoy — no romper lo que ya depende de ellos (ver
      `_columnas_visibles`, línea ~558). Requiere que el paso 1 esté en `[x]`
      (mismo archivo y misma función).
      Criterio de listo: menos altura vertical antes de llegar a la tabla en
      una captura de referencia con 3+ campos elegidos; ningún filtro deja de
      funcionar.
- [ ] 4. (copilot) `ui_revision/app_streamlit.py` — iterar visualmente con la
      app corriendo sobre la base del paso 3: ajustar espaciados, anchos de
      columna y tamaños hasta que se vea compacto y moderno, consistente con
      el CSS de tablas y el azul ya aplicados (`_inyectar_css`). Requiere que
      el paso 3 esté en `[x]` (mismo archivo).
- [ ] 5. (claude/revisor) — leer el diff de los pasos 1, 2, 3 y 4: confirmar
      que ninguna tabla perdió búsqueda o filtros, que `-999` y
      `PORCENTAJE_CALIDAD` no se tocaron, que no se agregaron dependencias, y
      que `pytest`/`ruff` siguen en verde/limpio. Requiere 1-4 en `[x]`.
- [ ] 6. (claude/ui-streamlit) — prueba manual final con
      `streamlit run ui_revision/app_streamlit.py` antes de entregar: abrir
      cada una de las 6 secciones, aplicar y quitar filtros sobre una tabla
      grande, confirmar que el panel se ve compacto y que la interacción
      responde sin demora perceptible. Requiere que el paso 5 esté en `[x]`.

**Primer bloque paralelo:** pasos 1 y 2 (optimización y pruebas de
regresión), porque no comparten archivo. Los pasos 3, 4, 5 y 6 son
secuenciales porque cada uno depende de que el anterior haya cerrado sobre el
mismo archivo compartido.

## Decisiones

- Optimización antes que diseño: ambas tocan `_filtros_avanzados()` en el
  mismo archivo, así que no pueden ser literalmente paralelas sin pisarse;
  optimizar primero evita rediseñar dos veces si cambia la forma interna de
  calcular los filtros.
- Las pruebas de regresión (paso 2) se escriben contra el comportamiento
  actual, antes del cambio — así el paso 1 tiene un contrato objetivo que no
  puede romper.

## Abierto

-

## Verificación

- [ ] `pytest` en verde
- [ ] `ruff check src/ tests/ ui_revision/` limpio (sin errores nuevos sobre
      el baseline ya conocido)
- [ ] Linea agregada a `.ai/bitacora.jsonl`
