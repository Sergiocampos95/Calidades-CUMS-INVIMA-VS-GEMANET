import pandas as pd

from gemma_cum_loader.auditoria.coherencia_invima import (
    _CAMPOS_COMPLETITUD_REPORTE,
    CAMPOS_COMPARADOS_COHERENCIA,
    EstadoCoherencia,
    auditar_coherencia,
)
from gemma_cum_loader.catalogos.resolver import cargar_catalogo
from gemma_cum_loader.normaliza.texto import normalizar_entidad

_CATALOGO_UNIDAD = cargar_catalogo([(10, "MG - MILIGRAMO")])
_CATALOGO_MARCA = cargar_catalogo(
    [(200, "ACME SAS")], normalizador=normalizar_entidad, dividir_sigla_descripcion=False
)


def _fila_gemanet(codigo_interno, **overrides):
    base = {
        "CODIGO_INTERNO": codigo_interno,
        "DESCRIPCION": "ACETAMINOFEN TABLETA",
        "CONCENTRACION": "500 MG",
        "FORMA_FARMACEUTICA": "TABLETA",
        "PRINCIPIO_ACTIVO": "ACETAMINOFEN",
        "CODIGO_ATC": "N02BE01",
        "MARCA_MEDICAMENTO": 200,
        "UNIDAD_MEDIDA": 10,
    }
    base.update(overrides)
    return base


def _fila_invima(codigo_interno, **overrides):
    base = {
        "CODIGO_INTERNO": codigo_interno,
        "TITULAR": "ACME SAS",
        "UNIDAD_MEDIDA": "mg",
        "PRINCIPIO_ACTIVO": "ACETAMINOFEN",
        "UNIDAD_REFERENCIA": "TABLETA",
        "CONCENTRACION": "500 MG",
        "FORMA_FARMACEUTICA": "TABLETA",
        "ATC": "N02BE01",
    }
    base.update(overrides)
    return base


def _auditar(
    gemanet_filas, invima_filas, vencidos_filas=None, otros_estados_filas=None, renovacion_filas=None
):
    reporte = pd.DataFrame(gemanet_filas)
    invima = pd.DataFrame(invima_filas)
    vencidos = pd.DataFrame(vencidos_filas) if vencidos_filas is not None else None
    otros_estados = pd.DataFrame(otros_estados_filas) if otros_estados_filas is not None else None
    renovacion = pd.DataFrame(renovacion_filas) if renovacion_filas is not None else None
    return auditar_coherencia(
        reporte,
        invima,
        _CATALOGO_UNIDAD,
        _CATALOGO_MARCA,
        df_invima_vencidos=vencidos,
        df_invima_otros_estados=otros_estados,
        df_invima_renovacion=renovacion,
    ).set_index("CODIGO_INTERNO")


def test_campos_comparados_coherencia_tiene_los_7_campos_que_arma_la_matriz():
    assert len(CAMPOS_COMPARADOS_COHERENCIA) == 7
    assert set(CAMPOS_COMPARADOS_COHERENCIA) == {
        "CONCENTRACION", "FORMA_FARMACEUTICA", "PRINCIPIO_ACTIVO", "CODIGO_ATC",
        "DESCRIPCION", "MARCA_MEDICAMENTO", "UNIDAD_MEDIDA",
    }


def test_todo_coincide_es_correcto():
    resultado = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    assert resultado.loc["500-1", "ESTADO_COHERENCIA"] == EstadoCoherencia.CORRECTO.value
    assert resultado.loc["500-1", "CAMPOS_CON_DIFERENCIA"] == ""
    assert resultado.loc["500-1", "PORCENTAJE_CALIDAD"] == 100.0


def test_campo_distinto_marca_con_diferencias_y_lo_nombra():
    resultado = _auditar(
        [_fila_gemanet("500-1", CONCENTRACION="250 MG")], [_fila_invima("500-1")]
    )
    fila = resultado.loc["500-1"]
    assert fila["ESTADO_COHERENCIA"] == EstadoCoherencia.CON_DIFERENCIAS.value
    assert "CONCENTRACION" in fila["CAMPOS_CON_DIFERENCIA"]
    # 6 de los 7 campos comparables coinciden (solo CONCENTRACION difiere) --
    # aunque haya un hallazgo, sigue siendo util saber que tan alineado esta
    # el resto del dato, no solo la bandera binaria correcto/con_diferencias
    assert fila["PORCENTAJE_CALIDAD"] == round(6 / 7 * 100, 1)


