---
description: Tomar el siguiente paso del plan compartido asignado a Claude Code y ejecutarlo
argument-hint: [slug del plan]
allowed-tools: Read, Write, Edit, Grep, Glob, Bash, Task
---

Ejecuta el siguiente paso que me corresponde en el plan compartido. Plan: $ARGUMENTS

1. Busca el plan en `.ai/planes/` (`Estado: en curso`). Si `$ARGUMENTS` esta
   vacio y hay mas de un plan activo, preguntame cual.
2. Toma el primer paso `[ ]` cuyo dueno empiece por `claude/`.
   - Si el siguiente paso es de `copilot`, **para y dimelo** para que lo lance
     en VS Code. No lo hagas tu: el reparto existe por algo.
   - Si un paso `[~]` de Copilot toca los mismos archivos, **para y dimelo**.
3. Marca el paso `[~]` en el plan y **guarda antes de empezar**. Ese es el
   candado.
4. Delega en el agente que nombre el paso (`implementador`, `pruebas`,
   `ui-streamlit`, `dominio-invima`, `revisor`). Si hay varios pasos mios
   seguidos sin archivos compartidos, lanzalos en paralelo.
5. Verifica: `pytest` y `ruff check src/ tests/ ui_revision/`.
6. Marca `[x]`, anota en `## Decisiones` lo que el siguiente necesite saber, y
   en `## Abierto` lo que quedo pendiente.
7. Si te bloqueas, deja el paso en `[~]` con la razon en `## Abierto`. Nunca
   dejes un `[~]` mudo.

Cierra diciendome cual es el siguiente paso y de quien es.
