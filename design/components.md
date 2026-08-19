# Mapeo de patrones de Gemma Net → componentes Streamlit

Referencia para cuando se construya `ui_revision/app_streamlit.py`. Cada fila describe un patrón visual observado en las capturas de Gemma Net y su equivalente más cercano en Streamlit, usando los valores de `design_tokens.json`.

| Patrón observado en Gemma Net | Equivalente en Streamlit | Nota |
|---|---|---|
| Formulario con label a la izquierda, input a la derecha | `st.columns([1, 2])` por fila, label en la primera columna, control en la segunda | Streamlit no tiene un layout label-izquierda nativo para `st.text_input` |
| Input de texto (fondo gris claro, borde fino) | `st.text_input` + CSS override (`fondo_input`, `borde_input`, `radio_input_px`) | El estilo base de Streamlit no expone estas variables por tema, requiere CSS inyectado |
| Dropdown redondeado | `st.selectbox` | Opciones deben venir ya normalizadas (ver `catalogos/resolver.py`) |
| Selector "Nivel de Servicio" (checkbox, una sola opción marcable, bajo un encabezado "Seleccione uno") | `st.radio` | Es selección única aunque el control visual en Gemma Net es un checkbox — `st.radio` refleja mejor la semántica real que `st.multiselect` |
| Botones píldora azul claro con icono (Agregar, Remover, Anterior, Actualizar) | `st.button(label, icon="...")` + CSS override para `fondo_boton`, `texto_boton`, `radio_boton_px` | Streamlit permite `icon=` desde versiones recientes; si no está disponible, usar emoji como fallback |
| Barra superior azul con logo circular | Contenedor `st.markdown` con HTML/CSS inyectado, fijo en la parte superior | Streamlit no permite reemplazar su header nativo; se simula con un bloque propio |
| Badge de estado CUM (Vigente/Vencido) o CUM Activo/Inactivo | `st.badge` si la versión de Streamlit lo soporta, si no un `<span>` HTML con color de `estado_ok`/`estado_alerta` | **Colores no confirmados** — no hay un badge real en las capturas recibidas, ver `style_guide.md` |
| Bandeja de filas en cuarentena (motor de validación) | `st.dataframe` con columna de `motivo` visible, más un panel de detalle al seleccionar fila | Cada fila cae aquí por `Accion.CUARENTENA` desde `validacion/reglas.py`, con su `motivo` ya como texto explicativo |

## Pendiente de las capturas que aún no llegaron

- Un badge de estado real (para no seguir usando los colores estimados de `estado_ok`/`estado_alerta`).
- Un mensaje de error o de validación fallida dentro de Gemma Net, para replicar el tono/formato en la bandeja de rechazos.
