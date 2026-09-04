import pandas as pd

from gemma_cum_loader.auditoria.calidades import (
    _con_columnas_derivadas,
    _consultas_verificacion_gemanet,
    calidades_auditoria,
    columnas_de_seccion,
    filtrar_por_seccion,
    secciones_de_diferencia,
)
from gemma_cum_loader.auditoria.coherencia_invima import EstadoCoherencia


def _fila(codigo_interno, **overrides):
    base = {
        "CODIGO_INTERNO": codigo_interno,
        "DESCRIPCION": "ACETAMINOFEN 500MG TABLETA",
        "ACTIVO": "SI",
        "ESTADO_COHERENCIA": EstadoCoherencia.CORRECTO.value,
        # Veredicto de vigencia real de INVIMA ("Activo"/"Inactivo"),
        # independiente del listado. La calidad "Vigencia confirmada" y otras
        # se definen usando ESTADO_CUM_INVIMA, no ESTADO_LISTADO_INVIMA.
        "ESTADO_CUM_INVIMA": "Activo",
        # Metadato de ubicacion: en cual archivo/listado aparece el registro.
        "ESTADO_LISTADO_INVIMA": "vigente",
        "VIGENCIA_NO_CONFIRMABLE": "",
        "CODIGO_DUPLICADO_EN_REPORTE": False,
        "FORMATO_CODIGO_INTERNO_INVALIDO": "",
        "CAMPOS_CON_DIFERENCIA": "",
        "INCONSISTENCIA_FECHAS_ACTIVO": "",
        "INTEGRIDAD_REFERENCIAL_CATALOGO": "",
    }
    base.update(overrides)
    return base


def test_devuelve_las_6_calidades_en_orden():
    auditoria = pd.DataFrame([_fila("500-1")])
    calidades = calidades_auditoria(auditoria)
    # Rediseño 2026-09-02: ahora son 6 calidades (no 7). La tarjeta de
    # "Inactivo en Gemma Net pero vigente en INVIMA" se integro dentro de
    # "Diferencia de estado o campos" (tarjeta 6). El veredicto de vigencia
    # ahora es ESTADO_CUM_INVIMA (el campo real de INVIMA), no
    # ESTADO_LISTADO_INVIMA (que es solo ubicacion).
    assert len(calidades) == 6
    assert calidades[0].nombre == "Vigencia confirmada"
    assert calidades[-1].nombre == "Diferencia de estado o campos"


def _conteo_por_nombre(auditoria):
    return {c.nombre: c.medicamentos for c in calidades_auditoria(auditoria)}


def test_gracia_de_lotes_va_en_registro_vencido_no_en_vigencia_confirmada():
    """La gracia de lotes -- activo en Gemma Net, listado 'vencido', pero
    ESTADO_CUM todavia 'Activo' en INVIMA -- va en "Registro vencido en
    INVIMA", nunca en "Vigencia confirmada".

    Decision del usuario (2026-09-03): "en este apartado meramente deben de
    aparecer los que pertenezcan solo al listado de vigentes". El listado es
    la UBICACION donde alguien encontrara el registro al buscarlo a mano en
    los Excel de INVIMA, asi que el caso vive con los demas vencidos y se
    distingue por la columna ESTADO_CUM_INVIMA.

    Antes esta misma fila contaba como vigencia confirmada; al restaurar el
    filtro de listado en esa tarjeta se habria quedado sin ninguna, que es
    justo lo que este test impide que vuelva a pasar."""
    auditoria = pd.DataFrame(
        [_fila("20111111-1", ESTADO_CUM_INVIMA="Activo", ESTADO_LISTADO_INVIMA="vencido")]
    )
    conteo = _conteo_por_nombre(auditoria)
    assert conteo["Vigencia confirmada"] == 0
    assert conteo["Registro vencido en INVIMA"] == 1