def test_porcentaje_calidad_es_nan_si_no_hay_correspondencia_con_invima():
    # no tiene sentido un "% de calidad" cuando no hay nada contra que
    # comparar -- NaN, no 0%, para no leerse como "dato pesimo"
    resultado = _auditar([_fila_gemanet("999-9")], [_fila_invima("500-1")])
    assert pd.isna(resultado.loc["999-9", "PORCENTAJE_CALIDAD"])


def test_marca_resuelta_por_codigo_se_compara_contra_titular_invima():
    # MARCA_MEDICAMENTO=200 -> "ACME SAS" (catalogo); INVIMA TITULAR distinto
    resultado = _auditar(
        [_fila_gemanet("500-1")], [_fila_invima("500-1", TITULAR="OTRO LABORATORIO SAS")]
    )
    fila = resultado.loc["500-1"]
    assert fila["ESTADO_COHERENCIA"] == EstadoCoherencia.CON_DIFERENCIAS.value
    assert "MARCA_MEDICAMENTO" in fila["CAMPOS_CON_DIFERENCIA"]


def test_sin_vencidos_provisto_cae_en_sin_correspondencia():
    # comportamiento previo a esta funcionalidad: si no se pasa df_invima_vencidos,
    # nunca se puede distinguir vencido de codigo legado -- degradacion explicita
    resultado = _auditar([_fila_gemanet("999-9")], [_fila_invima("500-1")])
    assert resultado.loc["999-9", "ESTADO_COHERENCIA"] == EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value


def test_no_encontrado_en_vigentes_pero_si_en_vencidos_es_vencido_en_invima():
    resultado = _auditar(
        [_fila_gemanet("999-9")],
        [_fila_invima("500-1")],
        vencidos_filas=[_fila_invima("999-9")],
    )
    assert resultado.loc["999-9", "ESTADO_COHERENCIA"] == EstadoCoherencia.VENCIDO_EN_INVIMA.value


def test_no_encontrado_en_ninguno_de_los_dos_es_sin_correspondencia():
    resultado = _auditar(
        [_fila_gemanet("111-1")],
        [_fila_invima("500-1")],
        vencidos_filas=[_fila_invima("999-9")],
    )
    assert resultado.loc["111-1", "ESTADO_COHERENCIA"] == EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value


def test_dataset_de_vencidos_vacio_no_rompe_y_no_marca_nada_como_vencido():
    resultado = _auditar(
        [_fila_gemanet("999-9")], [_fila_invima("500-1")], vencidos_filas=[]
    )
    assert resultado.loc["999-9", "ESTADO_COHERENCIA"] == EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value


def test_codigo_correcto_no_se_reclasifica_como_vencido_aunque_aparezca_en_vencidos():
    # un CODIGO_INTERNO que SI tiene correspondencia en Vigentes nunca deberia
    # marcarse vencido solo porque (por datos viejos/duplicados) tambien
    # aparece en el dataset de Vencidos -- Vigentes manda si hay correspondencia
    resultado = _auditar(
        [_fila_gemanet("500-1")],
        [_fila_invima("500-1")],
        vencidos_filas=[_fila_invima("500-1")],
    )
    assert resultado.loc["500-1", "ESTADO_COHERENCIA"] == EstadoCoherencia.CORRECTO.value


def test_no_encontrado_en_ningun_lado_pero_si_en_otros_estados_es_encontrado_en_otro_estado():
    resultado = _auditar(
        [_fila_gemanet("999-9")],
        [_fila_invima("500-1")],
        otros_estados_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Inactivo")],
    )
    assert resultado.loc["999-9", "ESTADO_COHERENCIA"] == EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value


def test_estado_invima_detalle_lleva_el_estado_registro_real_de_otros_estados():
    # Otros Estados es heterogeneo (Cancelado/Suspendido/Inactivo/etc.) --
    # el detalle real no se puede esconder detras de una etiqueta generica
    resultado = _auditar(
        [_fila_gemanet("999-9")],
        [_fila_invima("500-1")],
        otros_estados_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Cancelado")],
    )
    assert resultado.loc["999-9", "ESTADO_INVIMA_DETALLE"] == "Cancelado"


