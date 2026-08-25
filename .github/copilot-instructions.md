# Instrucciones para GitHub Copilot — gemma-cum-loader

Proyecto Python 3.12 que cruza el catalogo CUM/IUM de INVIMA con la plataforma
Gemma Net (Pijao Salud EPSI). Dos flujos que no se mezclan nunca:

| Pregunta | Flujo | Modulos |
|---|---|---|
| Que medicamentos de INVIMA **faltan** por cargar | Candidatos | `armado/`, `validacion/`, `exportacion/` |
| De lo **ya cargado**, que esta mal o desactualizado | Auditoria | `auditoria/coherencia_invima.py` |

La fuente unica de verdad es **`CLAUDE.md`** en la raiz, y `README.md` es la
documentacion funcional completa. Leelos antes de tocar logica de negocio.
Aqui solo esta lo minimo para no romper nada.

## Reglas duras — romper una es un bug, no un detalle de estilo

1. **Nada se adivina en silencio.** Lo ambiguo va a `cuarentena`.
2. **Nunca fusionar filas con `CODIGO_INTERNO` duplicado**: suelen ser
   medicamentos combinados y fusionarlas pierde un principio activo.
3. La cascada de `catalogos/resolver.py` (`exacto -> alias -> fuzzy ->
   sin_resolver`) es **100 % deterministica**: nunca llama a la IA ni a la red.
   Son 200.000 filas, tiene que ser exacta y rapida.
4. **La IA solo traduce**, no decide. `explicar_motivo()` se llama una vez por
   motivo distinto, jamas una vez por fila.
5. **`-999` es el centinela de "sin dato"** de Gemma Net, no un numero. Si un
   campo supera el 90 % en `-999` es un problema de proceso, no miles de
   hallazgos sueltos.
6. **`PORCENTAJE_CALIDAD` queda vacio, no en 0 %**, cuando no hay
   correspondencia con INVIMA: no hay nada que comparar y no es lo mismo.
7. **Degradacion explicita.** Si falta un archivo auxiliar se reporta; no se
   asume un valor por defecto.
8. **`data/` no se lee en tests, no se versiona y su contenido no se pega en un
   chat ni en un reporte.** Son datos reales de produccion de Pijao Salud. Se
   citan conteos y porcentajes, nunca filas.

## Convenciones de codigo

- Codigo fuente en espanol **sin tildes**: identificadores, docstrings y
  comentarios son ASCII (`codigos`, `deterministica`, `espanol`). Los `.md` de
  `README` y `design/` si llevan tildes.
- `from __future__ import annotations` al inicio de cada modulo.
- Dataclasses (a menudo `frozen=True`) para los valores de retorno.
- Type hints en todas las firmas publicas.
- **Los comentarios explican el porque, no el que.** Varios documentan
  hallazgos reales contra datos de produccion. Son la memoria del proyecto:
  no los borres ni los "limpies" de paso.
- Sin dependencias nuevas sin justificarlas: `pyproject.toml` es corto a
  proposito.

## Comandos

```bash
pytest                                    # suite completa
ruff check src/ tests/ ui_revision/       # lint
streamlit run ui_revision/app_streamlit.py
```

Entorno: venv en `.venv/`, Windows. El interprete es
`.venv\Scripts\python.exe`.

## Como trabajamos en equipo con Claude Code

Este repositorio lo trabajan dos herramientas sobre los mismos archivos. El
reparto y el protocolo anticolision estan en **`.ai/planes/README.md`**; leelo
antes de empezar cualquier tarea que toque mas de un archivo.

Resumen de una linea: **Claude Code decide y verifica; Copilot acelera dentro
de una decision ya tomada.**

- **Tuyo (Copilot):** lo que pasa en el editor abierto con el usuario mirando —
  completado inline, explicar codigo seleccionado, iterar la UI de Streamlit
  con la app corriendo al lado, docstrings, renombres, un test mas en una
  parametrizacion existente, mensajes de commit, leer errores de la terminal.
- **De Claude Code:** diseno de cambios que tocan varios modulos, reglas de
  negocio nuevas, la cascada del resolver, la auditoria de coherencia,
  refactors de contratos entre paquetes, y la verificacion final.
- **Regla anticolision:** un paso, un dueno, un archivo a la vez. Antes de
  editar un archivo, comprueba que el plan activo en `.ai/planes/` no lo tenga
  marcado `[~]` a nombre de la otra herramienta.
- Si te piden algo que cae del lado de Claude Code, **dilo y propon el plan**
  en vez de improvisar la implementacion.

## Antes de terminar una tarea no trivial

1. Corre `pytest` y `ruff check src/ tests/ ui_revision/`.
2. Marca `[x]` tu paso en el plan de `.ai/planes/`.
3. Agrega una linea a `.ai/bitacora.jsonl` (formato en `.ai/README.md`).
4. Si propones mensaje de commit, incluye el trailer
   `Agente: Copilot Chat (VS Code)`.
