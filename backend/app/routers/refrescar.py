"""POST /refrescar -- solicita al worker que adelante su ciclo periodico.
GET /refrescar/progreso -- sondea el estado del refresco actual.

No hay concurrencia: si uno ya esta en curso, pedir otro devuelve 409.
El progreso se persiste en el DB de estado (worker/estado.py) para que
sobreviva a reinicios del backend.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.dependencies import ruta_estado
from worker.estado import (
    ESTADO_PASO_HECHO,
    hay_solicitud_pendiente,
    progreso_actual,
    solicitar_refresco_manual,
)

router = APIRouter(prefix="/refrescar", tags=["refresco"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def pedir_refresco(
    ruta_sqlite: Path = Depends(ruta_estado),
) -> dict[str, str]:
    """Pide al worker que ejecute un ciclo de refresco ahora, sin esperar su
    intervalo periodico. Devuelve 202 Accepted inmediatamente; el cliente
    sondea el progreso via GET /refrescar/progreso. El worker detecta la
    solicitud en su siguiente ciclo de vigilancia y la ejecuta."""
    
    # Si ya hay uno en curso (solicitud pendiente en el DB), rechazar.
    if hay_solicitud_pendiente(ruta_sqlite):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay un refresco en curso. Espera a que termine.",
        )
    
    # Escribe la solicitud en el DB para que el worker la detecte.
    solicitar_refresco_manual(ruta=ruta_sqlite)
    
    return {"solicitud": "aceptada"}


@router.get("/progreso")
def obtener_progreso_refresco(
    ruta_sqlite: Path = Depends(ruta_estado),
) -> dict[str, object]:
    """Sondea el estado actual del refresco (si hay uno en curso o si termino).
    Lee el DB de estado para obtener el progreso real."""
    pasos = progreso_actual(ruta=ruta_sqlite)
    
    # Si no hay pasos registrados, aun no se pidio ninguno.
    if not pasos:
        return {"en_curso": False, "pasos": []}
    
    # En curso si hay algun paso que no sea "hecho" o "error".
    en_curso = any(p.estado not in (ESTADO_PASO_HECHO, "error") for p in pasos)
    
    # Convierte PasoProgreso dataclass a dict para JSON.
    return {
        "en_curso": en_curso,
        "pasos": [
            {"nombre": p.nombre, "estado": p.estado, "detalle": p.detalle}
            for p in pasos
        ],
    }
