from gemma_cum_loader.validacion.reglas import (
    Accion,
    es_error_excel,
    filtro_codigo_interno_valido,
    filtro_cruce_invima,
    filtro_integridad_estructural,
)

COLUMNAS_ESPERADAS = ["POS", "CLASIFICADO", "RESTRINGIDO", "REGULADO"]


def test_fila_bien_formada_no_dispara_filtro():
    fila = {"POS": "SI", "CLASIFICADO": "NO", "RESTRINGIDO": "NO", "REGULADO": "NO"}
    assert filtro_integridad_estructural(fila, COLUMNAS_ESPERADAS) is None


def test_fila_desalineada_cae_en_cuarentena():
    # caso real: ATC volcado en "Clasificado", importes en "Restringido"/"Regulado"
    fila = {"POS": "SI", "CLASIFICADO": "", "RESTRINGIDO": "", "REGULADO": ""}
    resultado = filtro_integridad_estructural(fila, COLUMNAS_ESPERADAS)
    assert resultado is not None
    assert resultado.accion is Accion.CUARENTENA


def test_cruce_invima_vigente_activo_acepta():
    resultado = filtro_cruce_invima("10815-3", {"10815-3"}, {"10815-3"})
    assert resultado.accion is Accion.ACEPTA


def test_cruce_invima_vigente_inactivo_cuarentena_distinta_de_sin_match():
    resultado = filtro_cruce_invima("20147-1", set(), {"20147-1"})
    assert resultado.accion is Accion.CUARENTENA
    assert "inactivo" in resultado.motivo


def test_cruce_invima_sin_match_nunca_dice_vencido():
    resultado = filtro_cruce_invima("99999-9", set(), set())
    assert resultado.accion is Accion.CUARENTENA
    assert "no implica vencido" in resultado.motivo


def test_codigo_interno_valido_no_dispara_filtro():
    assert filtro_codigo_interno_valido("104739-1") is None


def test_codigo_interno_float_nan_va_a_cuarentena():
    # caso real: EXPEDIENTE con error de digitacion ("2B") hace que
    # pd.to_numeric(errors="coerce") lo vuelva NaN, y la concatenacion de
    # pandas propaga ese NaN a CODIGO_INTERNO completo -- llega aqui como
    # el float nan, no como texto vacio
    resultado = filtro_codigo_interno_valido(float("nan"))
    assert resultado is not None
    assert resultado.accion is Accion.CUARENTENA
    assert "digitacion" in resultado.motivo


def test_codigo_interno_vacio_va_a_cuarentena():
    resultado = filtro_codigo_interno_valido("")
    assert resultado is not None
    assert resultado.accion is Accion.CUARENTENA


def test_codigo_interno_error_de_excel_va_a_cuarentena():
    resultado = filtro_codigo_interno_valido("#NAME?")
    assert resultado is not None
    assert "#NAME?" in resultado.motivo


def test_es_error_excel_reconoce_los_comunes():
    for valor in ["#NAME?", "#N/A", "#REF!", "#VALUE!", "#DIV/0!", "#NULL!"]:
        assert es_error_excel(valor), valor


def test_es_error_excel_no_marca_texto_normal():
    assert not es_error_excel("104739-1")
    assert not es_error_excel("ACETAMINOFEN")
