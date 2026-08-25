"""Hook PostToolUse: pasa ruff sobre el archivo Python recien editado.

Se escribe como script de Python y no como una linea de shell porque esta
maquina no tiene `jq` (el patron habitual de los hooks); el interprete del
.venv si esta garantizado. Lee el JSON del hook por stdin, saca la ruta del
archivo tocado y, si es .py, corre `ruff check --fix` sobre el.

Lo que ruff puede arreglar solo, lo arregla en silencio. Lo que queda se
devuelve al modelo en `additionalContext` para que lo corrija en el mismo
turno -- es lo que permite trabajar sin que una persona revise cada edicion.
Nunca bloquea: un fallo del hook no puede tumbar el trabajo del agente.

REGLAS: se fija `--select E9,F` a proposito, no se usan las de por defecto.
Medido el 2026-08-19 con ruff 0.16.3, el proyecto esta limpio en E9,F (errores
reales: sintaxis, nombres indefinidos, imports sin usar) pero arrastra 26
hallazgos de estilo con las reglas por defecto, 13 de ellos de orden de
imports. Con las reglas por defecto este hook reordenaria imports de cualquier
archivo que un agente toque de paso, metiendo ruido en el diff que nadie pidio,
y avisaria en cada edicion de cosas preexistentes. El subconjunto fijo hace que
solo suene cuando hay un defecto de verdad.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
RUFF = RAIZ / ".venv" / "Scripts" / "ruff.exe"


def _emitir(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def main() -> int:
    try:
        datos = json.load(sys.stdin)
    except Exception:
        return 0

    entrada = datos.get("tool_input") or {}
    respuesta = datos.get("tool_response") or {}
    ruta = respuesta.get("filePath") or entrada.get("file_path")

    if not ruta or not str(ruta).endswith(".py"):
        return 0

    archivo = pathlib.Path(str(ruta))
    if not archivo.is_file() or not RUFF.is_file():
        return 0

    try:
        proceso = subprocess.run(
            [str(RUFF), "check", "--select", "E9,F", "--fix", "--quiet", str(archivo)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            cwd=str(RAIZ),
            check=False,
        )
    except Exception:
        # El hook es una comodidad, no un guardian: si ruff no corre, el
        # trabajo del agente sigue igual.
        return 0

    pendiente = (proceso.stdout or "").strip()
    if not pendiente:
        return 0

    _emitir(
        {
            "suppressOutput": True,
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f"ruff dejo problemas sin corregir en {archivo.name} "
                    f"(los autocorregibles ya se aplicaron):\n{pendiente}"
                ),
            },
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
