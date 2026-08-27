"""GET /cargue/* -- las 4 tablas que deja el worker cuando SI encuentra la
Estructura Cargue Medicamentos en `data/` (ver `worker/tareas.py::_tablas_cargue`).
Si no la encuentra, ninguna de las 4 existe en el snapshot -- degradacion
explicita, 503 con el motivo exacto, nunca "0 candidatos listos" que se
confunda con un resultado real."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import carpeta_snapshots
from backend.app.paginacion import paginar
from backend.app.schemas import LIMITE_PREVISUALIZACION_DEFECTO, PaginaTabla
from worker.almacen_snapshots import leer_tabla

router = APIRouter(prefix="/cargue", tags=["cargue"])

_MENSAJE_SIN_MALLA = (
    "El worker no encontro una Estructura Cargue Medicamentos en data/ en el ultimo "
    "refresco (o el snapshot todavia no corrio). Sin esa malla de referencia no se "
    "puede derivar POS, Modelo de Servicio, edad, copagos ni el resto de reglas de "
    "negocio -- no se inventa un valor por defecto. Consulta /salud para el estado "
    "del ultimo refresco."
)


def _tabla_cargue(nombre: str, carpeta: Path):
    df = leer_tabla(nombre, carpeta)
    if df is None:
        raise HTTPException(status_code=503, detail=_MENSAJE_SIN_MALLA)
    return df


@router.get("/estructura", response_model=PaginaTabla)
def listar_estructura(
    q: str | None = None,
    listo: bool | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    carpeta: Path = Depends(carpeta_snapshots),
) -> PaginaTabla:
    """El archivo de auditoria de estructura: TODOS los candidatos (listos y
    pendientes), con ESTADO/CAMPOS_CON_ERROR/COMO_VERIFICAR."""
    df = _tabla_cargue("cargue_estructura", carpeta)
    if listo is not None and "ESTADO" in df.columns:
        objetivo = "Listo para cargue" if listo else "Pendiente de clasificacion manual"
        df = df[df["ESTADO"] == objetivo]
    return paginar(df, q=q, limite=limite, offset=offset, todo=todo)


@router.get("/final", response_model=PaginaTabla)
def listar_cargue_final(
    q: str | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    carpeta: Path = Depends(carpeta_snapshots),
) -> PaginaTabla:
    """Solo lo listo para subir -- las 37 columnas exactas del Excel de
    cargue. Puede venir vacio (0 filas): no es un error, significa que
    ningun candidato de esta corrida tiene los 4 campos verificables
    resueltos con certeza todavia."""
    return paginar(_tabla_cargue("cargue_final", carpeta), q=q, limite=limite, offset=offset, todo=todo)


@router.get("/resumen")
def resumen_cargue(carpeta: Path = Depends(carpeta_snapshots)) -> dict[str, int]:
    df = _tabla_cargue("cargue_evaluados", carpeta)
    if "listo_para_cargue" not in df.columns:
        return {}
    listos = int(df["listo_para_cargue"].sum())
    return {"listos": listos, "pendientes": len(df) - listos}


@router.get("/advertencias")
def advertencias_malla(carpeta: Path = Depends(carpeta_snapshots)) -> list[dict[str, Any]]:
    """Campos de la malla de referencia que no se pudieron tomar con
    certeza (columna faltante, o menos del 100% de consistencia) -- ver
    `armado/reglas_negocio.py::derivar_reglas_negocio`."""
    df = _tabla_cargue("cargue_reglas_advertencias", carpeta)
    return df.to_dict(orient="records")
