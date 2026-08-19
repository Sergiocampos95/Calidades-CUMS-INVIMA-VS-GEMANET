import pandas as pd

from gemma_cum_loader.armado.reglas_negocio import ClasificacionExpediente, ReglasNegocio
from gemma_cum_loader.exportacion.cargue import (
    CAMPOS_CARGUE_GEMANET,
    CAMPOS_PENDIENTES_REGLA_NEGOCIO,
    NOMBRE_DISPLAY,
    evaluar_candidatos_cargue,
    generar_excel_cargue,
    preparar_filas_cargue,
)

_CAMPOS_POR_EXPEDIENTE = {"POS", "CODIGO_INTERNO_MODELO_SERVICIO"}
_CAMPOS_VALOR_FIJO = [c for c in CAMPOS_PENDIENTES_REGLA_NEGOCIO if c not in _CAMPOS_POR_EXPEDIENTE]


def _resultado():
    return pd.DataFrame(
        {
            "CODIGO_INTERNO": ["1-1", "2-1", "3-1", "4-1", "5-1"],
            "DESCRIPCION": ["DESC 1", "DESC 2", "DESC 3", "DESC 4", "DESC 5"],
            "CONCENTRACION": ["500 MG", "1 G", "2 ML", "3 MG", "4 MG"],
            "EXPEDIENTE": [1, 2, 3, 4, 999],
            "CONSECUTIVO": [1, 1, 1, 1, 1],
            "FORMA_FARMACEUTICA": ["TABLETA", "TABLETA", "JARABE", "TABLETA", "TABLETA"],
            "PRINCIPIO_ACTIVO": ["ACETAMINOFEN", "IBUPROFENO", "LORATADINA", "ASPIRINA", "NAPROXENO"],
            "ATC": ["N02BE01", "M01AE01", "R06AX13", "N02BA01", "M01AE02"],
            "unidad_metodo": ["exacto_sigla"] * 5,
            "unidad_codigo": [10, 11, 14, 10, 10],
            "marca_metodo": ["exacto_sigla", "exacto_sigla", "exacto_sigla", "sin_resolver", "exacto_sigla"],
            "marca_codigo": [200, 201, 202, 1, 200],
            "marca_sugerencia": ["", "", "", "LAFRANCOL SAS (85%, codigo 99)", ""],
            # "2-1" ya existe en Gemma Net; "4-1" es candidato pero su marca no
            # resolvio (si trae sugerencia aproximada); "5-1" es candidato con
            # marca/unidad resueltas pero su EXPEDIENTE (999) no tiene
            # precedente de clasificacion POS/modelo
            "accion": ["candidato", "ya_existe", "candidato", "candidato", "candidato"],
        }
    )


def _reglas():
    valores = {campo: "VALOR_PRUEBA" for campo in _CAMPOS_VALOR_FIJO}
    clasificaciones = {
        "POS": {
            1: ClasificacionExpediente(valor="SI", cierta=True),
            3: ClasificacionExpediente(valor="NO", cierta=True),
        },
        "CODIGO_INTERNO_MODELO_SERVICIO": {
            1: ClasificacionExpediente(valor=39, cierta=True),
            3: ClasificacionExpediente(valor=40, cierta=True),
        },
    }
    return ReglasNegocio(valores=valores, clasificaciones_por_expediente=clasificaciones)


def test_preparar_filas_cargue_solo_incluye_candidatos_listos():
    df = preparar_filas_cargue(_resultado(), _reglas())
    assert list(df["CODIGO_INTERNO"]) == ["1-1", "3-1"]
    assert list(df["UNIDAD_MEDIDA"]) == [10, 14]
    assert list(df["MARCA_MEDICAMENTO"]) == [200, 202]


def test_preparar_filas_cargue_usa_pos_y_modelo_por_expediente():
    df = preparar_filas_cargue(_resultado(), _reglas())
    assert list(df["POS"]) == ["SI", "NO"]
    assert list(df["CODIGO_INTERNO_MODELO_SERVICIO"]) == [39, 40]


def test_preparar_filas_cargue_excluye_marca_sin_resolver():
    # "4-1" es candidato nuevo pero su marca no resolvio contra catalogo -- no
    # debe cargar con el codigo de fallback (FALLBACK_CODIGO=1) disfrazado de
    # codigo real
    df = preparar_filas_cargue(_resultado(), _reglas())
    assert "4-1" not in set(df["CODIGO_INTERNO"])


def test_preparar_filas_cargue_excluye_lo_que_ya_existe_en_gemanet():
    df = preparar_filas_cargue(_resultado(), _reglas())
    assert "2-1" not in set(df["CODIGO_INTERNO"])


def test_preparar_filas_cargue_excluye_expediente_sin_clasificacion_cierta():
    # "5-1": marca y unidad resueltas, pero su EXPEDIENTE (999) nunca aparecio
    # en la malla de referencia -- no hay POS/modelo de servicio ciertos, no
    # se adivina, la fila entera queda fuera
    df = preparar_filas_cargue(_resultado(), _reglas())
    assert "5-1" not in set(df["CODIGO_INTERNO"])


