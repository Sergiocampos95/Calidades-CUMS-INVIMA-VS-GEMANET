import pandas as pd
import pytest

from gemma_cum_loader.normaliza.codigos import (
    TIPOS_CODIGO_INTERNO,
    clasificar_codigo,
    clasificar_codigos,
    es_cum,
    partir_cum,
)


@pytest.mark.parametrize(
    "codigo,esperado",
    [
        ("104739-1", True),  # malla de cargue limpia
        ("20147526-1", True),  # LISTADO_MEDICAMENTOS, formato compatible
        ("20047839-01", True),
        ("ZIAL", False),  # codigo interno propio, sin expediente
        ("Z-BEC", False),
        ("Z-FULL", False),
        ("1L1018031005100", False),  # IUM completo, sin guion
        ("3AH0112", False),  # alfanumerico corrupto
        ("-999", False),  # centinela de "sin dato", no un CUM
        ("", False),
        (None, False),
    ],
)
def test_es_cum(codigo, esperado):
    assert es_cum(codigo) is esperado


def test_clasificar_codigo_cum():
    assert clasificar_codigo("104739-1") == "cum"


def test_es_cum_sigue_siendo_estricto_tras_ampliar_la_clasificacion():
    """`clasificar_codigo()` gano ramas nuevas; `es_cum()` no cambio en nada
    -- sigue siendo el predicado estricto EXPEDIENTE-CONSECUTIVO del que
    depende la cascada de resolucion y el cruce contra INVIMA."""
    assert es_cum("00009811-01-0M01AE01") is False  # CUM con sufijo ATC
    assert es_cum("V10XX029556981") is False  # familia ATC+expediente
    assert es_cum("104739-1") is True


def test_clasificar_codigo_no_reconoce_el_cum_con_sufijo_atc_como_cum_simple():
    assert clasificar_codigo("00009811-01-0M01AE01") != "cum"


def test_clasificar_codigo_cum_con_sufijo_atc():
    """147 filas reales en produccion (2026-08-26), 48 activas: CUM validos
    cuya columna EXPEDIENTE trae -999 -- el expediente solo vive parseando
    el codigo. Ver design/tipos_codigo_interno.md."""
    assert clasificar_codigo("00009811-01-0M01AE01") == "cum_con_sufijo_atc"
    assert clasificar_codigo("00017702-01-0A11AA03") == "cum_con_sufijo_atc"
    assert clasificar_codigo("00206777-01-0H03AA01") == "cum_con_sufijo_atc"


def test_el_sufijo_debe_ser_un_atc_no_un_relleno_de_digitos():
    """"99999999-99-00000001" tiene la misma forma de dos guiones que un CUM
    con sufijo ATC, pero el tercer segmento es puro relleno de digito
    repetido, no un codigo ATC (letra + digitos). No debe colar."""
    assert clasificar_codigo("99999999-99-00000001") != "cum_con_sufijo_atc"


def test_clasificar_codigo_familia_atc_expediente_consecutivo():
    """Un tercio de tb_medicamento (64.779 filas medidas), 0% activas: capa
    legada duplicada de un medicamento que tambien existe como fila CUM
    independiente en el 90% de los casos."""
    assert clasificar_codigo("V10XX029556981") == "atc_expediente_consecutivo"
    assert clasificar_codigo("V10XA022291221") == "atc_expediente_consecutivo"
    assert clasificar_codigo("B02BD072267491") == "atc_expediente_consecutivo"


def test_el_ium_y_la_familia_atc_no_se_confunden():
    """El IUM empieza por digito; la familia ATC empieza por letra."""
    assert clasificar_codigo("1C1016781003102")[0] != clasificar_codigo("V10XX029556981")[0]
    assert clasificar_codigo("1C1016781003102") == "ium"
    assert clasificar_codigo("V10XX029556981") == "atc_expediente_consecutivo"