def test_no_encontrado_en_ningun_lado_pero_si_en_renovacion_es_en_tramite_renovacion():
    resultado = _auditar(
        [_fila_gemanet("999-9")],
        [_fila_invima("500-1")],
        renovacion_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Tramite de Renovacion")],
    )
    assert resultado.loc["999-9", "ESTADO_COHERENCIA"] == EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value
    assert resultado.loc["999-9", "ESTADO_INVIMA_DETALLE"] == "Tramite de Renovacion"


def test_vencido_tiene_prioridad_sobre_otros_estados_si_aparece_en_ambos():
    resultado = _auditar(
        [_fila_gemanet("999-9")],
        [_fila_invima("500-1")],
        vencidos_filas=[_fila_invima("999-9")],
        otros_estados_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Inactivo")],
    )
    assert resultado.loc["999-9", "ESTADO_COHERENCIA"] == EstadoCoherencia.VENCIDO_EN_INVIMA.value
    assert resultado.loc["999-9", "ESTADO_INVIMA_DETALLE"] == ""


def test_otros_estados_tiene_prioridad_sobre_renovacion_si_aparece_en_ambos():
    resultado = _auditar(
        [_fila_gemanet("999-9")],
        [_fila_invima("500-1")],
        otros_estados_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Inactivo")],
        renovacion_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Tramite de Renovacion")],
    )
    assert resultado.loc["999-9", "ESTADO_COHERENCIA"] == EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value
    assert resultado.loc["999-9", "ESTADO_INVIMA_DETALLE"] == "Inactivo"


def test_codigo_correcto_no_se_reclasifica_aunque_aparezca_en_otros_estados_o_renovacion():
    resultado = _auditar(
        [_fila_gemanet("500-1")],
        [_fila_invima("500-1")],
        otros_estados_filas=[_fila_invima("500-1", ESTADO_REGISTRO="Inactivo")],
        renovacion_filas=[_fila_invima("500-1", ESTADO_REGISTRO="Tramite de Renovacion")],
    )
    assert resultado.loc["500-1", "ESTADO_COHERENCIA"] == EstadoCoherencia.CORRECTO.value


def test_estado_invima_detalle_vacio_cuando_no_aplica():
    resultado = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    assert resultado.loc["500-1", "ESTADO_INVIMA_DETALLE"] == ""


def test_datasets_otros_estados_y_renovacion_vacios_no_rompen():
    resultado = _auditar(
        [_fila_gemanet("999-9")],
        [_fila_invima("500-1")],
        otros_estados_filas=[],
        renovacion_filas=[],
    )
    assert resultado.loc["999-9", "ESTADO_COHERENCIA"] == EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value


def test_estado_registro_tramite_renov_dentro_de_otros_estados_se_reclasifica_como_renovacion():
    # valor real confirmado contra el archivo real de Otros Estados
    # (2026-08-19): "Temp. no comercializado - En Tramite Renov" significa
    # lo mismo que el dataset separado de Renovacion -- decision confirmada
    # por el usuario, no debe quedar como riesgo alto (otro estado)
    resultado = _auditar(
        [_fila_gemanet("999-9")],
        [_fila_invima("500-1")],
        otros_estados_filas=[
            _fila_invima("999-9", ESTADO_REGISTRO="Temp. no comercializado - En Tramite Renov")
        ],
    )
    assert resultado.loc["999-9", "ESTADO_COHERENCIA"] == EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value
    assert resultado.loc["999-9", "ESTADO_INVIMA_DETALLE"] == "Temp. no comercializado - En Tramite Renov"


def test_estado_registro_cancelado_dentro_de_otros_estados_sigue_siendo_otro_estado():
    resultado = _auditar(
        [_fila_gemanet("999-9")],
        [_fila_invima("500-1")],
        otros_estados_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Cancelado")],
    )
    assert resultado.loc["999-9", "ESTADO_COHERENCIA"] == EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value


def test_subset_de_renovacion_en_otros_estados_no_afecta_otros_codigos_del_mismo_dataset():
    resultado = _auditar(
        [_fila_gemanet("111-1"), _fila_gemanet("222-2")],
        [_fila_invima("500-1")],
        otros_estados_filas=[
            _fila_invima("111-1", ESTADO_REGISTRO="Temp. no comercializado - En Tramite Renov"),
            _fila_invima("222-2", ESTADO_REGISTRO="Negado"),
        ],
    )
    assert resultado.loc["111-1", "ESTADO_COHERENCIA"] == EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value
    assert resultado.loc["222-2", "ESTADO_COHERENCIA"] == EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value


