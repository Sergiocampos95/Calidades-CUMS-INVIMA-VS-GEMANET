"""Arma las filas candidatas a creacion directamente desde el catalogo INVIMA
vigente -- reemplaza la depuracion y el armado que antes se hacian a mano en
Excel sobre la malla (fases 2, 4 y 5 del SOP de negocio).

Fase 2 (depuracion): ESTADO_CUM=Activo, TIPO_ROL=FABRICANTE, ESTADO_REGISTRO=
Vigente, y exclusion de muestra medica (columna MUESTRA_MEDICA=Si, o
DESCRIPCION_COMERCIAL que la mencione aunque la columna diga No). Ver
`universo_invima_clasificado` -- ninguna fila de INVIMA se descarta en
silencio: la que no pasa fase 2 queda igual en el resultado, con
CLASIFICACION_CREACION diciendo exactamente por que campo no califica.
Pedido explicito del usuario: poder verificar contra el archivo real de
INVIMA que campos se tuvieron en cuenta para decidir si un medicamento se
crea o no, no solo ver la lista final de candidatos.

Fase 4 (codigo interno): ya la resuelve `leer_catalogo_invima` (usa
COD_MEDICAMENTO_INVIMA si el corte la trae, o EXPEDIENTE-CONSECUTIVO si no).

Fase 5 (descripcion): PRINCIPIO_ACTIVO + UNIDAD_REFERENCIA.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gemma_cum_loader.normaliza.texto import normalizar

# Orden de prioridad: la primera condicion que se cumpla es la que se
# reporta -- una fila puede fallar varios campos a la vez (ej. rol distinto
# de fabricante Y ademas CUM inactivo), pero solo se necesita el primer
# motivo real para saber por que no es candidata.
CLASIFICACIONES_CREACION = [
    "rol_no_fabricante",
    "cum_inactivo",
    "registro_no_vigente",
    "muestra_medica",
    "candidato",
]


def universo_invima_clasificado(df_invima: pd.DataFrame) -> pd.DataFrame:
    """Una fila por registro de INVIMA (TODAS, no solo las candidatas), con
    CLASIFICACION_CREACION explicando exactamente que campo(s) de la fase 2
    del SOP determinaron si es o no candidata a creacion:

    - "rol_no_fabricante": TIPO_ROL != FABRICANTE (ej. IMPORTADOR).
    - "cum_inactivo": ESTADO_CUM != Activo (presentacion descontinuada).
    - "registro_no_vigente": ESTADO_REGISTRO != Vigente (registro sanitario
      vencido o en otro estado) -- NO implica que el CUM este vencido, ver
      docstring de `validacion/reglas.py::filtro_cruce_invima` (el origen
      de esta logica, antes sin usar en el pipeline activo).
    - "muestra_medica": pasa los 3 anteriores pero es muestra medica
      (columna o mencion en la descripcion comercial).
    - "candidato": pasa los 4 filtros, es candidata a creacion.

    Verificable directamente contra el archivo de INVIMA: cada fila trae su
    EXPEDIENTE/PRODUCTO/ESTADO_CUM/TIPO_ROL/ESTADO_REGISTRO originales, sin
    que candidatos_creacion() las haya descartado en silencio.
    """
    df = df_invima.copy()
    tipo_rol = df["TIPO_ROL"].astype(str).map(normalizar)
    estado_cum = df["ESTADO_CUM"].astype(str).map(normalizar)
    estado_registro = df["ESTADO_REGISTRO"].astype(str).map(normalizar)
    es_muestra_medica = df["MUESTRA_MEDICA"].astype(str).map(normalizar).eq("SI")
    menciona_muestra = df["DESCRIPCION_COMERCIAL"].astype(str).map(normalizar).str.contains(
        "MUESTRA MEDICA", na=False
    )

    condiciones = [
        tipo_rol.ne("FABRICANTE"),
        estado_cum.ne("ACTIVO"),
        estado_registro.ne("VIGENTE"),
        es_muestra_medica | menciona_muestra,
    ]
    df["CLASIFICACION_CREACION"] = np.select(
        condiciones, CLASIFICACIONES_CREACION[:-1], default="candidato"
    )
    return df


def candidatos_creacion(df_invima: pd.DataFrame) -> pd.DataFrame:
    df = universo_invima_clasificado(df_invima)
    df = df[df["CLASIFICACION_CREACION"] == "candidato"].copy()

    df["DESCRIPCION"] = (
        df["PRINCIPIO_ACTIVO"].astype(str).str.strip()
        + " "
        + df["UNIDAD_REFERENCIA"].astype(str).str.strip()
    ).str.strip()
    df["MARCA_MEDICAMENTO"] = df["TITULAR"]
    df["UNIDAD_DE_MEDIDA"] = df["UNIDAD_MEDIDA"]
    return df
