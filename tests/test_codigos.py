import pytest

from gemma_cum_loader.normaliza.codigos import clasificar_codigo, es_cum, partir_cum


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


def test_clasificar_codigo_ium():
    assert clasificar_codigo("ZIAL") == "ium"


def test_partir_cum():
    assert partir_cum("104739-1") == (104739, 1)


def test_partir_cum_no_cum_devuelve_none():
    assert partir_cum("ZIAL") is None
