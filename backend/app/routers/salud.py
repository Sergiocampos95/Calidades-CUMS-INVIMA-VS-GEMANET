"""GET /salud -- la pieza que sostiene "degradacion explicita, nunca fallo
silencioso" para cualquier cliente (Streamlit hoy, el frontend nuevo
despues). Nunca dice "ok" cuando en realidad no hay snapshot o el ultimo
refresco fallo."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends

from backend.app.dependencies import carpeta_snapshots, ruta_estado
from backend.app.schemas import EstadoSalud
from worker.almacen_snapshots import snapshot_actual
from worker.estado import ESTADO_ERROR, ultimo_refresco

router = APIRouter(prefix="/salud", tags=["salud"])

# Si el snapshot vigente es mas viejo que esto, se marca "desactualizado" --
# 2x el intervalo del worker (50 min) da margen a UN refresco perdido antes
# de avisar, sin ser tan laxo que un worker caido tarde horas en notarse.
UMBRAL_DESACTUALIZADO_SEGUNDOS = 50 * 60 * 2

_FORMATO_MARCA = "%Y%m%dT%H%M%S%fZ"


@router.get("", response_model=EstadoSalud)
def obtener_salud(
    carpeta: Path = Depends(carpeta_snapshots),
    ruta_sqlite: Path = Depends(ruta_estado),
) -> EstadoSalud:
    refresco = ultimo_refresco(ruta_sqlite)
    snapshot = snapshot_actual(carpeta)

    if refresco is None or snapshot is None:
        return EstadoSalud(
            estado="sin_datos",
            ultima_actualizacion_utc=None,
            antiguedad_segundos=None,
            duracion_ultimo_refresco_segundos=None,
            detalle_error="El worker todavia no genero ningun snapshot.",
        )

    generado = datetime.strptime(snapshot.generado_utc, _FORMATO_MARCA).replace(tzinfo=UTC)
    antiguedad = (datetime.now(UTC) - generado).total_seconds()

    if refresco.estado == ESTADO_ERROR:
        estado = "error"
    elif antiguedad > UMBRAL_DESACTUALIZADO_SEGUNDOS:
        estado = "desactualizado"
    else:
        estado = "ok"

    return EstadoSalud(
        estado=estado,
        ultima_actualizacion_utc=snapshot.generado_utc,
        antiguedad_segundos=antiguedad,
        duracion_ultimo_refresco_segundos=refresco.duracion_segundos,
        detalle_error=refresco.detalle_error,
    )
