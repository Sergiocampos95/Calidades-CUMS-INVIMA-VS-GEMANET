"""GET /auditoria -- el snapshot de `auditar_coherencia_gemanet` que deja
el worker. Mismo criterio que candidatos.py: 503 si todavia no hay
snapshot, nunca una lista vacia que se confunda con "todo esta bien"."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import carpeta_snapshots
from backend.app.paginacion import paginar, valores_distintos
from backend.app.schemas import LIMITE_PREVISUALIZACION_DEFECTO, PaginaTabla
from gemma_cum_loader.auditoria.coherencia_invima import (
    clasificar_prioridad_accion,
    filtrar_universo_auditable,
)
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
            detail="Todavía no hay datos de la auditoría: la primera actualización no ha "
            "terminado. Intente de nuevo en unos minutos; el indicador de la barra superior muestra el estado de la actualización.",
        )
    return filtrar_universo_auditable(df)


def _priorizables(carpeta: Path):
    """El universo auditable recortado a los ACTIVOS, con `PRIORIDAD_ACCION`.

    UN SOLO lugar aplica este recorte, y no cada endpoint por su cuenta, por
    un bug que reporto el usuario (2026-09-07): las tarjetas de "Priorizar lo
    que requiere accion" contaban sobre `_tabla_auditoria` (64.466 filas) y la
    tabla de abajo sobre los activos (55.572), asi que la tarjeta prometia
    "Vencido en INVIMA: 540" y al abrirla salian 360. La diferencia exacta era
    la excepcion de inactivo-aqui/vigente-en-INVIMA, que `_tabla_auditoria`
    conserva a proposito y esta vista no debe mostrar.

    Los inactivos no van aca ni siquiera con esa excepcion -- pedido del
    usuario (2026-09-01): "aqui tambien se deben de eliminar los estados
    inactivos". La excepcion no se pierde: tiene su propia calidad dedicada,
    que es donde se revisa a proposito. Un inactivo no es una accion
    pendiente: ya esta fuera de circulacion.
    """
    df = _tabla_auditoria(carpeta)
    if "ACTIVO" in df.columns:
        df = df[df["ACTIVO"].fillna("").astype(str).str.strip().str.upper().eq("SI")]
    # Se calcula aca y no solo en el snapshot para que un snapshot anterior a
    # la columna siga sirviendo la vista en vez de mostrarla vacia. Es la
    # MISMA funcion que usa `auditar_coherencia`, asi que no pueden discrepar.
    if "PRIORIDAD_ACCION" not in df.columns:
        df = df.assign(PRIORIDAD_ACCION=clasificar_prioridad_accion(df))
    return df


@router.get("", response_model=PaginaTabla)
def listar_auditoria(
    q: str | None = None,
    estado_coherencia: str | None = None,
    prioridad: str | None = None,
    columnas: str | None = None,
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
    df = _priorizables(carpeta)
    if estado_coherencia and "ESTADO_COHERENCIA" in df.columns:
        valores = [v.strip() for v in estado_coherencia.split(",") if v.strip()]
        df = df[df["ESTADO_COHERENCIA"].isin(valores)]
    if prioridad and "PRIORIDAD_ACCION" in df.columns:
        niveles = [v.strip() for v in prioridad.split(",") if v.strip()]
        df = df[df["PRIORIDAD_ACCION"].isin(niveles)]
    # El recorte va DESPUES de filtrar, nunca antes: la busqueda libre mira
    # TODAS las columnas a proposito (ver _buscar_texto_libre), asi que
    # recortar primero haria que buscar por un campo no visible dejara de
    # encontrar. Aca solo decide que se SERIALIZA.
    #
    # "Priorizar" muestra 6 columnas y el snapshot trae 93: la pagina de 1.000
    # filas pesaba 2,97 MB para pintar seis. Es opcional porque "Explorar
    # todos los hallazgos" usa el mismo endpoint y si quiere el ancho completo.
    if columnas:
        pedidas = [c.strip() for c in columnas.split(",") if c.strip() in df.columns]
        if pedidas:
            df = df[pedidas]
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
    checkbox-list del filtro estilo Excel (pedido del usuario, 2026-08-28).

    Sobre `_priorizables`, no sobre `_tabla_auditoria`: el filtro debe ofrecer
    los valores que la tabla PUEDE mostrar. Con el universo sin recortar
    aparecian opciones que al marcarlas no devolvian ninguna fila."""
    return valores_distintos(_priorizables(carpeta), columna)


@router.get("/resumen")
def resumen_auditoria(carpeta: Path = Depends(carpeta_snapshots)) -> dict[str, int]:
    """Conteo por `PRIORIDAD_ACCION` sobre EXACTAMENTE las filas que sirve
    `GET /auditoria` -- las tarjetas suman el total de la tabla, siempre.

    Antes contaba por `ESTADO_COHERENCIA` y sobre `_tabla_auditoria` (sin el
    recorte de activos), que es como una tarjeta podia decir 540 y la tabla
    que abria mostrar 360. Ahora ambas salen de `_priorizables`.

    Las cifras coinciden ademas con las tarjetas de "Entender la calidad del
    catalogo", que el usuario ya verifico: `clasificar_prioridad_accion` se
    apoya en el mismo par ESTADO_CUM_INVIMA + ESTADO_LISTADO_INVIMA que las
    mascaras de `calidades.py` (5.459 "no existe", 16.479 "en renovacion",
    31.210 "vigencia confirmada")."""
    df = _priorizables(carpeta)
    if "PRIORIDAD_ACCION" not in df.columns:
        return {}
    return df["PRIORIDAD_ACCION"].value_counts().to_dict()
