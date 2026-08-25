---
mode: agent
description: Tomar el siguiente paso libre asignado a Copilot en el plan activo y ejecutarlo
---

Ejecuta el siguiente paso que me corresponde en el plan compartido.

1. Busca el plan activo en `.ai/planes/` (`Estado: en curso`). Si hay mas de
   uno, preguntame cual.
2. Elige el primer paso `[ ]` cuyo dueno sea `copilot`.
   - Si el paso que sigue esta a nombre de `claude/...`, **para y dimelo**: es
     de Claude Code, no lo hagas tu.
   - Si algun paso `[~]` de la otra herramienta toca los mismos archivos que
     el tuyo, **para y dimelo**. No se edita un archivo tomado.
3. Marca ese paso `[~] (copilot)` en el plan y **guarda el archivo antes de
   empezar**. Esa marca es el candado.
4. Ejecuta el paso. Respeta `.github/copilot-instructions.md` y las
   instrucciones con `applyTo` de la carpeta que estes tocando.
5. Verifica: `pytest -q` y `ruff check src/ tests/ ui_revision/`.
6. Marca el paso `[x]`, anota en `## Decisiones` lo que el siguiente necesite
   saber, y en `## Abierto` lo que quedo pendiente.
7. Si te bloqueaste: deja el paso en `[~]`, escribe la razon en `## Abierto` y
   avisame. Nunca dejes un `[~]` sin nota.

Al terminar, dime cual es el siguiente paso y de quien es.
