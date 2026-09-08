"""Hook PostToolUse (matcher "Write|Edit"): dos avisos independientes para que
`design/` no se quede atras del codigo, en vez de depender de que alguien se
acuerde de actualizarla.

1. **No leiste el mecanismo antes de tocarlo.** Si se edito un modulo
   sensible y esta sesion no leyo (via `marcar_lectura_docs.py`) ninguno de
   los documentos que lo explican, avisa una vez por sesion.

2. **El documento quedo mas viejo que el codigo.** Compara la fecha de
   modificacion del archivo fuente contra la de su `design/mecanismos/*.md`.
   Si el codigo es MAS NUEVO que el documento, avisa -- sin importar si esta
   sesion lo leyo o no, y CADA VEZ que se vuelva a editar, hasta que alguien
   guarde el documento de nuevo. Es la mitad que faltaba: leer antes de tocar
   no sirve de nada si nadie actualiza despues de tocar. La fecha de
   modificacion es una senal objetiva -- no depende de que el modelo se
   acuerde ni de un estado de sesion que se pierde al cerrar el chat.

Por que existe: el usuario pidio (2026-09-09) que "este modelo de desarrollo
se siga alimentando con el pasar del tiempo" y que "todo este alineado con
cambios" -- no solo un documento correcto hoy, sino uno que no se desactualice
mañana sin que nadie se entere. Ver tambien `feedback_memoria_apunta_no_duplica`
en la memoria del usuario: el mismo problema (una copia que no se entera
cuando el original cambia) resuelto del otro lado -- ahi era la memoria la
que podia quedar atras del codigo; aca es la documentacion.

Por que es un AVISO y no un bloqueo: no hay certeza sobre el esquema exacto
que usa esta version de Claude Code para bloquear una edicion desde un hook
PreToolUse, y un hook que intenta bloquear con un esquema equivocado puede
fallar de forma mas dañina que no bloquear nada. `hookSpecificOutput.
additionalContext` en PostToolUse SI esta probado en este mismo repo (es el
mecanismo de `ruff_post_edit.py`, ya visto funcionando).

Alcance deliberadamente angosto al empezar: solo los modulos que ya tienen un
archivo en `design/mecanismos/`. Avisar sobre CUALQUIER edicion seria ruido.
Extender MODULOS_SENSIBLES es el mismo gesto que agregar un archivo nuevo a
`design/mecanismos/` (ver la regla en `.claude/AGENTES.md`).
"""

from __future__ import annotations

import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
ESTADO = pathlib.Path(__file__).resolve().parent / ".estado_docs_leidas.json"

# prefijo de ruta (relativo a la raiz del repo) -> config del modulo.
#   claves_lectura: cualquiera de estas marcada en la sesion evita el aviso 1.
#   mensaje_lectura: texto del aviso 1.
#   doc_mecanismo: ruta (relativa a la raiz) contra la que se compara la
#     fecha de modificacion para el aviso 2. None si el modulo no tiene un
#     documento 1:1 todavia (ej. calidades.py vive repartido en varias
#     secciones de reglas_negocio.md -- comparar su mtime daria falsos
#     negativos constantes, se edita por razones que no tocan calidades.py).
MODULOS_SENSIBLES: dict[str, dict[str, object]] = {
    "src/gemma_cum_loader/auditoria/coherencia_invima.py": {
        "claves_lectura": ("reglas_negocio", "mecanismo_auditoria"),
        "mensaje_lectura": (
            "Se edito coherencia_invima.py sin evidencia de haber leido "
            "design/mecanismos/auditoria_coherencia.md ni design/reglas_negocio.md "
            "en esta sesion. Ese archivo tiene cascadas de .where()/.mask() donde "
            "el ORDEN de las asignaciones decide el resultado (ver el mecanismo "
            "documentado) -- confirma el cambio contra ese documento antes de "
            "seguir, o descarta este aviso si ya lo verificaste por otra via."
        ),
        "doc_mecanismo": "design/mecanismos/auditoria_coherencia.md",
        "mensaje_desactualizado": (
            "design/mecanismos/auditoria_coherencia.md quedo mas VIEJO que "
            "coherencia_invima.py (ultima modificacion del codigo posterior a "
            "la del documento). Si este cambio altero una formula, un orden de "
            "asignacion o un umbral que el documento describe, actualizalo "
            "antes de terminar el turno -- si el cambio no afecta el mecanismo "
            "documentado (ej. un comentario, un nombre de variable local), "
            "descarta este aviso."
        ),
    },
    "src/gemma_cum_loader/auditoria/calidades.py": {
        "claves_lectura": ("reglas_negocio", "mecanismo_auditoria"),
        "mensaje_lectura": (
            "Se edito calidades.py sin evidencia de haber leido "
            "design/reglas_negocio.md en esta sesion (secciones 3 y 8: que se "
            "ignora vs que se audita, y las 6 calidades). Confirma el cambio "
            "contra ese documento, o descarta este aviso si ya lo verificaste."
        ),
        "doc_mecanismo": None,
        "mensaje_desactualizado": None,
    },
}


def _leidas_en_sesion(sesion: str) -> set[str]:
    try:
        estado = json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return set(estado.get(sesion, []))


def _doc_desactualizado(archivo_editado: pathlib.Path, doc_relativo: str) -> bool:
    """True si `doc_relativo` existe y su fecha de modificacion es ANTERIOR
    a la del archivo editado -- el codigo cambio despues que el documento."""
    doc = RAIZ / doc_relativo
    if not doc.is_file() or not archivo_editado.is_file():
        return False
    try:
        return doc.stat().st_mtime < archivo_editado.stat().st_mtime
    except OSError:
        return False


def main() -> int:
    try:
        datos = json.load(sys.stdin)
    except Exception:
        return 0

    entrada = datos.get("tool_input") or {}
    respuesta = datos.get("tool_response") or {}
    ruta_cruda = str(respuesta.get("filePath") or entrada.get("file_path") or "")
    ruta = ruta_cruda.replace("\\", "/")
    if not ruta:
        return 0

    config = next(
        (cfg for sufijo, cfg in MODULOS_SENSIBLES.items() if ruta.endswith(sufijo)),
        None,
    )
    if config is None:
        return 0

    avisos: list[str] = []

    sesion = str(datos.get("session_id") or "sin-sesion")
    leidas = _leidas_en_sesion(sesion)
    if not (leidas & set(config["claves_lectura"])):
        avisos.append(str(config["mensaje_lectura"]))

    doc_mecanismo = config.get("doc_mecanismo")
    if doc_mecanismo:
        archivo = pathlib.Path(ruta_cruda) if pathlib.Path(ruta_cruda).is_absolute() else RAIZ / ruta
        if _doc_desactualizado(archivo, str(doc_mecanismo)):
            avisos.append(str(config["mensaje_desactualizado"]))

    if not avisos:
        return 0

    print(
        json.dumps(
            {
                "suppressOutput": True,
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": "\n\n".join(avisos),
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
