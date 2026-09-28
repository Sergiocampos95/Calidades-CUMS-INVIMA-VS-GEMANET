import pandas as pd

from gemma_cum_loader.armado.indice_ium import ESTADO_UN_CUM, ESTADO_VARIOS_CUM
from gemma_cum_loader.auditoria.coherencia_ium import (
    ESTADO_NO_PUBLICADO,
    auditar_coherencia_ium,
)
from gemma_cum_loader.catalogos.resolver import cargar_catalogo
from gemma_cum_loader.normaliza.texto import normalizar_entidad

_CATALOGO_UNIDAD = cargar_catalogo([(10, "MG - MILIGRAMO")])
_CATALOGO_MARCA = cargar_catalogo(
    [(200, "ACME SAS")], normalizador=normalizar_entidad, dividir_sigla_descripcion=False
)

_IUM = "1C1016781003102"
_CUM = "20083667-1"


def _fila_gemanet(codigo_interno, activo="SI", **overrides):
    base = {
        "CODIGO_INTERNO": codigo_interno,
        "ACTIVO": activo,
        "DESCRIPCION": "CEFAZOLINA 1000MG POLVO",
        "CONCENTRACION": "1000 MG",
        "FORMA_FARMACEUTICA": "POLVO PARA RECONSTITUIR",
        "PRINCIPIO_ACTIVO": "CEFAZOLINA",
        "CODIGO_ATC": "J01DB04",
        "MARCA_MEDICAMENTO": 200,
        "UNIDAD_MEDIDA": 10,
    }
    base.update(overrides)
    return base


def _fila_invima(codigo_interno, ium=None, **overrides):
    base = {
        "CODIGO_INTERNO": codigo_interno,
        "IUM": ium,
        "TITULAR": "ACME SAS",
        "UNIDAD_MEDIDA": "mg",
        "CANTIDAD": 1000,
        "PRINCIPIO_ACTIVO": "CEFAZOLINA",
        "UNIDAD_REFERENCIA": "CADA VIAL CONTIENE",
        "CONCENTRACION": "1000 MG",
        "DESCRIPCION_COMERCIAL": "VIAL POR 1",
        "FORMA_FARMACEUTICA": "POLVO PARA RECONSTITUIR",
        "ATC": "J01DB04",
    }
    base.update(overrides)
    return base


def _auditar(gemanet_filas, invima_filas):
    reporte = pd.DataFrame(gemanet_filas)
    invima = pd.DataFrame(invima_filas)
    return auditar_coherencia_ium(reporte, invima, _CATALOGO_UNIDAD, _CATALOGO_MARCA)


def test_solo_toma_filas_tipo_ium():
    gemanet = [_fila_gemanet(_IUM), _fila_gemanet("20099999-1")]  # la segunda es CUM normal
    invima = [_fila_invima(_CUM, ium=_IUM)]
    resultado = _auditar(gemanet, invima)
    assert list(resultado["CODIGO_INTERNO"]) == [_IUM]


def test_un_cum_compara_contra_la_fila_de_invima_de_ese_cum():
    gemanet = [_fila_gemanet(_IUM)]
    invima = [_fila_invima(_CUM, ium=_IUM)]
    resultado = _auditar(gemanet, invima)
    fila = resultado.iloc[0]
    assert fila["ESTADO_IUM"] == ESTADO_UN_CUM
    assert fila["CUM_INVIMA"] == [_CUM]
    # lo que importa aca es que SI se comparo contra INVIMA (no quedo "sin
    # correspondencia"): el detalle exacto de que campos coinciden es la
    # misma logica ya probada en test_coherencia_invima.py.
    assert fila["ESTADO_COHERENCIA"] != "sin_correspondencia_invima"
    assert not pd.isna(fila["PORCENTAJE_CALIDAD"])


