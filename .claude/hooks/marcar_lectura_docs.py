"""Hook PostToolUse (matcher "Read"): registra que esta sesion leyo un
documento de `design/` -- es la mitad "marcar" del par con
`recordar_docs_negocio.py`, que avisa si se edito CODIGO de un modulo sensible
sin haber pasado por aca antes.

Estado por sesion (mismo patron que `.estado_pytest.json`): un JSON con
`{session_id: [claves de doc leidas]}`. Vive fuera de git.

Nunca bloquea ni falla el turno: si el estado no se puede escribir, el
proximo hook (`recordar_docs_negocio.py`) simplemente va a avisar de mas en
vez de no avisar -- el sentido seguro para un recordatorio es "avisa de mas",
no "se calla".
"""

from __future__ import annotations

import json
import pathlib
import sys

ESTADO = pathlib.Path(__file__).resolve().parent / ".estado_docs_leidas.json"

# Ruta relativa (desde la raiz del repo) -> clave corta para el estado.
# Un archivo se reconoce por SUFIJO de ruta, no por igualdad exacta, para que
# de igual si Claude Code manda la ruta absoluta o relativa.
DOCS_RECONOCIDOS = {
    "design/reglas_negocio.md": "reglas_negocio",
    "design/mapa_del_proyecto.md": "mapa_del_proyecto",
    "design/mecanismos/auditoria_coherencia.md": "mecanismo_auditoria",
}


def _leer_estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _guardar_estado(estado: dict) -> None:
    try:
        ESTADO.write_text(json.dumps(estado), encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    try:
        datos = json.load(sys.stdin)
    except Exception:
        return 0

    sesion = str(datos.get("session_id") or "sin-sesion")
    ruta = str((datos.get("tool_input") or {}).get("file_path") or "").replace("\\", "/")
    if not ruta:
        return 0

    clave = next((v for k, v in DOCS_RECONOCIDOS.items() if ruta.endswith(k)), None)
    if clave is None:
        return 0

    estado = _leer_estado()
    leidas = set(estado.get(sesion, []))
    if clave in leidas:
        return 0
    leidas.add(clave)
    estado[sesion] = sorted(leidas)
    _guardar_estado(estado)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
