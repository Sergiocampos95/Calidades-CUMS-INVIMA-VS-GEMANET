"""Hook PostToolUse (matcher "Write|Edit"): si se edito un modulo sensible de
logica de negocio y esta sesion no leyo (via `marcar_lectura_docs.py`) ninguno
de los documentos que lo explican, avisa DESPUES de la edicion en vez de
quedarse callado.

Por que existe: el usuario pidio (2026-09-09) que Claude ya sepa que hacer en
cualquier sesion en vez de manejarse re-analizando todo, y que el uso de
`design/` deje de depender de que el modelo se acuerde de leerlo -- lo mismo
que motivo `feedback_memoria_apunta_no_duplica` en la memoria del usuario.
`CLAUDE.md` ya lo pide por escrito, pero pedirlo por escrito no es lo mismo
que hacerlo cumplir: nada impedia editar `auditoria/coherencia_invima.py` sin
haber leido nunca `design/mecanismos/auditoria_coherencia.md`, ni para "algo
muy puntual".

Por que es un AVISO y no un bloqueo: no hay certeza sobre el esquema exacto
que usa esta version de Claude Code para bloquear una edicion desde un hook
PreToolUse, y un hook que intenta bloquear con un esquema equivocado puede
fallar de forma mas dañina que no bloquear nada. `hookSpecificOutput.
additionalContext` en PostToolUse SI esta probado en este mismo repo (es el
mecanismo de `ruff_post_edit.py`, ya visto funcionando). Avisar DESPUES de la
edicion, en el mismo turno, sigue permitiendo corregir antes de continuar --
y es honesto sobre lo que un hook puede garantizar y lo que no.

Alcance deliberadamente angosto al empezar: solo los modulos que ya tienen un
archivo en `design/mecanismos/`. Bloquear (o avisar) sobre CUALQUIER edicion
seria ruido -- un typo en un docstring no necesita releer la cascada de
ESTADO_COHERENCIA. Extender la tabla MODULOS_SENSIBLES es el mismo gesto que
agregar un archivo nuevo a `design/mecanismos/` (ver la regla en
`.claude/AGENTES.md`): un mecanismo nuevo documentado es un modulo nuevo aca.
"""

from __future__ import annotations

import json
import pathlib
import sys

ESTADO = pathlib.Path(__file__).resolve().parent / ".estado_docs_leidas.json"

# prefijo de ruta (relativo a la raiz del repo) -> (claves de doc que
# CUALQUIERA de las cuales alcanza para no avisar, texto del recordatorio).
MODULOS_SENSIBLES: dict[str, tuple[tuple[str, ...], str]] = {
    "src/gemma_cum_loader/auditoria/coherencia_invima.py": (
        ("reglas_negocio", "mecanismo_auditoria"),
        (
            "Se edito coherencia_invima.py sin evidencia de haber leido "
            "design/mecanismos/auditoria_coherencia.md ni design/reglas_negocio.md "
            "en esta sesion. Ese archivo tiene cascadas de .where()/.mask() donde "
            "el ORDEN de las asignaciones decide el resultado (ver el mecanismo "
            "documentado) -- confirma el cambio contra ese documento antes de "
            "seguir, o descarta este aviso si ya lo verificaste por otra via."
        ),
    ),
    "src/gemma_cum_loader/auditoria/calidades.py": (
        ("reglas_negocio", "mecanismo_auditoria"),
        (
            "Se edito calidades.py sin evidencia de haber leido "
            "design/reglas_negocio.md en esta sesion (secciones 3 y 8: que se "
            "ignora vs que se audita, y las 6 calidades). Confirma el cambio "
            "contra ese documento, o descarta este aviso si ya lo verificaste."
        ),
    ),
}


def _leidas_en_sesion(sesion: str) -> set[str]:
    try:
        estado = json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return set(estado.get(sesion, []))


def main() -> int:
    try:
        datos = json.load(sys.stdin)
    except Exception:
        return 0

    entrada = datos.get("tool_input") or {}
    respuesta = datos.get("tool_response") or {}
    ruta = str(respuesta.get("filePath") or entrada.get("file_path") or "").replace("\\", "/")
    if not ruta:
        return 0

    coincidencia = next(
        ((claves, mensaje) for sufijo, (claves, mensaje) in MODULOS_SENSIBLES.items() if ruta.endswith(sufijo)),
        None,
    )
    if coincidencia is None:
        return 0
    claves_validas, mensaje = coincidencia

    sesion = str(datos.get("session_id") or "sin-sesion")
    leidas = _leidas_en_sesion(sesion)
    if leidas & set(claves_validas):
        return 0

    print(
        json.dumps(
            {
                "suppressOutput": True,
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": mensaje,
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
