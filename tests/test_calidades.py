import pandas as pd

from gemma_cum_loader.auditoria.calidades import calidades_auditoria
from gemma_cum_loader.auditoria.coherencia_invima import EstadoCoherencia


def _fila(codigo_interno, **overrides):
    base = {
        "CODIGO_INTERNO": codigo_interno,
        "DESCRIPCION": "ACETAMINOFEN 500MG TABLETA",
        "ACTIVO": "SI",
        "ESTADO_COHERENCIA": EstadoCoherencia.CORRECTO.value,
        "CODIGO_DUPLICADO_EN_REPORTE": False,
        "FORMATO_CODIGO_INTERNO_INVALIDO": "",
        "CAMPOS_CON_DIFERENCIA": "",
        "INCONSISTENCIA_FECHAS_ACTIVO": "",
        "INTEGRIDAD_REFERENCIAL_CATALOGO": "",
    }
    base.update(overrides)
    return base


def test_devuelve_las_10_calidades_en_orden():
    auditoria = pd.DataFrame([_fila("500-1")])
    calidades = calidades_auditoria(auditoria)
    assert len(calidades) == 10
    assert calidades[0].nombre == "No se pudo encontrar en INVIMA"
    assert calidades[-1].nombre == "Activos aquí sin vigencia en INVIMA"


def test_codigo_legado_cae_en_no_se_pudo_encontrar():
    """Códigos legados (no EXPEDIENTE-CONSECUTIVO) caen en la calidad
    'No se pudo encontrar en INVIMA' junto con códigos con formato correcto
    pero también no encontrados. Se distinguen por TIPO_SIN_CORRESPONDENCIA."""
    auditoria = pd.DataFrame([
        _fila("CODIGO-LEGADO-XYZ", ESTADO_COHERENCIA=EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value),
        _fila("500-1")
    ])
    calidades = calidades_auditoria(auditoria)
    no_encontrados = calidades[0]
    assert no_encontrados.nombre == "No se pudo encontrar en INVIMA"
    assert no_encontrados.medicamentos == 1
    assert no_encontrados.df_tabla["CODIGO_INTERNO"].tolist() == ["CODIGO-LEGADO-XYZ"]


def test_codigo_duplicado_se_detecta():
    auditoria = pd.DataFrame(
        [_fila("500-1", CODIGO_DUPLICADO_EN_REPORTE=True), _fila("500-2")]
    )
    calidades = calidades_auditoria(auditoria)
    duplicados = next(c for c in calidades if c.nombre == "Código repetido dentro del reporte")
    assert duplicados.medicamentos == 1


def test_activos_sin_vigencia_invima_requiere_activo_y_estado_de_riesgo():
    auditoria = pd.DataFrame(
        [
            _fila("500-1", ACTIVO="SI", ESTADO_COHERENCIA=EstadoCoherencia.VENCIDO_EN_INVIMA.value),
            # Vencido pero INACTIVO -- no cuenta, no hay riesgo de autorizacion.
            _fila("500-2", ACTIVO="NO", ESTADO_COHERENCIA=EstadoCoherencia.VENCIDO_EN_INVIMA.value),
            # Activo pero correcto -- no cuenta.
            _fila("500-3", ACTIVO="SI", ESTADO_COHERENCIA=EstadoCoherencia.CORRECTO.value),
        ]
    )
    calidades = calidades_auditoria(auditoria)
    riesgo = next(c for c in calidades if c.nombre == "Activos aquí sin vigencia en INVIMA")
    assert riesgo.medicamentos == 1
    assert riesgo.df_tabla["CODIGO_INTERNO"].tolist() == ["500-1"]


def test_porcentaje_del_catalogo_es_sobre_el_total_no_sobre_el_subconjunto():
    auditoria = pd.DataFrame(
        [_fila("500-1", CODIGO_DUPLICADO_EN_REPORTE=True)] + [_fila(f"500-{i}") for i in range(2, 5)]
    )
    calidades = calidades_auditoria(auditoria)
    duplicados = next(c for c in calidades if c.nombre == "Código repetido dentro del reporte")
    assert duplicados.porcentaje_del_catalogo == 25.0  # 1 de 4, no 1 de 1


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
    auditoria = pd.DataFrame([_fila("500-1", CODIGO_DUPLICADO_EN_REPORTE=True)])
    duplicados = _calidad(auditoria, "Código repetido dentro del reporte")
    consulta = duplicados.df_tabla["CONSULTA_VERIFICACION_SQL"].iloc[0]
    assert "administrativo.tb_medicamento" in consulta
    assert "codigo_interno = '500-1'" in consulta
    assert "descripcion" in consulta
    assert "concentracion" in consulta


def test_consulta_de_verificacion_sql_escapa_comillas_simples():
    auditoria = pd.DataFrame([_fila("500-1'; DROP TABLE--", CODIGO_DUPLICADO_EN_REPORTE=True)])
    duplicados = _calidad(auditoria, "Código repetido dentro del reporte")
    consulta = duplicados.df_tabla["CONSULTA_VERIFICACION_SQL"].iloc[0]
    assert "500-1''; DROP TABLE--" in consulta


def test_consejo_sale_de_naturaleza_hallazgo_y_queda_vacio_sin_hallazgo():
    auditoria = pd.DataFrame(
        [
            _fila(
                "500-1",
                CODIGO_DUPLICADO_EN_REPORTE=True,
                NATURALEZA_HALLAZGO="Vigencia en riesgo",
            ),
            _fila(
                "500-2",
                CODIGO_DUPLICADO_EN_REPORTE=True,
                NATURALEZA_HALLAZGO="",  # sin hallazgo -- sin consejo
            ),
        ]
    )
    duplicados = _calidad(auditoria, "Código repetido dentro del reporte")
    tabla = duplicados.df_tabla.set_index("CODIGO_INTERNO")
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
    con_diferencias = next(c for c in calidades if c.nombre == "Con algún campo distinto al de INVIMA")
    assert "DESCRIPCION_GEMANET" in con_diferencias.columnas
    assert "DESCRIPCION_INVIMA" in con_diferencias.columnas
    assert "DESCRIPCION_VALIDACION" in con_diferencias.columnas
    fila = con_diferencias.df_tabla.iloc[0]
    assert fila["DESCRIPCION_GEMANET"] == "ACETAMINOFEN 500MG"
    assert fila["DESCRIPCION_INVIMA"] == "ACETAMINOFEN 500 MG"
    assert fila["DESCRIPCION_VALIDACION"] == "difiere"
