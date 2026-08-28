"""GET /universo -- el universo COMPLETO de INVIMA clasificado (los
~101.183 registros del corte, no solo los "candidato"). Alimenta la
sub-vista "Detalle por registro": por que cada fila de INVIMA si o no
llego a ser candidato."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import carpeta_snapshots
from backend.app.paginacion import paginar, valores_distintos
from backend.app.schemas import LIMITE_PREVISUALIZACION_DEFECTO, PaginaTabla
from worker.almacen_snapshots import leer_tabla

router = APIRouter(prefix="/universo", tags=["universo"])


def _tabla_universo(carpeta: Path):
    df = leer_tabla("universo", carpeta)
    if df is None:
        raise HTTPException(
            status_code=503,
            detail="El worker todavia no genero ningun snapshot del universo INVIMA. "
            "Consulta /salud para ver el estado del ultimo refresco.",
        )
    return df


@router.get("", response_model=PaginaTabla)
def listar_universo(
    q: str | None = None,
    clasificacion: str | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    ordenar_por: str | None = None,
    orden_descendente: bool = False,
    filtros_json: str | None = None,
    carpeta: Path = Depends(carpeta_snapshots),
) -> PaginaTabla:
    df = _tabla_universo(carpeta)
    if clasificacion and "CLASIFICACION_CREACION" in df.columns:
        df = df[df["CLASIFICACION_CREACION"] == clasificacion]
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
    """Los valores distintos de una columna, con conteo -- alimenta el
    checkbox-list del filtro estilo Excel (pedido del usuario, 2026-08-28)."""
    return valores_distintos(_tabla_universo(carpeta), columna)


@router.get("/resumen")
def resumen_universo(carpeta: Path = Depends(carpeta_snapshots)) -> dict[str, int]:
    """Conteo por `CLASIFICACION_CREACION` -- las 5 tarjetas de "Detalle por
    registro" en la UI de Streamlit hoy. Las cinco suman el archivo INVIMA
    completo (cada fila recibe la etiqueta del PRIMER filtro que incumple)."""
    df = _tabla_universo(carpeta)
    if "CLASIFICACION_CREACION" not in df.columns:
        return {}
    return df["CLASIFICACION_CREACION"].value_counts().to_dict()
