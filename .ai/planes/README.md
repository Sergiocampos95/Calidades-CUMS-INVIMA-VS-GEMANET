# Planes — historia de las tareas grandes

Un plan es un archivo markdown por tarea. Sirve para no perder el hilo cuando
un cambio toca varios modulos y no cabe en una sola pasada.

## Que cambio (2026-09-08)

Esta carpeta nacio para coordinar a **Claude Code y Copilot** trabajando sobre
el mismo repo: quien hace que paso, en que orden, y que archivo esta tomado
ahora mismo. Ese reparto ya no existe -- **Claude Code es el unico agente que
trabaja este repositorio**.

Con eso se fueron `PLANTILLA.md` (llevaba un dueno por paso), los comandos
`/plan-equipo` y `/tomar-paso`, y el andamiaje de Copilot (`AGENTS.md`,
`.github/copilot-instructions.md`, `.github/instructions/`, `.github/prompts/`).
Todo esta en el historial de git si alguna vez hace falta.

## Los planes que hay aca son HISTORIA

Documentan tareas ya ejecutadas y por que se hicieron asi. **No se editan**: si
un plan viejo dice algo que hoy es falso, lo que vale es
`design/reglas_negocio.md`, que se mantiene al dia.

Varios mencionan a Copilot y el reparto de pasos. Es correcto: asi se trabajo
en ese momento.

## Como se trabaja ahora

**Una sesion, un problema.** Es la regla que reemplaza al plan compartido, y
nacio de una sesion que empezo en una tabla de priorizacion y termino tocando
delimitadores, fechas centinela, el worker, el boton de actualizar y la
definicion de CUM. Cada salto fue razonable por separado; el conjunto quedo
imposible de revisar y rompio cosas que ya estaban bien.

Antes de tocar logica de negocio, leer:

1. `CLAUDE.md` -- convenciones y flujo de trabajo.
2. `design/reglas_negocio.md` -- que significan los datos y por que. Incluye
   las reglas que ya se probaron y se REVIRTIERON, para no reproponerlas.
3. `design/mapa_del_proyecto.md` -- donde vive cada cosa.

Al cerrar: commit con el porque en el mensaje, y una entrada en
`.ai/bitacora.jsonl` (comando `/bitacora`).

## Cuando SI escribir un plan nuevo

Solo si la tarea no cabe en una sesion y hay que retomarla despues. En ese caso
el plan es una nota para uno mismo -- objetivo, pasos, que quedo verificado --
no un contrato entre herramientas. Si cabe en una sesion, no hace falta: el
mensaje de commit y la bitacora ya dejan la trazabilidad.
