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


def test_devuelve_las_11_calidades_en_orden():
    auditoria = pd.DataFrame([_fila("500-1")])
    calidades = calidades_auditoria(auditoria)
    assert len(calidades) == 11
    assert calidades[0].nombre == "Sin código verificable contra INVIMA"
    assert calidades[-1].nombre == "Activos aquí sin vigencia en INVIMA"


def test_codigo_sin_formato_invima_cae_en_la_primera_calidad():
    auditoria = pd.DataFrame([_fila("CODIGO-LEGADO-XYZ"), _fila("500-1")])
    calidades = calidades_auditoria(auditoria)
    sin_formato = calidades[0]
    assert sin_formato.medicamentos == 1
    assert sin_formato.df_tabla["CODIGO_INTERNO"].tolist() == ["CODIGO-LEGADO-XYZ"]


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