def test_registro_vencido_recoge_el_vencido_pleno_del_listado():
    """El vencido pleno (ESTADO_CUM 'Inactivo' + listado 'vencido') tambien
    vive en esta tarjeta, junto a la gracia de lotes -- los dos sub-casos
    conviven y se separan mirando ESTADO_CUM_INVIMA, no partiendo la tarjeta
    (ver `test_gracia_de_lotes_va_en_registro_vencido_no_en_vigencia_confirmada`)."""
    auditoria = pd.DataFrame(
        [_fila("20222222-1", ESTADO_CUM_INVIMA="Inactivo", ESTADO_LISTADO_INVIMA="vencido")]
    )
    conteo = _conteo_por_nombre(auditoria)
    assert conteo["Registro vencido en INVIMA"] == 1
    assert conteo["Vigencia confirmada"] == 0


def test_calidades_excluyen_no_cums_y_inactivos_salvo_la_excepcion():
    """La auditoria del negocio debe mostrar solo CUMs activos y validos
    contra INVIMA; los legados, no-CUM y activos locales inactivos quedan
    fuera del listado de calidades accionables -- CON una unica excepcion:
    un CUM inactivo en Gemma Net pero vigente en INVIMA (ESTADO_CUM_INVIMA=
    'Activo') es justo el caso de mayor riesgo y debe seguir siendo visible,
    ahora dentro de la tarjeta 6 'Diferencia de estado o campos'."""
    auditoria = pd.DataFrame([
        _fila("500-1", ESTADO_CUM_INVIMA="Activo"),
        _fila(
            "500-2",
            ACTIVO="NO",
            ESTADO_CUM_INVIMA="Inactivo",
            ESTADO_LISTADO_INVIMA="vencido",
        ),
        _fila("CODIGO-LEGADO-XYZ", ESTADO_CUM_INVIMA=""),
    ])
    calidades = calidades_auditoria(auditoria)
    vigentes = next(c for c in calidades if c.nombre == "Vigencia confirmada")
    assert vigentes.medicamentos == 1
    assert vigentes.df_tabla["CODIGO_INTERNO"].tolist() == ["500-1"]
    # "500-2" esta inactivo y con ESTADO_CUM_INVIMA='Inactivo' -- NO es la
    # excepcion (esa solo aplica si ESTADO_CUM_INVIMA == 'Activo'), asi que
    # sigue invisible en todas las calidades.
    assert all(c.medicamentos == 0 for c in calidades if c.nombre != "Vigencia confirmada")


def test_inactivo_en_gemanet_pero_vigente_en_invima_es_la_unica_excepcion_visible():
    """Un CUM inactivo en Gemma Net que INVIMA SI tiene vigente
    (ESTADO_CUM_INVIMA='Activo') es el unico caso donde un inactivo debe
    verse -- ahora dentro de la tarjeta 6 'Diferencia de estado o campos'."""
    auditoria = pd.DataFrame([
        _fila("500-1", ESTADO_CUM_INVIMA="Activo"),
        _fila(
            "500-2",
            ACTIVO="NO",
            ESTADO_CUM_INVIMA="Activo",
            ESTADO_LISTADO_INVIMA="vigente",
        ),
    ])
    calidades = calidades_auditoria(auditoria)
    excepcion = next(c for c in calidades if c.nombre == "Diferencia de estado o campos")
    assert excepcion.medicamentos == 1
    assert excepcion.df_tabla["CODIGO_INTERNO"].tolist() == ["500-2"]
    # No debe aparecer duplicado en ninguna otra calidad -- son mutuamente
    # excluyentes con las de "solo activos".
    assert all(
        c.medicamentos == 0
        for c in calidades
        if c.nombre not in ("Vigencia confirmada", "Diferencia de estado o campos")
    )
    vigentes = next(c for c in calidades if c.nombre == "Vigencia confirmada")
    assert vigentes.medicamentos == 1


def test_codigo_duplicado_ya_no_es_una_calidad():
    """La deteccion NO se perdio: sigue calculandose en la columna
    CODIGO_DUPLICADO_EN_REPORTE y se muestra como la dimension "Unicidad" en
    /auditoria/dimensiones (tarjetas laterales). Dejo de ser una calidad
    propia porque era la misma cifra repetida dos veces en la misma pantalla
    -- pedido del usuario, 2026-09-01."""
    auditoria = pd.DataFrame(
        [_fila("500-1", CODIGO_DUPLICADO_EN_REPORTE=True), _fila("500-2")]
    )
    nombres = {c.nombre for c in calidades_auditoria(auditoria)}
    assert "Código repetido dentro del reporte" not in nombres
    assert "Código de marca o unidad inexistente" not in nombres


