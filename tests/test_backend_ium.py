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
