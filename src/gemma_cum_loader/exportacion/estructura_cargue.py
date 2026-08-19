"""Genera el archivo de auditoria "Estructura de Cargue" -- un Excel aparte
del cargue final que muestra TODOS los candidatos de la corrida (listos y
pendientes de clasificacion), con CODIGO_INTERNO y DESCRIPCION ya
concatenados (fases 4 y 5 del SOP) y una columna de estado + como verificar
cada pendiente.

Reemplaza el rol que la copia manual de "plantilla" a "plantilla (2)"
cumplia en el SOP original: alli el operador duplicaba la hoja original,
trabajaba los cruces y homologaciones a mano sobre la copia, y dejaba
"plantilla" intacta como respaldo. Esa copia de trabajo (con nombre tipo
"Vigente_MMYYYY") es exactamente lo que este modulo genera automaticamente
en cada corrida -- el usuario ya no arma esta tabla a mano, pero sigue
teniendo el mismo artefacto auditable para revisar contra los archivos
oficiales de Pijao Salud si el programa reporta un error.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from gemma_cum_loader.armado.reglas_negocio import ReglasNegocio
from gemma_cum_loader.exportacion.cargue import (
    NOMBRE_DISPLAY,
    armar_columnas_cargue,
    evaluar_candidatos_cargue,
)

COLUMNA_ESTADO = "ESTADO"
COLUMNA_COMO_VERIFICAR = "COMO_VERIFICAR"
COLUMNA_CAMPOS_CON_ERROR = "CAMPOS_CON_ERROR"
COLUMNA_PORCENTAJE_COMPLETITUD = "PORCENTAJE_COMPLETITUD"


def nombre_periodo(fecha: dt.date | None = None) -> str:
    """"Vigente_MMYYYY" -- misma convencion de nombre que pedia el SOP manual
    (fase 10) para poder rastrear que corte de INVIMA se proceso cada mes."""
    fecha = fecha or dt.date.today()
    return f"Vigente_{fecha.month:02d}{fecha.year}"


def armar_estructura_cargue(resultado: pd.DataFrame, reglas: ReglasNegocio) -> pd.DataFrame:
    evaluados = evaluar_candidatos_cargue(resultado, reglas)
    salida = armar_columnas_cargue(evaluados, reglas)
    salida[COLUMNA_ESTADO] = evaluados["listo_para_cargue"].map(
        {True: "Listo para cargue", False: "Pendiente de clasificacion manual"}
    )
    salida[COLUMNA_COMO_VERIFICAR] = evaluados["motivo_pendiente"]
    salida[COLUMNA_CAMPOS_CON_ERROR] = evaluados["campos_con_error"]
    salida[COLUMNA_PORCENTAJE_COMPLETITUD] = evaluados["porcentaje_completitud"]
    return salida


def generar_excel_estructura_cargue(df_estructura: pd.DataFrame, ruta: str | Path) -> None:
    nombres = dict(NOMBRE_DISPLAY)
    nombres[COLUMNA_ESTADO] = "ESTADO"
    nombres[COLUMNA_COMO_VERIFICAR] = "CÓMO VERIFICAR"
    nombres[COLUMNA_CAMPOS_CON_ERROR] = "CAMPOS CON ERROR"
    nombres[COLUMNA_PORCENTAJE_COMPLETITUD] = "% COMPLETITUD"
    df_estructura.rename(columns=nombres).to_excel(ruta, index=False)
