"""GET /ium -- el snapshot de `auditar_coherencia_ium_gemanet` que deja el
worker (modulo IUM, separado del de CUM -- ver auditoria/coherencia_ium.py).

Nunca ejecuta el pipeline: si el worker todavia no genero la tabla (primera
corrida, o el paso se degrado ese dia -- ver worker/tareas.py::_paso_opcional
y armado/indice_ium.py sobre fuentes sin columna IUM), se responde 503
(degradacion explicita), nunca una lista vacia que se lea como "no hay
IUM con problemas"."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import carpeta_snapshots
from backend.app.paginacion import filtrar_tabla, paginar, valores_distintos
from backend.app.schemas import (
    LIMITE_PREVISUALIZACION_DEFECTO,
    CalidadResumen,
    PaginaTabla,
    SeccionCalidad,
)
from gemma_cum_loader.auditoria.calidades import (
    ETIQUETAS_CAMPO_DIFERENCIA,
    Calidad,
    calidad_admite_secciones,
    columnas_de_seccion,
    filtrar_por_seccion,
    secciones_de_diferencia,
)
from gemma_cum_loader.auditoria.calidades_ium import calidades_ium
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


# ---- "Casos por calidad" del modulo IUM -- ver auditoria/calidades_ium.py.
# Sin cache (a diferencia de /auditoria/calidades): a ~90 filas, recalcular
# en cada request no se acerca a los 666 ms medidos sobre 200.000 filas que
# justificaron la cache alla (ver backend/app/routers/calidades.py).


def _calidades_ium(carpeta: Path) -> list[Calidad]:
    return calidades_ium(_tabla_auditoria_ium(carpeta))


@router.get("/calidades", response_model=list[CalidadResumen])
def listar_calidades_ium(carpeta: Path = Depends(carpeta_snapshots)) -> list[CalidadResumen]:
    return [
        CalidadResumen(
            nombre=c.nombre,
            explica=c.explica,
            medicamentos=c.medicamentos,
            porcentaje_del_catalogo=c.porcentaje_del_catalogo,
            columnas=list(c.columnas),
            criterios=list(c.criterios),
            que_hacer=c.que_hacer,
        )
        for c in _calidades_ium(carpeta)
    ]


def _calidad_ium_o_404(nombre: str, carpeta: Path) -> Calidad:
    calidades = {c.nombre: c for c in _calidades_ium(carpeta)}
    calidad = calidades.get(nombre)
    if calidad is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{nombre}' no es una calidad IUM reconocida. Disponibles: {', '.join(calidades)}.",
        )
    return calidad


@router.get("/calidades/{nombre}/secciones", response_model=list[SeccionCalidad])
def listar_secciones_calidad_ium(
    nombre: str, carpeta: Path = Depends(carpeta_snapshots)
) -> list[SeccionCalidad]:
    calidad = _calidad_ium_o_404(nombre, carpeta)
    if not calidad_admite_secciones(nombre):
        return []
    return [
        SeccionCalidad(
            clave=s.clave,
            etiqueta=s.etiqueta,
            medicamentos=s.medicamentos,
            derivado_de=[ETIQUETAS_CAMPO_DIFERENCIA.get(c, c) for c in s.derivado_de],
            explica=s.explica,
        )
        for s in secciones_de_diferencia(calidad.df_tabla)
    ]


def tabla_calidad_ium_filtrada(
    nombre: str,
    carpeta: Path,
    *,
    seccion: str | None = None,
    q: str | None = None,
    filtros_json: str | None = None,
) -> pd.DataFrame:
    calidad = _calidad_ium_o_404(nombre, carpeta)
    aplica = seccion is not None and calidad_admite_secciones(nombre)
    tabla = filtrar_por_seccion(calidad.df_tabla, seccion) if aplica else calidad.df_tabla
    if aplica and seccion is not None:
        columnas = columnas_de_seccion(seccion)
        if columnas:
            tabla = tabla[[c for c in columnas if c in tabla.columns]]
    else:
        tabla = tabla[[c for c in calidad.columnas if c in tabla.columns]]
    return filtrar_tabla(tabla, q=q, filtros_json=filtros_json)


@router.get("/calidades/{nombre}", response_model=PaginaTabla)
def obtener_calidad_ium(
    nombre: str,
    q: str | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    ordenar_por: str | None = None,
    orden_descendente: bool = False,
    filtros_json: str | None = None,
    seccion: str | None = None,
    carpeta: Path = Depends(carpeta_snapshots),
) -> PaginaTabla:
    tabla = tabla_calidad_ium_filtrada(nombre, carpeta, seccion=seccion, q=q, filtros_json=filtros_json)
    return paginar(
        tabla,
        limite=limite,
        offset=offset,
        todo=todo,
        ordenar_por=ordenar_por,
        orden_descendente=orden_descendente,
    )


@router.get("/calidades/{nombre}/valores")
def valores_columna_calidad_ium(
    nombre: str,
    columna: str,
    seccion: str | None = None,
    carpeta: Path = Depends(carpeta_snapshots),
) -> list[dict[str, object]]:
    tabla = _calidad_ium_o_404(nombre, carpeta).df_tabla
    if seccion is not None and calidad_admite_secciones(nombre):
        tabla = filtrar_por_seccion(tabla, seccion)
    return valores_distintos(tabla, columna)
