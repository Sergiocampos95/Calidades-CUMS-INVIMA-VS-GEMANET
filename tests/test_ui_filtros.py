"""Pruebas de los helpers de filtrado de la interfaz.

La UI no se prueba entera (haria falta un runtime de Streamlit), pero estos
dos helpers son pandas puro y deciden lo que el usuario ve: merecen prueba.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ui_revision"))

import streamlit as st
from app_streamlit import (
    _PREFIJO_FILTRO_RESULTADO,
    _buscar_auditoria,
    _conteo_por_campo,
    _derivado_filtro,
    _fechas_legibles,
    _filtrar_exploracion_auditoria,
    _filtrar_por_campos,
    _filtrar_por_valores,
    _filtros_estandar,
    _legible,
    _opciones_filtro,
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


# --- Cache de opciones de filtro (2026-08-26: "cargar todos los filtros una vez") ---


def test_opciones_filtro_sin_clave_cache_no_toca_session_state():
    df = pd.DataFrame({"X": ["b", "a", "a"]})
    claves_antes = {k for k in st.session_state if k.startswith("_opc_filtro_")}

    assert _opciones_filtro(df, "X") == ["a", "b"]

    claves_despues = {k for k in st.session_state if k.startswith("_opc_filtro_")}
    assert claves_antes == claves_despues


def test_opciones_filtro_con_clave_cache_se_calcula_una_sola_vez():
    df = pd.DataFrame({"Y": ["m", "n", "m"]})
    clave = f"prueba_cache_{id(df)}"

    primera = _opciones_filtro(df, "Y", clave_cache=clave)
    segunda = _opciones_filtro(df, "Y", clave_cache=clave)

    assert primera == ["m", "n"] == segunda
    assert primera is segunda  # el segundo llamado devuelve el MISMO objeto: no se recalculo
    assert f"_opc_filtro_{clave}_Y_3" in st.session_state


def test_opciones_filtro_cache_distingue_subconjuntos_de_distinto_tamano():
    """Mismo key_prefix, DataFrame de fondo distinto (ej.
    _panel_prioridades_auditoria reusa un unico key_prefix para cualquier
    calidad elegida) -- no deben compartir cache."""
    clave = "prioridad_auditoria"
    chico = pd.DataFrame({"Z": ["p", "q"]})
    grande = pd.DataFrame({"Z": ["p", "q", "r", "s"]})

    assert _opciones_filtro(chico, "Z", clave_cache=clave) == ["p", "q"]
    assert _opciones_filtro(grande, "Z", clave_cache=clave) == ["p", "q", "r", "s"]


def test_filtros_estandar_cachea_el_resultado_del_filtrado():
    """Con varias tablas de medicamentos abiertas a la vez (una por tarjeta
    de hallazgo), cualquier clic en OTRA parte de la pantalla vuelve a
    correr Streamlit entero -- sin esto, cada tabla ya abierta se
    recalculaba de cero en cada rerun aunque sus filtros no cambiaran.
    Pedido explicito (2026-08-26): "mejores mas la capacidad del programa
    para guardar en cache ... para que no sea inutilizable"."""
    df = pd.DataFrame({"CODIGO_INTERNO": ["1-1", "2-2"], "DESCRIPCION": ["a", "b"]})
    clave = f"prueba_filtro_res_{id(df)}"

    primera = _filtros_estandar(df, key_prefix=clave)
    segunda = _filtros_estandar(df, key_prefix=clave)

    assert primera is segunda  # el segundo llamado devuelve el MISMO objeto: no se recalculo
    claves = [k for k in st.session_state if k.startswith(f"_filtro_res_{clave}_")]
    assert len(claves) == 1


def test_filtros_estandar_cache_distingue_subconjuntos_de_distinto_tamano():
    clave = f"prueba_filtro_res_subconjuntos_{id(object())}"
    chico = pd.DataFrame({"CODIGO_INTERNO": ["1-1"], "DESCRIPCION": ["a"]})
    grande = pd.DataFrame({"CODIGO_INTERNO": ["1-1", "2-2"], "DESCRIPCION": ["a", "b"]})

    assert len(_filtros_estandar(chico, key_prefix=clave)) == 1
    assert len(_filtros_estandar(grande, key_prefix=clave)) == 2


def test_derivado_filtro_desaloja_resultados_viejos_de_la_misma_tabla():
    """Escribir "aceta" letra por letra armaba una clave nueva por cada
    tecla (a, ac, ace...) y `_derivado` a secas nunca las borraba -- 5
    DataFrames filtrados completos quedaban huerfanos en `session_state`.
    `_derivado_filtro` debe dejar como maximo 1 resultado cacheado por
    tabla (`prefijo_tabla`), sin importar cuantas claves distintas se
    hayan pedido antes."""
    prefijo = f"prueba_derivado_filtro_{id(object())}"

    for busqueda in ("a", "ac", "ace", "acet", "aceta"):
        clave = f"{_PREFIJO_FILTRO_RESULTADO}{prefijo}_{busqueda}"
        _derivado_filtro(prefijo, clave, lambda b=busqueda: pd.DataFrame({"busqueda": [b]}))

    claves_vivas = [
        k for k in st.session_state if k.startswith(f"{_PREFIJO_FILTRO_RESULTADO}{prefijo}_")
    ]
    assert len(claves_vivas) == 1
    # y es la ULTIMA que se pidio, no una cualquiera
    assert st.session_state[claves_vivas[0]]["busqueda"].iloc[0] == "aceta"


def test_derivado_filtro_no_desaloja_tablas_hermanas():
    """Purgar por `prefijo_tabla` (el `key_prefix` de la tabla que esta
    filtrando), nunca por el prefijo generico de TODAS las tablas -- dos
    tablas abiertas a la vez no deben invalidarse entre si."""
    prefijo_a = f"prueba_derivado_filtro_hermana_a_{id(object())}"
    prefijo_b = f"prueba_derivado_filtro_hermana_b_{id(object())}"
    clave_a = f"{_PREFIJO_FILTRO_RESULTADO}{prefijo_a}_x"
    clave_b = f"{_PREFIJO_FILTRO_RESULTADO}{prefijo_b}_y"

    _derivado_filtro(prefijo_a, clave_a, lambda: pd.DataFrame({"tabla": ["a"]}))
    _derivado_filtro(prefijo_b, clave_b, lambda: pd.DataFrame({"tabla": ["b"]}))

    assert clave_a in st.session_state
    assert clave_b in st.session_state
