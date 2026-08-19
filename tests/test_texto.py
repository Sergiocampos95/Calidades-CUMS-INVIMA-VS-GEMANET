import pytest

from gemma_cum_loader.normaliza.texto import normalizar, normalizar_entidad, normalizar_encabezado


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("mg.", "MG"),
        ("  Miligramos  ", "MILIGRAMOS"),
        ("Grünenthal", "GRUNENTHAL"),
        (None, ""),
    ],
)
def test_normalizar_casos_basicos(valor, esperado):
    assert normalizar(valor) == esperado


@pytest.mark.parametrize(
    "valor,esperado",
    [
        # casos reales del diagnostico contra la malla: la empresa si esta en
        # el catalogo (TECNOQUIMICAS SAS, QUIBI SAS), solo cambia el sufijo
        # societario y sobra un calificador de planta/estado despues
        ("TECNOQUIMICAS S.A. (PLANTA JAMUNDI)", "TECNOQUIMICAS"),
        ("TECNOQUIMICAS S.A. PLANTA JAMUNDI", "TECNOQUIMICAS"),
        ("QUIBI S.A. EN REESTRUCTURACION", "QUIBI"),
        ("GENFAR SAS", "GENFAR"),
        ("LABORATORIOS SIEGFRIED SAS.", "LABORATORIOS SIEGFRIED"),
    ],
)
def test_normalizar_entidad_trunca_en_sufijo_societario(valor, esperado):
    assert normalizar_entidad(valor) == esperado


def test_normalizar_entidad_no_trunca_sufijos_extranjeros():
    # NOVARTIS PHARMA A.G. (matriz suiza) no debe truncarse igual que una SAS
    # colombiana -- "AG" no es un sufijo local, y fusionar matriz/filial por
    # texto seria un error de negocio, no una limpieza de texto legitima
    assert normalizar_entidad("NOVARTIS PHARMA A.G.") == "NOVARTIS PHARMA AG"


def test_normalizar_entidad_sin_sufijo_devuelve_normalizado_completo():
    assert normalizar_entidad("LABORATORIOS CHALVER DE COLOMBIA S.A.S.") == "LABORATORIOS CHALVER DE COLOMBIA"


def test_normalizar_encabezado_espacios_a_guion_bajo():
    assert normalizar_encabezado("Código Interno") == "CODIGO_INTERNO"