def test_subset_de_renovacion_en_otros_estados_se_combina_con_dataset_dedicado_de_renovacion():
    # un codigo real del dataset dedicado de Renovacion y otro que viene del
    # subset reclasificado de Otros Estados deben quedar ambos en el mismo
    # estado, sin que uno pise al otro
    resultado = _auditar(
        [_fila_gemanet("111-1"), _fila_gemanet("222-2")],
        [_fila_invima("500-1")],
        renovacion_filas=[_fila_invima("111-1", ESTADO_REGISTRO="Tramite de Renovacion")],
        otros_estados_filas=[
            _fila_invima("222-2", ESTADO_REGISTRO="Temp. no comercializado - En Tramite Renov")
        ],
    )
    assert resultado.loc["111-1", "ESTADO_COHERENCIA"] == EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value
    assert resultado.loc["222-2", "ESTADO_COHERENCIA"] == EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value


# ---- Calidad #9: INTEGRIDAD_REFERENCIAL_CATALOGO -- MARCA_MEDICAMENTO/
# UNIDAD_MEDIDA deben ser codigos que EXISTAN en el catalogo interno
# (config/catalogos/*.csv), no solo comparables contra INVIMA ----

def test_marca_medicamento_con_codigo_huerfano_se_detecta_con_mensaje_accionable():
    resultado = _auditar(
        [_fila_gemanet("500-1", MARCA_MEDICAMENTO=999)], [_fila_invima("500-1")]
    )
    hallazgo = resultado.loc["500-1", "INTEGRIDAD_REFERENCIAL_CATALOGO"]
    assert "MARCA_MEDICAMENTO" in hallazgo
    assert "999" in hallazgo
    assert "marca_medicamento.csv" in hallazgo


def test_unidad_medida_con_codigo_huerfano_se_detecta_con_mensaje_accionable():
    resultado = _auditar(
        [_fila_gemanet("500-1", UNIDAD_MEDIDA=888)], [_fila_invima("500-1")]
    )
    hallazgo = resultado.loc["500-1", "INTEGRIDAD_REFERENCIAL_CATALOGO"]
    assert "UNIDAD_MEDIDA" in hallazgo
    assert "888" in hallazgo
    assert "unidad_medida.csv" in hallazgo


def test_marca_y_unidad_con_codigos_validos_no_generan_hallazgo_de_integridad_referencial():
    resultado = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    assert resultado.loc["500-1", "INTEGRIDAD_REFERENCIAL_CATALOGO"] == ""


def test_marca_y_unidad_huerfanas_a_la_vez_reportan_ambos_hallazgos():
    resultado = _auditar(
        [_fila_gemanet("500-1", MARCA_MEDICAMENTO=999, UNIDAD_MEDIDA=888)],
        [_fila_invima("500-1")],
    )
    hallazgo = resultado.loc["500-1", "INTEGRIDAD_REFERENCIAL_CATALOGO"]
    assert "MARCA_MEDICAMENTO" in hallazgo
    assert "UNIDAD_MEDIDA" in hallazgo


def test_tipo_sin_correspondencia_distingue_formato_invima_de_codigo_legado():
    # "111-1" sigue el patron EXPEDIENTE-CONSECUTIVO pero no aparece en
    # INVIMA -- amerita revision puntual (posible error de digitacion).
    # "ZIAL" es un codigo legado real (ver armado/cruce_gemanet.py): nunca
    # tuvo expediente, no hay nada que revisar contra INVIMA
    resultado = _auditar(
        [_fila_gemanet("111-1"), _fila_gemanet("ZIAL")], [_fila_invima("500-1")]
    )
    assert "EXPEDIENTE-CONSECUTIVO" in resultado.loc["111-1", "TIPO_SIN_CORRESPONDENCIA"]
    assert "legado" in resultado.loc["ZIAL", "TIPO_SIN_CORRESPONDENCIA"]


def test_tipo_sin_correspondencia_vacio_para_filas_que_no_son_sin_correspondencia():
    resultado = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    assert resultado.loc["500-1", "TIPO_SIN_CORRESPONDENCIA"] == ""


def test_tipo_sin_correspondencia_vacio_para_otro_estado_y_renovacion():
    # mismo criterio que vencido -- ya son su propia clasificacion clara
    resultado = _auditar(
        [_fila_gemanet("999-9"), _fila_gemanet("888-8")],
        [_fila_invima("500-1")],
        otros_estados_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Inactivo")],
        renovacion_filas=[_fila_invima("888-8", ESTADO_REGISTRO="Tramite de Renovacion")],
    )
    assert resultado.loc["999-9", "TIPO_SIN_CORRESPONDENCIA"] == ""
    assert resultado.loc["888-8", "TIPO_SIN_CORRESPONDENCIA"] == ""


