"""GET /auditoria/cadena -- la cadena de calidad H1-H6 (pedido de Sergio,
ver `auditoria/cadena_calidad.py`). Se calcula sobre el snapshot de
auditoria que ya dejo el worker: son operaciones vectorizadas (interseccion
de mascaras booleanas) sobre un DataFrame ya materializado, NO el pipeline
pesado -- por eso es aceptable calcularla dentro de un request, a
diferencia de `auditar_coherencia_gemanet` (esa si es exclusiva del
worker, ver `dependencies.py`)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import carpeta_snapshots
from backend.app.paginacion import paginar, valores_distintos
from backend.app.schemas import (
    LIMITE_PREVISUALIZACION_DEFECTO,
    EslabonResumen,
    PaginaTabla,
)
from gemma_cum_loader.auditoria.cadena_calidad import (
    EslabonCalidad,
    construir_cadena_calidad,
)
from worker.almacen_snapshots import leer_tabla, snapshot_actual

router = APIRouter(prefix="/auditoria/cadena", tags=["cadena de calidad"])

# construir_cadena_calidad() es vectorizada (ver docstring del router), pero
# sobre 200.000 filas sigue costando algo -- y tanto listar_cadena() como
# obtener_eslabon() la llamaban de nuevo en CADA click de H1..H6 y en cada
# pagina/filtro dentro de una tabla del eslabon. Mismo criterio de "una
# entrada, se reemplaza sola al llegar snapshot nuevo" que el cache de
# leer_tabla en almacen_snapshots.py -- no crece sin limite.
_CACHE_CADENA: dict[str, tuple[str, list[EslabonCalidad]]] = {}


def _cadena(carpeta: Path) -> list[EslabonCalidad]:
    auditoria = leer_tabla("auditoria", carpeta)
    if auditoria is None:
        raise HTTPException(
            status_code=503,
            detail="Todavía no hay datos de la auditoría: la primera actualización no ha "
            "terminado. Intente de nuevo en unos minutos; el indicador de la barra superior muestra el estado de la actualización.",
        )
    actual = snapshot_actual(carpeta)
    assert actual is not None  # leer_tabla ya encontro datos -> tiene que haber snapshot

    clave = str(carpeta)
    en_cache = _CACHE_CADENA.get(clave)
    if en_cache is not None and en_cache[0] == actual.nombre:
        return en_cache[1]
    cadena = construir_cadena_calidad(auditoria)
    _CACHE_CADENA[clave] = (actual.nombre, cadena)
    return cadena


@router.get("", response_model=list[EslabonResumen])
def listar_cadena(carpeta: Path = Depends(carpeta_snapshots)) -> list[EslabonResumen]:
    return [
        EslabonResumen(
            nombre=e.nombre,
            campos_acumulados=list(e.campos_acumulados),
            universo=e.universo,
            porcentaje_total=e.porcentaje_total,
            columnas_trio=list(e.columnas_trio),
            columna_estado=e.columna_estado,
        )
        for e in _cadena(carpeta)
    ]


def _eslabon_o_404(nombre: str, carpeta: Path) -> EslabonCalidad:
    eslabones = {e.nombre: e for e in _cadena(carpeta)}
    eslabon = eslabones.get(nombre)
    if eslabon is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{nombre}' no es una tabla de la cadena. Tablas disponibles: "
            f"{', '.join(eslabones)}.",
        )
    return eslabon


@router.get("/{nombre}", response_model=PaginaTabla)
def obtener_eslabon(
    nombre: str,
    q: str | None = None,
    solo_pasa: bool | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    ordenar_por: str | None = None,
    orden_descendente: bool = False,
    filtros_json: str | None = None,
    carpeta: Path = Depends(carpeta_snapshots),
) -> PaginaTabla:
    eslabon = _eslabon_o_404(nombre, carpeta)
    df = eslabon.df_tabla
    if solo_pasa is not None:
        df = df[df[eslabon.columna_estado] == ("pasa" if solo_pasa else "no_pasa")]
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


@router.get("/{nombre}/valores")
def valores_columna_eslabon(
    nombre: str, columna: str, carpeta: Path = Depends(carpeta_snapshots)
) -> list[dict[str, object]]:
    return valores_distintos(_eslabon_o_404(nombre, carpeta).df_tabla, columna)


def tabla_eslabon(nombre: str, carpeta: Path):
    """La tabla COMPLETA de un eslabon H1-H6, sin paginar ni filtrar --
    para la descarga (mismo criterio que `tabla_calidad_filtrada` en
    calidades.py: la paginacion es comodidad de la vista, un reporte no se
    recorta). Lanza 404/503 igual que el resto del router."""
    return _eslabon_o_404(nombre, carpeta).df_tabla
