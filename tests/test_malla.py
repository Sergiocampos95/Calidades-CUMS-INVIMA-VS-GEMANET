import pandas as pd

from gemma_cum_loader.armado.malla import (
    candidatos_creacion,
    universo_invima_clasificado,
)


def _fila(**overrides):
    base = {
        "CODIGO_INTERNO": "1-1",
        "ESTADO_CUM": "Activo",
        "TIPO_ROL": "FABRICANTE",
        "ESTADO_REGISTRO": "Vigente",
        "MUESTRA_MEDICA": "No",
        "DESCRIPCION_COMERCIAL": "CAJA X 10 TABLETAS",
        "PRINCIPIO_ACTIVO": "ACETAMINOFEN",
        "UNIDAD_REFERENCIA": "500 MG TABLETA",
        "TITULAR": "ACME SAS",
        "UNIDAD_MEDIDA": "mg",
    }
    base.update(overrides)
    return base


def test_arma_descripcion_desde_principio_activo_y_unidad_referencia():
    df = pd.DataFrame([_fila()])
    resultado = candidatos_creacion(df)
    assert resultado.iloc[0]["DESCRIPCION"] == "ACETAMINOFEN 500 MG TABLETA"


def test_pasa_titular_y_unidad_medida_para_resolver_despues():
    # nombres crudos, sin resolver todavia -- eso lo hace catalogos/resolver.py
    # rio abajo en pipeline.py
    df = pd.DataFrame([_fila()])
    resultado = candidatos_creacion(df)
    assert resultado.iloc[0]["MARCA_MEDICAMENTO"] == "ACME SAS"
    assert resultado.iloc[0]["UNIDAD_DE_MEDIDA"] == "mg"


def test_excluye_registro_no_vigente():
    df = pd.DataFrame([_fila(ESTADO_REGISTRO="Vencido")])
    resultado = candidatos_creacion(df)
    assert resultado.empty


def test_excluye_cum_inactivo_o_rol_distinto_de_fabricante():
    df = pd.DataFrame(
        [
            _fila(CODIGO_INTERNO="1-1", ESTADO_CUM="Inactivo"),
            _fila(CODIGO_INTERNO="2-1", TIPO_ROL="IMPORTADOR"),
        ]
    )
    resultado = candidatos_creacion(df)
    assert resultado.empty


def test_excluye_muestra_medica_por_columna():
    df = pd.DataFrame([_fila(MUESTRA_MEDICA="Si")])
    resultado = candidatos_creacion(df)
    assert resultado.empty


def test_excluye_muestra_medica_mencionada_en_descripcion_aunque_columna_diga_no():
    # caso real del SOP: la columna puede decir "No" pero el texto comercial
    # igual menciona "muestra medica" -- con tilde, para probar que normalizar()
    # cubre el caso, no solo un .upper() plano
    df = pd.DataFrame(
        [_fila(MUESTRA_MEDICA="No", DESCRIPCION_COMERCIAL="CAJA X 2 - MUESTRA MÉDICA")]
    )
    resultado = candidatos_creacion(df)
    assert resultado.empty


def test_conserva_filas_validas():
    df = pd.DataFrame([_fila(CODIGO_INTERNO="1-1"), _fila(CODIGO_INTERNO="2-1")])
    resultado = candidatos_creacion(df)
    assert list(resultado["CODIGO_INTERNO"]) == ["1-1", "2-1"]


def test_universo_clasificado_no_descarta_ninguna_fila_de_invima():
    # a diferencia de candidatos_creacion, esto conserva TODAS las filas --
    # pedido explicito del usuario: poder verificar contra el archivo real
    # que campos determinaron si un medicamento no llego a ser candidato
    df = pd.DataFrame(
        [
            _fila(CODIGO_INTERNO="1-1"),
            _fila(CODIGO_INTERNO="2-1", ESTADO_REGISTRO="Vencido"),
            _fila(CODIGO_INTERNO="3-1", ESTADO_CUM="Inactivo"),
            _fila(CODIGO_INTERNO="4-1", TIPO_ROL="IMPORTADOR"),
            _fila(CODIGO_INTERNO="5-1", MUESTRA_MEDICA="Si"),
        ]
    )
    resultado = universo_invima_clasificado(df)
    assert len(resultado) == 5
    assert set(resultado["CODIGO_INTERNO"]) == {"1-1", "2-1", "3-1", "4-1", "5-1"}


def test_universo_clasificado_asigna_el_motivo_correcto_por_fila():
    df = pd.DataFrame(
        [
            _fila(CODIGO_INTERNO="1-1"),
            _fila(CODIGO_INTERNO="2-1", ESTADO_REGISTRO="Vencido"),
            _fila(CODIGO_INTERNO="3-1", ESTADO_CUM="Inactivo"),
            _fila(CODIGO_INTERNO="4-1", TIPO_ROL="IMPORTADOR"),
            _fila(CODIGO_INTERNO="5-1", MUESTRA_MEDICA="Si"),
        ]
    )
    resultado = universo_invima_clasificado(df).set_index("CODIGO_INTERNO")
    assert resultado.loc["1-1", "CLASIFICACION_CREACION"] == "candidato"
    assert resultado.loc["2-1", "CLASIFICACION_CREACION"] == "registro_no_vigente"
    assert resultado.loc["3-1", "CLASIFICACION_CREACION"] == "cum_inactivo"
    assert resultado.loc["4-1", "CLASIFICACION_CREACION"] == "rol_no_fabricante"
    assert resultado.loc["5-1", "CLASIFICACION_CREACION"] == "muestra_medica"


def test_universo_clasificado_prioriza_rol_no_fabricante_sobre_otros_motivos():
    # una fila puede fallar varios campos a la vez -- se reporta el primero
    # en la lista de prioridad, no una lista de todos los que fallan
    df = pd.DataFrame(
        [_fila(TIPO_ROL="IMPORTADOR", ESTADO_CUM="Inactivo", ESTADO_REGISTRO="Vencido")]
    )
    resultado = universo_invima_clasificado(df)
    assert resultado.iloc[0]["CLASIFICACION_CREACION"] == "rol_no_fabricante"
