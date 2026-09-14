"""Elegir de donde sale el catalogo de INVIMA: API o los Excel de `data/`."""

from __future__ import annotations

import pandas as pd
import pytest

from gemma_cum_loader.ingesta.fuente_invima import (
    FUENTE_API,
    FUENTE_ARCHIVOS,
    LectorInvimaDeArchivos,
    lector_para_fuente,
)
from gemma_cum_loader.ingesta.invima_socrata import DATASET_CUM_VIGENTES


def _excel(ruta, filas=1):
    pd.DataFrame({"EXPEDIENTE": ["19900001"] * filas}).to_excel(ruta, index=False)


def test_el_lector_de_archivos_ignora_el_parquet_cacheado_de_la_api(tmp_path):
    """El riesgo real de esta funcionalidad: `LectorInvimaConRespaldo` guarda
    cada descarga exitosa de Socrata como `invima_vigentes_*.parquet` en la
    misma carpeta, y esos archivos son SIEMPRE mas recientes que el Excel que
    alguien bajo a mano. Un descubrimiento por fecha elegiria el parquet y
    devolveria, calladamente, las cifras de la API a quien pidio "archivos"
    -- el snapshot se veria igual de sano y nadie lo notaria."""
    _excel(tmp_path / "ListadoCodigoUnicoVigentes2022.xlsx")
    # Parquet mas nuevo, como el que deja el cache tras una lectura en vivo.
    pd.DataFrame({"EXPEDIENTE": ["20260907"]}).to_parquet(
        tmp_path / "invima_vigentes_20260907.parquet"
    )

    leidos = []
    falso = {DATASET_CUM_VIGENTES: ("invima_vigentes", lambda r: leidos.append(r) or pd.DataFrame())}
    LectorInvimaDeArchivos(tmp_path, por_dataset=falso).leer(DATASET_CUM_VIGENTES)

    assert leidos and leidos[0].suffix == ".xlsx"


def test_el_lector_de_archivos_nunca_cae_a_la_api(tmp_path):
    """Sin Excel disponible revienta. Degradar a la API daria cifras de otra
    fuente a quien pidio explicitamente la linea base."""
    with pytest.raises(FileNotFoundError, match="cargue desde archivos|listado"):
        LectorInvimaDeArchivos(tmp_path).leer(DATASET_CUM_VIGENTES)


def test_el_lector_de_archivos_deja_constancia_del_origen(tmp_path):
    """Mismo atributo `advertencias` que LectorInvimaConRespaldo: el paso del
    progreso muestra de que archivo salio el dato, no solo que salio bien."""
    _excel(tmp_path / "ListadoCodigoUnicoVigentes2022.xlsx")
    falso = {DATASET_CUM_VIGENTES: ("invima_vigentes", lambda r: pd.DataFrame())}
    lector = LectorInvimaDeArchivos(tmp_path, por_dataset=falso)
    lector.leer(DATASET_CUM_VIGENTES)

    assert len(lector.advertencias) == 1
    assert "ListadoCodigoUnicoVigentes2022.xlsx" in lector.advertencias[0]


def test_la_fuente_api_conserva_el_lector_por_defecto():
    """None es lo que `ejecutar_refresco` interpreta como "construi vos el
    LectorInvimaConRespaldo". Devolver un lector propio aca duplicaria el
    respaldo automatico y las dos copias se desincronizarian."""
    assert lector_para_fuente(FUENTE_API) is None


def test_la_fuente_archivos_devuelve_un_lector_invocable():
    assert callable(lector_para_fuente(FUENTE_ARCHIVOS))


def test_una_fuente_desconocida_no_se_interpreta_como_la_api():
    with pytest.raises(ValueError, match="desconocida"):
        lector_para_fuente("excel_viejo")


def test_solo_los_archivos_estan_habilitados():
    """Decision del usuario (2026-09-14): la API de Socrata queda deshabilitada,
    no borrada -- reactivarla es volver a listarla en FUENTES_HABILITADAS."""
    from gemma_cum_loader.ingesta.fuente_invima import (
        FUENTE_ARCHIVOS,
        FUENTES_HABILITADAS,
        FUENTES_VALIDAS,
    )

    assert FUENTES_HABILITADAS == (FUENTE_ARCHIVOS,)
    assert set(FUENTES_HABILITADAS) <= set(FUENTES_VALIDAS)
