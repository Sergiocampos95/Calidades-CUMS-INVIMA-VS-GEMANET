import pandas as pd

from gemma_cum_loader.armado.indice_ium import (
    ESTADO_MAL_FORMADO,
    ESTADO_UN_CUM,
    ESTADO_VARIOS_CUM,
)
from gemma_cum_loader.auditoria.calidades import (
    filtrar_por_seccion,
    secciones_de_diferencia,
)
from gemma_cum_loader.auditoria.calidades_ium import (
    NOMBRE_CALIDAD_DIFERENCIAS,
    calidades_ium,
)

_IUM = "1C1016781003102"


def _fila(codigo_interno=_IUM, **overrides):
    base = {
        "CODIGO_INTERNO": codigo_interno,
        "DESCRIPCION": "CEFAZOLINA 1000MG POLVO",
        "ACTIVO": "SI",
        "ESTADO_IUM": ESTADO_UN_CUM,
        "CUM_INVIMA": ["20083667-1"],
        "IDENTIDAD_DUPLICADA": "",
        "ESTADO_CUM_INVIMA": "Activo",
        "ESTADO_LISTADO_INVIMA": "vigente",
        "CAMPOS_CON_DIFERENCIA": "",
        "INCONSISTENCIA_FECHAS_ACTIVO": "",
    }
    base.update(overrides)
    return base


def test_devuelve_una_sola_calidad():
    calidades = calidades_ium(pd.DataFrame([_fila()]))
    assert len(calidades) == 1
    assert calidades[0].nombre == NOMBRE_CALIDAD_DIFERENCIAS


def test_solo_cuenta_iums_comparables_un_cum():
    # varios_cum y mal_formado no entran aunque tengan CAMPOS_CON_DIFERENCIA
    # -- no hay un unico CUM contra el cual haber comparado nada.
    auditoria = pd.DataFrame(
        [
            _fila("1", ESTADO_IUM=ESTADO_VARIOS_CUM, CAMPOS_CON_DIFERENCIA="DESCRIPCION"),
            _fila("2", ESTADO_IUM=ESTADO_MAL_FORMADO, CAMPOS_CON_DIFERENCIA="DESCRIPCION"),
            _fila("3", ESTADO_IUM=ESTADO_UN_CUM, CAMPOS_CON_DIFERENCIA="DESCRIPCION"),
        ]
    )
    calidad = calidades_ium(auditoria)[0]
    assert calidad.medicamentos == 1
    assert list(calidad.df_tabla["CODIGO_INTERNO"]) == ["3"]


def test_detecta_discrepancia_de_vigencia_activo_aqui_inactivo_invima():
    auditoria = pd.DataFrame([_fila(ACTIVO="SI", ESTADO_CUM_INVIMA="Inactivo", ESTADO_LISTADO_INVIMA="otros_estados")])
    calidad = calidades_ium(auditoria)[0]
    assert calidad.medicamentos == 1


def test_detecta_diferencia_de_campos_si_esta_activo():
    auditoria = pd.DataFrame([_fila(CAMPOS_CON_DIFERENCIA="PRINCIPIO_ACTIVO")])
    calidad = calidades_ium(auditoria)[0]
    assert calidad.medicamentos == 1


def test_sin_diferencia_ni_discrepancia_no_entra():
    auditoria = pd.DataFrame([_fila()])
    calidad = calidades_ium(auditoria)[0]
    assert calidad.medicamentos == 0


def test_porcentaje_es_sobre_el_total_comparable_no_sobre_todos_los_ium():
    auditoria = pd.DataFrame(
        [
            _fila("1", CAMPOS_CON_DIFERENCIA="DESCRIPCION"),  # comparable, con diferencia
            _fila("2"),  # comparable, sin diferencia
            _fila("3", ESTADO_IUM=ESTADO_VARIOS_CUM),  # no comparable, no cuenta en el denominador
        ]
    )
    calidad = calidades_ium(auditoria)[0]
    assert calidad.medicamentos == 1
    assert calidad.porcentaje_del_catalogo == 50.0  # 1 de 2 comparables, no 1 de 3


def test_catalogo_vacio_no_revienta_por_division_entre_cero():
    calidad = calidades_ium(pd.DataFrame(columns=["CODIGO_INTERNO", "ESTADO_IUM"]))[0]
    assert calidad.medicamentos == 0
    assert calidad.porcentaje_del_catalogo == 0.0


def test_secciones_de_diferencia_funcionan_igual_que_para_cum():
    # Reuso directo de calidades.py::secciones_de_diferencia -- confirma que
    # es genuinamente generico y no hace falta una version IUM aparte.
    auditoria = pd.DataFrame(
        [
            _fila("1", CAMPOS_CON_DIFERENCIA="PRINCIPIO_ACTIVO"),
            _fila("2", CAMPOS_CON_DIFERENCIA="CONCENTRACION"),
        ]
    )
    calidad = calidades_ium(auditoria)[0]
    secciones = secciones_de_diferencia(calidad.df_tabla)
    claves = {s.clave for s in secciones}
    assert "campo:PRINCIPIO_ACTIVO" in claves
    assert "campo:CONCENTRACION" in claves
    solo_pa = filtrar_por_seccion(calidad.df_tabla, "campo:PRINCIPIO_ACTIVO")
    assert list(solo_pa["CODIGO_INTERNO"]) == ["1"]
