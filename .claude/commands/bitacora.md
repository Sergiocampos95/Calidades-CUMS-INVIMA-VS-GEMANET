---
description: Cerrar la tarea — verificar alineacion de design/, entrada en .ai/bitacora.jsonl, mensaje de commit con trailer, recordar push
allowed-tools: Read, Write, Edit, Bash(git status*), Bash(git diff*), Bash(git log*)
---

Cierra el trabajo de esta sesion. El objetivo no es solo dejar un registro:
es que la sesion SIGUIENTE encuentre `design/` alineado con lo que esta
sesion cambio -- ver `feedback_memoria_apunta_no_duplica` y el pedido del
usuario (2026-09-09) de que "este modelo de desarrollo se siga alimentando
con el pasar del tiempo".

1. `git status` y `git diff --stat` para ver que cambio de verdad.

2. **Verificar alineacion de `design/`.** Si el diff toca un modulo que tiene
   documento en `design/mecanismos/` (hoy: `coherencia_invima.py` ->
   `mecanismos/auditoria_coherencia.md`; ver `MODULOS_SENSIBLES` en
   `.claude/hooks/recordar_docs_negocio.py` para la lista vigente) o una
   regla de `reglas_negocio.md`, decidir explicitamente uno de los dos:
   - El cambio alteró el mecanismo/la regla documentada -> **actualizar el
     documento ahora**, como parte de este cierre, no como una tarea aparte.
   - El cambio no lo afecta (es interno, un refactor sin cambio de
     comportamiento, un comentario) -> decirlo en el resumen de la bitacora
     ("no requirio actualizar reglas_negocio.md porque..."), para que quede
     registrada la decision, no solo el silencio.
   Si el diff no toca ningun modulo con documento, este paso no aplica --
   decilo y segui.

3. **Revisar la memoria del usuario si corresponde.** Solo si esta sesion
   estableció o corrigió un hecho de negocio que la memoria persistente ya
   describe (buscar por el tema, no releer toda la memoria) -- actualizarla
   seria el mismo gesto que el paso 2 pero para la memoria en vez de
   `design/`. Si no aplica, no hace falta decir nada.

4. Agrega **una** linea a `.ai/bitacora.jsonl`, formato exacto de
   `.ai/README.md`, `agente` con el modo que uso ("Claude Code
   (implementador)", "Claude Code (ui-vite)", ...). Es append-only: no
   reescribas lineas anteriores. El `resumen` dice que cambio y **por que**,
   Y si el paso 2 aplico, que se hizo con la documentacion; los archivos ya
   van en `archivos`. Si el cambio fue trivial, dimelo y no agregues nada.

5. Si hay un plan en `.ai/planes/` con todos sus pasos en `[x]`, ponle
   `Estado: terminado` y vacia `## Abierto`.

6. Propon el mensaje de commit con el trailer `Agente: Claude Code (<modo>)`.
   No hagas commit ni push.

7. Recorda cuantos commits locales quedan sin subir
   (`git log --oneline origin/<rama>..HEAD` si hay remoto configurado) y
   pregunta si se hace `git push`. "Un dia de trabajo sin push es un dia que
   vive unicamente en un disco" -- CLAUDE.md, seccion de flujo de trabajo.