def test_tipo_sin_correspondencia_vacio_para_vencido_en_invima():
    # vencido ya es su propia clasificacion clara -- no necesita ademas un
    # TIPO_SIN_CORRESPONDENCIA, seria redundante/confuso
    resultado = _auditar(
        [_fila_gemanet("999-9")], [_fila_invima("500-1")], vencidos_filas=[_fila_invima("999-9")]
    )
    assert resultado.loc["999-9", "TIPO_SIN_CORRESPONDENCIA"] == ""


def test_fecha_fin_anterior_a_fecha_inicio_es_inconsistencia():
    resultado = _auditar(
        [_fila_gemanet("500-1", ACTIVO="SI", FECHA_INICIO="2026-06-01", FECHA_FIN="2026-01-01")],
        [_fila_invima("500-1")],
    )
    assert "FECHA_FIN anterior a FECHA_INICIO" in resultado.loc["500-1", "INCONSISTENCIA_FECHAS_ACTIVO"]


def test_activo_no_sin_fecha_fin_es_inconsistencia():
    resultado = _auditar(
        [_fila_gemanet("500-1", ACTIVO="NO", FECHA_INICIO="2026-01-01", FECHA_FIN=None)],
        [_fila_invima("500-1")],
    )
    assert "ACTIVO=NO sin FECHA_FIN" in resultado.loc["500-1", "INCONSISTENCIA_FECHAS_ACTIVO"]


def test_activo_si_con_fecha_fin_pasada_es_inconsistencia():
    resultado = _auditar(
        [_fila_gemanet("500-1", ACTIVO="SI", FECHA_INICIO="2020-01-01", FECHA_FIN="2020-06-01")],
        [_fila_invima("500-1")],
    )
    assert "FECHA_FIN ya paso" in resultado.loc["500-1", "INCONSISTENCIA_FECHAS_ACTIVO"]


def test_fechas_coherentes_no_generan_inconsistencia():
    resultado = _auditar(
        [_fila_gemanet("500-1", ACTIVO="SI", FECHA_INICIO="2020-01-01", FECHA_FIN=None)],
        [_fila_invima("500-1")],
    )
    assert resultado.loc["500-1", "INCONSISTENCIA_FECHAS_ACTIVO"] == ""


def test_fechas_ausentes_o_no_parseables_no_generan_inconsistencia_por_si_solas():
    # un dato de fecha faltante/invalido es un problema de formato de
    # archivo, no una inconsistencia de logica de negocio -- no se asume
    # nada sobre una fecha que no se pudo leer
    resultado = _auditar(
        [_fila_gemanet("500-1", ACTIVO="SI", FECHA_INICIO="no-es-una-fecha", FECHA_FIN=None)],
        [_fila_invima("500-1")],
    )
    assert resultado.loc["500-1", "INCONSISTENCIA_FECHAS_ACTIVO"] == ""


def test_activo_si_con_registro_vencido_en_invima_es_inconsistencia_de_mayor_riesgo():
    resultado = _auditar(
        [_fila_gemanet("999-9", ACTIVO="SI", FECHA_INICIO="2020-01-01", FECHA_FIN=None)],
        [_fila_invima("500-1")],
        vencidos_filas=[_fila_invima("999-9")],
    )
    inconsistencia = resultado.loc["999-9", "INCONSISTENCIA_FECHAS_ACTIVO"]
    assert "VENCIDO en INVIMA" in inconsistencia


def test_activo_no_con_registro_vencido_en_invima_no_agrega_la_inconsistencia_de_riesgo():
    # la combinacion de riesgo especifica es ACTIVO=SI -- si ya esta
    # ACTIVO=NO, no hay contradiccion que senalar ahi
    resultado = _auditar(
        [_fila_gemanet("999-9", ACTIVO="NO", FECHA_INICIO="2020-01-01", FECHA_FIN="2020-06-01")],
        [_fila_invima("500-1")],
        vencidos_filas=[_fila_invima("999-9")],
    )
    assert "VENCIDO en INVIMA" not in resultado.loc["999-9", "INCONSISTENCIA_FECHAS_ACTIVO"]


