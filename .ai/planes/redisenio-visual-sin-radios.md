# Rediseño visual sin radios

- **Estado:** en curso
- **Creado:** 2026-08-25 por Copilot CLI
- **Objetivo:** la aplicación se navega y se filtra sin controles de radio visibles, y todas las tablas presentan datos de forma consistente, legible y escalable.

## Contexto

El usuario rechazó el diseño actual: el sidebar y las sub-vistas parecen un
formulario por los radios circulares, y las tablas siguen visualmente planas.
La captura del 2026-08-25 confirma ambos problemas. El rediseño conserva las
seis secciones, las claves de `session_state` actuales y el patrón que evita
recalcular DataFrames grandes. No toca `src/`.

## Pasos

- [x] 1. (claude/ui-streamlit) `ui_revision/app_streamlit.py` — definir
      `SUBVISTAS_POR_SECCION` y reemplazar los radios de navegación y
      sub-vistas por botones accesibles de dos niveles; mantener
      `seccion_activa`, `resumen_vista`, `cuarentena_vista`,
      `cargue_vista`, `diagnostico_origen` y `vista_auditoria`.
- [x] 2. (claude/ui-streamlit) `ui_revision/app_streamlit.py` —
      reemplazar el radio restante de fuente por `st.selectbox`, y consolidar
      el CSS de navegación, acciones y foco visible con tokens existentes.
- [~] 3. (claude/ui-streamlit) `ui_revision/app_streamlit.py` — crear un
      renderizador único de tablas para resumen y medicamentos; unificar
      cabecera, formatos, densidad, scroll y previsualización acotada sin
      truncar exportaciones ni fusionar filas.
- [ ] 4. (claude/pruebas) `tests/test_ui_navegacion.py` y
      `tests/test_ui_filtros.py` — cubrir contrato de navegación, ausencia de
      radios, previsualización limitada y conservación de filtros.
- [ ] 5. (copilot) `design/design_tokens.json`, `design/components.md` —
      documentar roles visuales y equivalencias Streamlit del diseño sin
      radios, sin introducir colores o dependencias nuevos. Requiere 1 y 2.
- [ ] 6. (copilot) `ui_revision/app_streamlit.py` — iterar el resultado con
      Streamlit corriendo: seis secciones, sidebar colapsado, foco de teclado,
      tablas vacías/parciales y navegación sin recálculo. Requiere 1-4.
- [ ] 7. (claude/revisor) — revisar el diff conjunto: sin radios visibles,
      tablas de medicamentos con búsqueda/filtros, sin serializar 200.000
      filas al navegador y sin cálculos o red duplicados. Requiere 1-6.

**Paralelo posible:** los pasos 1-3 son secuenciales sobre el mismo archivo;
el paso 4 puede empezar tras definir el contrato de navegación en el paso 1.
El paso 5 espera los pasos 1-2; no comparte archivos con el paso 4.

## Decisiones

- Botones nativos, no HTML interactivo ni `st.tabs`: preservan teclado y no
  ejecutan vistas ocultas.
- La previsualización limita únicamente lo enviado al navegador; el
  DataFrame filtrado completo sigue disponible para descarga.

## Abierto

- La actualización de README/CLAUDE sobre cinco versus seis secciones se
  evaluará después del rediseño; no es parte del cambio visual.

## Verificación

- [ ] `pytest` en verde
- [ ] `ruff check src/ tests/ ui_revision/` limpio
- [ ] Streamlit probado en ejecución
- [ ] Línea agregada a `.ai/bitacora.jsonl`