def test_evaluar_candidatos_marca_correctamente_listo_vs_pendiente():
    evaluados = evaluar_candidatos_cargue(_resultado(), _reglas())
    por_codigo = evaluados.set_index("CODIGO_INTERNO")

    assert por_codigo.loc["1-1", "listo_para_cargue"] == True  # noqa: E712
    assert por_codigo.loc["3-1", "listo_para_cargue"] == True  # noqa: E712
    assert por_codigo.loc["4-1", "listo_para_cargue"] == False  # noqa: E712
    assert por_codigo.loc["5-1", "listo_para_cargue"] == False  # noqa: E712
    assert "no tiene ninguna presentacion previa" in por_codigo.loc["5-1", "motivo_pendiente"]


def test_campos_con_error_nombra_exactamente_los_campos_que_fallan():
    # "4-1": marca no resolvio Y su expediente (4) tampoco tiene precedente
    # de POS/modelo en _reglas() -- los 3 deben aparecer, nombrados, no una
    # frase generica que obligue a adivinar cual de los 4 campos fallo
    evaluados = evaluar_candidatos_cargue(_resultado(), _reglas())
    por_codigo = evaluados.set_index("CODIGO_INTERNO")
    assert por_codigo.loc["4-1", "campos_con_error"] == "MARCA_MEDICAMENTO, POS, CODIGO_INTERNO_MODELO_SERVICIO"
    assert por_codigo.loc["1-1", "campos_con_error"] == ""


def test_campos_con_error_lista_varios_campos_a_la_vez():
    # "5-1": expediente 999 no tiene NINGUN precedente -- POS y
    # CODIGO_INTERNO_MODELO_SERVICIO fallan los dos, los dos deben aparecer
    # (marca y unidad si resuelven para esta fila)
    evaluados = evaluar_candidatos_cargue(_resultado(), _reglas())
    campos = evaluados.set_index("CODIGO_INTERNO").loc["5-1", "campos_con_error"]
    assert campos == "POS, CODIGO_INTERNO_MODELO_SERVICIO"


def test_porcentaje_completitud_refleja_cuantos_de_los_4_campos_verificables_fallan():
    evaluados = evaluar_candidatos_cargue(_resultado(), _reglas())
    por_codigo = evaluados.set_index("CODIGO_INTERNO")
    assert por_codigo.loc["1-1", "porcentaje_completitud"] == 100.0  # listo, 0 de 4 fallan
    assert por_codigo.loc["4-1", "porcentaje_completitud"] == 25.0  # 3 de 4 fallan (marca, pos, modelo)
    assert por_codigo.loc["5-1", "porcentaje_completitud"] == 50.0  # 2 de 4 fallan (pos y modelo)


def test_marca_sin_resolver_incluye_sugerencia_como_guia_no_confirmada():
    evaluados = evaluar_candidatos_cargue(_resultado(), _reglas())
    motivo = evaluados.set_index("CODIGO_INTERNO").loc["4-1", "motivo_pendiente"]
    assert "MARCA MEDICAMENTO no se encontro" in motivo
    assert "LAFRANCOL SAS (85%, codigo 99)" in motivo
    assert "NO confirmado" in motivo
    assert "Mantenimiento Marcas de Medicamentos" in motivo


def test_marca_sin_resolver_sin_sugerencia_lo_dice_explicitamente():
    resultado = _resultado()
    resultado.loc[resultado["CODIGO_INTERNO"] == "4-1", "marca_sugerencia"] = ""
    evaluados = evaluar_candidatos_cargue(resultado, _reglas())
    motivo = evaluados.set_index("CODIGO_INTERNO").loc["4-1", "motivo_pendiente"]
    assert "No se encontro ninguna coincidencia aproximada" in motivo


def test_columnas_de_salida_son_los_37_campos_confirmados_en_orden():
    df = preparar_filas_cargue(_resultado(), _reglas())
    assert list(df.columns) == CAMPOS_CARGUE_GEMANET


def test_codigo_atc_toma_el_campo_atc_de_origen():
    df = preparar_filas_cargue(_resultado(), _reglas())
    assert list(df["CODIGO_ATC"]) == ["N02BE01", "R06AX13"]


def test_campos_de_regla_de_negocio_de_valor_fijo_nunca_quedan_en_blanco():
    # ya no se deja vacio: se completa con lo que derivo armado/reglas_negocio.py
    df = preparar_filas_cargue(_resultado(), _reglas())
    for campo in _CAMPOS_VALOR_FIJO:
        assert (df[campo] == "VALOR_PRUEBA").all()


def test_nombre_display_cubre_los_37_campos():
    assert set(NOMBRE_DISPLAY.keys()) == set(CAMPOS_CARGUE_GEMANET)


def test_generar_excel_cargue_usa_encabezados_reales(tmp_path):
    df = preparar_filas_cargue(_resultado(), _reglas())
    ruta = tmp_path / "cargue.xlsx"
    generar_excel_cargue(df, ruta)

    leido = pd.read_excel(ruta)
    assert list(leido.columns) == [NOMBRE_DISPLAY[c] for c in CAMPOS_CARGUE_GEMANET]
    assert list(leido["CÓDIGO INTERNO"]) == ["1-1", "3-1"]
    assert list(leido["DESCRIPCIÓN"]) == ["DESC 1", "DESC 3"]
