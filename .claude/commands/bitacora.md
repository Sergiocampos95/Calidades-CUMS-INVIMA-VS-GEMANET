---
description: Cerrar la tarea — entrada en .ai/bitacora.jsonl y mensaje de commit con trailer
allowed-tools: Read, Write, Edit, Bash(git status*), Bash(git diff*), Bash(git log*)
---

Cierra el trabajo de esta sesion.

1. `git status` y `git diff --stat` para ver que cambio de verdad.
2. Agrega **una** linea a `.ai/bitacora.jsonl`, formato exacto de
   `.ai/README.md`, `agente` con el modo que uso ("Claude Code
   (implementador)", "Claude Code (ui-vite)", ...). Es append-only: no
   reescribas lineas anteriores. El `resumen` dice que cambio y **por que**;
   los archivos ya van en `archivos`. Si el cambio fue trivial, dimelo y no
   agregues nada.
3. Si hay un plan en `.ai/planes/` con todos sus pasos en `[x]`, ponle
   `Estado: terminado` y vacia `## Abierto`.
4. Propon el mensaje de commit con el trailer `Agente: Claude Code (<modo>)`.
   No hagas commit ni push.