def test_no_existe_la_calidad_redundante_de_activos_sin_vigencia():
    """Tras el rediseño 2026-09-02, ya no existe calidad redundante. La
    tarjeta de 'Inactivo en Gemma Net pero vigente en INVIMA' se integro
    dentro de 'Diferencia de estado o campos', eliminando duplicados."""
    auditoria = pd.DataFrame(
        [_fila("500-1", ACTIVO="SI", ESTADO_CUM_INVIMA="Inactivo", ESTADO_LISTADO_INVIMA="vencido")]
    )
    nombres = [c.nombre for c in calidades_auditoria(auditoria)]
    assert "Activos aquí sin vigencia en INVIMA" not in nombres
    assert "Inactivo en Gemma Net pero vigente en INVIMA" not in nombres
    # El medicamento NO se pierde: sigue contado en su calidad especifica.
    vencidos = next(c for c in calidades_auditoria(auditoria) if c.nombre == "Registro vencido en INVIMA")
    assert vencidos.medicamentos == 1


def test_porcentaje_del_catalogo_es_sobre_el_total_no_sobre_el_subconjunto():
    auditoria = pd.DataFrame(
        [_fila("500-1", CODIGO_DUPLICADO_EN_REPORTE=True)] + [_fila(f"500-{i}") for i in range(2, 5)]
    )
    calidades = calidades_auditoria(auditoria)
    vigentes = next(c for c in calidades if c.nombre == "Vigencia confirmada")
    # Las 4 filas son "Vigencia confirmada"; el denominador es el universo
    # auditable (4), no el subconjunto de la calidad.
    assert vigentes.porcentaje_del_catalogo == 100.0


def test_catalogo_vacio_no_revienta_por_division_entre_cero():
    auditoria = pd.DataFrame(columns=["CODIGO_INTERNO", "ESTADO_COHERENCIA"])
    calidades = calidades_auditoria(auditoria)
    assert all(c.medicamentos == 0 for c in calidades)
    assert all(c.porcentaje_del_catalogo == 0.0 for c in calidades)


def test_columna_faltante_no_revienta_y_queda_fuera_de_columnas():
    """FECHA_FIN/DETALLE_VIGENCIA_INVIMA pueden faltar si esta corrida no
    trajo ese dato -- degradacion explicita: la calidad se sigue calculando
    (mascara False, cero medicamentos), no revienta con KeyError."""
    auditoria = pd.DataFrame([_fila("500-1")])  # sin FECHA_FIN ni DETALLE_VIGENCIA_INVIMA
    calidades = calidades_auditoria(auditoria)
    vencidos = next(c for c in calidades if c.nombre == "Registro vencido en INVIMA")
    assert vencidos.medicamentos == 0
    assert "FECHA_FIN" not in vencidos.columnas


def _calidad(auditoria: pd.DataFrame, nombre: str):
    return next(c for c in calidades_auditoria(auditoria) if c.nombre == nombre)


def test_consulta_de_verificacion_sql_apunta_a_la_tabla_y_columnas_reales():
    """La consulta tiene que poder pegarse tal cual en un cliente SQL contra
    Gemma Net -- mismas columnas que ya usa ingesta/gemanet_sql.py."""
    auditoria = pd.DataFrame([_fila("500-1")])
    vigentes = _calidad(auditoria, "Vigencia confirmada")
    consulta = vigentes.df_tabla["CONSULTA_VERIFICACION_SQL"].iloc[0]
    assert "administrativo.tb_medicamento" in consulta
    assert "codigo_interno = '500-1'" in consulta
    assert "descripcion" in consulta
    assert "concentracion" in consulta


