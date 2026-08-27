"""GET /descargas/* -- los .xlsx que Streamlit ofrecia via `_descarga_diferida`
(9 puntos de descarga en `app_streamlit.py`). El backend no tenia ninguna
via de exportacion todavia -- este es el hueco de mayor prioridad detectado
en la revision de paridad: el Excel de cargue final es literalmente lo que
el equipo le entrega a Hugo para cargar en Gemma Net (ver memoria del
proyecto), asi que sin esto el frontend nuevo no reemplaza a Streamlit para
el trabajo real, por mas rapido que sea.

Cada endpoint reusa el generador real (`guardar_reporte`,
`generar_excel_cargue`, `generar_excel_estructura_cargue`) tal cual los usa
Streamlit -- no se reimplementa el formato del Excel aca. Igual que alli,
puede tardar (openpyxl con 200k filas mide varios segundos, ver el
diagnostico de rendimiento del proyecto) -- es aceptable porque solo corre
cuando alguien pide la descarga explicitamente, nunca en cada visita a la
pantalla.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Response

from backend.app.dependencies import carpeta_snapshots
from backend.app.exportar import bytes_desde_escritor
from gemma_cum_loader.exportacion.cargue import generar_excel_cargue
from gemma_cum_loader.exportacion.estructura_cargue import (
    generar_excel_estructura_cargue,
    nombre_periodo,
)
from gemma_cum_loader.pipeline import guardar_reporte
from worker.almacen_snapshots import leer_tabla

router = APIRouter(prefix="/descargas", tags=["descargas"])

MEDIA_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _adjunto(nombre_archivo: str, contenido: bytes) -> Response:
    return Response(
        content=contenido,
        media_type=MEDIA_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


def _tabla_o_503(nombre_tabla: str, carpeta: Path, mensaje: str) -> pd.DataFrame:
    df = leer_tabla(nombre_tabla, carpeta)
    if df is None:
        raise HTTPException(status_code=503, detail=mensaje)
    return df


@router.get("/candidatos")
def descargar_candidatos(carpeta: Path = Depends(carpeta_snapshots)) -> Response:
    """El reporte de cruce completo (candidatos + ya_existe + cuarentena),
    una hoja por `accion` -- mismo archivo que `_bytes_reporte_cruce` en
    Streamlit."""
    df = _tabla_o_503(
        "candidatos", carpeta, "El worker todavia no genero ningun snapshot de candidatos."
    )
    contenido = bytes_desde_escritor(lambda ruta: guardar_reporte(df, ruta))
    return _adjunto("reporte_cruce_invima.xlsx", contenido)


@router.get("/auditoria")
def descargar_auditoria(carpeta: Path = Depends(carpeta_snapshots)) -> Response:
    """La auditoria de coherencia completa, una hoja por `ESTADO_COHERENCIA`."""
    df = _tabla_o_503(
        "auditoria", carpeta, "El worker todavia no genero ningun snapshot de auditoria."
    )
    contenido = bytes_desde_escritor(
        lambda ruta: guardar_reporte(df, ruta, columna_hoja="ESTADO_COHERENCIA")
    )
    return _adjunto("auditoria_coherencia_invima.xlsx", contenido)


@router.get("/cargue-estructura")
def descargar_cargue_estructura(carpeta: Path = Depends(carpeta_snapshots)) -> Response:
    """El archivo de auditoria de estructura (TODOS los candidatos, listos
    y pendientes) -- reemplaza la copia manual "plantilla (2)" del SOP
    original."""
    df = _tabla_o_503(
        "cargue_estructura",
        carpeta,
        "Sin Estructura Cargue Medicamentos disponible -- ver /cargue/estructura.",
    )
    contenido = bytes_desde_escritor(lambda ruta: generar_excel_estructura_cargue(df, ruta))
    return _adjunto(f"{nombre_periodo()}.xlsx", contenido)


@router.get("/cargue-final")
def descargar_cargue_final(carpeta: Path = Depends(carpeta_snapshots)) -> Response:
    """Solo lo listo para subir -- el archivo que se entrega para cargar
    en Gemma Net."""
    df = _tabla_o_503(
        "cargue_final", carpeta, "Sin Estructura Cargue Medicamentos disponible -- ver /cargue/final."
    )
    contenido = bytes_desde_escritor(lambda ruta: generar_excel_cargue(df, ruta))
    return _adjunto("cargue_gemma_net.xlsx", contenido)
