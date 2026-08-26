# Rediseño de filtros/menú lateral (Copilot) y optimización de consultas (Claude Code)

- **Estado:** en curso
- **Creado:** 2026-08-25 por Claude Code
- **Objetivo:** las 6 secciones muestran primero la información importante,
  usan un único patrón de filtro estandarizado (dos desplegables de selección
  múltiple, nunca radios), los avisos largos se leen como tarjeta emergente,
  el **sidebar** pasa a ser un menú de dos niveles dinámico (secciones +
  subsecciones desplegables dentro del mismo menú lateral, con animación de
  carga cuando hay un proceso corriendo), y la aplicación deja de sentirse
  lenta al consultar datos.

## Contexto para quien no vio esta conversación (Copilot: leé esto entero antes de tocar código)

Este plan viene de una conversación larga con el dueño del producto sobre
`ui_revision/app_streamlit.py`. Antes de este plan ya se hicieron, EN ESTE
MISMO DÍA, los siguientes cambios — no los repitas ni los reviertas:

1. **Tema de color**: se agregó `[theme] primaryColor = "#2A4D8F"` en
   `.streamlit/config.toml` porque Streamlit pintaba radios/checkboxes/toggles
   con su rojo de acento por defecto (`#FF4B4B`), y al usuario **le gustó**
   el azul. Cualquier color nuevo que agregues sale de
   `design/design_tokens.json` (diccionarios `color`, `tipografia`, `forma`
   que ya recibe `_inyectar_css(tokens)` en la línea 302), nunca inventado.
2. **El punto nativo de los radio buttons se oculta por CSS** en el sidebar
   (`section[data-testid="stSidebar"] label[data-baseweb="radio"] > div:first-child { display: none; }`,
   dentro de `_inyectar_css`, línea ~302-420 aprox.) porque al usuario "esa
   selección redonda se ve horrible". El plan de este documento va más allá:
   ver Paso 5 más abajo, se reemplaza el mecanismo completo, no solo su CSS.
3. **El bloque "Archivos de entrada" desaparece del todo tras procesar** (ni
   siquiera queda colapsado) — hay una línea corta "Fuente: ... [Cambiar
   fuente de datos]" en su lugar. Patrón: `procesado_ya` / `editando_fuentes`
   en `session_state`, cerca de la línea 1826 de `main()`.
4. **Los banners nunca van de borde a borde**: hay una regla CSS con
   `max-width: 900px` sobre los contenedores de alerta de Streamlit
   (`stAlertContainer`/`stAlert`) dentro de `_inyectar_css`. El Paso 4 de
   este plan va más allá de eso para avisos largos (tarjeta emergente).
5. **Las 6 secciones ya están subdivididas en sub-vistas** con
   `st.radio(horizontal=True, key=...)` dibujado HOY dentro del cuerpo de la
   página (no en el sidebar). Es lo que el Paso 5 de este plan mueve al
   sidebar como menú de dos niveles. El mapa completo, con las claves de
   `session_state` que ya existen y que **no se deben renombrar** (el resto
   del código lee esas claves más abajo):

   | Sección (valor en `SECCIONES`) | ¿Sub-vistas? | `key` del radio actual | Opciones (orden real) | Dónde se dibuja hoy |
   |---|---|---|---|---|
   | Resumen de resolución | Sí | `resumen_vista` | Resumen · Cómo se resolvió · Detalle por registro | línea ~2536, dentro de `if seccion == "Resumen de resolución":` |
   | Casos que requieren decisión | Sí | `cuarentena_vista` | Bandeja de casos · Explicar con IA | línea ~2600 |
   | Cargue a Gemma Net | Sí | `cargue_vista` | Auditoría de estructura · Excel de cargue final | línea ~2739 |
   | Por qué no se cargó | Sí | `diagnostico_origen` | Candidatos nuevos que no se cargaron · Ya cargados con diferencias frente a INVIMA · Novedades de vigencia contra INVIMA | línea ~2885 |
   | Consultar INVIMA | No | — | (vista única, sin sub-radio) | línea ~2989 |
   | Auditoría de coherencia | Sí | `vista_auditoria` | Priorizar lo que requiere accion · Entender la calidad del catalogo · Explorar todos los hallazgos | línea ~3314 |

   Los números de línea son del momento en que se escribió este plan — el
   frente de optimización (Paso 8 en adelante) puede correr antes y moverlos
   unas pocas líneas; buscá por el texto del `key=` o del título de sección
   para ubicarte, no confíes ciegamente en el número.

