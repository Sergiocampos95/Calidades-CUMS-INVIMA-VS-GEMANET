"""GET /candidatos -- el snapshot de `procesar_desde_catalogo_invima` que
deja el worker (candidatos a crear / ya en Gemma Net / cuarentena).

Nunca ejecuta el pipeline: si el worker todavia no genero un snapshot, se
responde 503 (degradacion explicita), no una lista vacia que un cliente
pueda confundir con "cero candidatos"."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import carpeta_snapshots
from backend.app.paginacion import paginar
from backend.app.schemas import LIMITE_PREVISUALIZACION_DEFECTO, PaginaTabla
from worker.almacen_snapshots import leer_tabla

router = APIRouter(prefix="/candidatos", tags=["candidatos"])


def _tabla_candidatos(carpeta: Path):
    df = leer_tabla("candidatos", carpeta)
    if df is None:
        raise HTTPException(
            status_code=503,
            detail="El worker todavia no genero ningun snapshot de candidatos. "
            "Consulta /salud para ver el estado del ultimo refresco.",
        )
    return df


@router.get("", response_model=PaginaTabla)
def listar_candidatos(
    q: str | None = None,
    accion: str | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    carpeta: Path = Depends(carpeta_snapshots),
) -> PaginaTabla:
    df = _tabla_candidatos(carpeta)
    if accion and "accion" in df.columns:
        df = df[df["accion"] == accion]
    return paginar(df, q=q, limite=limite, offset=offset, todo=todo)


@router.get("/resumen")
def resumen_candidatos(carpeta: Path = Depends(carpeta_snapshots)) -> dict[str, int]:
    """Conteo por `accion` -- lo mismo que muestran las 4 tarjetas de
    "Resumen de resolucion" en la UI de Streamlit hoy."""
    df = _tabla_candidatos(carpeta)
    if "accion" not in df.columns:
        return {}
    return df["accion"].value_counts().to_dict()


@router.get("/resumen-metodos")
def resumen_metodos(carpeta: Path = Depends(carpeta_snapshots)) -> dict[str, dict[str, int]]:
    """Como se resolvieron UNIDAD_DE_MEDIDA y MARCA_MEDICAMENTO contra el
    catalogo interno (exacto/alias/fuzzy/sin_resolver) -- alimenta la
    sub-vista "Como se resolvio". No es un dato de negocio: es el nivel de
    confianza del proceso de traduccion texto->codigo."""
    df = _tabla_candidatos(carpeta)
    resultado: dict[str, dict[str, int]] = {}
    for columna, clave in (("unidad_metodo", "unidad"), ("marca_metodo", "marca")):
        if columna in df.columns:
            resultado[clave] = df[columna].value_counts().to_dict()
    return resultado
