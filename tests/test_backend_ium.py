import pandas as pd
from fastapi.testclient import TestClient

from backend.app.dependencies import carpeta_snapshots
from backend.app.main import app
from worker.almacen_snapshots import escribir_snapshot


def _cliente(tmp_path):
    carpeta = tmp_path / "snapshots"
    app.dependency_overrides[carpeta_snapshots] = lambda: carpeta
    return TestClient(app), carpeta


def test_ium_503_sin_tabla_todavia(tmp_path):
    cliente, _ = _cliente(tmp_path)
    try:
        r = cliente.get("/ium")
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_ium_lista_del_snapshot(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {
                "CODIGO_INTERNO": ["1C1016781003102", "2H2016781003103"],
                "ESTADO_IUM": ["un_cum", "varios_cum"],
            }
        )
        escribir_snapshot({"auditoria_ium": df}, carpeta=carpeta)

        r = cliente.get("/ium")
        cuerpo = r.json()
        assert cuerpo["total"] == 2
    finally:
        app.dependency_overrides.clear()


def test_ium_filtra_por_estado_ium(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {
                "CODIGO_INTERNO": ["1C1016781003102", "2H2016781003103"],
                "ESTADO_IUM": ["un_cum", "varios_cum"],
            }
        )
        escribir_snapshot({"auditoria_ium": df}, carpeta=carpeta)

        r = cliente.get("/ium", params={"estado_ium": "un_cum"})
        cuerpo = r.json()
        assert cuerpo["total"] == 1
        assert cuerpo["filas"][0]["CODIGO_INTERNO"] == "1C1016781003102"
    finally:
        app.dependency_overrides.clear()


def test_ium_resumen_cuenta_por_estado(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {
                "CODIGO_INTERNO": ["a", "b", "c"],
                "ESTADO_IUM": ["un_cum", "un_cum", "varios_cum"],
            }
        )
        escribir_snapshot({"auditoria_ium": df}, carpeta=carpeta)

        r = cliente.get("/ium/resumen")
        assert r.json() == {"un_cum": 2, "varios_cum": 1}
    finally:
        app.dependency_overrides.clear()


def _df_calidad_ium():
    return pd.DataFrame(
        [
            {
                "CODIGO_INTERNO": "1C1016781003102",
                "DESCRIPCION": "X",
                "ACTIVO": "SI",
                "ESTADO_IUM": "un_cum",
                "CUM_INVIMA": ["20083667-1"],
                "IDENTIDAD_DUPLICADA": "",
                "ESTADO_CUM_INVIMA": "Activo",
                "ESTADO_LISTADO_INVIMA": "vigente",
                "CAMPOS_CON_DIFERENCIA": "PRINCIPIO_ACTIVO",
                "INCONSISTENCIA_FECHAS_ACTIVO": "",
            },
            {
                "CODIGO_INTERNO": "2H2016781003103",
                "DESCRIPCION": "Y",
                "ACTIVO": "SI",
                "ESTADO_IUM": "varios_cum",
                "CUM_INVIMA": ["20083667-1", "20083667-2"],
                "IDENTIDAD_DUPLICADA": "",
                "ESTADO_CUM_INVIMA": "",
                "ESTADO_LISTADO_INVIMA": "",
                "CAMPOS_CON_DIFERENCIA": "",
                "INCONSISTENCIA_FECHAS_ACTIVO": "",
            },
        ]
    )


def test_ium_calidades_lista_una_tarjeta(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria_ium": _df_calidad_ium()}, carpeta=carpeta)
        r = cliente.get("/ium/calidades")
        cuerpo = r.json()
        assert len(cuerpo) == 1
        assert cuerpo[0]["nombre"] == "Diferencia de estado o campos"
        assert cuerpo[0]["medicamentos"] == 1
        assert cuerpo[0]["porcentaje_del_catalogo"] == 100.0  # 1 de 1 comparable (un_cum)
    finally:
        app.dependency_overrides.clear()


def test_ium_calidad_desconocida_da_404(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria_ium": _df_calidad_ium()}, carpeta=carpeta)
        r = cliente.get("/ium/calidades/no-existe")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_ium_calidad_secciones_por_campo(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria_ium": _df_calidad_ium()}, carpeta=carpeta)
        r = cliente.get("/ium/calidades/Diferencia de estado o campos/secciones")
        claves = {s["clave"] for s in r.json()}
        assert "campo:PRINCIPIO_ACTIVO" in claves
    finally:
        app.dependency_overrides.clear()


def test_ium_calidad_tabla_y_filtro_por_seccion(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria_ium": _df_calidad_ium()}, carpeta=carpeta)
        r = cliente.get(
            "/ium/calidades/Diferencia de estado o campos",
            params={"seccion": "campo:PRINCIPIO_ACTIVO"},
        )
        cuerpo = r.json()
        assert cuerpo["total"] == 1
        assert cuerpo["filas"][0]["CODIGO_INTERNO"] == "1C1016781003102"
    finally:
        app.dependency_overrides.clear()
