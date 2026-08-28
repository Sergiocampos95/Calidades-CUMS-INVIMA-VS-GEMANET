from datetime import date
from pathlib import Path

import pandas as pd

from gemma_cum_loader.ingesta.almacen_local import ArchivoDescubierto
from gemma_cum_loader.ingesta.invima_con_respaldo import LectorInvimaConRespaldo
from gemma_cum_loader.ingesta.invima_socrata import (
    DATASET_CUM_VENCIDOS,
    DATASET_CUM_VIGENTES,
)
from gemma_cum_loader.integraciones.socrata import ErrorSocrata

_DF_VIGENTES_API = pd.DataFrame({"CODIGO_INTERNO": ["1-1"], "origen": ["socrata"]})
_DF_RESPALDO_PARQUET = pd.DataFrame({"CODIGO_INTERNO": ["1-1"], "origen": ["parquet_local"]})
_DF_RESPALDO_EXCEL = pd.DataFrame({"CODIGO_INTERNO": ["1-1"], "origen": ["excel_local"]})


def _archivo_falso(nombre: str) -> ArchivoDescubierto:
    return ArchivoDescubierto(
        tipo="invima_vigentes", ruta=Path(nombre), tamano_mb=1.0, modificado=date(2026, 8, 27)
    )


def test_socrata_exitoso_no_toca_el_respaldo_y_lo_guarda_para_la_proxima():
    llamadas_localizador = []
    llamadas_guardador = []
    lector = LectorInvimaConRespaldo(
        lector_api=lambda dataset=DATASET_CUM_VIGENTES: _DF_VIGENTES_API,
        localizador=lambda tipo, carpeta: llamadas_localizador.append(tipo) or None,
        guardador=lambda df, tipo, carpeta: llamadas_guardador.append((tipo, len(df))),
    )

    resultado = lector.leer(dataset=DATASET_CUM_VIGENTES)

    assert resultado is _DF_VIGENTES_API
    assert llamadas_localizador == []  # nunca se busco respaldo, Socrata funciono
    assert llamadas_guardador == [("invima_vigentes", 1)]
    assert lector.advertencias == []


def test_socrata_falla_y_usa_el_parquet_local_mas_reciente():
    lector = LectorInvimaConRespaldo(
        lector_api=lambda dataset=DATASET_CUM_VIGENTES: (_ for _ in ()).throw(ErrorSocrata("caida")),
        localizador=lambda tipo, carpeta: _archivo_falso("invima_vigentes_20260827.parquet"),
        lector_parquet=lambda ruta: _DF_RESPALDO_PARQUET,
    )

    resultado = lector.leer(dataset=DATASET_CUM_VIGENTES)

    assert resultado is _DF_RESPALDO_PARQUET
    assert len(lector.advertencias) == 1
    assert "invima_vigentes" in lector.advertencias[0]
    assert "caida" in lector.advertencias[0]


def test_socrata_falla_y_usa_el_excel_subido_a_mano():
    lector = LectorInvimaConRespaldo(
        lector_api=lambda dataset=DATASET_CUM_VENCIDOS: (_ for _ in ()).throw(ErrorSocrata("caida")),
        localizador=lambda tipo, carpeta: _archivo_falso("ListadoVencidos.xlsx"),
        configuracion={DATASET_CUM_VENCIDOS: ("invima_vencidos", lambda ruta: _DF_RESPALDO_EXCEL)},
    )

    resultado = lector.leer(dataset=DATASET_CUM_VENCIDOS)

    assert resultado is _DF_RESPALDO_EXCEL


def test_socrata_falla_sin_ningun_respaldo_local_sube_el_error_original():
    lector = LectorInvimaConRespaldo(
        lector_api=lambda dataset=DATASET_CUM_VIGENTES: (_ for _ in ()).throw(
            ErrorSocrata("dataset vacio")
        ),
        localizador=lambda tipo, carpeta: None,
    )

    try:
        lector.leer(dataset=DATASET_CUM_VIGENTES)
        raise AssertionError("debia propagar ErrorSocrata")
    except ErrorSocrata as exc:
        assert "dataset vacio" in str(exc)
    assert lector.advertencias == []


def test_otro_tipo_de_error_no_cae_al_respaldo():
    """Solo ErrorSocrata dispara el respaldo -- un error distinto (ej. de
    red generico, o un bug real) no debe esconderse detras de un archivo
    viejo."""
    llamadas = []
    lector = LectorInvimaConRespaldo(
        lector_api=lambda dataset=DATASET_CUM_VIGENTES: (_ for _ in ()).throw(RuntimeError("otra cosa")),
        localizador=lambda tipo, carpeta: llamadas.append(tipo),
    )

    try:
        lector.leer(dataset=DATASET_CUM_VIGENTES)
        raise AssertionError("debia propagar RuntimeError")
    except RuntimeError:
        pass
    assert llamadas == []
