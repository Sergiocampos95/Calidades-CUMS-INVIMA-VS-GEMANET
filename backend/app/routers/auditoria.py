"""GET /auditoria -- el snapshot de `auditar_coherencia_gemanet` que deja
el worker. Mismo criterio que candidatos.py: 503 si todavia no hay
snapshot, nunca una lista vacia que se confunda con "todo esta bien"."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import carpeta_snapshots
from backend.app.paginacion import paginar, valores_distintos
from backend.app.schemas import LIMITE_PREVISUALIZACION_DEFECTO, PaginaTabla
from gemma_cum_loader.auditoria.coherencia_invima import filtrar_universo_auditable
from worker.almacen_snapshots import leer_tabla

router = APIRouter(prefix="/auditoria", tags=["auditoria"])


def _tabla_auditoria(carpeta: Path):
    """El snapshot de auditoria YA RECORTADO al universo auditable.

    El worker persiste el reporte COMPLETO (199.611 filas) a proposito: las
    dimensiones de auto-consistencia (`/auditoria/dimensiones`) tienen que
    poder ver basura en CUALQUIER fila -- si el recorte corriera antes, la fila
    con el problema ya no existiria para contarla (ver pipeline.py). Pero todo
    lo que esta seccion MUESTRA como auditoria es el universo auditable: CUMs
    activos, sin ancestrales/plantas ni codigo legado, con la unica excepcion
    de inactivo-aqui/vigente-en-INVIMA (decision del usuario, 2026-09-01 --
    ver `filtrar_universo_auditable`).

    Se aplica aca, en un solo lugar, y no en cada endpoint: antes solo
    `/resumen` filtraba, asi que la tabla de `GET /auditoria` y los valores de
    los filtros (`/valores`) seguian mostrando inactivos y codigos que no son
    CUM -- tres respuestas distintas al mismo criterio dentro de la misma
    pantalla.
    """
    df = leer_tabla("auditoria", carpeta)
    if df is None:
        raise HTTPException(
            status_code=503,
            detail="El worker todavia no genero ningun snapshot de auditoria. "
            "Consulta /salud para ver el estado del ultimo refresco.",
        )
    return filtrar_universo_auditable(df)


@router.get("", response_model=PaginaTabla)
def listar_auditoria(
    q: str | None = None,
    estado_coherencia: str | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    ordenar_por: str | None = None,
    orden_descendente: bool = False,
    filtros_json: str | None = None,
    carpeta: Path = Depends(carpeta_snapshots),
) -> PaginaTabla:
    """`estado_coherencia` acepta varios valores separados por coma
    (ej. "vencido_en_invima,encontrado_en_otro_estado_invima") -- pedido
    del usuario (2026-08-28): el filtro de un solo estado a la vez no
    alcanzaba, "mas bien seleccion multiple es lo mejor para el caso"."""
    df = _tabla_auditoria(carpeta)
    # "Priorizar lo que requiere accion" es una lista de TRABAJO: aca los
    # inactivos no van, ni siquiera los de la excepcion (inactivo aqui /
    # vigente en INVIMA) -- pedido del usuario (2026-09-01): "aqui tambien se
    # deben de eliminar los estados inactivos". Esa excepcion no se pierde:
    # tiene su propia calidad dedicada ("Inactivo en Gemma Net pero vigente en
    # INVIMA"), que es donde se revisa a proposito. Un inactivo no es una
    # accion pendiente: ya esta fuera de circulacion.
    if "ACTIVO" in df.columns:
        df = df[df["ACTIVO"].fillna("").astype(str).str.strip().str.upper().eq("SI")]
    if estado_coherencia and "ESTADO_COHERENCIA" in df.columns:
        valores = [v.strip() for v in estado_coherencia.split(",") if v.strip()]
        df = df[df["ESTADO_COHERENCIA"].isin(valores)]
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
    return valores_distintos(_tabla_auditoria(carpeta), columna)


@router.get("/resumen")
def resumen_auditoria(carpeta: Path = Depends(carpeta_snapshots)) -> dict[str, int]:
    """Conteo por `ESTADO_COHERENCIA` sobre el universo auditable.

    El recorte ya lo hace `_tabla_auditoria` (ver su docstring): sin el,
    "Priorizar lo que requiere accion" mostraba "Vencido en INVIMA: 50.039"
    en vez de los 371 realmente activos, contradiciendo directamente el
    pedido de "ignorar totalmente los inactivos". `filtrar_universo_auditable`
    es el MISMO criterio que aplica cada mascara de `calidades.py`, asi
    que estas cifras coinciden con la suma de las calidades."""
    df = _tabla_auditoria(carpeta)
    if "ESTADO_COHERENCIA" not in df.columns:
        return {}
    return df["ESTADO_COHERENCIA"].value_counts().to_dict()