6. **El sidebar hoy** (línea ~2520): un único `st.radio` plano con las 6
   secciones (`SECCIONES = SECCIONES_CANDIDATOS + SECCIONES_CARGADOS`,
   definidas en líneas ~2499-2508), `key="seccion_activa"`,
   `label_visibility="collapsed"`. **Esto es lo que el Paso 5 reemplaza.**

7. No hay imágenes adjuntas de referencia del usuario para este pedido
   ("segunda imagen", "tercera imagen", "última foto" de un pedido anterior)
   — no dependas de ellas para nada de lo que sigue, este plan es autónomo.

## Reglas que no se pueden romper (repaso rápido de `CLAUDE.md`)

- Toda tabla de medicamentos lleva búsqueda libre y filtros, nunca se muestra
  en crudo.
- Advertencias como tarjeta corta + detalle en expander/popover, nunca
  párrafos largos en banner.
- No se toca `src/gemma_cum_loader/` desde el frente de diseño.
- No se agregan dependencias nuevas sin justificar por qué Streamlit +
  CSS inyectado no alcanza.
- Los comentarios de código son ASCII sin tildes; el texto que ve el usuario
  en pantalla sí lleva tildes (mirá el estilo de los strings ya existentes).
- No borres comentarios que documentan hallazgos reales de producción — si
  movés código, el comentario se mueve con él.

## Pasos

### Frente 1 — Diseño (dueño: copilot, archivo: `ui_revision/app_streamlit.py`)

- [x] 1. (copilot) **Jerarquía de contenido**: en cada una de las 6
      secciones, la métrica/cifra/resultado más importante va primero,
      arriba de todo, antes que cualquier detalle o tabla extensa. Ejemplo
      concreto: en "Resumen de resolución" → sub-vista "Resumen"
      (`_seccion_resumen_metricas`, función definida en línea ~1845), las 4
      métricas (`Registros evaluados`, `Candidatos a crear`, `Ya en Gemma
      Net`, `En cuarentena`) ya están arriba — confirmar que este orden se
      mantenga en las demás secciones al reorganizar por los pasos
      siguientes, no invertirlo por accidente.

