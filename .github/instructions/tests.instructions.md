---
applyTo: "tests/**/*.py"
description: Reglas de la suite de pytest
---

# Editando `tests/`

- **Nunca golpear APIs reales ni la base de Gemma Net desde pytest.** El
  cliente se inyecta: `ClienteExplicacionIA(client=...)`, lo mismo para
  Socrata/HTTP y para Postgres.
- **Nunca leer `data/`.** Los tests se construyen con DataFrames pequenos
  in-line, no con archivos de produccion.
- Un `tests/test_<modulo>.py` por modulo de `src/`.
- Nombres de test descriptivos en espanol y sin tildes, coherentes con los
  existentes (`def test_cuarentena_cuando_la_marca_no_resuelve(): ...`).
- Un test que reproduce un bug se escribe **antes** del arreglo y se deja en el
  repositorio despues.
- Cubre el caso ambiguo, no solo el feliz: si la funcion puede mandar algo a
  `cuarentena`, hay un test que lo demuestra.

Corre `pytest -q` antes de dar la tarea por terminada.
