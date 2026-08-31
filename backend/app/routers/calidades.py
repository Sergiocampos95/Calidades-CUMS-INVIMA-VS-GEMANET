"""GET /auditoria/calidades, /auditoria/dimensiones, /auditoria/naturaleza --
la "tabla de calidades" que pide el negocio (ver `auditoria/calidades.py`),
las 6 dimensiones de calidad que todavia no tenian endpoint propio, y "que
hacer con cada hallazgo" (`ACCION_POR_NATURALEZA`). Las tres se calculan
sobre el snapshot de auditoria que ya dejo el worker: son mascaras
booleanas vectorizadas sobre un DataFrame ya materializado, NO el pipeline
pesado -- mismo criterio ya documentado en cadena_calidad.py."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import carpeta_snapshots
from backend.app.paginacion import paginar, valores_distintos
from backend.app.schemas import (
    LIMITE_PREVISUALIZACION_DEFECTO,
    CalidadResumen,
    DimensionesCalidad,
    HallazgoNaturaleza,
    PaginaTabla,
)

# Force fresh import to avoid cached bytecode
if 'gemma_cum_loader.auditoria.calidades' in sys.modules:
    del sys.modules['gemma_cum_loader.auditoria.calidades']
if 'gemma_cum_loader.auditoria.coherencia_invima' in sys.modules:
    del sys.modules['gemma_cum_loader.auditoria.coherencia_invima']

from gemma_cum_loader.auditoria.calidades import Calidad, calidades_auditoria
from gemma_cum_loader.auditoria.coherencia_invima import ACCION_POR_NATURALEZA
from worker.almacen_snapshots import leer_tabla

router = APIRouter(prefix="/auditoria", tags=["calidad del catalogo"])

_MENSAJE_SIN_AUDITORIA = (
    "El worker todavia no genero ningun snapshot de auditoria. "
    "Consulta /salud para ver el estado del ultimo refresco."
)

# CACHE DESHABILITADO TEMPORALMENTE PARA DEBUG
# Mismo criterio de cache que cadena_calidad.py: una entrada por carpeta,
# se reemplaza sola al llegar un snapshot nuevo -- nunca crece sin limite.
_CACHE_CALIDADES: dict[str, tuple[str, list[Calidad]]] = {}


def _tabla_auditoria(carpeta: Path):
    df = leer_tabla("auditoria", carpeta)
    if df is None:
        raise HTTPException(status_code=503, detail=_MENSAJE_SIN_AUDITORIA)
    return df


def _calidades(carpeta: Path) -> list[Calidad]:
    auditoria = _tabla_auditoria(carpeta)
    # CACHE DESHABILITADO - Siempre recalcula para debug
    calidades = calidades_auditoria(auditoria)
    return calidades


@router.get("/calidades-debug")
def debug_calidades(carpeta: Path = Depends(carpeta_snapshots)) -> dict:
    """Endpoint de debug - devuelve exactamente lo que calcula _calidades()"""
    cals = _calidades(carpeta)
    return {
        "count": len(cals),
        "total_medicamentos": sum(c.medicamentos for c in cals),
        "calidades": [{"nombre": c.nombre, "medicamentos": c.medicamentos} for c in cals]
    }

@router.get("/calidades", response_model=list[CalidadResumen])
def listar_calidades(carpeta: Path = Depends(carpeta_snapshots)) -> list[CalidadResumen]:
    cals = _calidades(carpeta)
    print(f"DEBUG: _calidades devolvió {len(cals)} calidades")
    total_meds = sum(c.medicamentos for c in cals)
    print(f"DEBUG: total medicamentos en calidades: {total_meds}")
    for c in cals:
        print(f"  {c.nombre}: {c.medicamentos}")
    resultado = [
        CalidadResumen(
            nombre=c.nombre,
            explica=c.explica,
            medicamentos=c.medicamentos,
            porcentaje_del_catalogo=c.porcentaje_del_catalogo,
            columnas=list(c.columnas),
        )
        for c in cals
    ]
    print(f"DEBUG: devolviendo {len(resultado)} CalidadResumen con {total_meds} medicamentos total")
    return resultado


def _calidad_o_404(nombre: str, carpeta: Path) -> Calidad:
    calidades = {c.nombre: c for c in _calidades(carpeta)}
    calidad = calidades.get(nombre)
    if calidad is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{nombre}' no es una calidad reconocida. Calidades disponibles: "
            f"{', '.join(calidades)}.",
        )
    return calidad


@router.get("/calidades/{nombre}", response_model=PaginaTabla)
def obtener_calidad(
    nombre: str,
    q: str | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    ordenar_por: str | None = None,
    orden_descendente: bool = False,
    filtros_json: str | None = None,
    carpeta: Path = Depends(carpeta_snapshots),
) -> PaginaTabla:
    calidad = _calidad_o_404(nombre, carpeta)
    return paginar(
        calidad.df_tabla,
        q=q,
        limite=limite,
        offset=offset,
        todo=todo,
        ordenar_por=ordenar_por,
        orden_descendente=orden_descendente,
        filtros_json=filtros_json,
    )


@router.get("/calidades/{nombre}/valores")
def valores_columna_calidad(
    nombre: str, columna: str, carpeta: Path = Depends(carpeta_snapshots)
) -> list[dict[str, object]]:
    return valores_distintos(_calidad_o_404(nombre, carpeta).df_tabla, columna)


@router.get("/dimensiones", response_model=DimensionesCalidad)
def dimensiones_calidad(carpeta: Path = Depends(carpeta_snapshots)) -> DimensionesCalidad:
    auditoria = _tabla_auditoria(carpeta)
    completitud = (
        auditoria["PORCENTAJE_COMPLETITUD_REPORTE"].mean()
        if "PORCENTAJE_COMPLETITUD_REPORTE" in auditoria.columns
        else None
    )

    def _contar_no_vacio(columna: str) -> int:
        if columna not in auditoria.columns:
            return 0
        return int((auditoria[columna] != "").sum())

    return DimensionesCalidad(
        n_total_auditado=len(auditoria),
        completitud_promedio=None if completitud is None or pd.isna(completitud) else round(float(completitud), 1),
        duplicados=int(auditoria["CODIGO_DUPLICADO_EN_REPORTE"].sum()) if "CODIGO_DUPLICADO_EN_REPORTE" in auditoria.columns else 0,
        fuera_de_dominio=_contar_no_vacio("VALORES_FUERA_DE_DOMINIO"),
        inconsistencia_numerica=_contar_no_vacio("INCONSISTENCIA_NUMERICA"),
        formato_invalido=_contar_no_vacio("FORMATO_CODIGO_INTERNO_INVALIDO"),
        integridad_referencial=_contar_no_vacio("INTEGRIDAD_REFERENCIAL_CATALOGO"),
    )


@router.get("/naturaleza", response_model=list[HallazgoNaturaleza])
def naturaleza_hallazgos(carpeta: Path = Depends(carpeta_snapshots)) -> list[HallazgoNaturaleza]:
    """"Que hacer con cada hallazgo" -- una fila por NATURALEZA_HALLAZGO con
    conteo > 0, en el mismo orden de prioridad de atencion que
    ACCION_POR_NATURALEZA (lo que pone en riesgo una autorizacion primero,
    lo residual de la migracion al final)."""
    auditoria = _tabla_auditoria(carpeta)
    if "NATURALEZA_HALLAZGO" not in auditoria.columns:
        return []
    conteo = auditoria["NATURALEZA_HALLAZGO"].value_counts()
    return [
        HallazgoNaturaleza(naturaleza=etiqueta, medicamentos=int(conteo[etiqueta]), que_hacer=que_hacer)
        for etiqueta, que_hacer in ACCION_POR_NATURALEZA.items()
        if etiqueta in conteo.index and conteo[etiqueta] > 0
    ]