# ---- Calidad #4: COMPLETITUD ----

def test_completitud_reporte_100_cuando_todos_los_campos_del_cargue_estan_diligenciados():
    # CODIGO_INTERNO se excluye del spread -- ya lo fija _fila_gemanet por
    # su primer argumento posicional, incluirlo aca lo sobreescribiria
    campos = {c: "VALOR" for c in _CAMPOS_COMPLETITUD_REPORTE if c != "CODIGO_INTERNO"}
    resultado = _auditar([_fila_gemanet("500-1", **campos)], [_fila_invima("500-1")])
    assert resultado.loc["500-1", "PORCENTAJE_COMPLETITUD_REPORTE"] == 100.0


def test_completitud_reporte_baja_si_faltan_campos_del_cargue():
    campos = {c: "VALOR" for c in _CAMPOS_COMPLETITUD_REPORTE if c != "CODIGO_INTERNO"}
    campos["GRUPO_MEDICAMENTO"] = ""  # 1 de 37 vacio
    resultado = _auditar([_fila_gemanet("500-1", **campos)], [_fila_invima("500-1")])
    porcentaje = resultado.loc["500-1", "PORCENTAJE_COMPLETITUD_REPORTE"]
    assert porcentaje == round((len(_CAMPOS_COMPLETITUD_REPORTE) - 1) / len(_CAMPOS_COMPLETITUD_REPORTE) * 100, 1)


def test_completitud_reporte_error_de_excel_cuenta_como_no_diligenciado():
    campos = {c: "VALOR" for c in _CAMPOS_COMPLETITUD_REPORTE if c != "CODIGO_INTERNO"}
    campos["VALOR"] = "#N/A"  # un error de formula de Excel guardado como texto
    resultado = _auditar([_fila_gemanet("500-1", **campos)], [_fila_invima("500-1")])
    assert resultado.loc["500-1", "PORCENTAJE_COMPLETITUD_REPORTE"] < 100.0


def test_advertencia_campo_sistemicamente_no_diligenciado_cuando_casi_todo_es_menos_999():
    # POSOLOGIA="-999" en (casi) todas las filas -- señal de proceso, no de
    # datos faltantes puntuales. Caso real medido sobre el reporte completo
    # de produccion (2026-08-19): POSOLOGIA trae "-999" en el 99.9% de las
    # 199.689 filas.
    campos = {c: "VALOR" for c in _CAMPOS_COMPLETITUD_REPORTE if c != "CODIGO_INTERNO"}
    campos["POSOLOGIA"] = "-999"
    filas = [_fila_gemanet(f"{500 + i}-1", **campos) for i in range(10)]
    resultado = _auditar(filas, [_fila_invima(f"{500 + i}-1") for i in range(10)])
    advertencias = resultado.attrs.get("advertencias_calidad", [])
    assert any("POSOLOGIA" in a and "100.0%" in a for a in advertencias)


def test_sin_advertencia_sistemica_cuando_el_campo_si_esta_diligenciado():
    campos = {c: "VALOR" for c in _CAMPOS_COMPLETITUD_REPORTE if c != "CODIGO_INTERNO"}
    resultado = _auditar([_fila_gemanet("500-1", **campos)], [_fila_invima("500-1")])
    assert resultado.attrs.get("advertencias_calidad", []) == []


def test_completitud_reporte_sentinela_menos_999_cuenta_como_no_diligenciado():
    # "-999" confirmado contra el reporte real de Gemma Net (2026-08-19) como
    # sentinela de "sin dato" en EXPEDIENTE/CONSECUTIVO para codigo legado.
    campos = {c: "VALOR" for c in _CAMPOS_COMPLETITUD_REPORTE if c != "CODIGO_INTERNO"}
    campos["EXPEDIENTE"] = "-999"
    campos["CONSECUTIVO"] = "-999"
    resultado = _auditar([_fila_gemanet("500-1", **campos)], [_fila_invima("500-1")])
    porcentaje = resultado.loc["500-1", "PORCENTAJE_COMPLETITUD_REPORTE"]
    assert porcentaje == round((len(_CAMPOS_COMPLETITUD_REPORTE) - 2) / len(_CAMPOS_COMPLETITUD_REPORTE) * 100, 1)


# ---- Calidad #5: UNICIDAD ----

