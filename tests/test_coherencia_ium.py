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


def test_la_descripcion_de_un_ium_se_compara_solo_contra_la_forma_de_la_guia():
    """D4, decision del usuario (2026-10-15): la descripcion de una fila IUM se
    compara SOLO contra PRINCIPIO_ACTIVO + UNIDAD_REFERENCIA, como dicta la
    guia -- "si la guia dicta que asi es asi debe ser"."""
    gemanet = [_fila_gemanet(_IUM, DESCRIPCION="CEFAZOLINA CADA VIAL CONTIENE")]
    invima = [_fila_invima(_CUM, ium=_IUM)]
    fila = _auditar(gemanet, invima).iloc[0]
    assert fila["DESCRIPCION_VALIDACION"] == "coincide"
    assert fila["DESCRIPCION_INVIMA"] == "CEFAZOLINA CADA VIAL CONTIENE"


def test_la_descripcion_de_un_ium_con_la_forma_de_la_plataforma_difiere():
    """La forma de la plataforma (PA + cantidad + unidad + forma) se acepta en
    un CUM, pero NO en un IUM: ahi manda la guia, coincida o no. Era el caso
    del unico IUM que coincidia antes (1N1043301000100, "NIFEDIPINO 30MG
    CAPSULA...")."""
    gemanet = [_fila_gemanet(_IUM, DESCRIPCION="CEFAZOLINA 1000MG POLVO PARA RECONSTITUIR")]
    invima = [_fila_invima(_CUM, ium=_IUM)]
    fila = _auditar(gemanet, invima).iloc[0]
    assert fila["DESCRIPCION_VALIDACION"] == "difiere"
    assert "DESCRIPCION" in fila["CAMPOS_CON_DIFERENCIA"]
    # Se muestra contra lo que se comparo: la forma de la guia.
    assert fila["DESCRIPCION_INVIMA"] == "CEFAZOLINA CADA VIAL CONTIENE"


def test_el_nombre_oficial_del_ium_ya_no_queda_sin_comparar():
    """Hasta el 2026-10-14 el nombre oficial del IUM quedaba "sin comparar" (D4
    pendiente). Con D4 decidida se compara contra la guia y entra al porcentaje."""
    nombre_oficial = "CEFAZOLINA 1000mg/1 U POLVOS PARA RECONSTITUIR INTRAMUSCULAR INTRAVENOSA"
    gemanet = [_fila_gemanet(_IUM, DESCRIPCION=nombre_oficial)]
    invima = [_fila_invima(_CUM, ium=_IUM)]
    fila = _auditar(gemanet, invima).iloc[0]
    assert fila["DESCRIPCION_VALIDACION"] == "difiere"
    assert not pd.isna(fila["SIMILITUD_DESCRIPCION"])
    assert fila["PORCENTAJE_CALIDAD"] < 100.0
    # Lo que se muestra sigue siendo el dato crudo de Gemma Net.
    assert fila["DESCRIPCION_GEMANET"] == nombre_oficial


def test_sin_unidad_de_referencia_en_invima_la_descripcion_queda_sin_comparar():
    """Sin UNIDAD_REFERENCIA la forma de la guia no se puede armar: comparar
    contra el principio activo solo seria decidir a ciegas. Queda "sin
    comparar" y fuera del porcentaje -- no "difiere"."""
    gemanet = [_fila_gemanet(_IUM, DESCRIPCION="CEFAZOLINA 1000MG POLVO PARA RECONSTITUIR")]
    invima = [_fila_invima(_CUM, ium=_IUM, UNIDAD_REFERENCIA=None)]
    fila = _auditar(gemanet, invima).iloc[0]
    assert fila["DESCRIPCION_VALIDACION"] == "sin comparar"
    assert "DESCRIPCION" not in fila["CAMPOS_CON_DIFERENCIA"]
    assert fila["PORCENTAJE_CALIDAD"] == 100.0


def test_en_un_ium_los_demas_campos_se_siguen_comparando():
    """Solo DESCRIPCION sale de la comparacion: PRINCIPIO_ACTIVO se compara con
    la misma funcion que un CUM (plan del modulo IUM, dimension 1)."""
    gemanet = [_fila_gemanet(_IUM, PRINCIPIO_ACTIVO="CEFAZOLINA 1000mg/1 U POLVOS")]
    invima = [_fila_invima(_CUM, ium=_IUM)]
    fila = _auditar(gemanet, invima).iloc[0]
    assert fila["PRINCIPIO_ACTIVO_VALIDACION"] == "difiere"
    assert "PRINCIPIO_ACTIVO" in fila["CAMPOS_CON_DIFERENCIA"]


def test_sin_filas_ium_en_gemanet_devuelve_vacio():
    gemanet = [_fila_gemanet("20099999-1")]  # solo CUM, ningun IUM
    invima = [_fila_invima(_CUM, ium=_IUM)]
    resultado = _auditar(gemanet, invima)
    assert resultado.empty