def test_consulta_de_verificacion_sql_escapa_comillas_simples():
    """Se prueba sobre el helper y no a traves de una calidad: un codigo con
    comilla no es un CUM valido, asi que desde 2026-09-01 no cae en ninguna
    calidad (todas exigen formato EXPEDIENTE-CONSECUTIVO). El escape sigue
    importando igual -- la consulta se pega tal cual en un cliente SQL ajeno
    y tiene que ser valida sea cual sea el caracter que traiga el dato."""
    consultas = _consultas_verificacion_gemanet(pd.Series(["500-1'; DROP TABLE--"]))
    assert "500-1''; DROP TABLE--" in consultas.iloc[0]


def test_consejo_sale_de_naturaleza_hallazgo_y_queda_vacio_sin_hallazgo():
    auditoria = pd.DataFrame(
        [
            _fila("500-1", NATURALEZA_HALLAZGO="Vigencia en riesgo"),
            _fila("500-2", NATURALEZA_HALLAZGO=""),  # sin hallazgo -- sin consejo
        ]
    )
    vigentes = _calidad(auditoria, "Vigencia confirmada")
    tabla = vigentes.df_tabla.set_index("CODIGO_INTERNO")
    assert "Revisar antes de autorizar" in tabla.loc["500-1", "CONSEJO"]
    assert tabla.loc["500-2", "CONSEJO"] == ""


def test_con_diferencias_muestra_el_trio_gemanet_invima_validacion_por_campo():
    """Pedido explicito del usuario (2026-08-28): CAMPOS_CON_DIFERENCIA dice
    CUALES campos difieren, pero no que contienen -- esta calidad tiene que
    traer el valor de Gemma Net, el de INVIMA y el veredicto de cada uno de
    los 7 campos comparables, no solo el nombre del campo."""
    auditoria = pd.DataFrame(
        [
            _fila(
                "500-1",
                CAMPOS_CON_DIFERENCIA="DESCRIPCION",
                DESCRIPCION_GEMANET="ACETAMINOFEN 500MG",
                DESCRIPCION_INVIMA="ACETAMINOFEN 500 MG",
                DESCRIPCION_VALIDACION="difiere",
            )
        ]
    )
    calidades = calidades_auditoria(auditoria)
    con_diferencias = next(c for c in calidades if c.nombre == "Diferencia de estado o campos")
    assert "DESCRIPCION_GEMANET" in con_diferencias.columnas
    assert "DESCRIPCION_INVIMA" in con_diferencias.columnas
    assert "DESCRIPCION_VALIDACION" in con_diferencias.columnas
    fila = con_diferencias.df_tabla.iloc[0]
    assert fila["DESCRIPCION_GEMANET"] == "ACETAMINOFEN 500MG"
    assert fila["DESCRIPCION_INVIMA"] == "ACETAMINOFEN 500 MG"
    assert fila["DESCRIPCION_VALIDACION"] == "difiere"


# --- Secciones de diferencia (partir una calidad grande por tipo) ----------


def _tabla_con_diferencias():
    """Cuatro filas que cubren los tres mecanismos de diferencia distintos:
    campos comparados, fechas contra INVIMA y contradiccion interna."""
    return pd.DataFrame(
        [
            _fila("500-1", CAMPOS_CON_DIFERENCIA="CONCENTRACION, DESCRIPCION"),
            _fila("500-2", CAMPOS_CON_DIFERENCIA="DESCRIPCION"),
            _fila(
                "500-3",
                COHERENCIA_FECHAS_INVIMA="Falta actualizar FECHA_FIN en Gemma Net: INVIMA reporta...",
            ),
            _fila("500-4", INCONSISTENCIA_FECHAS_ACTIVO="ACTIVO=NO sin FECHA_FIN registrada"),
        ]
    )


def test_secciones_cuentan_por_tipo_de_diferencia_y_omiten_las_vacias():
    secciones = secciones_de_diferencia(_tabla_con_diferencias())
    por_clave = {s.clave: s.medicamentos for s in secciones}
    assert por_clave["campo:DESCRIPCION"] == 2
    assert por_clave["campo:CONCENTRACION"] == 1
    assert por_clave["fecha:FECHA_FIN"] == 1
    # "Fechas que se contradicen" se elimino (2026-09-03): no era pedido.
    # Un campo sin ninguna diferencia no aparece: la columna lateral se libero
    # para ganar claridad.
    assert "campo:MARCA_MEDICAMENTO" not in por_clave
    assert "interna:fechas" not in por_clave


