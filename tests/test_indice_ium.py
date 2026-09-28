import pandas as pd

from gemma_cum_loader.armado.indice_ium import (
    ESTADO_MAL_FORMADO,
    ESTADO_UN_CUM,
    ESTADO_VARIOS_CUM,
    indice_ium,
)


def _catalogo(filas: list[dict]) -> pd.DataFrame:
    base = {"IUM": None, "CODIGO_INTERNO": None, "PRINCIPIO_ACTIVO": "ALGO"}
    return pd.DataFrame([{**base, **fila} for fila in filas])


def test_un_ium_con_un_cum_queda_un_cum():
    df = _catalogo(
        [{"IUM": "1C1016781003102", "CODIGO_INTERNO": "20083667-1", "PRINCIPIO_ACTIVO": "CEFAZOLINA"}]
    )
    indice = indice_ium(df)
    assert list(indice["ESTADO_IUM"]) == [ESTADO_UN_CUM]
    assert indice.iloc[0]["CUM_INVIMA"] == ["20083667-1"]
    assert indice.iloc[0]["N_CUM_INVIMA"] == 1


def test_un_ium_con_varios_cum_queda_varios_cum_y_lista_todos():
    df = _catalogo(
        [
            {"IUM": "1C1016781003102", "CODIGO_INTERNO": "20083667-1"},
            {"IUM": "1C1016781003102", "CODIGO_INTERNO": "20083667-2"},
        ]
    )
    indice = indice_ium(df)
    assert list(indice["ESTADO_IUM"]) == [ESTADO_VARIOS_CUM]
    assert indice.iloc[0]["CUM_INVIMA"] == ["20083667-1", "20083667-2"]
    assert indice.iloc[0]["N_CUM_INVIMA"] == 2


def test_combinado_cuenta_principios_sin_fusionar_filas():
    # mismo IUM, mismo CUM, dos filas por dos principios activos -- caso
    # real de medicamento combinado (ver invima_reader.py). No se colapsan.
    df = _catalogo(
        [
            {"IUM": "1C1016781003102", "CODIGO_INTERNO": "40222-1", "PRINCIPIO_ACTIVO": "CLORFENIRAMINA"},
            {"IUM": "1C1016781003102", "CODIGO_INTERNO": "40222-1", "PRINCIPIO_ACTIVO": "DEXTROMETORFANO"},
        ]
    )
    indice = indice_ium(df)
    assert indice.iloc[0]["N_CUM_INVIMA"] == 1
    assert indice.iloc[0]["N_PRINCIPIOS_ACTIVOS"] == 2


def test_normaliza_mayusculas_y_espacios():
    df = _catalogo(
        [
            {"IUM": " 1c1016781003102 ", "CODIGO_INTERNO": "20083667-1"},
            {"IUM": "1C1016781003102", "CODIGO_INTERNO": "20083667-1"},
        ]
    )
    indice = indice_ium(df)
    # las dos filas son el mismo IUM tras normalizar -- un solo grupo
    assert len(indice) == 1
    assert indice.iloc[0]["IUM"] == "1C1016781003102"


def test_valor_mal_formado_queda_marcado_no_descartado():
    # "99" no cumple la forma de 15 caracteres de un IUM real -- se marca,
    # no se descarta en silencio (regla 1 del proyecto).
    df = _catalogo([{"IUM": "99", "CODIGO_INTERNO": "20083667-1"}])
    indice = indice_ium(df)
    assert len(indice) == 1
    assert indice.iloc[0]["ESTADO_IUM"] == ESTADO_MAL_FORMADO


def test_sin_columna_ium_lo_dice_en_vez_de_devolver_vacio():
    df = pd.DataFrame([{"CODIGO_INTERNO": "20083667-1", "PRINCIPIO_ACTIVO": "ALGO"}])
    indice = indice_ium(df)
    assert indice.empty
    assert indice.attrs["sin_fuente_ium"] is True


def test_columna_ium_presente_pero_vacia_tambien_lo_dice():
    df = _catalogo([{"IUM": None, "CODIGO_INTERNO": "20083667-1"}])
    indice = indice_ium(df)
    assert indice.empty
    assert indice.attrs["sin_fuente_ium"] is True
