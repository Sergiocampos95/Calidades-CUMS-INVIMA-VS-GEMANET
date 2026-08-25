"""Hook Stop: impide dar por terminado el turno con la suite en rojo.

Corre pytest cuando el modelo va a detenerse. Si falla, devuelve el fallo para
que lo arregle en vez de reportar trabajo terminado sobre algo roto -- es lo
que hace confiable el trabajo desatendido.

Dos protecciones deliberadas:

1. **No corre si no cambio codigo.** Guarda una huella (ruta+mtime+tamano) de
   los .py de src/ y tests/. Si la huella es identica a la de la ultima
   corrida verde, sale en silencio. Asi un turno de preguntas no paga los ~5s
   de la suite.
2. **Deja de bloquear tras MAX_BLOQUEOS seguidos.** Si el modelo no logra
   arreglar el rojo en 3 intentos, el hook se rinde y avisa al usuario en vez
   de insistir para siempre. Un hook Stop sin tope se convierte en un bucle.

El estado vive en un JSON local por sesion, fuera de git.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
PYTHON = RAIZ / ".venv" / "Scripts" / "python.exe"
ESTADO = pathlib.Path(__file__).resolve().parent / ".estado_pytest.json"

MAX_BLOQUEOS = 3
LINEAS_REPORTE = 40


def _emitir(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _huella() -> str:
    """Identifica el estado del codigo sin leerlo: ruta, mtime y tamano."""
    partes = []
    for carpeta in ("src", "tests"):
        base = RAIZ / carpeta
        if not base.is_dir():
            continue
        for archivo in sorted(base.rglob("*.py")):
            try:
                st = archivo.stat()
            except OSError:
                continue
            partes.append(f"{archivo.relative_to(RAIZ)}:{st.st_mtime_ns}:{st.st_size}")
    return "|".join(partes)


def _leer_estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _guardar_estado(estado: dict) -> None:
    try:
        ESTADO.write_text(json.dumps(estado), encoding="utf-8")
    except OSError:
        # El estado es una optimizacion; sin el, el hook solo corre de mas.
        pass


def main() -> int:
    try:
        datos = json.load(sys.stdin)
    except Exception:
        datos = {}

    sesion = str(datos.get("session_id") or "sin-sesion")
    estado = _leer_estado()
    huella_actual = _huella()

    # Nada cambio desde la ultima corrida verde: no hay nada que verificar.
    if estado.get("huella_verde") == huella_actual:
        return 0

    if not PYTHON.is_file():
        return 0

    try:
        proceso = subprocess.run(
            [str(PYTHON), "-m", "pytest", "-q", "--no-header", "-x"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            cwd=str(RAIZ),
            check=False,
        )
    except Exception:
        # Si pytest no puede correr, no es motivo para bloquear el turno.
        return 0

    if proceso.returncode == 0:
        estado["huella_verde"] = huella_actual
        estado.pop("bloqueos", None)
        _guardar_estado(estado)
        return 0

    salida = ((proceso.stdout or "") + (proceso.stderr or "")).strip()
    resumen = "\n".join(salida.splitlines()[-LINEAS_REPORTE:])

    bloqueos = int(estado.get("bloqueos", 0)) if estado.get("sesion") == sesion else 0

    if bloqueos >= MAX_BLOQUEOS:
        # Se rinde a proposito: insistir mas seria un bucle, y el usuario
        # necesita enterarse de que quedo rojo.
        estado["sesion"] = sesion
        estado["bloqueos"] = 0
        _guardar_estado(estado)
        _emitir(
            {
                "systemMessage": (
                    f"pytest sigue fallando tras {MAX_BLOQUEOS} intentos. "
                    "El hook deja de bloquear; la suite queda en rojo y "
                    "necesita revision manual."
                )
            }
        )
        return 0

    estado["sesion"] = sesion
    estado["bloqueos"] = bloqueos + 1
    _guardar_estado(estado)

    _emitir(
        {
            "decision": "block",
            "reason": (
                "La suite de pruebas quedo en rojo. No des el trabajo por "
                f"terminado: arregla el fallo y vuelve a correr pytest.\n\n{resumen}"
            ),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
