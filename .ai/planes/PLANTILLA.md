# <titulo corto de la tarea>

- **Estado:** en curso
- **Creado:** AAAA-MM-DD por <Claude Code | Copilot Chat>
- **Objetivo:** una frase. Que tiene que ser cierto cuando esto termine.

## Contexto

Que sabemos ya, y que hallazgo o pedido origina la tarea. Enlaza los archivos
relevantes. Si hay una regla del proyecto en juego, nombrala.

## Pasos

Un paso, un dueno, los archivos que toca. `[ ]` libre · `[~]` tomado · `[x]` hecho.

- [ ] 1. (claude/arquitecto) — decidir <lo que haya que decidir>
- [ ] 2. (claude/implementador) `src/gemma_cum_loader/<...>.py` — <que hace>
- [ ] 3. (claude/pruebas) `tests/test_<...>.py` — <que cubre>
- [ ] 4. (copilot) `ui_revision/app_streamlit.py` — <que muestra>
- [ ] 5. (claude/revisor) — revision antes del commit

## Decisiones

Lo que se resolvio durante la ejecucion y el siguiente necesita saber.
Una linea por decision, con la razon.

- 

## Abierto

Preguntas sin responder, pasos bloqueados y por que. Vacio al cerrar el plan.

- 

## Verificacion

- [ ] `pytest` en verde
- [ ] `ruff check src/ tests/ ui_revision/` limpio
- [ ] Linea agregada a `.ai/bitacora.jsonl`