def test_clasificar_codigo_ium_solo_reconoce_el_patron_de_quince_caracteres():
    """Medido sobre las 85 filas reales que cumplen el patron: digito +
    letra + 13 digitos, exactamente 15 caracteres."""
    assert clasificar_codigo("1C1016781003102") == "ium"
    assert clasificar_codigo("1V1019601002100") == "ium"
    assert clasificar_codigo("1L1018031005100") == "ium"


def test_clasificar_codigo_registro_sanitario():
    """Numero de registro sanitario INVIMA usado como codigo -- no es CUM,
    ni IUM, ni propio: es otra identidad de INVIMA en el campo equivocado."""
    assert clasificar_codigo("2007M-0007029") == "registro_sanitario"  # formato moderno
    assert clasificar_codigo("M-14042") == "registro_sanitario"  # formato antiguo
    assert clasificar_codigo("2006DM-0000309") == "registro_sanitario"  # marcador DM
    assert clasificar_codigo("2011DM000720901") == "registro_sanitario"  # DM sin separador
    assert clasificar_codigo("INVIMA 2003M-00") == "registro_sanitario"  # truncado a 15


def test_clasificar_codigo_forma_cups():
    """21 de 27 filas con esta forma se verificaron cruzando contra
    tb_cup.codigo_interno (no contra tb_cup.cup, que es la PK sustituta y
    da falsos positivos) -- por eso se llama "forma", no "es"."""
    assert clasificar_codigo("881331") == "forma_cups"
    assert clasificar_codigo("903437") == "forma_cups"
    assert clasificar_codigo("C40102") == "forma_cups"
    assert clasificar_codigo("S500001") == "forma_cups"


def test_forma_cups_no_atrapa_codigos_propios_parecidos():
    """"CU1155" y "D00001" son codigo_propio (prefijo + secuencia), no
    forma_cups -- el patron de forma_cups exige prefijo S/M/C seguido SOLO
    de digitos, nunca otra letra."""
    assert clasificar_codigo("CU1155") != "forma_cups"
    assert clasificar_codigo("D00001") != "forma_cups"


def test_clasificar_codigo_propio_prefijo_y_texto_libre():
    assert clasificar_codigo("CU1155") == "codigo_propio"  # cuidador
    assert clasificar_codigo("MED000064") == "codigo_propio"  # cargado a mano
    assert clasificar_codigo("D00001") == "codigo_propio"  # dispositivo
    assert clasificar_codigo("PEDIAVIT") == "codigo_propio"  # texto libre
    assert clasificar_codigo("ZIAL") == "codigo_propio"


def test_lo_ambiguo_queda_sin_clasificar_no_se_adivina():
    """El relleno de digito repetido ("99999999-99-...", "666...618") no
    tiene una heuristica confiable (da falsos positivos sobre expedientes
    legitimos) -- se deja explicitamente sin clasificar en vez de forzarlo
    a una categoria."""
    assert clasificar_codigo("99999999-99-00000001") == "sin_clasificar"
    assert clasificar_codigo("66666666666618") == "sin_clasificar"
    assert clasificar_codigo("") == "sin_clasificar"
    assert clasificar_codigo(None) == "sin_clasificar"


def test_ningun_tipo_contiene_el_separador_de_lista():
    """La UI trata una columna como "lista de valores separados por coma"
    si sus celdas contienen ", " -- si un TIPO_CODIGO_INTERNO lo llevara,
    el filtro cambiaria de semantica sin que nadie lo note."""
    assert all(", " not in tipo for tipo in TIPOS_CODIGO_INTERNO)


def test_clasificar_codigos_vectorizado_da_lo_mismo_que_el_escalar():
    codigos = [
        "104739-1",
        "00009811-01-0M01AE01",
        "V10XX029556981",
        "1C1016781003102",
        "2007M-0007029",
        "881331",
        "CU1155",
        "99999999-99-00000001",
        "",
        None,
    ]
    serie = pd.Series(codigos)
    esperado = serie.map(clasificar_codigo)
    real = clasificar_codigos(serie)
    assert list(real) == list(esperado)


def test_partir_cum():
    assert partir_cum("104739-1") == (104739, 1)


def test_partir_cum_no_cum_devuelve_none():
    assert partir_cum("ZIAL") is None