def test_varios_cum_no_elige_ninguno_y_queda_sin_comparar():
    gemanet = [_fila_gemanet(_IUM)]
    invima = [
        _fila_invima("20083667-1", ium=_IUM),
        _fila_invima("20083667-2", ium=_IUM),
    ]
    resultado = _auditar(gemanet, invima)
    fila = resultado.iloc[0]
    assert fila["ESTADO_IUM"] == ESTADO_VARIOS_CUM
    assert sorted(fila["CUM_INVIMA"]) == ["20083667-1", "20083667-2"]
    assert fila["ESTADO_COHERENCIA"] == "sin_correspondencia_invima"
    assert pd.isna(fila["PORCENTAJE_CALIDAD"])


def test_no_encontrado_deja_porcentaje_vacio_no_cero():
    gemanet = [_fila_gemanet(_IUM)]
    invima = [_fila_invima(_CUM, ium="9X9999999999999")]  # otro IUM, no el nuestro
    resultado = _auditar(gemanet, invima)
    fila = resultado.iloc[0]
    assert fila["ESTADO_IUM"] == ESTADO_NO_PUBLICADO
    assert pd.isna(fila["PORCENTAJE_CALIDAD"])


def test_no_dice_codigo_legado():
    gemanet = [_fila_gemanet(_IUM)]
    invima = [_fila_invima(_CUM, ium="9X9999999999999")]
    resultado = _auditar(gemanet, invima)
    assert "TIPO_SIN_CORRESPONDENCIA" not in resultado.columns


def test_prioridad_vacia_si_no_es_un_cum():
    gemanet = [_fila_gemanet(_IUM)]
    invima = [
        _fila_invima("20083667-1", ium=_IUM),
        _fila_invima("20083667-2", ium=_IUM),
    ]
    resultado = _auditar(gemanet, invima)
    fila = resultado.iloc[0]
    assert fila["PRIORIDAD_ACCION"] == ""
    assert fila["NATURALEZA_HALLAZGO"] == ""
    assert fila["ACCION_SUGERIDA"] == ""


def test_detecta_cum_hermano_activo_en_gemma_net():
    gemanet = [_fila_gemanet(_IUM), _fila_gemanet(_CUM, activo="SI")]
    invima = [_fila_invima(_CUM, ium=_IUM)]
    resultado = _auditar(gemanet, invima)
    fila = resultado[resultado["CODIGO_INTERNO"] == _IUM].iloc[0]
    assert _CUM in fila["IDENTIDAD_DUPLICADA"]
    assert "activo" in fila["IDENTIDAD_DUPLICADA"]


def test_sin_cum_hermano_identidad_duplicada_queda_vacia():
    gemanet = [_fila_gemanet(_IUM)]
    invima = [_fila_invima(_CUM, ium=_IUM)]
    resultado = _auditar(gemanet, invima)
    assert resultado.iloc[0]["IDENTIDAD_DUPLICADA"] == ""


def test_la_salida_lleva_el_ium_como_codigo_interno():
    gemanet = [_fila_gemanet(_IUM)]
    invima = [_fila_invima(_CUM, ium=_IUM)]
    resultado = _auditar(gemanet, invima)
    assert resultado.iloc[0]["CODIGO_INTERNO"] == _IUM
    assert _CUM not in set(resultado["CODIGO_INTERNO"])


def test_sin_columna_ium_en_la_fuente_se_marca_no_se_inventa_no_encontrado():
    gemanet = [_fila_gemanet(_IUM)]
    invima_sin_ium = pd.DataFrame([{k: v for k, v in _fila_invima(_CUM).items() if k != "IUM"}])
    resultado = auditar_coherencia_ium(
        pd.DataFrame(gemanet), invima_sin_ium, _CATALOGO_UNIDAD, _CATALOGO_MARCA
    )
    assert resultado.attrs.get("sin_fuente_ium") is True
    assert list(resultado["ESTADO_IUM"]) == [ESTADO_NO_PUBLICADO]


def test_sin_filas_ium_en_gemanet_devuelve_vacio():
    gemanet = [_fila_gemanet("20099999-1")]  # solo CUM, ningun IUM
    invima = [_fila_invima(_CUM, ium=_IUM)]
    resultado = _auditar(gemanet, invima)
    assert resultado.empty
