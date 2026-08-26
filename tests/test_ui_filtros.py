"""Pruebas de los helpers de filtrado de la interfaz.

La UI no se prueba entera (haria falta un runtime de Streamlit), pero estos
dos helpers son pandas puro y deciden lo que el usuario ve: merecen prueba.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ui_revision"))

from app_streamlit import (  # noqa: E402
    _buscar_auditoria,
    _conteo_por_campo,
    _ejemplos_evidencia_vigencia,
    _fechas_legibles,
    _filtrar_exploracion_auditoria,
    _filtrar_por_campos,
    _filtrar_por_valores,
    _legible,
    _valores_de_columna_lista,
)


def _serie(*valores: str) -> pd.Series:
    return pd.Series(list(valores), dtype="object")


def test_columna_con_listas_devuelve_los_valores_sueltos_no_las_combinaciones():
    """El motivo del cambio, con datos reales resumidos.

    CAMPOS_CON_DIFERENCIA guarda la lista de campos que fallan unida en un
    texto. Pedirle sus valores distintos daba 37 combinaciones para 7 campos
    (medido contra produccion el 2026-08-21). Aqui: 4 combinaciones, 3 campos.
    """
    serie = _serie(
        "CONCENTRACION",
        "CONCENTRACION, DESCRIPCION",
        "DESCRIPCION, UNIDAD_MEDIDA",
        "DESCRIPCION",
    )
    assert serie.nunique() == 4  # lo que ofrecia antes
    assert _valores_de_columna_lista(serie) == [
        "CONCENTRACION",
        "DESCRIPCION",
        "UNIDAD_MEDIDA",
    ]


def test_columna_normal_no_se_trata_como_lista():
    """Sin celdas con separador no hay nada que desarmar: se deja el filtro
    de categoria de siempre (devolver None es la senal de "no es una lista")."""
    assert _valores_de_columna_lista(_serie("correcto", "con_diferencias", "")) is None


def test_columna_vacia_no_se_trata_como_lista():
    assert _valores_de_columna_lista(_serie("", "", "")) is None


def test_las_celdas_vacias_no_producen_una_opcion_en_blanco():
    """Una fila sin hallazgos no debe aportar una opcion "" al desplegable."""
    valores = _valores_de_columna_lista(_serie("A, B", "", "B"))
    assert valores == ["A", "B"]


def test_solo_se_parte_por_el_separador_exacto_no_por_cualquier_coma():
    """La coma SOLA no separa, y es a proposito.

    El separador es una convencion del proyecto (", ", ver `_columnas_marcadas`
    en auditoria/coherencia_invima.py). Partir por cualquier coma romperia los
    valores que legitimamente llevan una: una razon social como
    "LABORATORIOS X, S.A." quedaria como dos marcas distintas.
    """
    assert _valores_de_columna_lista(_serie("A, B", "LABORATORIOS X,S.A.")) == [
        "A",
        "B",
        "LABORATORIOS X,S.A.",
    ]


def test_las_fechas_de_invima_se_muestran_sin_ambiguedad():
    """INVIMA trae "09/15/2027" -- mes/dia/año, formato de Estados Unidos.

    Aca se nota porque no hay mes 15, pero "05/03/2027" seria el 3 de mayo o
    el 5 de marzo segun quien lo lea, y se equivocaria en silencio.
    AAAA-MM-DD no admite dos lecturas.
    """
    df = pd.DataFrame({"FECHA_VENCIMIENTO": ["09/15/2027", "05/03/2027"]})
    assert list(_fechas_legibles(df)["FECHA_VENCIMIENTO"]) == ["2027-09-15", "2027-05-03"]


def test_una_columna_de_fecha_no_interpretable_conserva_su_texto():
    """Vale mas el texto original que una columna vacia: si no se pudo leer,
    quien revisa necesita ver que decia el archivo."""
    df = pd.DataFrame({"FECHA_VENCIMIENTO": ["sin fecha", "no aplica"]})
    assert list(_fechas_legibles(df)["FECHA_VENCIMIENTO"]) == ["sin fecha", "no aplica"]


def test_las_columnas_que_no_son_fecha_no_se_tocan():
    df = pd.DataFrame({"CODIGO_INTERNO": ["3521-1"], "PRODUCTO": ["ALERCET"]})
    assert _fechas_legibles(df).equals(df)


def test_el_vocabulario_interno_se_traduce_a_lenguaje_de_negocio():
    """Estos terminos llegaban crudos a la pantalla porque las tablas se
    dibujan con los valores del dato: nadie los escribio, nadie los tradujo."""
    assert _legible("exacto_sigla") == "Coincidencia exacta"
    assert _legible("fuzzy") == "Coincidencia aproximada"
    assert _legible("sin_resolver") == "Sin equivalencia en el catálogo"
    assert _legible("riesgo_activo_sin_vigencia") == "Activo aquí, sin vigencia en INVIMA"


def test_un_valor_desconocido_se_deja_como_esta():
    """La traduccion nunca puede ocultar un valor que no se previo."""
    assert _legible("un_valor_nuevo_que_nadie_previo") == "un_valor_nuevo_que_nadie_previo"


def test_busqueda_de_auditoria_encuentra_codigo_descripcion_y_expediente():
    df = pd.DataFrame(
        {
            "CODIGO_INTERNO": ["500-1", "501-1", "502-1"],
            "DESCRIPCION": ["ACETAMINOFEN", "IBUPROFENO", "LORATADINA"],
            "EXPEDIENTE": [500, 501, 502],
        }
    )

    assert list(_buscar_auditoria(df, "501")["CODIGO_INTERNO"]) == ["501-1"]
    assert list(_buscar_auditoria(df, "lora")["CODIGO_INTERNO"]) == ["502-1"]


def test_busqueda_de_auditoria_vacia_conserva_el_dataframe_original():
    df = pd.DataFrame({"CODIGO_INTERNO": ["500-1"]})

    assert _buscar_auditoria(df, "   ") is df


def test_filtro_de_exploracion_aplica_estado_y_campo_sin_apply_por_fila():
    auditoria = pd.DataFrame(
        {
            "ESTADO_COHERENCIA": ["con_diferencias", "vencido_en_invima", "con_diferencias"],
            "CAMPOS_CON_DIFERENCIA": ["DESCRIPCION, UNIDAD_MEDIDA", "", "CONCENTRACION"],
        }
    )

    filtrado = _filtrar_exploracion_auditoria(
        auditoria, ["con_diferencias"], ["UNIDAD_MEDIDA"]
    )

    assert list(filtrado.index) == [0]


def _auditoria_vigencia(*detalles: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "CODIGO_INTERNO": [f"{500 + i}-1" for i in range(len(detalles))],
            "NOVEDAD_VIGENCIA_INVIMA": ["riesgo_activo_sin_vigencia"] * len(detalles),
            "DETALLE_VIGENCIA_INVIMA": list(detalles),
        }
    )


def test_ejemplos_de_evidencia_muestran_el_dato_crudo_de_cada_lado():
    """El caso real que motivo esto: el usuario dudo de un hallazgo correcto
    porque la tarjeta agregada no mostraba el valor exacto de cada fuente,
    solo el conteo. Los ejemplos deben traer codigo + el detalle por fila tal
    cual, sin resumir ni redondear."""
    auditoria = _auditoria_vigencia(
        "Gemma Net: ACTIVO. INVIMA: ESTADO_CUM=INACTIVO, FECHA_INACTIVO=2026-03-01."
    )
    mascara = auditoria["NOVEDAD_VIGENCIA_INVIMA"] == "riesgo_activo_sin_vigencia"

    texto = _ejemplos_evidencia_vigencia(auditoria, mascara)

    assert "500-1" in texto
    assert "Gemma Net: ACTIVO. INVIMA: ESTADO_CUM=INACTIVO, FECHA_INACTIVO=2026-03-01." in texto


def test_ejemplos_de_evidencia_se_limitan_y_avisan_el_total():
    auditoria = _auditoria_vigencia(*[f"detalle {i}" for i in range(5)])
    mascara = auditoria["NOVEDAD_VIGENCIA_INVIMA"] == "riesgo_activo_sin_vigencia"

    texto = _ejemplos_evidencia_vigencia(auditoria, mascara, limite=3)

    assert texto.count("- 50") == 3  # solo 3 ejemplos, no los 5
    assert "mostrando 3 de 5" in texto


def test_sin_hallazgos_no_hay_texto_de_ejemplos():
    auditoria = _auditoria_vigencia()
    mascara = pd.Series([], dtype=bool)

    assert _ejemplos_evidencia_vigencia(auditoria, mascara) == ""


def test_ejemplos_de_evidencia_no_revientan_sin_la_columna_de_detalle():
    """Degradacion explicita: si la auditoria no trae DETALLE_VIGENCIA_INVIMA
    (dimension no calculada), no se muestra evidencia inventada."""
    auditoria = pd.DataFrame({"CODIGO_INTERNO": ["500-1"]})
    mascara = pd.Series([True])

    assert _ejemplos_evidencia_vigencia(auditoria, mascara) == ""


def test_filtrar_por_campos_no_revienta_con_texto_libre_con_parentesis():
    """Bug real en produccion (2026-08-25): una columna de motivo/error trae
    oraciones libres, no identificadores cortos. `_filtrar_por_campos` usaba
    un regex `\\b...\\b` sobre ese texto tal cual, y PyArrow (el backend de
    pandas) reventaba con "Invalid regular expression" ante un parentesis
    sin cerrar como en "codigo 200) | TRAVENOL LABORATORIES INC. (61%"."""
    conflictivo = "codigo 200) | TRAVENOL LABORATORIES INC. (61%"
    df = pd.DataFrame(
        {
            "pendientes_campo_error": [
                conflictivo,
                "sin problema",
                "verificar igual en Gemma Net: LABORATORIOS RYAN SAS (70%",
            ]
        }
    )

    filtrado = _filtrar_por_campos(df, "pendientes_campo_error", [conflictivo])

    assert list(filtrado.index) == [0]


def test_filtrar_por_campos_encuentra_texto_que_termina_en_signo_de_puntuacion():
    """La otra mitad del mismo bug: aunque se escapara el regex, `\\b` nunca
    encuentra limite de palabra al final de un texto que termina en un
    caracter que no es de palabra (%, ), .). El filtro devolvia 0 filas en
    silencio -- exactamente la suposicion silenciosa que prohibe el
    proyecto. La coincidencia literal no tiene ese problema."""
    valor = "LABORATORIOS RYAN SAS (70%"
    df = pd.DataFrame({"campo": [valor, "otro valor distinto"]})

    filtrado = _filtrar_por_campos(df, "campo", [valor])

    assert list(filtrado.index) == [0]


def test_conteo_por_campo_no_revienta_con_texto_libre():
    conflictivo = "codigo 200) | TRAVENOL LABORATORIES INC. (61%"
    serie = pd.Series([conflictivo, "sin relacion"])

    conteo = _conteo_por_campo(serie, [conflictivo, "sin relacion"])

    assert conteo == {conflictivo: 1, "sin relacion": 1}


def test_filtrar_por_campos_sigue_funcionando_con_nombres_de_campo_fijos():
    """No se rompe el caso original: DESCRIPCION/MARCA_MEDICAMENTO en una
    lista separada por coma, sin confundirse con substrings parciales."""
    df = pd.DataFrame(
        {
            "CAMPOS_CON_DIFERENCIA": [
                "CONCENTRACION, DESCRIPCION",
                "DESCRIPCION, UNIDAD_MEDIDA",
                "CONCENTRACION",
            ]
        }
    )

    filtrado = _filtrar_por_campos(df, "CAMPOS_CON_DIFERENCIA", ["DESCRIPCION"])

    assert list(filtrado.index) == [0, 1]


# --- TIPO_CODIGO_INTERNO: filtro nuevo (design/tipos_codigo_interno.md) ---


def test_los_tipos_de_codigo_se_traducen_a_lenguaje_de_negocio():
    tipos = [
        "cum",
        "cum_con_sufijo_atc",
        "atc_expediente_consecutivo",
        "ium",
        "registro_sanitario",
        "forma_cups",
        "codigo_propio",
        "sin_clasificar",
    ]
    for tipo in tipos:
        assert _legible(tipo) != tipo  # todos tienen traduccion, ninguno queda crudo


def test_el_tipo_de_codigo_no_se_trata_como_columna_lista():
    """TIPO_CODIGO_INTERNO trae un valor por celda, nunca varios separados
    por ", " -- si algun dia lo hiciera, _filtros_estandar cambiaria de
    semantica sin que nadie lo note (ver _valores_de_columna_lista)."""
    serie = pd.Series(["cum", "atc_expediente_consecutivo", "ium", "cum"])
    assert _valores_de_columna_lista(serie) is None


def test_filtrar_por_tipo_de_codigo_conserva_solo_los_tipos_elegidos():
    df = pd.DataFrame(
        {
            "CODIGO_INTERNO": ["500-1", "V10XX029556981", "1C1016781003102"],
            "TIPO_CODIGO_INTERNO": ["cum", "atc_expediente_consecutivo", "ium"],
        }
    )

    filtrado = _filtrar_por_valores(df, "TIPO_CODIGO_INTERNO", ["cum", "ium"])

    assert sorted(filtrado["CODIGO_INTERNO"]) == ["1C1016781003102", "500-1"]


def test_filtrar_por_tipo_de_codigo_sin_seleccion_no_filtra():
    """Lista vacia de elegidos = no acotar por este dato, igual que el resto
    de los filtros de _filtros_estandar."""
    df = pd.DataFrame({"TIPO_CODIGO_INTERNO": ["cum", "ium"]})

    assert _filtrar_por_valores(df, "TIPO_CODIGO_INTERNO", []) is df
