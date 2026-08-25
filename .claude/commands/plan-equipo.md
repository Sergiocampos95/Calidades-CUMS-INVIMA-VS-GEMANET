---
description: Crear un plan compartido en .ai/planes/ y repartir los pasos entre Claude Code y Copilot
argument-hint: <descripcion de la tarea>
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(git status*), Bash(git log*), Bash(git diff*), Task
---

Escribe un **plan compartido** para esta tarea: $ARGUMENTS

No implementes nada en este turno. Solo el plan.

1. Lee `.ai/planes/README.md` (reparto y protocolo de marcas) y
   `.ai/planes/PLANTILLA.md` (formato).
2. Si la tarea toca mas de un modulo, cambia un contrato entre paquetes,
   agrega un dataset o una dimension de calidad, **lanza primero el agente
   `arquitecto`** y construye el plan sobre su respuesta. Si es mas chica,
   investiga tu mismo con `rastreador` o busqueda directa: los pasos tienen que
   nombrar archivos reales, no rutas supuestas.
3. Crea `.ai/planes/<slug>.md` desde la plantilla, `<slug>` en kebab-case.
4. Reparte cada paso segun la tabla de `.ai/planes/README.md`:
   - `claude/arquitecto`, `claude/implementador`, `claude/pruebas`,
     `claude/revisor`, `claude/dominio-invima`, `claude/ui-streamlit`
   - `copilot` para lo que gana estando en el editor con el usuario: iterar la
     UI con la app corriendo, docstrings, boilerplate, un caso mas en una
     parametrizacion existente, explicaciones.
5. **Dos pasos de duenos distintos no comparten archivo.** Es lo que permite
   correrlos en paralelo sin pisarse.
6. Marca explicitamente que pasos pueden ir en paralelo.
7. Deja todos los pasos en `[ ]`.

Cierra diciendome: cuantos pasos son mios, cuantos de Copilot, y cual es el
primer bloque que se puede lanzar en paralelo.
