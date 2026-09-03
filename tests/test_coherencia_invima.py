import pandas as pd

from gemma_cum_loader.auditoria.coherencia_invima import (
    _CAMPOS_COMPLETITUD_REPORTE,
    ACCION_POR_NATURALEZA,
    CAMPOS_COMPARADOS_COHERENCIA,
    NATURALEZA_CARGA_INCOMPLETA,
    NATURALEZA_DESACTUALIZADO,
    NATURALEZA_RESIDUAL_MIGRACION,
    EstadoCoherencia,
    auditar_coherencia,
    filtrar_universo_auditable,
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
        # Como la arma Gemma Net: PRINCIPIO_ACTIVO + CANTIDAD+UNIDAD + FORMA.
        # Antes decia "ACETAMINOFEN TABLETA", que codificaba la formula vieja
        # (PA + UNIDAD_REFERENCIA) -- la que fallaba en el 100 % de los casos
        # reales. Ver _descripcion_esperada_invima.
        "DESCRIPCION": "ACETAMINOFEN 500MG TABLETA",
        # El campo se llama CONCENTRACION pero Gemma Net guarda ahi la
        # PRESENTACION COMERCIAL. No es un descuido del fixture: es lo que
        # trae el dato real, y por eso se compara contra DESCRIPCION_COMERCIAL
        # de INVIMA y no contra su columna homonima (ver _CAMPOS_DIRECTOS).
        "CONCENTRACION": "CAJA POR 100 TABLETAS EN BLISTER PVC/ALUMINIO",
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
        "CANTIDAD": 500,
        "PRINCIPIO_ACTIVO": "ACETAMINOFEN",
        # UNIDAD_REFERENCIA se conserva porque el archivo real la trae, pero
        # ya NO participa de la descripcion esperada: es una frase ("CADA
        # CAPSULA DE GELATINA DURA CONTIENE"), no un dato.
        "UNIDAD_REFERENCIA": "CADA TABLETA CONTIENE",
        # CONCENTRACION de INVIMA si es una concentracion. Se deja en el
        # fixture -- distinta de la del reporte -- justamente para que se note
        # si alguien vuelve a mapearla contra el CONCENTRACION local: la
        # comparacion pasaria a fallar en el 100 % de las filas, como pasaba
        # antes del 2026-08-21.
        "CONCENTRACION": "500 MG",
        "DESCRIPCION_COMERCIAL": "CAJA POR 100 TABLETAS EN BLISTER PVC/ALUMINIO",
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


def test_naturaleza_separa_residual_de_migracion_de_cargue_incompleto():
    """Una fecha comodin y una fecha en blanco piden cosas distintas.

    "1900-01-01"/"2999-12-31" son fechas que la migracion ESCRIBIO para no
    dejar la celda vacia: no se corrigen fila por fila. Una fecha realmente
    en blanco si hay que diligenciarla. En produccion son 11.526 contra
    1.636, y mezclarlas volvia el reporte inmanejable.
    """
    residual = _auditar(
        [_fila_gemanet("500-1", ACTIVO="No", FECHA_INICIO="2006-11-10", FECHA_FIN="2999-12-31")],
        [_fila_invima("500-1")],
    ).loc["500-1"]
    assert residual["NATURALEZA_HALLAZGO"] == NATURALEZA_RESIDUAL_MIGRACION

    en_blanco = _auditar(
        [_fila_gemanet("500-1", ACTIVO="No", FECHA_INICIO="2006-11-10", FECHA_FIN="")],
        [_fila_invima("500-1")],
    ).loc["500-1"]
    assert en_blanco["NATURALEZA_HALLAZGO"] == NATURALEZA_CARGA_INCOMPLETA


def test_naturaleza_prioriza_lo_que_pide_trabajo_sobre_lo_que_no():
    """Un dato desactualizado gana a un residual de migracion: el residual no
    pide nada, y si compitiera hacia arriba taparia lo que si hay que hacer."""
    fila = _auditar(
        [
            _fila_gemanet(
                "500-1",
                CODIGO_ATC="OTRO",
                ACTIVO="No",
                FECHA_INICIO="2006-11-10",
                FECHA_FIN="1900-01-01",
            )
        ],
        [_fila_invima("500-1")],
    ).loc["500-1"]
    assert fila["NATURALEZA_HALLAZGO"] == NATURALEZA_DESACTUALIZADO
    assert fila["ACCION_SUGERIDA"] == ACCION_POR_NATURALEZA[NATURALEZA_DESACTUALIZADO]


def test_sin_hallazgos_la_naturaleza_queda_vacia():
    fila = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")]).loc["500-1"]
    assert fila["NATURALEZA_HALLAZGO"] == ""
    assert fila["ACCION_SUGERIDA"] == ""


def test_marca_sin_informacion_no_se_reporta_como_diferencia_con_invima():
    """Codigo 1 = "SIN INFORMACION": la marca no esta registrada, no esta mal.

    Contarlo como "no coincide con INVIMA" producia 40.044 hallazgos de marca
    en produccion -- el 93 % de todo lo comparable -- para lo que en realidad
    es UN problema: el campo no se esta diligenciando. La ausencia se sigue
    viendo, pero en COMPLETITUD, que es su dimension.
    """
    resultado = _auditar(
        [_fila_gemanet("500-1", MARCA_MEDICAMENTO=1)], [_fila_invima("500-1")]
    ).loc["500-1"]
    assert resultado["MARCA_MEDICAMENTO_VALIDACION"] == "sin dato en Gemma Net"
    assert "MARCA_MEDICAMENTO" not in resultado["CAMPOS_CON_DIFERENCIA"]
    # y el campo sale del denominador: 6 comparables, 6 coinciden
    assert resultado["PORCENTAJE_CALIDAD"] == 100.0


def test_campo_en_menos_999_tampoco_cuenta_como_diferencia():
    """Mismo criterio para el centinela de texto que para el de catalogo."""
    resultado = _auditar(
        [_fila_gemanet("500-1", CODIGO_ATC="-999")], [_fila_invima("500-1")]
    ).loc["500-1"]
    assert resultado["CODIGO_ATC_VALIDACION"] == "sin dato en Gemma Net"
    assert resultado["PORCENTAJE_CALIDAD"] == 100.0


def test_unidad_coincide_con_cualquiera_de_las_siglas_del_codigo():
    """Un codigo con varias entradas no tiene una forma "buena" y otras malas.

    El codigo 10001000 (miligramo) trae en el catalogo real "MG - MILIGRAMO",
    "mg/parche", "mg (titer)" y "mg/CAP". Al quedarse con una sola, la
    auditoria mostraba "MG/CAP" y lo daba por distinto del "mg" de INVIMA:
    33.677 filas de produccion, el 95 % de las diferencias de unidad, sin que
    ninguna fuera un problema del dato.
    """
    catalogo_varias = cargar_catalogo(
        [(10, "MG - MILIGRAMO"), (10, "mg/parche"), (10, "mg/CAP")]
    )
    resultado = auditar_coherencia(
        pd.DataFrame([_fila_gemanet("500-1")]),
        pd.DataFrame([_fila_invima("500-1")]),
        catalogo_varias,
        _CATALOGO_MARCA,
    ).set_index("CODIGO_INTERNO")
    fila = resultado.loc["500-1"]
    assert fila["UNIDAD_MEDIDA_VALIDACION"] == "coincide"
    assert fila["ESTADO_COHERENCIA"] == EstadoCoherencia.CORRECTO.value


def test_unidad_que_no_calza_con_ninguna_sigla_del_codigo_sigue_siendo_hallazgo():
    """El conjunto amplia lo aceptable, no lo vuelve todo aceptable."""
    catalogo_varias = cargar_catalogo(
        [(10, "MG - MILIGRAMO"), (10, "mg/parche"), (10, "mg/CAP")]
    )
    resultado = auditar_coherencia(
        pd.DataFrame([_fila_gemanet("500-1")]),
        pd.DataFrame([_fila_invima("500-1", UNIDAD_MEDIDA="UI")]),
        catalogo_varias,
        _CATALOGO_MARCA,
    ).set_index("CODIGO_INTERNO")
    fila = resultado.loc["500-1"]
    assert fila["UNIDAD_MEDIDA_VALIDACION"] == "difiere"
    assert "UNIDAD_MEDIDA" in fila["CAMPOS_CON_DIFERENCIA"]


def test_concentracion_local_se_compara_contra_descripcion_comercial_de_invima():
    """El campo CONCENTRACION del reporte guarda la PRESENTACION comercial.

    Su equivalente en INVIMA es DESCRIPCION_COMERCIAL, no la columna del mismo
    nombre. Mapearlo mal hacia fallar el 100 % de las filas (2 exactas sobre
    43.266 medidas contra produccion) y dejaba ESTADO_COHERENCIA=correcto en
    cero para todo el reporte. Aca la presentacion coincide y la concentracion
    de INVIMA es distinta: si alguien invierte el mapeo, este test lo dice.
    """
    resultado = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    fila = resultado.loc["500-1"]
    assert fila["CONCENTRACION_VALIDACION"] == "coincide"
    assert fila["CONCENTRACION_INVIMA"] == "CAJA POR 100 TABLETAS EN BLISTER PVC/ALUMINIO"


def test_trio_de_columnas_por_campo_trae_los_dos_lados_y_el_veredicto():
    """Por cada campo comparable: valor local, valor de INVIMA y veredicto.

    Los valores van CRUDOS -- la normalizacion existe para comparar, no para
    mostrar -- y de MARCA/UNIDAD se muestra el texto resuelto y no el codigo,
    porque un codigo al lado del titular de INVIMA no deja comparar nada.
    """
    resultado = _auditar(
        [_fila_gemanet("500-1", PRINCIPIO_ACTIVO="acetaminofen  ")], [_fila_invima("500-1")]
    )
    fila = resultado.loc["500-1"]
    for campo in CAMPOS_COMPARADOS_COHERENCIA:
        assert f"{campo}_GEMANET" in fila.index
        assert f"{campo}_INVIMA" in fila.index
        assert f"{campo}_VALIDACION" in fila.index
    # crudo: se muestra tal cual esta guardado, con sus espacios
    assert fila["PRINCIPIO_ACTIVO_GEMANET"] == "acetaminofen  "
    # ...pero el veredicto si usa la normalizacion
    assert fila["PRINCIPIO_ACTIVO_VALIDACION"] == "coincide"
    assert fila["MARCA_MEDICAMENTO_GEMANET"] == normalizar_entidad("ACME SAS")
    assert fila["MARCA_MEDICAMENTO_INVIMA"] == "ACME SAS"


def test_veredicto_es_sin_comparar_cuando_no_hay_correspondencia_en_invima():
    """"sin comparar" no es "coincide": sin correspondencia no hay contra que
    validar. Mismo criterio que PORCENTAJE_CALIDAD, que queda vacio y no en 0."""
    resultado = _auditar([_fila_gemanet("999-9")], [_fila_invima("500-1")])
    fila = resultado.loc["999-9"]
    for campo in CAMPOS_COMPARADOS_COHERENCIA:
        assert fila[f"{campo}_VALIDACION"] == "sin comparar"


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


def test_un_alias_de_unidad_no_se_reporta_como_diferencia():
    """"IU" es la sigla inglesa de "UI": es la misma unidad, no un hallazgo.

    Los alias son equivalencias auditadas a mano que la normalizacion de texto
    no puede deducir sola. Ya existian y los usaba la cascada de resolucion,
    pero la auditoria comparaba los textos crudos. Medido contra produccion el
    2026-08-24: 459 de las 984 diferencias de UNIDAD_MEDIDA -- el 47 % -- eran
    dos pares de alias, y ninguna era un problema del dato.
    """
    resultado = auditar_coherencia(
        pd.DataFrame([_fila_gemanet("500-1", UNIDAD_MEDIDA=10)]),
        pd.DataFrame([_fila_invima("500-1", UNIDAD_MEDIDA="IU")]),
        cargar_catalogo([(10, "UI - UNIDAD INTERNACIONAL")]),
        _CATALOGO_MARCA,
        alias_unidad={"IU": "UI"},
    ).set_index("CODIGO_INTERNO")
    assert resultado.loc["500-1", "UNIDAD_MEDIDA_VALIDACION"] == "coincide"


def test_sin_alias_esa_misma_unidad_si_se_reporta_como_diferencia():
    """El alias es lo que resuelve el caso, no la normalizacion: sin el mapa
    la auditoria no tiene como saber que IU y UI son lo mismo."""
    resultado = auditar_coherencia(
        pd.DataFrame([_fila_gemanet("500-1", UNIDAD_MEDIDA=10)]),
        pd.DataFrame([_fila_invima("500-1", UNIDAD_MEDIDA="IU")]),
        cargar_catalogo([(10, "UI - UNIDAD INTERNACIONAL")]),
        _CATALOGO_MARCA,
    ).set_index("CODIGO_INTERNO")
    assert resultado.loc["500-1", "UNIDAD_MEDIDA_VALIDACION"] == "difiere"


def test_el_alias_no_hace_coincidir_unidades_de_verdad_distintas():
    """La red de seguridad: miligramos y gramos NO son lo mismo, y un alias
    mal puesto no puede convertir un hallazgo real en un "coincide"."""
    resultado = auditar_coherencia(
        pd.DataFrame([_fila_gemanet("500-1", UNIDAD_MEDIDA=10)]),
        pd.DataFrame([_fila_invima("500-1", UNIDAD_MEDIDA="g")]),
        cargar_catalogo([(10, "MG - MILIGRAMO")]),
        _CATALOGO_MARCA,
        alias_unidad={"IU": "UI"},
    ).set_index("CODIGO_INTERNO")
    assert resultado.loc["500-1", "UNIDAD_MEDIDA_VALIDACION"] == "difiere"


def test_temp_no_comercializado_vigente_no_es_riesgo_de_vigencia():
    """INVIMA dice "Vigente" en la misma celda: no se puede pintar como riesgo.

    Dentro de Otros Estados hay filas cuyo ESTADO_REGISTRO dice literalmente
    "Temp. no comerc - Vigente": el registro sanitario esta al dia y lo unico
    que pasa es que el producto no se comercializa ahora. Medido contra
    produccion el 2026-08-24, eran 2.887 de los 10.469 que la auditoria
    marcaba como riesgo alto -- el 27,6 %.
    """
    resultado = _auditar(
        [_fila_gemanet("999-9")],
        [_fila_invima("500-1")],
        otros_estados_filas=[
            _fila_invima("999-9", ESTADO_REGISTRO="Temp. no comerc - Vigente")
        ],
    )
    assert (
        resultado.loc["999-9", "ESTADO_COHERENCIA"]
        == EstadoCoherencia.VIGENTE_NO_COMERCIALIZADO_INVIMA.value
    )


def test_activo_aqui_y_sin_vigencia_en_invima_es_riesgo_no_reactivacion():
    """"Revisar reactivacion" solo tiene sentido si esta INACTIVO aca.

    Un medicamento ACTIVO en Gemma Net cuyo registro INVIMA dio por Negado no
    es candidato a reactivar: es el riesgo mas alto que hay. Se estaba
    etiquetando como leve -- 28 casos reales quedaban invisibles, y la tarjeta
    "inactivo(s) aqui pero vigente(s) en INVIMA" contaba 18.360 filas que en
    realidad estaban activas.
    """
    resultado = _auditar(
        [_fila_gemanet("999-9", ACTIVO="Si")],
        [_fila_invima("500-1")],
        otros_estados_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Negado")],
    )
    assert resultado.loc["999-9", "NOVEDAD_VIGENCIA_INVIMA"] == "riesgo_activo_sin_vigencia"


def test_inactivo_aqui_y_en_otro_estado_si_es_revisar_reactivacion():
    """El caso legitimo de la etiqueta: aca inactivo, alla no vencido."""
    resultado = _auditar(
        [_fila_gemanet("999-9", ACTIVO="No")],
        [_fila_invima("500-1")],
        otros_estados_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Negado")],
    )
    assert resultado.loc["999-9", "NOVEDAD_VIGENCIA_INVIMA"] == "revisar_reactivacion"


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


def test_marca_ausente_se_detecta_como_medicamento_cargado_sin_marca():
    """Antes pasaba invisible: la condicion exigia notna(), asi que una fila
    sin codigo de marca no entraba al diagnostico, se resolvia en silencio a
    texto vacio y salia como CON_DIFERENCIAS -- justo el diagnostico enganoso
    que esta dimension existe para evitar. Medido en produccion: 99 filas."""
    resultado = _auditar(
        [_fila_gemanet("500-1", MARCA_MEDICAMENTO=None)], [_fila_invima("500-1")]
    )
    hallazgo = resultado.loc["500-1", "INTEGRIDAD_REFERENCIAL_CATALOGO"]
    assert "MARCA_MEDICAMENTO" in hallazgo
    assert "sin dato" in hallazgo
    assert "sin marca" in hallazgo


def test_unidad_ausente_se_detecta_como_medicamento_cargado_sin_unidad():
    resultado = _auditar(
        [_fila_gemanet("500-1", UNIDAD_MEDIDA=None)], [_fila_invima("500-1")]
    )
    hallazgo = resultado.loc["500-1", "INTEGRIDAD_REFERENCIAL_CATALOGO"]
    assert "UNIDAD_MEDIDA" in hallazgo
    assert "sin unidad de medida" in hallazgo


def test_centinela_menos_999_es_sin_dato_no_codigo_huerfano():
    """-999 es el centinela de "sin dato" de Gemma Net: reportarlo como codigo
    huerfano mandaria a alguien a agregar "-999" al catalogo interno."""
    resultado = _auditar(
        [_fila_gemanet("500-1", MARCA_MEDICAMENTO=-999)], [_fila_invima("500-1")]
    )
    hallazgo = resultado.loc["500-1", "INTEGRIDAD_REFERENCIAL_CATALOGO"]
    assert "sin dato" in hallazgo
    assert "no existe en el catalogo" not in hallazgo


def test_codigo_cero_se_trata_como_sin_dato_no_como_huerfano():
    """0 aparece en el reporte real con el mismo sentido que -999 (medido
    2026-08-20: 13 filas con UNIDAD_MEDIDA=0)."""
    resultado = _auditar(
        [_fila_gemanet("500-1", UNIDAD_MEDIDA=0)], [_fila_invima("500-1")]
    )
    hallazgo = resultado.loc["500-1", "INTEGRIDAD_REFERENCIAL_CATALOGO"]
    assert "sin dato" in hallazgo
    assert "no existe en el catalogo" not in hallazgo


def test_marca_ausente_y_unidad_huerfana_reportan_las_dos_fallas_distintas():
    resultado = _auditar(
        [_fila_gemanet("500-1", MARCA_MEDICAMENTO=None, UNIDAD_MEDIDA=888)],
        [_fila_invima("500-1")],
    )
    hallazgo = resultado.loc["500-1", "INTEGRIDAD_REFERENCIAL_CATALOGO"]
    assert "MARCA_MEDICAMENTO sin dato" in hallazgo
    assert "UNIDAD_MEDIDA (codigo 888)" in hallazgo


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


def test_campos_calidad_mascaras_selecciona_exactamente_las_filas_sin_dato():
    """La UI usa `campos_calidad_mascaras` (attrs) para mostrar, junto a la
    cifra de cada campo sistemicamente vacio, la tabla de medicamentos que
    la componen -- pedido explicito (2026-08-26). La mascara debe indexar
    directamente sobre lo que devuelve `auditar_coherencia()`, SIN
    reindexar (la UI nunca hace `.set_index()` sobre el resultado)."""
    campos = {c: "VALOR" for c in _CAMPOS_COMPLETITUD_REPORTE if c != "CODIGO_INTERNO"}
    campos["POSOLOGIA"] = "-999"
    filas = [_fila_gemanet(f"{500 + i}-1", **campos) for i in range(10)]
    resultado = auditar_coherencia(
        pd.DataFrame(filas),
        pd.DataFrame([_fila_invima(f"{500 + i}-1") for i in range(10)]),
        _CATALOGO_UNIDAD,
        _CATALOGO_MARCA,
    )
    mascaras = resultado.attrs.get("campos_calidad_mascaras", {})
    assert set(mascaras) == {"POSOLOGIA"}
    mascara = mascaras["POSOLOGIA"]
    assert int(mascara.sum()) == 10
    assert resultado[mascara]["CODIGO_INTERNO"].tolist() == resultado["CODIGO_INTERNO"].tolist()


def test_sin_campos_calidad_mascaras_cuando_todo_esta_diligenciado():
    campos = {c: "VALOR" for c in _CAMPOS_COMPLETITUD_REPORTE if c != "CODIGO_INTERNO"}
    resultado = auditar_coherencia(
        pd.DataFrame([_fila_gemanet("500-1", **campos)]),
        pd.DataFrame([_fila_invima("500-1")]),
        _CATALOGO_UNIDAD,
        _CATALOGO_MARCA,
    )
    assert resultado.attrs.get("campos_calidad_mascaras", {}) == {}


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


# ---- Calidad #10: NOVEDAD_VIGENCIA_INVIMA -- contraste de vigencia contra
# INVIMA para las filas cuya vigencia local no se puede interpretar sola.
# Pedido de negocio (Carlos, 2026-08-20): las fechas comodin son residuo de la
# migracion de Gemma Net a la nube, no se corrigen una por una, pero SI se
# contrastan contra INVIMA para fundamentar novedades. ----


def _fila_vigencia(codigo, activo, fecha_fin, **extra):
    return _fila_gemanet(codigo, ACTIVO=activo, FECHA_INICIO="2012-01-01", FECHA_FIN=fecha_fin, **extra)


def test_comodin_1900_no_cuenta_como_fecha_de_fin_real():
    """El caso que producia 13.815 hallazgos falsos: 1900-01-01 significa
    "sin fecha", no "vencio en 1900"."""
    resultado = _auditar(
        [_fila_vigencia("500-1", "Si", "1900-01-01")],
        [_fila_invima("500-1", ESTADO_CUM="Activo")],
    )
    assert "FECHA_FIN anterior a FECHA_INICIO" not in resultado.loc["500-1", "INCONSISTENCIA_FECHAS_ACTIVO"]
    assert "ya paso" not in resultado.loc["500-1", "INCONSISTENCIA_FECHAS_ACTIVO"]


def test_comodin_2999_no_revienta_aunque_exceda_el_rango_de_pandas():
    """2999-12-31 esta fuera de datetime64[ns] (tope 2262-04-11). Comparar por
    componentes evita el OutOfBoundsDatetime que rompia toda la auditoria."""
    resultado = _auditar(
        [_fila_vigencia("500-1", "Si", "2999-12-31")],
        [_fila_invima("500-1", ESTADO_CUM="Activo")],
    )
    assert resultado.loc["500-1", "INCONSISTENCIA_FECHAS_ACTIVO"] == ""


def test_activo_local_pero_inactivo_en_invima_es_el_riesgo_mas_alto():
    resultado = _auditar(
        [_fila_vigencia("500-1", "Si", "1900-01-01")],
        [_fila_invima("500-1", ESTADO_CUM="Inactivo", FECHA_INACTIVO="2020-05-10")],
    )
    assert resultado.loc["500-1", "NOVEDAD_VIGENCIA_INVIMA"] == "riesgo_activo_sin_vigencia"
    assert "2020-05-10" in resultado.loc["500-1", "DETALLE_VIGENCIA_INVIMA"]


def test_inactivo_local_pero_activo_en_invima_sugiere_revisar_reactivacion():
    """El escenario exacto que planteo negocio: inactivo en la plataforma,
    vigente en INVIMA."""
    resultado = _auditar(
        [_fila_vigencia("500-1", "No", "1900-01-01")],
        [_fila_invima("500-1", ESTADO_CUM="Activo", FECHA_VENCIMIENTO="2030-01-01")],
    )
    assert resultado.loc["500-1", "NOVEDAD_VIGENCIA_INVIMA"] == "revisar_reactivacion"


def test_sin_fecha_local_pero_invima_la_tiene_es_novedad_a_actualizar():
    resultado = _auditar(
        [_fila_vigencia("500-1", "No", "1900-01-01")],
        [_fila_invima("500-1", ESTADO_CUM="Inactivo", FECHA_INACTIVO="2019-03-15")],
    )
    assert resultado.loc["500-1", "NOVEDAD_VIGENCIA_INVIMA"] == "actualizar_fecha_fin"
    assert "2019-03-15" in resultado.loc["500-1", "DETALLE_VIGENCIA_INVIMA"]


def test_registro_vencido_en_invima_se_reporta_aunque_el_cum_siga_activo():
    # FECHA_ACTIVO fija el corte del catalogo: sin el no se afirma vencimiento
    # (ver test_no_se_afirma_vencido_si_el_vencimiento_cae_despues_del_corte).
    resultado = _auditar(
        [_fila_vigencia("500-1", "Si", "2999-12-31")],
        [
            _fila_invima(
                "500-1",
                ESTADO_CUM="Activo",
                FECHA_ACTIVO="2022-12-15",
                FECHA_VENCIMIENTO="2015-01-01",
            )
        ],
    )
    assert resultado.loc["500-1", "NOVEDAD_VIGENCIA_INVIMA"] == "registro_vencido_en_invima"


def test_ambos_lados_coherentes_no_generan_novedad():
    resultado = _auditar(
        [_fila_vigencia("500-1", "Si", "2999-12-31")],
        [_fila_invima("500-1", ESTADO_CUM="Activo", FECHA_VENCIMIENTO="2030-01-01")],
    )
    assert resultado.loc["500-1", "NOVEDAD_VIGENCIA_INVIMA"] == "coherente"
    assert resultado.loc["500-1", "DETALLE_VIGENCIA_INVIMA"] == ""


def test_sin_correspondencia_no_se_afirma_nada_sobre_la_vigencia():
    """No se puede confirmar ni descartar: decir "coherente" seria mentir."""
    resultado = _auditar(
        [_fila_vigencia("999-9", "Si", "1900-01-01")],
        [_fila_invima("500-1")],
    )
    assert resultado.loc["999-9", "NOVEDAD_VIGENCIA_INVIMA"] == "no_verificable"


def test_la_dimension_corre_aunque_invima_no_traiga_las_columnas_de_vigencia():
    """Degradacion explicita: un catalogo INVIMA sin ESTADO_CUM ni fechas no
    debe tumbar la auditoria, solo dejar la dimension sin poder afirmar."""
    resultado = _auditar([_fila_vigencia("500-1", "Si", "1900-01-01")], [_fila_invima("500-1")])
    assert resultado.loc["500-1", "NOVEDAD_VIGENCIA_INVIMA"] in {"coherente", "no_verificable"}


def test_no_se_afirma_vencido_si_el_vencimiento_cae_despues_del_corte_del_catalogo():
    """Un registro que vence DESPUES de la foto del catalogo pudo renovarse y
    esa copia no se entera. Medido contra el listado real de 2022: el 100 % de
    los 73.716 "vencidos a hoy" caian despues del corte -- afirmarlo habria
    sido una decision a ciegas."""
    resultado = _auditar(
        [_fila_vigencia("500-1", "Si", "2999-12-31")],
        [
            _fila_invima(
                "500-1",
                ESTADO_CUM="Activo",
                FECHA_ACTIVO="2022-12-15",       # corte del catalogo
                FECHA_VENCIMIENTO="2024-01-01",  # vence DESPUES del corte
            )
        ],
    )
    assert resultado.loc["500-1", "NOVEDAD_VIGENCIA_INVIMA"] != "registro_vencido_en_invima"


def test_si_se_afirma_vencido_cuando_el_vencimiento_es_anterior_al_corte():
    resultado = _auditar(
        [_fila_vigencia("500-1", "Si", "2999-12-31")],
        [
            _fila_invima(
                "500-1",
                ESTADO_CUM="Activo",
                FECHA_ACTIVO="2022-12-15",
                FECHA_VENCIMIENTO="2020-06-30",  # ya estaba vencido al corte
            )
        ],
    )
    assert resultado.loc["500-1", "NOVEDAD_VIGENCIA_INVIMA"] == "registro_vencido_en_invima"


def test_vencido_en_vencidos_y_activo_local_es_riesgo_no_no_verificable():
    """Sin esto, con los 4 listados cargados la auditoria decia "vencido" en
    ESTADO_COHERENCIA y "no verificable" en la dimension 10 -- dos respuestas
    distintas a la misma pregunta en el mismo reporte."""
    resultado = _auditar(
        [_fila_vigencia("999-9", "Si", "1900-01-01")],
        [_fila_invima("500-1")],
        vencidos_filas=[_fila_invima("999-9")],
    )
    assert resultado.loc["999-9", "ESTADO_COHERENCIA"] == EstadoCoherencia.VENCIDO_EN_INVIMA.value
    assert resultado.loc["999-9", "NOVEDAD_VIGENCIA_INVIMA"] == "riesgo_activo_sin_vigencia"


def test_en_renovacion_no_se_reporta_como_no_verificable():
    """Estar en renovacion es saber algo, no es "no se sabe".

    El veredicto concreto depende de si el medicamento esta activo aca (ver
    los dos tests siguientes); lo que esta prueba fija es que nunca cae en
    "no verificable", que era el bug original.
    """
    for activo in ("Si", "No"):
        resultado = _auditar(
            [_fila_vigencia("999-9", activo, "1900-01-01")],
            [_fila_invima("500-1")],
            renovacion_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Tramite de Renovacion")],
        )
        assert resultado.loc["999-9", "NOVEDAD_VIGENCIA_INVIMA"] != "no_verificable"


def test_activo_aqui_y_en_renovacion_alla_es_coherente_no_reactivacion():
    """A lo que ya esta activo no se le puede pedir que se reactive.

    Si ademas el registro sigue siendo valido en INVIMA (en renovacion), los
    dos lados coinciden y no hay novedad. Antes esto caia en
    "revisar_reactivacion", y la tarjeta lo mostraba como "inactivo aqui pero
    vigente en INVIMA": 18.360 de las 38.098 filas de esa tarjeta estaban en
    realidad ACTIVAS (medido contra produccion el 2026-08-24).
    """
    resultado = _auditar(
        [_fila_vigencia("999-9", "Si", "1900-01-01")],
        [_fila_invima("500-1")],
        renovacion_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Tramite de Renovacion")],
    )
    assert resultado.loc["999-9", "NOVEDAD_VIGENCIA_INVIMA"] == "coherente"


def test_inactivo_aqui_y_en_renovacion_alla_si_es_revisar_reactivacion():
    """El caso legitimo de la etiqueta: aca inactivo, alla con registro vivo."""
    resultado = _auditar(
        [_fila_vigencia("999-9", "No", "1900-01-01")],
        [_fila_invima("500-1")],
        renovacion_filas=[_fila_invima("999-9", ESTADO_REGISTRO="Tramite de Renovacion")],
    )
    assert resultado.loc["999-9", "NOVEDAD_VIGENCIA_INVIMA"] == "revisar_reactivacion"
    assert "renovación" in resultado.loc["999-9", "DETALLE_VIGENCIA_INVIMA"]


def test_sin_ningun_auxiliar_sigue_siendo_no_verificable():
    """Cuando de verdad no hay como saber, se dice que no se sabe."""
    resultado = _auditar(
        [_fila_vigencia("999-9", "Si", "1900-01-01")], [_fila_invima("500-1")]
    )
    assert resultado.loc["999-9", "NOVEDAD_VIGENCIA_INVIMA"] == "no_verificable"


def test_vencido_e_inactivo_es_coherente_no_no_verificable():
    """Los dos lados coinciden en que no esta vigente: sabemos que paso, asi
    que llamarlo "no verificable" seria falso (y contradice ESTADO_COHERENCIA)."""
    resultado = _auditar(
        [_fila_vigencia("999-9", "No", "1900-01-01")],
        [_fila_invima("500-1")],
        vencidos_filas=[_fila_invima("999-9")],
    )
    assert resultado.loc["999-9", "NOVEDAD_VIGENCIA_INVIMA"] == "coherente"


# ---- Los tres defectos de conteo, corregidos el 2026-08-20 ----


def test_descripcion_se_arma_con_cantidad_unidad_y_forma():
    """La formula vieja (PA + UNIDAD_REFERENCIA) fallaba en el 100 % de los
    casos reales: 0 exactas sobre 43.266. La verificada da 74,9 %."""
    resultado = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    assert "DESCRIPCION" not in resultado.loc["500-1", "CAMPOS_CON_DIFERENCIA"]


def test_unidad_referencia_ya_no_participa_de_la_descripcion():
    """Es una frase, no un dato: cambiarla no debe alterar el veredicto."""
    resultado = _auditar(
        [_fila_gemanet("500-1")],
        [_fila_invima("500-1", UNIDAD_REFERENCIA="CUALQUIER OTRA FRASE")],
    )
    assert "DESCRIPCION" not in resultado.loc["500-1", "CAMPOS_CON_DIFERENCIA"]


def test_clasificado_no_es_hallazgo_por_diferencia_de_mayusculas():
    """Gemma Net guarda "No" y el dominio declara "NO". Comparar exacto
    marcaba 199.590 filas validas -- el 99,95 % del reporte."""
    resultado = _auditar([_fila_gemanet("500-1", CLASIFICADO="No")], [_fila_invima("500-1")])
    assert "CLASIFICADO" not in resultado.loc["500-1", "VALORES_FUERA_DE_DOMINIO"]


def test_clasificado_si_se_reporta_cuando_el_valor_no_existe_en_el_dominio():
    """Lo que hay que cazar sigue cazandose."""
    resultado = _auditar(
        [_fila_gemanet("500-1", CLASIFICADO="G03CA579349936")], [_fila_invima("500-1")]
    )
    assert "CLASIFICADO" in resultado.loc["500-1", "VALORES_FUERA_DE_DOMINIO"]


def test_filas_sin_codigo_no_se_cuentan_como_duplicadas():
    """Son una ausencia, no una duplicacion, y ya las cuenta la dimension de
    formato. De 98 "duplicados" reportados, 87 eran esto."""
    resultado = _auditar(
        [_fila_gemanet(None), _fila_gemanet(None), _fila_gemanet("500-1")],
        [_fila_invima("500-1")],
    )
    assert not resultado["CODIGO_DUPLICADO_EN_REPORTE"].any()


def test_un_codigo_repetido_de_verdad_si_se_marca_como_duplicado():
    resultado = _auditar(
        [_fila_gemanet("500-1"), _fila_gemanet("500-1")], [_fila_invima("500-1")]
    )
    assert resultado["CODIGO_DUPLICADO_EN_REPORTE"].all()


# --- TIPO_CODIGO_INTERNO: catalogo de estructuras (design/tipos_codigo_interno.md) ---


def test_auditoria_agrega_tipo_de_codigo_interno():
    resultado = _auditar(
        [
            _fila_gemanet("500-1"),
            _fila_gemanet("V10XX029556981"),
            _fila_gemanet("1C1016781003102"),
            _fila_gemanet("CU1155"),
        ],
        [_fila_invima("500-1")],
    )
    assert resultado.loc["500-1", "TIPO_CODIGO_INTERNO"] == "cum"
    assert resultado.loc["V10XX029556981", "TIPO_CODIGO_INTERNO"] == "atc_expediente_consecutivo"
    assert resultado.loc["1C1016781003102", "TIPO_CODIGO_INTERNO"] == "ium"
    assert resultado.loc["CU1155", "TIPO_CODIGO_INTERNO"] == "codigo_propio"


def test_el_tipo_de_codigo_no_altera_el_porcentaje_de_calidad():
    """Mismo caso que test_todo_coincide_es_correcto: la columna nueva no
    puede cambiar un resultado que ya estaba bien."""
    resultado = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    assert resultado.loc["500-1", "ESTADO_COHERENCIA"] == EstadoCoherencia.CORRECTO.value
    assert resultado.loc["500-1", "PORCENTAJE_CALIDAD"] == 100.0
    assert resultado.loc["500-1", "TIPO_CODIGO_INTERNO"] == "cum"


def test_el_tipo_de_codigo_no_altera_la_naturaleza_del_hallazgo():
    """Un codigo de la familia ATC-legado sin correspondencia en INVIMA
    sigue clasificandose por NATURALEZA_HALLAZGO exactamente igual que
    cualquier otro codigo sin correspondencia -- TIPO_CODIGO_INTERNO es
    informativo, no entra en esa decision."""
    con_atc = _auditar([_fila_gemanet("V10XX029556981")], [_fila_invima("500-1")])
    con_cum = _auditar([_fila_gemanet("999-9")], [_fila_invima("500-1")])
    assert (
        con_atc.loc["V10XX029556981", "NATURALEZA_HALLAZGO"]
        == con_cum.loc["999-9", "NATURALEZA_HALLAZGO"]
    )
    assert con_atc.loc["V10XX029556981", "TIPO_CODIGO_INTERNO"] == "atc_expediente_consecutivo"


def test_la_capa_legada_atc_se_reporta_una_vez_como_advertencia_no_por_fila():
    filas = [_fila_gemanet(f"V10XX02955698{i}") for i in range(5)]
    resultado = _auditar(filas, [_fila_invima("500-1")])
    advertencias = resultado.attrs.get("advertencias_calidad", [])
    coincidencias = [a for a in advertencias if "capa" in a and "legada" in a]
    assert len(coincidencias) == 1  # una sola frase, no 5
    assert "5 de 5" in coincidencias[0]
    assert "no se fusionan" in coincidencias[0]


def test_sin_capa_legada_atc_no_hay_advertencia():
    resultado = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    advertencias = resultado.attrs.get("advertencias_calidad", [])
    assert not any("capa" in a and "legada" in a for a in advertencias)


def test_capa_legada_atc_mascara_selecciona_exactamente_esas_filas():
    """Misma logica que campos_calidad_mascaras: la UI necesita la mascara
    alineada al resultado tal cual lo devuelve auditar_coherencia() para
    mostrar la tabla de medicamentos de esta tarjeta."""
    filas = [_fila_gemanet(f"V10XX02955698{i}") for i in range(5)]
    resultado = auditar_coherencia(
        pd.DataFrame(filas),
        pd.DataFrame([_fila_invima("500-1")]),
        _CATALOGO_UNIDAD,
        _CATALOGO_MARCA,
    )
    mascara = resultado.attrs.get("capa_legada_atc_mascara")
    assert mascara is not None
    assert int(mascara.sum()) == 5
    assert resultado[mascara]["CODIGO_INTERNO"].tolist() == resultado["CODIGO_INTERNO"].tolist()


def test_sin_capa_legada_atc_mascara_cuando_no_hay():
    resultado = auditar_coherencia(
        pd.DataFrame([_fila_gemanet("500-1")]),
        pd.DataFrame([_fila_invima("500-1")]),
        _CATALOGO_UNIDAD,
        _CATALOGO_MARCA,
    )
    assert "capa_legada_atc_mascara" not in resultado.attrs


def test_el_tipo_de_codigo_no_fusiona_ni_deduplica_codigos_repetidos():
    """Un CUM y su "gemelo" de la familia ATC-legado son DOS codigos
    distintos (aunque describan el mismo medicamento) -- deben seguir
    siendo DOS filas del resultado, cada una con su propio
    TIPO_CODIGO_INTERNO, y ninguna marcada como CODIGO_DUPLICADO_EN_REPORTE
    (ese hallazgo es solo para el MISMO CODIGO_INTERNO repetido)."""
    resultado = _auditar(
        [_fila_gemanet("500-1"), _fila_gemanet("V10XX029556981")],
        [_fila_invima("500-1")],
    )
    assert len(resultado) == 2
    assert resultado.loc["500-1", "TIPO_CODIGO_INTERNO"] == "cum"
    assert resultado.loc["V10XX029556981", "TIPO_CODIGO_INTERNO"] == "atc_expediente_consecutivo"
    assert not resultado["CODIGO_DUPLICADO_EN_REPORTE"].any()


# --- Paso 5: CUM con sufijo ATC recuperado contra INVIMA (aprobado 2026-08-26) ---


def test_cum_con_sufijo_atc_cruza_contra_invima_con_el_expediente_reconstruido():
    """Pedido de negocio explicito: reconstruir EXPEDIENTE-CONSECUTIVO desde
    el codigo (la columna EXPEDIENTE trae -999 en la mayoria de estos casos
    reales) y cruzarlo contra INVIMA de verdad -- no solo etiquetarlo."""
    resultado = _auditar(
        [_fila_gemanet("00009811-01-0M01AE01", EXPEDIENTE="-999")],
        [_fila_invima("9811-1")],
    )
    fila = resultado.loc["00009811-01-0M01AE01"]
    assert fila["TIPO_CODIGO_INTERNO"] == "cum_con_sufijo_atc"
    assert fila["CUM_RECONSTRUIDO"] == "9811-1"
    assert fila["ESTADO_COHERENCIA"] == EstadoCoherencia.CORRECTO.value  # ya no sin_correspondencia


def test_cum_con_sufijo_atc_con_diferencias_se_detecta_igual_que_un_cum_normal():
    resultado = _auditar(
        [_fila_gemanet("00009811-01-0M01AE01", EXPEDIENTE="-999", CONCENTRACION="250 MG")],
        [_fila_invima("9811-1")],
    )
    fila = resultado.loc["00009811-01-0M01AE01"]
    assert fila["ESTADO_COHERENCIA"] == EstadoCoherencia.CON_DIFERENCIAS.value
    assert "CONCENTRACION" in fila["CAMPOS_CON_DIFERENCIA"]


def test_cum_con_sufijo_atc_sin_gemelo_en_invima_sigue_sin_correspondencia():
    """Si el expediente reconstruido tampoco existe en INVIMA, el resultado
    es el mismo que para cualquier otro codigo huerfano -- no se inventa una
    correspondencia que no esta."""
    resultado = _auditar(
        [_fila_gemanet("00009811-01-0M01AE01", EXPEDIENTE="-999")],
        [_fila_invima("500-1")],
    )
    fila = resultado.loc["00009811-01-0M01AE01"]
    assert fila["ESTADO_COHERENCIA"] == EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value
    assert fila["CUM_RECONSTRUIDO"] == "9811-1"  # se reconstruyo igual, aunque no haya cruzado


def test_cum_reconstruido_vacio_para_los_demas_tipos_de_codigo():
    resultado = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    assert resultado.loc["500-1", "CUM_RECONSTRUIDO"] == ""


def test_cum_con_sufijo_atc_recuperado_no_afecta_un_cum_normal_en_la_misma_corrida():
    """El arreglo del paso 5 no debe cambiar nada del camino ya probado para
    codigos CUM comunes -- mismo caso que test_todo_coincide_es_correcto,
    corriendo junto con un CUM con sufijo ATC."""
    resultado = _auditar(
        [_fila_gemanet("500-1"), _fila_gemanet("00009811-01-0M01AE01", EXPEDIENTE="-999")],
        [_fila_invima("500-1"), _fila_invima("9811-1")],
    )
    assert resultado.loc["500-1", "ESTADO_COHERENCIA"] == EstadoCoherencia.CORRECTO.value
    assert resultado.loc["500-1", "PORCENTAJE_CALIDAD"] == 100.0
    assert resultado.loc["00009811-01-0M01AE01", "ESTADO_COHERENCIA"] == EstadoCoherencia.CORRECTO.value


def test_cum_con_sufijo_atc_vencido_en_invima_se_detecta_via_dataset_de_vencidos():
    """El expediente reconstruido tambien se usa para cruzar contra los
    datasets auxiliares (Vencidos/Otros Estados/Renovacion), no solo contra
    Vigentes -- si no, un CUM con sufijo ATC realmente vencido caeria en
    sin_correspondencia en vez de vencido_en_invima."""
    resultado = _auditar(
        [_fila_gemanet("00009811-01-0M01AE01", EXPEDIENTE="-999")],
        [_fila_invima("500-1")],
        vencidos_filas=[{"CODIGO_INTERNO": "9811-1"}],
    )
    fila = resultado.loc["00009811-01-0M01AE01"]
    assert fila["ESTADO_COHERENCIA"] == EstadoCoherencia.VENCIDO_EN_INVIMA.value


def test_el_indice_no_contiguo_del_reporte_no_altera_el_estado_de_coherencia():
    """Paso 2 del ciclo 2: normalizar el indice en auditar_coherencia() para
    evitar desalineaciones silenciosas cuando las busquedas posteriores usan
    .isin() sobre gemanet["_CLAVE_CRUCE_INVIMA"].

    Ejemplo: reporte con indice [0, 2, 3] se alinea mal contra combinado con
    RangeIndex [0, 1, 2] del merge. Resultado: medicamento en posicion 2 (indice
    3) aparecia como "sin_correspondencia" aunque estuviera en Vencidos.

    Este test verifica que el arreglo de reset_index(drop=True) hace que ambos
    reportes (uno con indice contiguo, otro filtrado con indice no contiguo)
    produzcan identicos ESTADO_COHERENCIA."""

    # Caso base: 4 medicamentos, con correspondencia distinta
    gemanet_base = [
        _fila_gemanet("500-1"),      # indice 0 - vencido
        _fila_gemanet("600-2"),      # indice 1 - correcto
        _fila_gemanet("700-3"),      # indice 2 - vencido
        _fila_gemanet("800-4"),      # indice 3 - sin correspondencia
    ]
    invima_base = [_fila_invima("500-1"), _fila_invima("600-2"), _fila_invima("700-3")]
    vencidos_base = [
        {"CODIGO_INTERNO": "500-1"},
        {"CODIGO_INTERNO": "700-3"},
    ]

    # Auditoria con indice contiguo [0, 1, 2, 3]
    resultado_contiguo = _auditar(gemanet_base, invima_base, vencidos_filas=vencidos_base)

    # Crear el mismo reporte pero con indice NO contiguo [0, 2, 3]
    # (simula un filtro que elimino la fila 1)
    reporte_filtrado = pd.DataFrame(gemanet_base).drop(1)
    invima = pd.DataFrame(invima_base)
    vencidos = pd.DataFrame(vencidos_base)
    resultado_filtrado = auditar_coherencia(
        reporte_filtrado,
        invima,
        _CATALOGO_UNIDAD,
        _CATALOGO_MARCA,
        df_invima_vencidos=vencidos,
    ).set_index("CODIGO_INTERNO")

    # Verificar que los estados de coherencia son identicos para los codigos
    # que quedan (ignorando el 600-2 que fue eliminado del filtro)
    codigos_comunes = {"500-1", "700-3", "800-4"}
    for codigo in codigos_comunes:
        assert (
            resultado_contiguo.loc[codigo, "ESTADO_COHERENCIA"]
            == resultado_filtrado.loc[codigo, "ESTADO_COHERENCIA"]
        ), f"Estado diferente para {codigo}: contiguo={resultado_contiguo.loc[codigo, 'ESTADO_COHERENCIA']}, filtrado={resultado_filtrado.loc[codigo, 'ESTADO_COHERENCIA']}"


def test_detecta_codigos_huerfanos_inactivos_sin_correspondencia():
    """Codigos huerfanos: sin correspondencia en INVIMA, INACTIVOS en Gemma
    Net. Ej. el medicamento X aparecia en INVIMA pero ya lo cerraron y ademas
    nunca aparece en vigentes/vencidos/otros_estados/renovacion -- residuo de
    migracion. Se reporta como una advertencia agregada, no fila por fila."""
    filas_gemanet = [
        _fila_gemanet("500-1", ACTIVO="SI"),  # Sin correspondencia pero ACTIVO -- no es huerfano
        _fila_gemanet("600-2", ACTIVO="NO"),  # Sin correspondencia e INACTIVO -- ES huerfano
        _fila_gemanet("700-3", ACTIVO="NO"),  # Sin correspondencia e INACTIVO -- ES huerfano
    ]
    invima = [_fila_invima("500-1")]  # Solo 500-1 aparece en vigentes
    resultado = _auditar(filas_gemanet, invima)
    advertencias = resultado.attrs.get("advertencias_calidad", [])
    # Debe haber una advertencia mentionando "codigos huerfanos"
    assert any("huerfanos" in a.lower() for a in advertencias), f"No encontre advertencia de codigos huerfanos en {advertencias}"
    # La advertencia debe mencionar 2 medicamentos (600-2 y 700-3)
    assert any("2" in a and "huerfanos" in a.lower() for a in advertencias), f"La advertencia no menciona cantidad 2 en {advertencias}"


def test_sin_advertencia_huerfanos_cuando_todos_tienen_correspondencia():
    """Si todos los medicamentos sin correspondencia estan ACTIVOS, no hay
    advertencia de huerfanos -- no se cuentan como residuos."""
    filas_gemanet = [
        _fila_gemanet("500-1", ACTIVO="SI"),
        _fila_gemanet("600-2", ACTIVO="SI"),
    ]
    invima = [_fila_invima("500-1")]  # 600-2 no aparece pero ESTA ACTIVO
    resultado = _auditar(filas_gemanet, invima)
    advertencias = resultado.attrs.get("advertencias_calidad", [])
    assert not any("huerfanos" in a.lower() for a in advertencias)


def test_mascara_codigos_huerfanos_selecciona_exactamente_los_inactivos_sin_correspondencia():
    """La mascara `codigos_huerfanos_mascara` debe indexar directamente sobre
    el resultado, sin reindexar (la UI nunca lo hace)."""
    filas_gemanet = [
        _fila_gemanet("500-1", ACTIVO="SI"),  # Sin correspondencia pero ACTIVO
        _fila_gemanet("600-2", ACTIVO="NO"),  # Sin correspondencia e INACTIVO
        _fila_gemanet("700-3", ACTIVO=""),    # Sin correspondencia, sin ACTIVO
        _fila_gemanet("800-4", ACTIVO="SI"),  # Con correspondencia
    ]
    invima = [_fila_invima("800-4")]
    resultado = auditar_coherencia(
        pd.DataFrame(filas_gemanet),
        pd.DataFrame(invima),
        _CATALOGO_UNIDAD,
        _CATALOGO_MARCA,
    )
    mascara = resultado.attrs.get("codigos_huerfanos_mascara", pd.Series())
    if not mascara.empty:
        # Debe incluir solo 600-2 y 700-3 (sin correspondencia e inactivos/vacios)
        codigos_huerfanos = resultado[mascara]["CODIGO_INTERNO"].tolist()
        assert set(codigos_huerfanos) == {"600-2", "700-3"}, f"Esperaba {{600-2, 700-3}}, obtuve {set(codigos_huerfanos)}"


def test_detecta_solape_medicamento_en_vencidos_y_renovacion():
    """Bug real (Paso 8): un medicamento que aparece en AMBOS datasets de
    Vencidos y Renovacion/Otros Estados debería reportarse como solape --
    estado ambiguo en INVIMA que requiere revision manual."""
    filas_gemanet = [
        _fila_gemanet("500-1"),
        _fila_gemanet("600-2"),
    ]
    invima = [_fila_invima("500-1")]
    vencidos = [_fila_invima("600-2")]
    # 600-2 aparece en AMBOS vencidos y renovacion
    renovacion = [_fila_invima("600-2", ESTADO_REGISTRO="En Tramite Renovacion")]
    resultado = _auditar(
        filas_gemanet, invima,
        vencidos_filas=vencidos,
        renovacion_filas=renovacion
    )
    advertencias = resultado.attrs.get("advertencias_calidad", [])
    # Debe reportar el solape
    assert any("solape" in a.lower() or "ambos" in a.lower() for a in advertencias), \
        f"No encontre advertencia de solape en {advertencias}"


def test_sin_solape_cuando_un_medicamento_esta_en_un_solo_dataset():
    """Sin solape si los medicamentos estan en datasets distintos pero no
    en ambos a la vez."""
    filas_gemanet = [
        _fila_gemanet("500-1"),
        _fila_gemanet("600-2"),
    ]
    invima = [_fila_invima("500-1")]
    vencidos = [_fila_invima("600-2")]
    renovacion = [_fila_invima("700-3")]  # Distinto medicamento
    resultado = _auditar(
        filas_gemanet, invima,
        vencidos_filas=vencidos,
        renovacion_filas=renovacion
    )
    advertencias = resultado.attrs.get("advertencias_calidad", [])
    assert not any("solape" in a.lower() or "ambos" in a.lower() for a in advertencias)


# --- Regresion: propagacion de fechas desde Vencidos (bug real 20102710-2, 2026-09-01) ---


def test_vencido_en_invima_via_vencidos_propaga_las_3_fechas_de_invima():
    """Antes del fix, `_aplicar_dataset_auxiliar` nunca se llamaba para el
    bloque de Vencidos (asignacion manual de `estado`) y las 3 columnas de
    fecha de INVIMA quedaban NaT para el 100% de los codigos
    "vencido_en_invima" -- aunque Vencidos trae las mismas 29 columnas que
    Vigentes, incluidas fechaactivo/fechainactivo/fechavencimiento. Caso real
    diagnosticado: 20102710-2."""
    resultado = _auditar(
        [_fila_gemanet("20102710-2")],
        [_fila_invima("500-1")],  # el codigo NO esta en Vigentes
        vencidos_filas=[
            _fila_invima(
                "20102710-2",
                FECHA_ACTIVO="2010-05-12",
                FECHA_INACTIVO="2020-01-30",
                FECHA_VENCIMIENTO="2019-12-31",
            )
        ],
    )
    fila = resultado.loc["20102710-2"]
    assert fila["ESTADO_COHERENCIA"] == EstadoCoherencia.VENCIDO_EN_INVIMA.value
    assert pd.notna(fila["FECHA_ACTIVO_INVIMA"])
    assert pd.notna(fila["FECHA_INACTIVO_INVIMA"])
    assert pd.notna(fila["FECHA_VENCIMIENTO_INVIMA"])
    assert fila["FECHA_ACTIVO_INVIMA"] == pd.Timestamp("2010-05-12")
    assert fila["FECHA_INACTIVO_INVIMA"] == pd.Timestamp("2020-01-30")
    assert fila["FECHA_VENCIMIENTO_INVIMA"] == pd.Timestamp("2019-12-31")


# --- ESTADO_LISTADO_INVIMA: el ARCHIVO de origen, no el veredicto ---
#
# Antes esta columna se derivaba de ESTADO_COHERENCIA con un mapa
# (correcto->"vigente", con_diferencias->"vigente", ...). Eso no es el archivo
# donde esta el registro sino una traduccion del veredicto, y su unico
# proposito declarado por el usuario (2026-09-02) es "ayudarnos a ubicar el
# archivo de forma manual en los excel de INVIMA". Estos tests fijan que diga
# el archivo REAL.


def test_estado_listado_invima_dice_el_archivo_real_no_el_veredicto():
    """Un codigo que solo existe en Vencidos debe reportar listado 'vencido'.

    Con el mapa viejo, cualquier fila con correspondencia terminaba en
    "vigente" via CORRECTO/CON_DIFERENCIAS, y el usuario lo buscaba en el
    Excel de Vigentes sin encontrarlo (casos reales 19931314-1 y
    20064726-4)."""
    resultado = _auditar(
        [_fila_gemanet("700-3")],
        [_fila_invima("500-1")],  # NO esta en Vigentes
        vencidos_filas=[_fila_invima("700-3", ESTADO_CUM="Inactivo")],
    )
    assert resultado.loc["700-3", "ESTADO_LISTADO_INVIMA"] == "vencido"


def test_listado_de_los_que_estan_en_otros_estados_pero_dicen_tramite_de_renovacion():
    """Su VEREDICTO es renovacion, pero su ARCHIVO es Otros Estados.

    Son dos datos distintos y hay que conservar los dos: el estado dice como
    tratarlo, el listado dice donde buscarlo. Mandarlo al Excel de Renovacion
    es mandarlo al archivo equivocado -- eran 459 codigos (medido contra
    invima_listados, 2026-09-02)."""
    resultado = _auditar(
        [_fila_gemanet("700-3")],
        [_fila_invima("500-1")],
        otros_estados_filas=[
            _fila_invima("700-3", ESTADO_REGISTRO="En tramite renov", ESTADO_CUM="Activo")
        ],
    )
    assert resultado.loc["700-3", "ESTADO_COHERENCIA"] == (
        EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value
    )
    assert resultado.loc["700-3", "ESTADO_LISTADO_INVIMA"] == "otros_estados"


def test_sin_correspondencia_en_ningun_dataset_reporta_ninguno():
    resultado = _auditar([_fila_gemanet("700-3")], [_fila_invima("500-1")])
    assert resultado.loc["700-3", "ESTADO_LISTADO_INVIMA"] == "ninguno"


# --- filtrar_universo_auditable(): los 3 casos limite documentados en su docstring ---


def _fila_universo(codigo_interno, **overrides):
    base = {
        "CODIGO_INTERNO": codigo_interno,
        "TIPO_CODIGO_INTERNO": "cum",
        "ESTADO_COHERENCIA": EstadoCoherencia.CORRECTO.value,
        "ESTADO_LISTADO_INVIMA": "vigente",
        "ACTIVO": "SI",
    }
    base.update(overrides)
    return base


def test_filtro_excluye_tipo_codigo_interno_fuera_del_universo_auditable_aunque_este_activo_y_correcto():
    df = pd.DataFrame([
        _fila_universo("500-1"),  # cum -- se conserva
        _fila_universo("600-2", TIPO_CODIGO_INTERNO="ium"),  # excluido: tipo no auditable
    ])
    resultado = filtrar_universo_auditable(df)
    assert set(resultado["CODIGO_INTERNO"]) == {"500-1"}


def test_filtro_excluye_no_valida_contra_invima_aunque_este_activo():
    df = pd.DataFrame([
        _fila_universo("500-1"),
        _fila_universo(
            "600-2",
            ESTADO_COHERENCIA=EstadoCoherencia.NO_VALIDA_CONTRA_INVIMA.value,
            ESTADO_LISTADO_INVIMA="ninguno",
        ),  # ancestral/planta: excluido aunque ACTIVO == 'SI'
    ])
    resultado = filtrar_universo_auditable(df)
    assert set(resultado["CODIGO_INTERNO"]) == {"500-1"}


def test_filtro_excluye_inactivo_sin_la_excepcion_de_vigente_en_invima():
    df = pd.DataFrame([
        _fila_universo("500-1"),
        _fila_universo(
            "600-2",
            ACTIVO="NO",
            ESTADO_COHERENCIA=EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value,
            ESTADO_LISTADO_INVIMA="ninguno",
        ),  # inactivo y no vigente en INVIMA: excluido
    ])
    resultado = filtrar_universo_auditable(df)
    assert set(resultado["CODIGO_INTERNO"]) == {"500-1"}


def test_filtro_conserva_inactivo_cuando_invima_si_lo_declara_vigente():
    """La unica excepcion: ACTIVO != 'SI' pero ESTADO_LISTADO_INVIMA == 'vigente'."""
    df = pd.DataFrame([
        _fila_universo(
            "700-3",
            ACTIVO="NO",
            ESTADO_COHERENCIA=EstadoCoherencia.CON_DIFERENCIAS.value,
            ESTADO_LISTADO_INVIMA="vigente",
        ),
    ])
    resultado = filtrar_universo_auditable(df)
    assert set(resultado["CODIGO_INTERNO"]) == {"700-3"}


def test_filtro_conserva_activo_sin_importar_el_estado_listado_invima():
    df = pd.DataFrame([
        _fila_universo("500-1", ESTADO_LISTADO_INVIMA="vigente"),
        _fila_universo(
            "600-2",
            ESTADO_COHERENCIA=EstadoCoherencia.VENCIDO_EN_INVIMA.value,
            ESTADO_LISTADO_INVIMA="vencido",
        ),
        _fila_universo(
            "700-3",
            ESTADO_COHERENCIA=EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value,
            ESTADO_LISTADO_INVIMA="ninguno",
        ),
    ])
    resultado = filtrar_universo_auditable(df)
    assert set(resultado["CODIGO_INTERNO"]) == {"500-1", "600-2", "700-3"}


# --- INCONSISTENCIA_FECHAS_ACTIVO: el aviso de vencido-y-activo no se repite ---


def test_activo_y_vencido_en_invima_no_repite_el_aviso():
    """Bug real (2026-09-01), visible en produccion para 20102710-2:
    `INCONSISTENCIA_FECHAS_ACTIVO` traia el mismo texto dos veces separado
    por "; ". Dos `.mask()` encadenados donde el segundo evaluaba la Serie
    YA modificada por el primero: la fila que acababa de recibir el aviso
    volvia a cumplir la condicion "no esta vacia" y se lo anexaba otra vez."""
    resultado = _auditar(
        # FECHA_FIN comodin (2999-12-31) para que _validar_fechas_activo no
        # aporte ningun hallazgo propio: el unico texto posible es el aviso
        # de vencido-y-activo, asi que si aparece dos veces es este bug.
        [_fila_gemanet("55-1", ACTIVO="Si", FECHA_INICIO="2016-07-23", FECHA_FIN="2999-12-31")],
        [_fila_invima("99-9")],
        vencidos_filas=[_fila_invima("55-1")],
    )
    aviso = resultado.loc["55-1", "INCONSISTENCIA_FECHAS_ACTIVO"]
    assert aviso == "ACTIVO=SI pero el registro sanitario esta VENCIDO en INVIMA"
    assert aviso.count("VENCIDO en INVIMA") == 1


def test_activo_y_vencido_en_invima_se_suma_a_un_hallazgo_previo_una_sola_vez():
    """El caso hermano: cuando `_validar_fechas_activo` SI aporto un
    hallazgo propio, el aviso se anexa -- pero una sola vez, y sin perder
    el hallazgo original."""
    resultado = _auditar(
        # FECHA_FIN real y anterior a FECHA_INICIO: hallazgo propio de
        # _validar_fechas_activo, independiente de INVIMA.
        [_fila_gemanet("55-1", ACTIVO="Si", FECHA_INICIO="2020-01-01", FECHA_FIN="2019-01-01")],
        [_fila_invima("99-9")],
        vencidos_filas=[_fila_invima("55-1")],
    )
    aviso = resultado.loc["55-1", "INCONSISTENCIA_FECHAS_ACTIVO"]
    assert aviso.count("VENCIDO en INVIMA") == 1
    assert "FECHA_FIN anterior a FECHA_INICIO" in aviso


# --- COHERENCIA_FECHAS_INVIMA: FECHA_INICIO vs FECHA ACTIVO, FECHA_FIN vs FECHA INACTIVO ---


def test_fecha_fin_que_no_cuadra_con_fecha_vencimiento_de_invima_se_reporta():
    """El caso real 20102710-2: FECHA_INICIO SI coincide con FECHA ACTIVO de
    INVIMA, pero FECHA_FIN (2999-12-31) no dice nada y INVIMA registra que el
    CUM se inactivo el 2021-10-01. Aca se usa una FECHA_FIN real y distinta
    para probar la comparacion misma."""
    resultado = _auditar(
        [_fila_gemanet("55-1", FECHA_INICIO="2016-07-23", FECHA_FIN="2022-01-01")],
        [_fila_invima("55-1", FECHA_ACTIVO="2016-07-23", FECHA_VENCIMIENTO="2021-10-01")],
    )
    coherencia = resultado.loc["55-1", "COHERENCIA_FECHAS_INVIMA"]
    assert "FECHA_FIN" in coherencia
    assert "2021-10-01" in coherencia
    # FECHA_INICIO si coincide: no debe aparecer en el mensaje.
    assert "FECHA_INICIO" not in coherencia


def test_fechas_que_coinciden_no_reportan_nada():
    resultado = _auditar(
        [_fila_gemanet("55-1", FECHA_INICIO="2016-07-23", FECHA_FIN="2021-10-01")],
        [_fila_invima("55-1", FECHA_ACTIVO="2016-07-23", FECHA_VENCIMIENTO="2021-10-01")],
    )
    assert resultado.loc["55-1", "COHERENCIA_FECHAS_INVIMA"] == ""


def test_fecha_comodin_con_fecha_real_en_invima_pide_actualizar_no_marca_diferencia():
    """`2999-12-31` es el centinela de "sin dato". Si INVIMA SI tiene la fecha,
    no es que el dato este equivocado: es que FALTA y hay que copiarlo --
    pedido del usuario (2026-09-02): "requiere que digamos que hace falta
    actualizar la fecha porque el invima si tiene una fecha vencimiento
    diligenciada"."""
    resultado = _auditar(
        [_fila_gemanet("55-1", FECHA_INICIO="2016-07-23", FECHA_FIN="2999-12-31")],
        [_fila_invima("55-1", FECHA_ACTIVO="2016-07-23", FECHA_VENCIMIENTO="2027-09-30")],
    )
    aviso = resultado.loc["55-1", "COHERENCIA_FECHAS_INVIMA"]
    assert "Falta actualizar FECHA_FIN" in aviso
    assert "2027-09-30" in aviso


def test_sin_correspondencia_en_invima_la_coherencia_de_fechas_queda_vacia():
    """Vacio, no "coincide": no hay con que comparar -- mismo criterio que
    PORCENTAJE_CALIDAD (regla de diseno #6)."""
    resultado = _auditar(
        [_fila_gemanet("55-1", FECHA_INICIO="2016-07-23", FECHA_FIN="2022-01-01")],
        [_fila_invima("99-9")],
    )
    assert resultado.loc["55-1", "COHERENCIA_FECHAS_INVIMA"] == ""


def test_las_fechas_de_un_cum_que_solo_esta_en_vencidos_si_se_contrastan():
    """El hueco que motivo la tarea: un CUM que no esta en Vigentes pero si en
    Vencidos llegaba SIN ninguna fecha de INVIMA, asi que su coherencia de
    fechas nunca se podia evaluar (caso real 20102710-2)."""
    resultado = _auditar(
        [_fila_gemanet("55-1", ACTIVO="Si", FECHA_INICIO="2016-07-23", FECHA_FIN="2022-01-01")],
        [_fila_invima("99-9")],
        vencidos_filas=[_fila_invima("55-1", FECHA_ACTIVO="2016-07-23", FECHA_VENCIMIENTO="2021-10-01")],
    )
    assert resultado.loc["55-1", "ESTADO_COHERENCIA"] == EstadoCoherencia.VENCIDO_EN_INVIMA.value
    coherencia = resultado.loc["55-1", "COHERENCIA_FECHAS_INVIMA"]
    assert "FECHA_FIN" in coherencia
    assert "2021-10-01" in coherencia


# --- VIGENCIA_NO_CONFIRMABLE: estar en "Vigentes" no significa vigente HOY ---


def test_vencimiento_ya_pasado_se_reporta_como_vencido():
    """Bug real reportado por el usuario (2026-09-02, caso 19931314-1): el CUM
    aparecia como "Vigentes y correctos" y al revisar INVIMA a mano ya no
    estaba en el listado de vigentes. Aparecer en el dataset "Vigentes" solo
    dice que estaba vigente AL CORTE del catalogo -- si su propia
    FECHA_VENCIMIENTO ya paso, no hay como afirmar que siga vigente."""
    resultado = _auditar(
        [_fila_gemanet("55-1", ACTIVO="Si")],
        [_fila_invima("55-1", FECHA_ACTIVO="2006-11-10", FECHA_VENCIMIENTO="2023-04-03")],
    )
    aviso = resultado.loc["55-1", "VIGENCIA_NO_CONFIRMABLE"]
    assert "2023-04-03" in aviso
    assert "vencido" in aviso.lower()


def test_vencimiento_futuro_si_queda_como_vigencia_confirmable():
    resultado = _auditar(
        [_fila_gemanet("55-1", ACTIVO="Si")],
        [_fila_invima("55-1", FECHA_ACTIVO="2006-11-10", FECHA_VENCIMIENTO="2099-01-01")],
    )
    assert resultado.loc["55-1", "VIGENCIA_NO_CONFIRMABLE"] == ""


def test_el_aviso_de_vencido_recuerda_verificar_la_renovacion():
    """El hecho se afirma sin rodeos -- la FECHA_VENCIMIENTO es de INVIMA y
    compararla con hoy es aritmetica, no una suposicion. Lo que si se anota es
    que una renovacion posterior al corte del catalogo no aparece en esta
    copia, para que nadie desactive sin verificar."""
    resultado = _auditar(
        [_fila_gemanet("55-1", ACTIVO="Si")],
        [_fila_invima("55-1", FECHA_ACTIVO="2006-11-10", FECHA_VENCIMIENTO="2023-04-03")],
    )
    aviso = resultado.loc["55-1", "VIGENCIA_NO_CONFIRMABLE"].lower()
    assert "confirmarla en invima" in aviso
    # El ESTADO_COHERENCIA sigue siendo "correcto": los CAMPOS si coinciden.
    # Lo que cambia es que ya no cuenta como "vigente y correcto".
    assert resultado.loc["55-1", "ESTADO_COHERENCIA"] == EstadoCoherencia.CORRECTO.value


def test_estado_cum_invima_se_propaga_desde_los_datasets_auxiliares():
    """ESTADO_CUM_INVIMA es el veredicto de vigencia real y tiene que llegar
    tambien para los CUM que solo existen en Vencidos / Otros Estados /
    Renovacion. Bug medido contra el snapshot real (2026-09-02): la columna
    quedaba poblada al 100 % en 'vigente' y al 0 % en los otros tres listados
    porque el criterio de "aun vacio" era `.isna()` sobre una serie que nace
    con cadena vacia, no con NaN."""
    resultado = _auditar(
        [_fila_gemanet("500-1"), _fila_gemanet("600-2"), _fila_gemanet("700-3")],
        [_fila_invima("900-9", ESTADO_CUM="Activo")],
        vencidos_filas=[_fila_invima("500-1", ESTADO_CUM="Activo", ESTADO_REGISTRO="Vencido")],
        otros_estados_filas=[_fila_invima("600-2", ESTADO_CUM="Inactivo", ESTADO_REGISTRO="Cancelado")],
        renovacion_filas=[_fila_invima("700-3", ESTADO_CUM="Activo", ESTADO_REGISTRO="En tramite")],
    )
    assert resultado.loc["500-1", "ESTADO_CUM_INVIMA"] == "Activo"
    assert resultado.loc["600-2", "ESTADO_CUM_INVIMA"] == "Inactivo"
    assert resultado.loc["700-3", "ESTADO_CUM_INVIMA"] == "Activo"


def test_estado_cum_invima_de_vigentes_no_lo_pisa_un_dataset_auxiliar():
    """Prioridad: si Vigentes ya resolvio el ESTADO_CUM, aparecer ademas en un
    listado auxiliar no puede sobreescribirlo ("completa vacios, nunca pisa")."""
    resultado = _auditar(
        [_fila_gemanet("500-1")],
        [_fila_invima("500-1", ESTADO_CUM="Activo")],
        vencidos_filas=[_fila_invima("500-1", ESTADO_CUM="Inactivo")],
    )
    assert resultado.loc["500-1", "ESTADO_CUM_INVIMA"] == "Activo"
