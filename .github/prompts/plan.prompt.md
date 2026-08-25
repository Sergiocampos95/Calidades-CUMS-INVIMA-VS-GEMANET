---
mode: agent
description: Crear un plan compartido en .ai/planes/ y repartir los pasos entre Copilot y Claude Code
---

Vas a escribir un **plan compartido** para esta tarea: ${input:tarea:Que hay que hacer}

No implementes nada todavia. Solo el plan.

Pasos:

1. Lee `.ai/planes/README.md` (el reparto y el protocolo de marcas) y
   `.ai/planes/PLANTILLA.md` (el formato).
2. Investiga lo minimo para que el plan sea concreto: que archivos se tocan de
   verdad. Usa busqueda en el repositorio, no supongas rutas.
3. Crea `.ai/planes/<slug>.md` a partir de la plantilla, con `<slug>` en
   kebab-case derivado de la tarea.
4. Reparte cada paso segun la tabla de `.ai/planes/README.md`:
   - decisiones de diseno, reglas de negocio, `src/`, la suite de pruebas y la
     revision final -> **Claude Code** (nombra el agente: `arquitecto`,
     `implementador`, `pruebas`, `revisor`, `dominio-invima`).
   - UI de Streamlit, docstrings, boilerplate, casos extra en tests
     existentes, explicaciones -> **copilot**.
5. Cada paso nombra los archivos concretos que toca. Dos pasos de duenos
   distintos **no pueden compartir archivo**.
6. Ordena los pasos de forma que lo que se pueda hacer en paralelo quede
   marcado como tal.
7. Deja todos los pasos en `[ ]`.

Al final, muestrame el plan y dime cuales pasos puedo lanzar ya en paralelo.
Si algo del plan depende de una decision que todavia no esta tomada, ponla
como primer paso a nombre de `claude/arquitecto` en vez de resolverla tu.
