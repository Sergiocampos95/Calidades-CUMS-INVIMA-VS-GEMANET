"""GET /ium -- el snapshot de `auditar_coherencia_ium_gemanet` que deja el
worker (modulo IUM, separado del de CUM -- ver auditoria/coherencia_ium.py).

Nunca ejecuta el pipeline: si el worker todavia no genero la tabla (primera
corrida, o el paso se degrado ese dia -- ver worker/tareas.py::_paso_opcional
y armado/indice_ium.py sobre fuentes sin columna IUM), se responde 503
(degradacion explicita), nunca una lista vacia que se lea como "no hay
IUM con problemas"."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import carpeta_snapshots
from backend.app.paginacion import paginar, valores_distintos
from backend.app.schemas import LIMITE_PREVISUALIZACION_DEFECTO, PaginaTabla
from worker.almacen_snapshots import leer_tabla

router = APIRouter(prefix="/ium", tags=["ium"])


def _tabla_auditoria_ium(carpeta: Path):
    df = leer_tabla("auditoria_ium", carpeta)
    if df is None:
        raise HTTPException(
            status_code=503,
            detail="Todavía no hay datos de IUM: la primera actualización no ha terminado, "
            "o la fuente de INVIMA de ese día no traía la columna IUM. Intente de nuevo "
            "en unos minutos; el indicador de la barra superior muestra el estado de la "
            "actualización.",
        )
    return df


@router.get("", response_model=PaginaTabla)
def listar_ium(
    q: str | None = None,
    estado_ium: str | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    ordenar_por: str | None = None,
    orden_descendente: bool = False,
    filtros_json: str | None = None,
    carpeta: Path = Depends(carpeta_snapshots),
) -> PaginaTabla:
    df = _tabla_auditoria_ium(carpeta)
    if estado_ium and "ESTADO_IUM" in df.columns:
        df = df[df["ESTADO_IUM"] == estado_ium]
    return paginar(
        df,
        q=q,
        limite=limite,
        offset=offset,
        todo=todo,
        ordenar_por=ordenar_por,
        orden_descendente=orden_descendente,
        filtros_json=filtros_json,
    )


@router.get("/valores")
def valores_columna(columna: str, carpeta: Path = Depends(carpeta_snapshots)) -> list[dict[str, object]]:
    return valores_distintos(_tabla_auditoria_ium(carpeta), columna)


@router.get("/resumen")
def resumen_ium(carpeta: Path = Depends(carpeta_snapshots)) -> dict[str, int]:
    """Conteo por ESTADO_IUM -- la tarjeta corta de "Bandeja de calidades IUM"."""
    df = _tabla_auditoria_ium(carpeta)
    if "ESTADO_IUM" not in df.columns:
        return {}
    return df["ESTADO_IUM"].value_counts().to_dict()