def test_secciones_agrupan_campos_antes_que_fechas():
    """Orden pedido por el usuario (2026-09-02), el mismo en que enumero los
    tipos: campos del medicamento, despues fechas, al final la contradiccion
    interna. Por volumen puro "Fecha fin" (el 97 %) aplastaria arriba y los
    campos quedarian al fondo, que es justo lo que se queria poder ver."""
    claves = [s.clave for s in secciones_de_diferencia(_tabla_con_diferencias())]
    grupos = [c.split(":", 1)[0] for c in claves]
    assert grupos == sorted(grupos, key=["campo", "fecha", "interna"].index)


def test_filtrar_por_seccion_devuelve_exactamente_lo_que_conto_la_tarjeta():
    """Conteo y filtro salen del mismo registro: si discreparan, la tarjeta
    diria un numero y la tabla mostraria otro."""
    tabla = _tabla_con_diferencias()
    for seccion in secciones_de_diferencia(tabla):
        assert len(filtrar_por_seccion(tabla, seccion.clave)) == seccion.medicamentos


def test_seccion_de_campo_no_matchea_por_substring():
    """CAMPOS_CON_DIFERENCIA es una lista separada por comas: buscar el campo
    como substring haria que un campo prefijo de otro se lleve filas ajenas."""
    tabla = pd.DataFrame([_fila("500-1", CAMPOS_CON_DIFERENCIA="DESCRIPCION_COMERCIAL")])
    assert len(filtrar_por_seccion(tabla, "campo:DESCRIPCION")) == 0


def test_descripcion_se_marca_como_efecto_de_principio_activo():
    """Sin esta marca "Descripcion" parece el problema mas grande cuando en
    buena parte es la consecuencia de que el principio activo este mal."""
    secciones = {s.clave: s for s in secciones_de_diferencia(_tabla_con_diferencias())}
    assert secciones["campo:DESCRIPCION"].derivado_de == ("PRINCIPIO_ACTIVO", "UNIDAD_MEDIDA")
    assert secciones["campo:CONCENTRACION"].derivado_de == ()


def test_calidad_sin_diferencias_no_tiene_secciones():
    assert secciones_de_diferencia(pd.DataFrame([_fila("500-1")])) == []


def test_seccion_desconocida_devuelve_la_tabla_entera():
    """Mejor mostrar de mas que fingir "no hay hallazgos" (que es como se lee
    una tabla vacia) por una clave vieja en un enlace."""
    tabla = _tabla_con_diferencias()
    assert len(filtrar_por_seccion(tabla, "campo:INVENTADO")) == len(tabla)


def test_estado_invima_no_repite_la_palabra_cuando_el_listado_ya_la_dice():
    """ESTADO_INVIMA fusiona listado + detalle en una sola columna. Antes
    salian contiguas diciendo lo mismo ("Vencido" | "Vencido") en el 91 % de
    las filas -- 116.267 de 127.734 medidas contra el snapshot."""
    auditoria = pd.DataFrame([
        _fila("500-1", ESTADO_LISTADO_INVIMA="vencido", ESTADO_INVIMA_DETALLE="Vencido"),
        _fila("600-1", ESTADO_LISTADO_INVIMA="vencido", ESTADO_INVIMA_DETALLE="Vencido"),
    ])

    columna = _con_columnas_derivadas(auditoria)["ESTADO_INVIMA"]

    assert list(columna) == ["Vencido", "Vencido"]


def test_estado_invima_conserva_el_detalle_cuando_el_listado_agrupa_varios():
    """`otros_estados` es heterogeneo por naturaleza: agrupa 8 estados reales
    (Cancelado, Negado, Perdida Fuerza Ejec...). Ahi el nombre del archivo no
    basta para saber que dice INVIMA, asi que el detalle va entre parentesis.

    El criterio es CONTAR cuantos valores agrupa el listado, no comparar los
    dos textos: comparar fallaba con las abreviaturas y producia el parentesis
    inutil "En trámite de renovación (En tramite renov)"."""
    auditoria = pd.DataFrame([
        _fila("500-1", ESTADO_LISTADO_INVIMA="otros_estados", ESTADO_INVIMA_DETALLE="Cancelado"),
        _fila("600-1", ESTADO_LISTADO_INVIMA="otros_estados", ESTADO_INVIMA_DETALLE="Negado"),
    ])

    columna = _con_columnas_derivadas(auditoria)["ESTADO_INVIMA"]

    assert list(columna) == ["Otro estado (Cancelado)", "Otro estado (Negado)"]


