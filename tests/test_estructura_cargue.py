import datetime as dt

import pandas as pd

from gemma_cum_loader.armado.reglas_negocio import ClasificacionExpediente, ReglasNegocio
from gemma_cum_loader.exportacion.cargue import CAMPOS_CARGUE_GEMANET
from gemma_cum_loader.exportacion.estructura_cargue import (
    armar_estructura_cargue,
    generar_excel_estructura_cargue,
    nombre_periodo,
)


def _resultado():
    return pd.DataFrame(
        {
            "CODIGO_INTERNO": ["1-1", "5-1"],
            "DESCRIPCION": ["DESC 1", "DESC 5"],
            "CONCENTRACION": ["500 MG", "4 MG"],
            "EXPEDIENTE": [1, 999],
            "CONSECUTIVO": [1, 1],
            "FORMA_FARMACEUTICA": ["TABLETA", "TABLETA"],
            "PRINCIPIO_ACTIVO": ["ACETAMINOFEN", "NAPROXENO"],
            "ATC": ["N02BE01", "M01AE02"],
            "unidad_metodo": ["exacto_sigla", "exacto_sigla"],
            "unidad_codigo": [10, 10],
            "marca_metodo": ["exacto_sigla", "exacto_sigla"],
            "marca_codigo": [200, 200],
            "accion": ["candidato", "candidato"],
        }
    )


def _reglas():
    valores = {campo: "VALOR_PRUEBA" for campo in CAMPOS_CARGUE_GEMANET}
    clasificaciones = {
        "POS": {1: ClasificacionExpediente(valor="SI", cierta=True)},
        "CODIGO_INTERNO_MODELO_SERVICIO": {1: ClasificacionExpediente(valor=39, cierta=True)},
    }
    return ReglasNegocio(valores=valores, clasificaciones_por_expediente=clasificaciones)


def test_incluye_listos_y_pendientes_con_estado():
    df = armar_estructura_cargue(_resultado(), _reglas())
    por_codigo = df.set_index("CODIGO_INTERNO")

    assert por_codigo.loc["1-1", "ESTADO"] == "Listo para cargue"
    assert por_codigo.loc["5-1", "ESTADO"] == "Pendiente de clasificacion manual"


def test_como_verificar_trae_el_motivo_especifico_del_pendiente():
    df = armar_estructura_cargue(_resultado(), _reglas())
    motivo = df.set_index("CODIGO_INTERNO").loc["5-1", "COMO_VERIFICAR"]
    assert "999" in motivo
    assert "no tiene ninguna presentacion previa" in motivo


def test_listo_no_tiene_motivo():
    df = armar_estructura_cargue(_resultado(), _reglas())
    assert df.set_index("CODIGO_INTERNO").loc["1-1", "COMO_VERIFICAR"] == ""


def test_campos_con_error_y_porcentaje_completitud_en_la_estructura_de_cargue():
    df = armar_estructura_cargue(_resultado(), _reglas()).set_index("CODIGO_INTERNO")
    assert df.loc["1-1", "CAMPOS_CON_ERROR"] == ""
    assert df.loc["1-1", "PORCENTAJE_COMPLETITUD"] == 100.0
    # "5-1": expediente 999 sin precedente -- POS y modelo de servicio fallan
    assert df.loc["5-1", "CAMPOS_CON_ERROR"] == "POS, CODIGO_INTERNO_MODELO_SERVICIO"
    assert df.loc["5-1", "PORCENTAJE_COMPLETITUD"] == 50.0


def test_nombre_periodo_formato_vigente_mmyyyy():
    assert nombre_periodo(dt.date(2026, 8, 14)) == "Vigente_082026"
    assert nombre_periodo(dt.date(2026, 1, 3)) == "Vigente_012026"


def test_generar_excel_estructura_cargue_incluye_columnas_de_estado(tmp_path):
    df = armar_estructura_cargue(_resultado(), _reglas())
    ruta = tmp_path / "estructura.xlsx"
    generar_excel_estructura_cargue(df, ruta)

    leido = pd.read_excel(ruta)
    assert "ESTADO" in leido.columns
    assert "CÓMO VERIFICAR" in leido.columns
    assert "CAMPOS CON ERROR" in leido.columns
    assert "% COMPLETITUD" in leido.columns
    assert len(leido) == 2
