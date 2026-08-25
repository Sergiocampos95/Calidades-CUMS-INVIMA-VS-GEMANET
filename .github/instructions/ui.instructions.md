---
applyTo: "ui_revision/**/*.py"
description: Reglas de la interfaz Streamlit que ve el equipo de negocio
---

# Editando `ui_revision/`

Esta interfaz la usa el equipo de negocio de Pijao Salud, no un tecnico.

- **Toda tabla de medicamentos lleva filtros y busqueda libre.** Ninguna se
  muestra en crudo.
- Las advertencias van como **tarjeta corta + detalle en un expander**, nunca
  como parrafos largos dentro de un banner.
- Cada cifra que se muestra tiene que poder abrirse a los medicamentos que la
  componen. Un numero sin forma de auditarlo no sirve.
- 5 pestanas: Resumen de resolucion · Bandeja de cuarentena · Cargue a Gemma
  Net · Consultar INVIMA · Auditoria de coherencia.
- **La UI no implementa logica de negocio.** Llama a `src/gemma_cum_loader/`.
  Si necesitas una regla nueva, va en el paquete y aqui solo se muestra.
- Cachea lo caro (`@st.cache_data`) — la UI carga cientos de miles de filas.
- El entregable del equipo son **hallazgos**: quien carga en Gemma Net es una
  persona (Hugo), no la aplicacion. No prometas en la UI que algo "se cargo".

Esta es la zona natural de Copilot: el usuario tiene la app corriendo al lado y
ve el efecto de cada cambio. Iterar aqui es barato; equivocarse en `src/` no.
