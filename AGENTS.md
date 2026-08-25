# AGENTS.md — puente de contexto entre herramientas

Este archivo existe para que GitHub Copilot CLI (que lee `AGENTS.md`
automaticamente) reciba las mismas reglas que Claude Code (que lee
`CLAUDE.md`). No dupliques reglas aqui: lee `CLAUDE.md` en la raiz del
proyecto primero, es la fuente unica de verdad.

Copilot Chat dentro de VS Code no lee este archivo por defecto: lee
`.github/copilot-instructions.md`, mas las reglas por carpeta de
`.github/instructions/*.instructions.md`. Los tres apuntan a `CLAUDE.md`.

## Reparto de tareas

**Claude Code decide y verifica; Copilot acelera dentro de una decision ya
tomada.** La tabla completa, los casos de frontera y el protocolo anticolision
estan en **`.ai/planes/README.md`**. Leelo antes de cualquier tarea que toque
mas de un archivo.

Lo minimo: cada tarea no trivial tiene un plan en `.ai/planes/<slug>.md` con un
dueno por paso y tres marcas — `[ ]` libre, `[~]` tomado ahora mismo, `[x]`
hecho. Antes de escribir, marca tu paso `[~]` y guarda: esa marca es el
candado. No se edita un archivo que otro tiene tomado.

Atajos:

| | Crear el plan | Tomar un paso | Cerrar |
|---|---|---|---|
| Claude Code | `/plan-equipo` | `/tomar-paso` | `/bitacora` |
| Copilot Chat | `/plan` | `/tomar-paso` | `/bitacora` |

## Bitacora compartida

Antes de terminar una tarea no trivial (varios archivos, una decision de
diseno, un fix de bug), agrega una linea a `.ai/bitacora.jsonl` con el agente,
la fecha, un resumen corto y los archivos tocados. Formato exacto en
`.ai/README.md`. Sirve para que el siguiente agente (Claude, Copilot CLI o
Copilot Chat) sepa que paso sin releer todo el historial de git.

La bitacora responde "que se hizo"; los planes de `.ai/planes/` responden "por
que se decidio asi". Son complementarios.

## Convencion de commits

Si vas a proponer un mensaje de commit, agrega un trailer con quien lo hizo:

```
Agente: Copilot CLI
Agente: Claude Code (implementador)
Agente: Copilot Chat (VS Code)
```

Asi `git log --grep="^Agente:"` filtra el historial por herramienta sin
depender de comparar estilos de codigo.