- [x] 2. (copilot) **Estandarizar filtros a un solo patrón.** Hoy conviven
      tres mecanismos de filtro sin relación entre sí — esto es lo que el
      usuario señaló como "por qué hay dos tipos de filtro para una tabla":
      - `_tabla_filtrable` (línea ~484): filtro genérico por columna,
        tipo-consciente (fechas, números, texto, listas de valores), usa
        `st.multiselect` por cada columna elegida.
      - `_tabla_auditoria_esencial` (línea ~1188): solo un `st.text_input` de
        búsqueda libre, sin filtros estructurados.
      - El expander "Acotar esta lista" en Auditoría (línea ~3470): dos
        `st.multiselect` sueltos (Estados, Campos con diferencia) fuera de
        los dos mecanismos anteriores.

      Reemplazar los tres por **un solo componente reusable** (una función
      nueva, ej. `_filtros_estandar(df, columnas_filtrables, ...)`) que
      combine: búsqueda libre (`st.text_input`, siempre visible, obligatoria
      por regla de negocio) + **exactamente dos desplegables de selección
      múltiple** colapsados por defecto (`st.multiselect` dentro de un
      `st.popover` o `st.expander` chico — **nunca `st.radio`**: pedido
      explícito y repetido del usuario, "no me vayas a poner radios, esa
      selección redonda se ve horrible"). Los dos desplegables son: (a) uno
      para la dimensión de estado/categoría más relevante de esa tabla
      (ESTADO_COHERENCIA, accion, etc.) y (b) uno para el campo/columna a
      acotar. Aplicarlo a las tablas de las 6 secciones que hoy usan
      cualquiera de los tres mecanismos viejos. Cada tabla conserva su
      búsqueda libre y sus filtros — ninguna se muestra en crudo (regla no
      negociable).

- [x] 3. (copilot) **Avisos largos como tarjeta emergente.** Ya existe
      `_mensaje_breve` (línea ~807) para tarjeta corta + detalle en
      expander — revisala antes de crear nada nuevo. Donde el contenido del
      detalle sea largo (más de ~3-4 líneas), migrar ese expander a un
      `st.popover` (tarjeta emergente al hacer click, no ocupa espacio fijo
      en la página) manteniendo la misma firma de función si es posible,
      para no tener que tocar cada sitio de llamada uno por uno. Aplicarlo de
      forma pareja en las 6 secciones, no solo donde el usuario vio el
      ejemplo original.

- [x] 4. (copilot) **Menú lateral dinámico de dos niveles — SOLO el sidebar,
      nada arriba de la página.** Corrección explícita del usuario sobre un
      intento anterior de este mismo pedido: NO se agrega un menú horizontal
      arriba de la página. El único menú que cambia es el `st.sidebar`
      existente (línea ~2520).

      Comportamiento pedido: el sidebar sigue mostrando las 6 secciones como
      hoy (una fila por sección, ver contexto punto 6). Al entrar a una
      sección — por click, y con una reacción visual también al pasar el
      mouse (hover) — esa fila se expande **dentro del mismo panel lateral**
      y debajo de ella aparecen sus subsecciones (ver la tabla del punto 5
      del contexto: Resumen → 3 subsecciones, Cuarentena → 2, Cargue → 2,
      "Por qué no se cargó" → 3, Auditoría → 3; "Consultar INVIMA" no tiene,
      se deja como fila simple sin expandir). Las demás secciones quedan
      colapsadas, mostrando solo su título de fila.

      Implementación sugerida (Streamlit no tiene un widget nativo de
      acordeón con hover — hay que armarlo con lo que hay, sin dependencias
      nuevas):
      - Nivel 1: en vez del `st.radio` plano actual, un `st.button` (o una
        fila clickeable armada con `st.container` + CSS, si el look de
        `st.button` no alcanza) por cada una de las 6 secciones, dentro de
        `with st.sidebar:`. Al hacer click, guardar la sección en
        `st.session_state["seccion_activa"]` (mismo nombre de clave que hoy,
        no lo cambies — el resto de `main()` ya lee esa clave) y `st.rerun()`.
      - Nivel 2: inmediatamente debajo del botón de la sección que sea
        `st.session_state["seccion_activa"]`, dibujar dentro del mismo
        `with st.sidebar:` el `st.radio(horizontal=False, key=...)` que HOY
        ya existe para esa sección (ver tabla del contexto: `resumen_vista`,
        `cuarentena_vista`, `cargue_vista`, `diagnostico_origen`,
        `vista_auditoria`) — **es un mover, no un crear**: sacás cada uno de
        esos 5 `st.radio` de donde están hoy (dentro del cuerpo de la
        página, ej. línea ~2536) y lo volvés a dibujar acá, con las mismas
        `key=` y las mismas opciones en el mismo orden, para que el resto
        del código (`if vista_resumen == "Resumen": ...` etc.) siga
        funcionando sin tocarlo. Cambiá `horizontal=True` a `horizontal=False`
        si el ancho del sidebar no alcanza para las opciones en fila.
      - **Hover**: efecto puramente visual por CSS (`:hover` en el
        contenedor de cada fila de sección — mismo patrón que ya usa el
        archivo en otros lados de `_inyectar_css`, ej. `background-color:
        {color["fondo_input"]["valor"]}`), no dispara ningún cambio de
        estado por sí solo. Lo que decide qué sección está activa y expandida
        es el click (o el estado ya guardado en `session_state`), nunca el
        hover — Streamlit no puede reaccionar a un hover sin un rerun
        explícito y forzar un rerun en cada movimiento del mouse arruinaría
        el rendimiento.
      - **Animación de carga sobre el proceso en curso**: cuando la sección
        activa está corriendo un cálculo pesado (los bloques que hoy usan
        `with st.status(...)`, por ejemplo "Cruzando el catálogo de INVIMA
        contra Gemma Net" o "Auditando el catálogo completo"), mostrar un
        indicador chico (ej. un `⏳` con una animación CSS `@keyframes`
        de pulso, o un `st.spinner` diminuto) junto a la fila de esa sección
        en el sidebar, no solo en el cuerpo de la página. Para esto hace
        falta un flag en `session_state` (ej.
        `st.session_state["seccion_procesando"] = "Resumen de resolución"`)
        que se prenda justo antes de entrar a un `with st.status(...)` largo
        y se apague al salir — coordinalo con el Paso 8 del frente de
        optimización si ese frente ya tocó esos mismos bloques, para no
        pisarse: revisá el estado del plan (`[~]`/`[x]`) antes de editar
        esas líneas.
      - Si after intentarlo el hover-CSS + acordeón por click no se ve bien
        con los widgets nativos de Streamlit (es una limitación conocida:
        `st.button` dentro de `st.sidebar` no admite anidar HTML libre sin
        `unsafe_allow_html`), es válido resolver el nivel 2 con
        `st.expander` en vez de filas custom — el expander de la sección
        activa arranca `expanded=True` y el resto `expanded=False`, sigue
        siendo "desplegable dentro del mismo menú lateral" y es mucho más
        simple de mantener. Priorizar que funcione bien sobre que sea
        pixel-perfect a un mockup que no existe.

- [x] 5. (copilot) **Seguir el rediseño de tablas**: sobre el CSS ya agregado
      (bordes redondeados, cabecera con fondo, en `_inyectar_css`), iterar
      más si hace falta (rayado alterno de filas, indicador de orden por
      columna, cabecera fija al hacer scroll) — usando siempre los tokens de
      `design/design_tokens.json`, nunca colores nuevos.

- [x] 6. (copilot) Probar cada punto en la aplicación corriendo
      (`streamlit run ui_revision/app_streamlit.py`) antes de darlo por
      cerrado — pedido explícito del usuario: "antes de entregarla
      probarla". Verificar en particular: que cambiar de sub-vista desde el
      sidebar no recalcula el pipeline ni la auditoría (mismo criterio de
      rendimiento que ya document el comentario de línea ~2490-2498), que
      solo una sección/subsección aparece expandida a la vez, y que las
      claves de `session_state` (`resumen_vista`, `cuarentena_vista`,
      `cargue_vista`, `diagnostico_origen`, `vista_auditoria`,
      `seccion_activa`) siguen existiendo con esos nombres exactos.

### Frente 2 — Optimización (dueño: claude/implementador, archivos:
`src/gemma_cum_loader/integraciones/gemanet_db.py`,
`src/gemma_cum_loader/integraciones/socrata.py`,
`src/gemma_cum_loader/auditoria/coherencia_invima.py`,
`ui_revision/app_streamlit.py` SOLO en los decoradores `@st.cache_data` /
`@st.cache_resource` ya existentes, para no pisar el archivo del frente 1)

- [x] 7. (claude/implementador) Diagnosticar con cifras reales dónde está la
      demora al consultar. Medido en `gemanet_db.py`/`socrata.py`/
      `coherencia_invima.py`: esas consultas mismas ya eran razonables (9 s
      medicamentos desde base, catálogos de marca/unidad/modelo son de
      decenas de kB). El cuello de botella real estaba en otro lado: ver
      Decisiones.
- [x] 8. (claude/implementador) Evaluar y aplicar caché donde sea seguro —
      ver Decisiones para el detalle. No se tocó la decisión existente de no
      cachear la auditoría completa en `st.cache_data`.
- [x] 9. (claude/implementador) Medir antes/después con cifras concretas y
      dejarlas en `## Decisiones` — hecho, ver abajo.
- [ ] 10. (claude/pruebas) Cubrir con test cualquier lógica de caché nueva
      que no dependa de Streamlit ni de la base real (inyectar cliente/mock).
- [ ] 11. (claude/revisor) Revisión final de ambos frentes juntos: `pytest`,
      `ruff check src/ tests/ ui_revision/`, que no haya llamadas de red
      dentro de un bucle por fila, que el frente de diseño no haya duplicado
      cálculo pesado al mover los `st.radio` al sidebar.

**Orden entre frentes:** el Paso 7-9 (optimización, toca decoradores de caché
en `app_streamlit.py`) conviene cerrarlo **antes** de que el Paso 4 del
frente de diseño reorganice ese mismo archivo a fondo (mover 5 `st.radio` de
lugar), para no generar conflictos de merge en las mismas líneas. Si ya
arrancó el frente de diseño, coordinar por el protocolo de marcas `[~]` de
`.ai/planes/README.md` antes de tocar los mismos bloques de código.

## Decisiones

- El menú superior propuesto en una versión anterior de este plan se
  descarta: el usuario corrigió que el cambio es únicamente sobre el
  sidebar, con las subsecciones desplegándose dentro del mismo panel
  lateral, no arriba de la página.
- **Paso 2 (2026-08-25):** `_filtros_estandar` concentra búsqueda local y
  dos multiselecciones dentro de popovers: categoría/estado y
  campo/columna. `_tabla_filtrable`, `_tabla_auditoria_esencial`, los
  diagnósticos y la bandeja de pendientes lo reutilizan. Las claves previas
  de búsqueda y de campos se conservan; `CAMPOS_CON_DIFERENCIA` mantiene el
  criterio "contiene cualquiera".
- **Hallazgo del frente de optimización (2026-08-25):** el cuello de botella
  medido no estaba en las consultas a Gemma Net/Socrata (esas son rapidas y
  ya estaban bien cacheadas) sino en `main()` de `ui_revision/app_streamlit.py`:
  `df_invima` y `resultado = _procesar_candidatos(...)` se recalculaban en
  **cada rerun de Streamlit** (cualquier clic, cualquier filtro, cualquier
  cambio de sub-vista en cualquier seccion), no solo al presionar "Procesar".
  Aunque `_procesar_candidatos` esta detras de `@st.cache_data`, Streamlit
  necesita HASHEAR sus argumentos en cada llamada para decidir si hay
  acierto de cache — con `df_invima` (~200.000 filas) y
  `archivo_gemma_net.df` (tamano comparable) como argumentos, eso midio
  ~0.067-0.079 s por DataFrame hasheado (`streamlit.runtime.caching.hashing.update_hash`
  sobre un DataFrame sintetico de 200.000 x 15 columnas de texto, 62 MB en
  memoria — sin datos de produccion disponibles en este entorno, `data/` esta
  vacio y en `.gitignore`), es decir ~150 ms perdidos en CADA interaccion de
  toda la aplicacion solo en hashear argumentos para un cache que casi
  siempre iba a acertar. Se descarto la hipotesis inicial de que
  `descubrir_todo()`/`tiene_hoja()` (abre el Excel de Estructura de Cargue
  con openpyxl en cada rerun) fuera el cuello de botella principal: medido
  con un .xlsx sintetico de ~13 MB / 200.000 filas, `tiene_hoja()` tardo
  ~2-5 ms por llamada en modo `read_only` — cargo insignificante, la
  sospecha no se sostuvo con datos (no se toco ese codigo).
  **Cambio aplicado:** `resultado` y `df_invima` ahora se calculan una sola
  vez por corrida y se guardan en `session_state["resultado_candidatos"]` /
  `session_state["df_invima_cache"]` (mismo patron que ya usaba
  `auditoria_coherencia`), leyendose de ahi en los reruns siguientes en vez
  de volver a invocar las funciones cacheadas con los DataFrames grandes como
  argumento. Se limpian junto con `auditoria_coherencia` al presionar
  "Procesar" de nuevo. Elimina el hasheo repetido de ~150 ms por interaccion
  en las 6 secciones, sin cambiar ningun resultado ni regla de negocio.
  Archivo tocado: `ui_revision/app_streamlit.py` (bloque de carga/cruce de
  INVIMA, cerca de donde antes estaba el `st.status` de "Cruzando el
  catalogo..."). No se toco `src/gemma_cum_loader/`.

## Abierto

- Viabilidad exacta del hover + acordeón con widgets nativos de Streamlit —
  el Paso 4 ya deja como salida válida usar `st.expander` si el enfoque de
  filas custom con CSS no da un resultado limpio.

## Verificación

- [ ] `pytest` en verde
- [ ] `ruff check src/ tests/ ui_revision/` sin errores nuevos
- [ ] Probado en la aplicación corriendo (Streamlit) antes de cerrar el plan
- [ ] Línea agregada a `.ai/bitacora.jsonl`