# --- columnas_de_seccion: que columnas viajan por cada seccion (paso 3) -----


def test_columnas_de_seccion_de_campo_trae_su_trio_y_no_el_de_otros_campos():
    """Antes de este recorte, abrir la seccion Concentracion traia los 7
    trios GEMANET/INVIMA/VALIDACION completos (38 columnas) aunque solo el
    trio de CONCENTRACION sirviera para leer ese hallazgo puntual. Si un
    cambio futuro volviera a mezclar el trio de otro campo (p.ej.
    DESCRIPCION) en esta seccion, esta prueba lo nota."""
    columnas = columnas_de_seccion("campo:CONCENTRACION")
    assert columnas == (
        "CODIGO_INTERNO",
        "DESCRIPCION",
        "CONCENTRACION_GEMANET",
        "CONCENTRACION_INVIMA",
        "CONCENTRACION_VALIDACION",
        "ACTIVO",
        "ESTADO_CUM_INVIMA",
        "ESTADO_INVIMA",
    )
    assert "DESCRIPCION_GEMANET" not in columnas
    assert "DESCRIPCION_INVIMA" not in columnas
    assert "DESCRIPCION_VALIDACION" not in columnas
    assert "PRINCIPIO_ACTIVO_GEMANET" not in columnas


def test_columnas_de_seccion_clave_desconocida_o_vacia_devuelve_tupla_vacia():
    """El paso 2 (backend) interpreta la tupla vacia como "no recortar nada".
    Si esta funcion inventara una lista de columnas para una clave que no
    existe, un enlace guardado con una seccion vieja dejaria la tabla sin
    las columnas que de verdad tiene."""
    assert columnas_de_seccion("campo:INVENTADO") == ()
    assert columnas_de_seccion("fecha:INVENTADA") == ()
    assert columnas_de_seccion("otro_prefijo:ALGO") == ()
    assert columnas_de_seccion("") == ()


def test_columnas_de_seccion_fecha_inicio_trae_el_par_fecha_activo_invima():
    assert columnas_de_seccion("fecha:FECHA_INICIO") == (
        "CODIGO_INTERNO",
        "DESCRIPCION",
        "FECHA_INICIO",
        "FECHA_ACTIVO_INVIMA",
        "COHERENCIA_FECHAS_INVIMA",
        "ACTIVO",
        "ESTADO_CUM_INVIMA",
        "ESTADO_INVIMA",
    )


def test_columnas_de_seccion_fecha_fin_trae_fecha_vencimiento_y_no_fecha_inactivo():
    """FECHA_FIN se compara contra FECHA_VENCIMIENTO_INVIMA, no contra
    FECHA_INACTIVO_INVIMA -- es la misma regla de negocio de
    PARES_FECHAS_GEMANET_INVIMA (coherencia_invima.py) que ya cambio una vez
    (2026-09-02). Si columnas_de_seccion volviera a leer el par viejo, la
    seccion "Fecha fin diferencias" mostraria una columna que ya no
    corresponde a lo que dice el mensaje de COHERENCIA_FECHAS_INVIMA."""
    columnas = columnas_de_seccion("fecha:FECHA_FIN")
    assert columnas == (
        "CODIGO_INTERNO",
        "DESCRIPCION",
        "FECHA_FIN",
        "FECHA_VENCIMIENTO_INVIMA",
        "COHERENCIA_FECHAS_INVIMA",
        "ACTIVO",
        "ESTADO_CUM_INVIMA",
        "ESTADO_INVIMA",
    )
    assert "FECHA_INACTIVO_INVIMA" not in columnas
