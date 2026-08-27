"""GET /auditoria -- el snapshot de `auditar_coherencia_gemanet` que deja
el worker. Mismo criterio que candidatos.py: 503 si todavia no hay
snapshot, nunca una lista vacia que se confunda con "todo esta bien"."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import carpeta_snapshots
from backend.app.paginacion import paginar
from backend.app.schemas import LIMITE_PREVISUALIZACION_DEFECTO, PaginaTabla
from worker.almacen_snapshots import leer_tabla

router = APIRouter(prefix="/auditoria", tags=["auditoria"])


def _tabla_auditoria(carpeta: Path):
    df = leer_tabla("auditoria", carpeta)
    if df is None:
        raise HTTPException(
            status_code=503,
            detail="El worker todavia no genero ningun snapshot de auditoria. "
            "Consulta /salud para ver el estado del ultimo refresco.",
        )
    return df


@router.get("", response_model=PaginaTabla)
def listar_auditoria(
    q: str | None = None,
    estado_coherencia: str | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    carpeta: Path = Depends(carpeta_snapshots),
) -> PaginaTabla:
    df = _tabla_auditoria(carpeta)
    if estado_coherencia and "ESTADO_COHERENCIA" in df.columns:
        df = df[df["ESTADO_COHERENCIA"] == estado_coherencia]
    return paginar(df, q=q, limite=limite, offset=offset, todo=todo)


@router.get("/resumen")
def resumen_auditoria(carpeta: Path = Depends(carpeta_snapshots)) -> dict[str, int]:
    """Conteo por `ESTADO_COHERENCIA` -- el mismo desglose que hoy arma
    `_mostrar_tabla_de_calidades`/las tarjetas de alerta en Streamlit."""
    df = _tabla_auditoria(carpeta)
    if "ESTADO_COHERENCIA" not in df.columns:
        return {}
    return df["ESTADO_COHERENCIA"].value_counts().to_dict()
