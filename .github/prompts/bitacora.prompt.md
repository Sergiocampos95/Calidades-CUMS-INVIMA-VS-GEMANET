---
mode: agent
description: Cerrar la tarea — entrada en la bitacora compartida y mensaje de commit con trailer
---

Cierra el trabajo de esta sesion.

1. Mira que cambio de verdad: `git status` y `git diff --stat`.
2. Agrega **una** linea a `.ai/bitacora.jsonl` con el formato exacto de
   `.ai/README.md`:

   ```json
   {"fecha": "AAAA-MM-DDTHH:MM:SS", "agente": "Copilot Chat (VS Code)", "resumen": "una frase", "archivos": ["ruta/uno.py"], "commit": null}
   ```

   Es append-only: no reescribas lineas anteriores. El `resumen` dice **que
   cambio y por que**, no que archivos se tocaron (eso ya va en `archivos`).
   Si el cambio fue trivial (typo, formato), dimelo y no agregues nada.
3. Si hay un plan en `.ai/planes/` para este trabajo y todos sus pasos estan
   `[x]`, ponle `Estado: terminado`.
4. Propon el mensaje de commit, con el trailer:

   ```
   Agente: Copilot Chat (VS Code)
   ```

No hagas `git commit` ni `git push`. Solo propon el mensaje.
