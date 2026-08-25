---
applyTo: "src/gemma_cum_loader/**/*.py"
description: Reglas del paquete — logica de negocio, 200.000 filas
---

# Editando `src/gemma_cum_loader/`

Aqui vive la logica de negocio. Es la zona donde un cambio "razonable" rompe
una regla del proyecto sin que ningun test obvio se ponga rojo.

**Antes de editar:** este es territorio de decision. Si el cambio toca mas de
un modulo, cambia el contrato entre paquetes, agrega un dataset o una dimension
de calidad, **no improvises**: pide el plan (Claude Code, agente `arquitecto`)
o escribe uno en `.ai/planes/`. Ver `.ai/planes/README.md`.

## Lo que se rompe con mas frecuencia

- `catalogos/resolver.py` — la cascada `exacto -> alias -> fuzzy ->
  sin_resolver` es deterministica. **Cero llamadas de red, cero IA.** Cualquier
  cosa que agregue una llamada por fila es un error de rendimiento a 200.000
  filas, no una mejora.
- `armado/cruce_gemanet.py` — nunca fusiones filas por `CODIGO_INTERNO`
  duplicado: son medicamentos combinados.
- `validacion/reglas.py` — el cuarto estado, `cuarentena`, existe para lo
  ambiguo. Ante la duda no se acepta ni se rechaza: se pone en cuarentena con
  el motivo.
- `auditoria/coherencia_invima.py` — `-999` es "sin dato", no un valor.
  `PORCENTAJE_CALIDAD` vacio != 0 %.
- `catalogos/ia_client.py` — la IA traduce motivos, no decide nada. Una llamada
  por motivo distinto, nunca una por fila.

## Estilo

- ASCII: espanol **sin tildes** en identificadores, docstrings y comentarios.
- `from __future__ import annotations` primero.
- Dataclasses `frozen=True` para retornos; type hints en firmas publicas.
- Vectoriza con pandas; evita `iterrows()` y `apply` fila a fila en rutas que
  ven el universo completo.
- No borres comentarios existentes que explican un hallazgo contra datos de
  produccion: son la memoria del proyecto.

## Al terminar

Todo modulo nuevo o cambiado necesita su `tests/test_<modulo>.py`. Corre
`pytest` y `ruff check src/`.
