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
from worker.almacen_snapshots import desfases_de_esquema, snapshot_actual
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
            detalle_error="La primera actualización no ha terminado todavía.",
        )

    generado = datetime.strptime(snapshot.generado_utc, _FORMATO_MARCA).replace(tzinfo=UTC)
    antiguedad = (datetime.now(UTC) - generado).total_seconds()

    # Colision de versiones: el snapshot en disco lo escribio una version
    # anterior del codigo y le faltan columnas que los calculos de hoy dan por
    # sentadas. Se reporta como "desactualizado" con el detalle, en vez de
    # dejar que las cifras salgan en cero y se lean como "no hay hallazgos"
    # (regla que pidio el usuario, 2026-09-02).
    desfases = desfases_de_esquema(carpeta)
    detalle_desfase = ""
    if desfases:
        detalle_desfase = (
            "Los datos vigentes los generó una versión anterior del programa y les faltan "
            "columnas: "
            + "; ".join(f"{tabla} -> {', '.join(cols)}" for tabla, cols in desfases.items())
            + ". Las cifras que dependan de ellas van a salir en cero. Ejecute una actualización."
        )

    # DOS problemas distintos, que no se pueden colapsar en uno:
    #
    #   a) El snapshot esta VIEJO (nadie corrio un refresco hace rato). Es
    #      cuestion de frescura y admite margen: el worker corre cada 50 min,
    #      asi que avisar antes solo genera ruido -- pedido del usuario
    #      (2026-09-02): "esto deberia salir despues de los 50 minutos".
    #
    #   b) Al snapshot le FALTAN COLUMNAS que el codigo de hoy usa para
    #      decidir. Eso no es frescura, es esquema roto, y no mejora por
    #      esperar: las cifras que dependan de esas columnas ya estan mal
    #      AHORA (degradan a un fallback o a cero). Un snapshot de 2 minutos
    #      al que le falta ESTADO_CUM_INVIMA reporta vigencia con el criterio
    #      equivocado, y callarlo por ser reciente es justo el fallo silencioso
    #      que la regla #2 prohibe.
    #
    # Se separan: (b) avisa siempre, (a) solo pasado el umbral.
    if refresco.estado == ESTADO_ERROR:
        estado = "error"
    elif desfases or antiguedad > UMBRAL_DESACTUALIZADO_SEGUNDOS:
        estado = "desactualizado"
    else:
        estado = "ok"

    return EstadoSalud(
        estado=estado,
        ultima_actualizacion_utc=snapshot.generado_utc,
        antiguedad_segundos=antiguedad,
        duracion_ultimo_refresco_segundos=refresco.duracion_segundos,
        detalle_error=" ".join(x for x in (refresco.detalle_error, detalle_desfase) if x),
    )
