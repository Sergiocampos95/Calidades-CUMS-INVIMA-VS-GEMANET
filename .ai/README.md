# Bitacora de agentes

`bitacora.jsonl` es un registro append-only (una linea JSON por entrada) de
cambios no triviales hechos por cualquier agente (Claude Code, Copilot Chat,
Copilot CLI) en este proyecto. No reemplaza a git -- git tiene el diff exacto;
esto tiene el "quien" y el "por que" en una linea legible sin abrir el log.

## Cuando agregar una entrada

Al terminar una tarea que toco mas de un archivo, cambio una regla de
negocio, o corrigio un bug no trivial. No hace falta para cambios triviales
(typos, formato).

## Formato de cada linea

```json
{"fecha": "AAAA-MM-DDTHH:MM:SS", "agente": "nombre y modo", "resumen": "una frase", "archivos": ["ruta/uno.py"], "commit": "sha o null"}
```

- `agente`: por ejemplo `"Claude Code (implementador)"`, `"Copilot CLI"`,
  `"Copilot Chat (VS Code)"`.
- `commit`: el sha corto si ya se hizo commit, o `null` si todavia no.

## Como leerla rapido

```bash
python -c "import json;[print(d['fecha'],'-',d['agente'],'-',d['resumen']) for d in (json.loads(l) for l in open('.ai/bitacora.jsonl', encoding='utf-8'))]"
```
