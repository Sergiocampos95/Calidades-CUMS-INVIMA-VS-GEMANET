# Validar el rediseño de auditoría de coherencia

- **Estado:** en curso
- **Creado:** 2026-08-25 por Claude Code
- **Objetivo:** el rediseño de la sección Auditoría de coherencia en
  `ui_revision/app_streamlit.py` (jerarquía Priorizar / Entender / Revisar
  medicamentos, filtros de hallazgos simplificados) queda validado por UI,
  pruebas y revisión de código, con los hallazgos aprobados incorporados.

## Contexto

Origen: rediseño descrito en
`C:\Users\TECNOLGO TIC\.copilot\session-state\ac1010c3-d83c-4cdc-97c7-609201d83585\plan.md`
(seccion "Delegacion para validacion"). Alcance limitado a la capa Streamlit:
no cambia `auditoria/coherencia_invima.py`, las diez dimensiones, los estados,
las columnas, las descargas ni los datos en `session_state`. No se toca la
vista transversal "Por que no se cargo".

Reglas del proyecto en juego: toda tabla de medicamentos lleva filtros y
busqueda libre (nunca en crudo); advertencias como tarjeta corta + detalle en
expander; cambiar de vista/filtro no debe releer archivos, consultar
Socrata/Gemma Net ni volver a ejecutar `auditar_coherencia`.

No se delega a Copilot en este bloque: la validacion requiere terminal y
Streamlit corriendo, que no estan disponibles en esa sesion.

## Pasos

- [ ] 1. (claude/ui-streamlit) `ui_revision/app_streamlit.py` — ejecutar
      Streamlit y validar los recorridos: sin auditoria, auditoria sin
      riesgos, riesgos de vigencia, diferencias de campos, dimension de
      calidad vacia y descarga diferida; corregir solo defectos de UI.
- [ ] 2. (claude/pruebas) `tests/test_ui_filtros.py` — ejecutar la prueba
      dirigida y cubrir filtros vacios, estados sin coincidencia y
      campos-lista para los nuevos helpers de clasificacion y filtros
      esenciales. **Puede correr en paralelo con el paso 1**: no comparte
      archivo.
- [ ] 3. (claude/revisor) — leer el diff resultante de 1 y 2; verificar que
      las tablas conserven busqueda y filtros, que no se recalcule la
      auditoria al cambiar de vista/filtro, y que cada cifra accionable siga
      siendo trazable a su lista de medicamentos. Requiere que 1 y 2 esten en
      `[x]`.
- [ ] 4. (claude/ui-streamlit) `ui_revision/app_streamlit.py` — incorporar los
      hallazgos aprobados del paso 3 y hacer la comprobacion visual final.
      Requiere que 3 este en `[x]`.

**Paralelo posible ahora:** pasos 1 y 2 (duenos y archivos distintos). El paso
3 espera a que ambos terminen; el paso 4 espera al 3.

## Decisiones

-

## Abierto

-

## Verificacion

- [ ] `pytest` en verde
- [ ] `ruff check src/ tests/ ui_revision/` limpio
- [ ] Linea agregada a `.ai/bitacora.jsonl`
