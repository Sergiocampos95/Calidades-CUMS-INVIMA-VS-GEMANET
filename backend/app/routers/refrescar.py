"""POST /refrescar + GET /refrescar/progreso -- refresco manual bajo
demanda. Pedido del usuario (2026-08-27): "ya no hace falta un boton en el
que sea para volver a cargar todas las consultas... acompañado de una
pequeña lista mostrando uno a uno los procesos que se van haciendo y su
progreso, un ejemplo como cuando uno descarga varias cosas en Google".

Excepcion documentada y ACOTADA a la regla de `dependencies.py`: este
router NO ejecuta el pipeline pesado ni habla con Gemma Net/INVIMA -- solo
escribe una senal (un flag en `estado_worker.sqlite3`, via
`worker.estado.solicitar_refresco_manual`) que el WORKER, en su propio
proceso, revisa cada pocos segundos y usa para adelantar su corrida
periodica (ver `worker/refresco.py::_vigilar_solicitud_manual`). El
request HTTP vuelve de inmediato (un INSERT barato); quien pidio el
refresco sondea GET /refrescar/progreso para ver el avance real, paso a
paso, sin que el backend bloquee ni un segundo de mas."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from backend.app.dependencies import ruta_estado
from backend.app.schemas import PasoProgresoAPI, ProgresoRefresco
from worker.estado import (
    ESTADO_PASO_EN_CURSO,
    progreso_actual,
    solicitar_refresco_manual,
)

router = APIRouter(prefix="/refrescar", tags=["refresco manual"])


@router.post("", status_code=202)
def pedir_refresco(ruta: Path = Depends(ruta_estado)) -> dict[str, str]:
    solicitar_refresco_manual(ruta=ruta)
    return {
        "mensaje": "Solicitud registrada -- el worker la toma en los proximos segundos. "
        "Consulta GET /refrescar/progreso para ver el avance."
    }


@router.get("/progreso", response_model=ProgresoRefresco)
def progreso(ruta: Path = Depends(ruta_estado)) -> ProgresoRefresco:
    pasos = progreso_actual(ruta=ruta)
    en_curso = any(p.estado == ESTADO_PASO_EN_CURSO for p in pasos)
    return ProgresoRefresco(
        en_curso=en_curso,
        pasos=[
            PasoProgresoAPI(nombre=p.nombre, estado=p.estado, detalle=p.detalle) for p in pasos
        ],
    )
