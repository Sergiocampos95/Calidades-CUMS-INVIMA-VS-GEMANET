# Optimización integral de rendimiento de la UI

- **Estado:** en curso
- **Creado:** 2026-08-25 por Claude Code (diagnóstico de `arquitecto`)
- **Objetivo:** ningún rerun de la UI paga un costo que no le corresponde —
  ni Excel generado antes de tiempo, ni DataFrames grandes rehasheados sin
  necesidad, ni copias duplicadas en memoria de lo que ya vive en
  `session_state`.

## Contexto

El dueño del producto reportó que "absolutamente todo" en la app es lento:
cargar archivos, tablas, cambiar de sección. Ya se habían corregido dos casos
puntuales (`resultado`/`df_invima` re-hasheados en cada rerun) pero el
problema persistía. Se lanzó `arquitecto` a auditar sistemáticamente todo
`ui_revision/app_streamlit.py` en busca del mismo patrón y de cualquier otro.

Diagnóstico completo (con líneas reales y mediciones sintéticas, `data/`
vacío en este entorno) en la conversación del 2026-08-25. Resumen de los 6
patrones encontrados, de mayor a menor impacto:

- **P1 — el 95% del problema**: dos `st.download_button(data=...)` calculan
  el Excel **en cada rerun** (no solo al hacer clic en descargar), porque
  `data=` se evalúa siempre. Medido sintéticamente: 20-145 s por rerun sobre
  ~100k filas. Ya existe el patrón correcto (`_descarga_diferida`, usado en
  4 sitios) — quedaron 2 sin migrar (`app_streamlit.py:1530-1538` y
  `:1822-1828`).
- **P2**: `ReglasNegocio` (un dict grande de dataclasses) y la malla de 26 MB
  se pasan como argumento a funciones `@st.cache_data` invocadas sin botón
  de por medio, en Cargue a Gemma Net y en "Por qué no se cargó". 1,5-3,5 s
  por rerun solo hasheando.
- **P3**: `_procesar_candidatos` y `_auditar_coherencia` siguen decoradas con
  `@st.cache_data` aunque su resultado ya vive en `session_state` — doble
  copia en RAM (~800 MB-1,5 GB), sin límite de entradas. Hipótesis con más
  poder explicativo del "todo tarda": si la máquina pagina, todo se
  arrastra.
- **P4** (correctitud, no velocidad): el hasher de Streamlit muestrea 10.000
  filas en DataFrames &gt;50.000 — una clave de cache poco confiable para
  DataFrames grandes. Ninguna función cacheada debería recibir un DataFrame
  grande como argumento después de P3.
- **P5**: recálculos menores (~200-400 ms por rerun) — `descubrir_todo()`
  duplicado, `_cargar_tokens()` sin cachear, sumas repetidas en
  `_mostrar_tabla_de_calidades`, proyección de columnas antes del recorte a
  1.000 filas en vez de después.
- **P6 — confirmado que NO es el problema**: la previsualización de tablas
  ya recorta a 1.000 filas antes de `st.dataframe` (correcto). `descubrir_todo()`/
  `tiene_hoja()` cuesta 2-5 ms (insignificante). `src/gemma_cum_loader/` no
  tiene `apply()`/`iterrows()` en camino caliente. Nada de esto se toca.

No se toca `src/gemma_cum_loader/` en ningún paso — todo el trabajo es de
política de cacheo/UI en `ui_revision/app_streamlit.py`.

## Pasos

- [x] 0. (claude/arquitecto) Diagnóstico completo con líneas reales y
      mediciones — hecho, ver Contexto.
- [x] 1. (claude/implementador) `ui_revision/app_streamlit.py:1530-1538,
      1822-1828` — migrados los 2 `download_button` restantes a
      `_descarga_diferida` (el patrón ya usado en otros 4 sitios), con la
      clave de descarga invalidada cuando cambia el filtro/subconjunto
      elegido (para no ofrecer un archivo que ya no corresponde a lo que se
      ve en pantalla).
- [x] 2. (claude/implementador) `ui_revision/app_streamlit.py:2108-2115,
      2179-2196` — quitado `@st.cache_data` de `_procesar_candidatos` y
      `_auditar_coherencia`: su resultado ya está protegido por
      `session_state`: el decorador solo duplicaba la memoria sin aportar
      protección real.