def test_codigo_duplicado_en_reporte_se_detecta():
    resultado = _auditar(
        [_fila_gemanet("500-1"), _fila_gemanet("500-1")], [_fila_invima("500-1")]
    )
    assert resultado.loc["500-1", "CODIGO_DUPLICADO_EN_REPORTE"].all()


def test_codigo_no_duplicado_en_reporte_no_se_marca():
    resultado = _auditar(
        [_fila_gemanet("500-1"), _fila_gemanet("600-1")], [_fila_invima("500-1")]
    )
    assert not resultado.loc["500-1", "CODIGO_DUPLICADO_EN_REPORTE"]
    assert not resultado.loc["600-1", "CODIGO_DUPLICADO_EN_REPORTE"]


# ---- Calidad #6: VALIDEZ DE DOMINIO ----

def test_clasificado_fuera_de_dominio_se_detecta():
    resultado = _auditar(
        [_fila_gemanet("500-1", CLASIFICADO="TAL VEZ")], [_fila_invima("500-1")]
    )
    assert "CLASIFICADO fuera de dominio" in resultado.loc["500-1", "VALORES_FUERA_DE_DOMINIO"]


def test_clasificado_valido_no_se_marca():
    resultado = _auditar(
        [_fila_gemanet("500-1", CLASIFICADO="SI")], [_fila_invima("500-1")]
    )
    assert resultado.loc["500-1", "VALORES_FUERA_DE_DOMINIO"] == ""


def test_pos_fuera_de_dominio_se_detecta():
    resultado = _auditar(
        [_fila_gemanet("500-1", POS="TALVEZ")], [_fila_invima("500-1")]
    )
    assert "POS fuera de dominio" in resultado.loc["500-1", "VALORES_FUERA_DE_DOMINIO"]


def test_codigo_nivel_servicio_fuera_de_dominio_se_detecta():
    resultado = _auditar(
        [_fila_gemanet("500-1", CODIGO_NIVEL_SERVICIO="Nivel 9")], [_fila_invima("500-1")]
    )
    assert "CODIGO_NIVEL_SERVICIO fuera de dominio" in resultado.loc["500-1", "VALORES_FUERA_DE_DOMINIO"]


# ---- Calidad #7: RAZONABILIDAD NUMERICA ----

def test_edad_minima_mayor_a_edad_maxima_es_inconsistencia():
    resultado = _auditar(
        [_fila_gemanet("500-1", EDAD_MINIMA=50, EDAD_MAXIMA=10)], [_fila_invima("500-1")]
    )
    assert "EDAD_MINIMA mayor a EDAD_MAXIMA" in resultado.loc["500-1", "INCONSISTENCIA_NUMERICA"]


def test_edades_coherentes_no_generan_inconsistencia():
    resultado = _auditar(
        [_fila_gemanet("500-1", EDAD_MINIMA=0, EDAD_MAXIMA=100)], [_fila_invima("500-1")]
    )
    assert resultado.loc["500-1", "INCONSISTENCIA_NUMERICA"] == ""


def test_topes_de_uso_desordenados_son_inconsistencia():
    resultado = _auditar(
        [_fila_gemanet("500-1", MAXIMA_VECES_DIA=10, MAXIMA_VECES_MESES=2)], [_fila_invima("500-1")]
    )
    assert "MAXIMA_VECES_DIA mayor a MAXIMA_VECES_MESES" in resultado.loc["500-1", "INCONSISTENCIA_NUMERICA"]


def test_valor_negativo_es_inconsistencia():
    resultado = _auditar(
        [_fila_gemanet("500-1", EDAD_MINIMA=-5)], [_fila_invima("500-1")]
    )
    assert "EDAD_MINIMA negativo" in resultado.loc["500-1", "INCONSISTENCIA_NUMERICA"]


def test_numeros_ausentes_no_generan_inconsistencia_por_si_solos():
    resultado = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    assert resultado.loc["500-1", "INCONSISTENCIA_NUMERICA"] == ""


# ---- Calidad #8: CONFORMIDAD DE FORMATO ----

def test_codigo_interno_error_de_excel_se_detecta():
    resultado = _auditar(
        [_fila_gemanet("#N/A")], [_fila_invima("500-1")]
    )
    assert "error de formula de Excel" in resultado.loc["#N/A", "FORMATO_CODIGO_INTERNO_INVALIDO"]


def test_codigo_interno_valido_no_se_marca():
    resultado = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    assert resultado.loc["500-1", "FORMATO_CODIGO_INTERNO_INVALIDO"] == ""
