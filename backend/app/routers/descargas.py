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

import re
import unicodedata
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Response

from backend.app.dependencies import carpeta_snapshots
from backend.app.exportar import DELIMITADOR_EXPORTACION, bytes_desde_escritor
from backend.app.routers.cadena_calidad import tabla_eslabon
from backend.app.routers.calidades import tabla_calidad_filtrada
from gemma_cum_loader.exportacion.cargue import generar_excel_cargue
from gemma_cum_loader.exportacion.estructura_cargue import (
    generar_excel_estructura_cargue,
    nombre_periodo,
)
from gemma_cum_loader.pipeline import guardar_reporte
from worker.almacen_snapshots import leer_tabla

router = APIRouter(prefix="/descargas", tags=["descargas"])

MEDIA_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MEDIA_CSV = "text/csv"
MEDIA_TXT = "text/plain"

# Formatos que acepta la descarga de una calidad filtrada -- xlsx para abrir
# tal cual en Excel, csv/txt para pegar en otra herramienta (hoja de calculo
# externa, correo). Un formato fuera de esta lista es 400, no un xlsx por
# defecto silencioso: quien arma el link se merece saber que se equivoco.
_FORMATOS_CALIDAD = ("xlsx", "csv", "txt")


def _adjunto(nombre_archivo: str, contenido: bytes, media_type: str = MEDIA_XLSX) -> Response:
    return Response(
        content=contenido,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


_NO_ALFANUMERICO_RE = re.compile(r"[^A-Za-z0-9]+")


def _nombre_de_archivo_seguro(*partes: str) -> str:
    """Une varias partes (nombre de calidad, clave de seccion) en un nombre de
    archivo ASCII sin espacios ni tildes -- la cabecera Content-Disposition no
    tolera cualquier caracter, y el nombre de una calidad trae ambos ("Diferencia
    de estado o campos"). NFKD + descartar los caracteres combinantes quita la
    tilde (mismo truco que `normalizar_encabezado` en normaliza/texto.py);
    todo lo que no sea letra/digito se colapsa a un solo guion bajo."""
    piezas = []
    for parte in partes:
        if not parte:
            continue
        sin_tildes = unicodedata.normalize("NFKD", parte)
        sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
        piezas.append(_NO_ALFANUMERICO_RE.sub("_", sin_tildes).strip("_").lower())
    return "_".join(p for p in piezas if p)


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


@router.get("/calidad/{nombre}")
def descargar_calidad(
    nombre: str,
    formato: str = "xlsx",
    seccion: str | None = None,
    filtros_json: str | None = None,
    busqueda: str | None = None,
    carpeta: Path = Depends(carpeta_snapshots),
) -> Response:
    """Una calidad de la tabla de calidades CON EL FILTRO VIGENTE en pantalla
    (seccion + busqueda libre + filtro por columna) -- decision del usuario
    (plan tablas-por-seccion-y-exportacion.md, paso 4): si el filtro deja
    8.865 filas el archivo trae 8.865, aunque en pantalla solo se vean 1.000
    (nunca se pagina aca, a diferencia de GET /auditoria/calidades/{nombre}).

    Llama a `tabla_calidad_filtrada` (calidades.py) -- el MISMO filtrado que
    usa la tabla en pantalla, no una copia -- para que archivo y pantalla no
    puedan mostrar cosas distintas. Esa funcion ya lanza 404 si `nombre` no es
    una calidad reconocida y 503 si el worker todavia no dejo ningun
    snapshot."""
    if formato not in _FORMATOS_CALIDAD:
        raise HTTPException(
            status_code=400,
            detail=f"formato '{formato}' no reconocido. Usa uno de: {', '.join(_FORMATOS_CALIDAD)}.",
        )
    tabla = tabla_calidad_filtrada(nombre, carpeta, seccion=seccion, q=busqueda, filtros_json=filtros_json)
    return _serializar_tabla_plana(tabla, _nombre_de_archivo_seguro(nombre, seccion or ""), formato)


@router.get("/cadena/{nombre}")
def descargar_eslabon_cadena(
    nombre: str,
    formato: str = "xlsx",
    carpeta: Path = Depends(carpeta_snapshots),
) -> Response:
    """Una tabla de la cadena de calidad H1-H6 COMPLETA (sin paginar) en
    xlsx/csv/txt. Faltaba: la vista "Trazabilidad de calidad" era la unica
    tabla de auditoria sin botones de descarga. Mismo criterio que
    `descargar_calidad`: el archivo trae todas las filas del eslabon, la
    paginacion de pantalla no recorta un reporte. `tabla_eslabon` ya lanza
    404 si el nombre no es un eslabon y 503 si no hay snapshot."""
    if formato not in _FORMATOS_CALIDAD:
        raise HTTPException(
            status_code=400,
            detail=f"formato '{formato}' no reconocido. Usa uno de: {', '.join(_FORMATOS_CALIDAD)}.",
        )
    tabla = tabla_eslabon(nombre, carpeta)
    return _serializar_tabla_plana(tabla, _nombre_de_archivo_seguro("cadena", nombre), formato)


def _serializar_tabla_plana(tabla: pd.DataFrame, nombre_archivo_base: str, formato: str) -> Response:
    """Una tabla plana -> Response con Content-Disposition, en el formato
    pedido. Compartido por la descarga de una calidad y la de un eslabon de
    la cadena: las dos son tablas de una sola hoja, sin agrupar."""
    if formato == "xlsx":
        # NO `guardar_reporte`: agrupa en una hoja por valor de `columna_hoja`
        # ("accion"/"ESTADO_COHERENCIA"), una columna que la tabla recortada
        # puede no traer -- rompería con KeyError. Es una tabla plana, una
        # sola hoja, mismo patron que `generar_excel_cargue`.
        contenido = bytes_desde_escritor(lambda ruta: tabla.to_excel(ruta, index=False))
        return _adjunto(f"{nombre_archivo_base}.xlsx", contenido, MEDIA_XLSX)

    # utf-8-sig (BOM): sin el BOM, Excel en Windows abre el archivo
    # interpretando cada tilde mal -- este equipo abre todo en Excel (regla del
    # proyecto).
    contenido = tabla.to_csv(index=False, sep=DELIMITADOR_EXPORTACION).encode("utf-8-sig")
    media = MEDIA_CSV if formato == "csv" else MEDIA_TXT
    extension = "csv" if formato == "csv" else "txt"
    return _adjunto(f"{nombre_archivo_base}.{extension}", contenido, media)
