"""Indice IUM -> CUM(s) segun el catalogo de INVIMA.

Existe para que `auditoria/coherencia_ium.py` pueda ubicar, para cada fila
que Gemma Net identifica por IUM, con cual(es) CODIGO_INTERNO (CUM) de
INVIMA corresponde -- INVIMA no expone el IUM como llave 1:1: un IUM puede
agrupar varios CUM (medido 2026-09-28 contra los 4 listados de INVIMA:
16.075 IUM distintos, 1.140 de ellos con 2 o mas CUM). Traducir IUM -> CUM
solo es seguro cuando hay exactamente uno; con varios, este indice lo deja
marcado como "varios_cum" y quien lo consuma NO elige ninguno -- ver
`design/reglas_negocio.md` seccion IUM y la regla 1 del proyecto (nada de
decisiones a ciegas).

No se usa para el flujo de candidatos (fuera de alcance de esta fase, ver
`.ai/planes/2026-09-28-modulo-ium-separado.md`) -- solo para la auditoria de
lo que Gemma Net ya carga.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gemma_cum_loader.ingesta.invima_reader import mapa_ium
from gemma_cum_loader.normaliza.codigos import clasificar_codigos

ESTADO_UN_CUM = "un_cum"
ESTADO_VARIOS_CUM = "varios_cum"
ESTADO_MAL_FORMADO = "mal_formado"

COLUMNAS_INDICE_IUM = ("IUM", "CUM_INVIMA", "N_CUM_INVIMA", "N_PRINCIPIOS_ACTIVOS", "ESTADO_IUM")


def _indice_vacio() -> pd.DataFrame:
    vacio = pd.DataFrame(columns=list(COLUMNAS_INDICE_IUM))
    vacio.attrs["sin_fuente_ium"] = True
    return vacio


def indice_ium(df_invima: pd.DataFrame) -> pd.DataFrame:
    """Una fila por IUM presente en el catalogo de INVIMA (`df_invima`, ya
    normalizado por `invima_reader`), con el o los CUM que le corresponden.

    Degradacion explicita (regla 2 del proyecto): si la fuente no trae la
    columna IUM, o la trae pero vacia en todas las filas, se devuelve un
    indice vacio con `attrs["sin_fuente_ium"] = True` en vez de un indice
    vacio "normal" -- quien lo llama no puede distinguir "no hay IUM en esta
    fuente" de "esta fuente no publica IUM" sin esa marca, y son dos
    situaciones distintas (caso real: el export nuevo del portal para
    Vigentes no trae la columna IUM, ver
    `.ai/planes/2026-09-28-modulo-ium-y-fuentes-invima.md`).
    """
    if "IUM" not in df_invima.columns:
        return _indice_vacio()

    con_ium = mapa_ium(df_invima)
    if con_ium.empty:
        return _indice_vacio()

    con_ium = con_ium.copy()
    con_ium["IUM"] = con_ium["IUM"].astype(str).str.strip().str.upper()

    formado = (clasificar_codigos(con_ium["IUM"]) == "ium").rename("_formado")
    con_ium = pd.concat([con_ium, formado], axis=1)

    agrupado = (
        con_ium.groupby("IUM", dropna=False)
        .agg(
            CUM_INVIMA=("CODIGO_INTERNO", lambda s: sorted(set(s.dropna()))),
            N_PRINCIPIOS_ACTIVOS=("PRINCIPIO_ACTIVO", "nunique"),
            _formado=("_formado", "all"),
        )
        .reset_index()
    )
    agrupado["N_CUM_INVIMA"] = agrupado["CUM_INVIMA"].apply(len)
    agrupado["ESTADO_IUM"] = np.select(
        [~agrupado["_formado"], agrupado["N_CUM_INVIMA"] > 1],
        [ESTADO_MAL_FORMADO, ESTADO_VARIOS_CUM],
        default=ESTADO_UN_CUM,
    )
    return agrupado[list(COLUMNAS_INDICE_IUM)]
