"""Orquestacion del modulo IUM -- paralelo a `pipeline.py` (CUM), no una
extension de el. Decision explicita del usuario (2026-09-28): "CUMs y IUMs
deben ser tratados por aparte dentro de la misma app con modulos distintos".

Reusa `_fuente()` de `pipeline.py` (misma resolucion de catalogos de unidad
y marca que ya usa el modulo CUM) en vez de copiarla -- son los mismos
catalogos, no hay una version "para IUM".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from gemma_cum_loader.armado.cruce_gemanet import leer_reporte_gemanet
from gemma_cum_loader.auditoria.coherencia_ium import auditar_coherencia_ium
from gemma_cum_loader.catalogos.fuentes import FuenteCatalogos
from gemma_cum_loader.pipeline import RUTA_CATALOGO_MARCA, RUTA_CATALOGO_UNIDAD, _fuente


def auditar_coherencia_ium_gemanet(
    df_invima: pd.DataFrame,
    archivo_gemma_net: Any,
    df_invima_vencidos: pd.DataFrame | None = None,
    df_invima_otros_estados: pd.DataFrame | None = None,
    df_invima_renovacion: pd.DataFrame | None = None,
    ruta_catalogo_unidad: str | Path = RUTA_CATALOGO_UNIDAD,
    ruta_catalogo_marca: str | Path = RUTA_CATALOGO_MARCA,
    fuente_catalogos: FuenteCatalogos | None = None,
) -> pd.DataFrame:
    """Version IUM de `pipeline.auditar_coherencia_gemanet`: mismo reporte de
    Gemma Net y mismos catalogos de unidad/marca, pero filtra al subconjunto
    identificado por IUM y cruza a traves del CUM que INVIMA le asocia (ver
    `auditoria/coherencia_ium.py`). Los listados de INVIMA se pasan
    COMPLETOS, nunca prefiltrados -- mismo motivo que la version CUM (la
    fecha de corte de vigencia se calcula sobre el catalogo completo).
    """
    reporte = leer_reporte_gemanet(archivo_gemma_net)
    fuente = _fuente(fuente_catalogos, ruta_catalogo_unidad, ruta_catalogo_marca)
    return auditar_coherencia_ium(
        reporte.df,
        df_invima,
        fuente.unidad(),
        fuente.marca(),
        df_invima_vencidos=df_invima_vencidos,
        df_invima_otros_estados=df_invima_otros_estados,
        df_invima_renovacion=df_invima_renovacion,
        alias_unidad=fuente.alias_unidad(),
    )