- [x] 2b. (claude/implementador, pedido directo del usuario 2026-08-25 tras
      probar la app: "el botón de Procesar dura más de un minuto") —
      reintroducido `@st.cache_data(persist="disk", max_entries=3)` en
      `_procesar_candidatos` y `_auditar_coherencia`, ahora seguro porque
      (paso 2) ambas solo se llaman UNA vez por corrida, no en cada rerun:
      el costo de hashear/reconstruir se paga como mucho una vez por sesión
      nueva, insignificante contra los minutos que ahorra. `persist="disk"`
      escribe en `~/.streamlit/cache` (fuera del repo). La clave de cache es
      el HASH DEL CONTENIDO de los DataFrames de entrada — si el archivo de
      origen cambia una fila, la clave cambia y se recalcula solo; esto
      cumple la regla de "degradación explícita, nunca suposición
      silenciosa" de `CLAUDE.md` en vez de violarla: el hash de contenido ES
      la validación de "no hubo modificaciones", no una suposición sin
      verificar.
- [x] 3. (claude/implementador, confirmado 2026-08-26 — el usuario reportó
      "sigue demorando" al cambiar de vista, que era justo este patrón)
      `ui_revision/app_streamlit.py` — implementado `_derivado(clave,
      calcular)` (calcula una vez por corrida, guarda en `session_state`) y
      `_limpiar_derivados()` (única función que centraliza TODAS las claves
      a borrar en "Procesar" — reemplaza los 3 `pop` sueltos). Quitado
      `@st.cache_data` de `_derivar_reglas_negocio_cacheada`,
      `_evaluar_candidatos_cargue_cacheado`, `_armar_estructura_cargue_cacheada`,
      `_preparar_filas_cargue_cacheada` y `_leer_malla_referencia_cacheada`
      (ya no aportan nada detrás de `_derivado`). Bonus encontrado: "Cargue
      a Gemma Net" y "Por qué no se cargó" derivaban `reglas`/`evaluados`
      DOS VECES cada uno (una por sección) — ahora comparten la misma clave
      derivada y solo se calculan una vez entre las dos.
- [ ] 4. (claude/implementador) Verificar (grep) que ninguna función
      `@st.cache_data` reciba un DataFrame grande como argumento tras el
      paso 3; dejar un comentario de convención explicando por qué (el
      muestreo de 10.000 filas del hasher de Streamlit no es una clave de
      cache confiable a esa escala).
- [ ] 5. (claude/implementador) Recálculos menores: unificar las dos
      llamadas a `descubrir_todo()` en el mismo rerun, cachear
      `_cargar_tokens()`, no sumar dos veces la máscara de cada calidad en
      `_mostrar_tabla_de_calidades`, proyectar columnas después de recortar
      a 1.000 filas (no antes).
- [ ] 6. (claude/pruebas) `tests/test_ui_rendimiento.py` (nuevo) — pruebas
      estáticas sobre el AST del archivo: ningún `download_button` calcula
      `data=` en el sitio, ninguna función cacheada recibe un DataFrame o
      `ReglasNegocio`. Más en `tests/test_ui_filtros.py`: `_limpiar_derivados`
      borra todas las claves, `_derivado` calcula una sola vez, la descarga
      diferida se invalida al cambiar el filtro, la tabla recorta antes de
      proyectar columnas.
- [ ] 7. (claude/revisor) Revisión final: `pytest`, `ruff check`, y — pedido
      explícito del usuario — probar a mano el caso que reportó: cargar
      Resumen de resolución, ir a Consultar INVIMA, volver, confirmar que no
      recalcula nada.

## Decisiones

- Se descarta cambiar `@st.cache_data` por `@st.cache_resource` en cualquier
  punto: `cache_resource` comparte el objeto mutable entre sesiones de
  distintos usuarios — filtrar en sitio corrompería la corrida de otro.
  `session_state` es el mecanismo correcto y ya es el patrón del archivo.
- No se recorta el Excel de descarga a 1.000 filas para "arreglar" P1: la
  lista completa es el entregable de negocio (ver memoria
  `reparto_hallazgos_vs_cargue`). El arreglo es diferir el cálculo, no
  truncar el resultado.
- El tiempo de la corrida inicial (cruce + auditoría sobre 200.000 filas,
  "varios minutos") no se toca en este plan: es trabajo real, se paga una
  vez, y ya está detrás de `st.status`. Si tras cerrar este plan la queja de
  lentitud persiste, el siguiente sospechoso es `ingesta/` (lectura de
  archivos reales), no la UI — con su propio diagnóstico.

## Abierto

- Paso 3 necesita luz verde explícita antes de implementarse: es el paso de
  mayor riesgo de correctitud (invalidación de `session_state` mal hecha =
  mostrar datos de la corrida anterior sin avisar). Los pasos 1 y 2 no
  tienen ese riesgo (mismo patrón ya probado en el resto del archivo /
  eliminación pura de una capa redundante) y se implementaron directo.

## Verificación

- [ ] `pytest` en verde
- [ ] `ruff check src/ tests/ ui_revision/` sin errores nuevos
- [ ] Probado en la aplicación corriendo: el caso puntual que reportó el
      usuario (cambiar de sección y volver no recalcula)
- [ ] Línea agregada a `.ai/bitacora.jsonl`
