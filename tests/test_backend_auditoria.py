import pandas as pd
from fastapi.testclient import TestClient

from backend.app.dependencies import carpeta_snapshots
from backend.app.main import app
from worker.almacen_snapshots import escribir_snapshot


def _cliente(tmp_path):
    carpeta = tmp_path / "snapshots"
    app.dependency_overrides[carpeta_snapshots] = lambda: carpeta
    return TestClient(app), carpeta


def test_sin_snapshot_todavia_responde_503(tmp_path):
    cliente, _ = _cliente(tmp_path)
    try:
        assert cliente.get("/auditoria").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_porcentaje_calidad_nan_llega_como_null_no_como_cero(tmp_path):
    """Regla no negociable del proyecto: PORCENTAJE_CALIDAD vacio (NaN) es
    "no hay con que comparar", nunca 0%. La API no puede convertir eso en
    0 al serializar -- tiene que llegar como null."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {
                "CODIGO_INTERNO": ["1-1", "2-2"],
                "PORCENTAJE_CALIDAD": [100.0, float("nan")],
                "ESTADO_COHERENCIA": ["correcto", "sin_correspondencia_invima"],
            }
        )
        escribir_snapshot({"auditoria": df}, carpeta=carpeta)

        r = cliente.get("/auditoria")
        filas = {f["CODIGO_INTERNO"]: f["PORCENTAJE_CALIDAD"] for f in r.json()["filas"]}
        assert filas["1-1"] == 100.0
        assert filas["2-2"] is None
    finally:
        app.dependency_overrides.clear()


def test_filtro_por_estado_coherencia(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {
                "CODIGO_INTERNO": ["1-1", "2-2"],
                "ESTADO_COHERENCIA": ["correcto", "con_diferencias"],
            }
        )
        escribir_snapshot({"auditoria": df}, carpeta=carpeta)

        r = cliente.get("/auditoria", params={"estado_coherencia": "con_diferencias"})
        cuerpo = r.json()
        assert cuerpo["total"] == 1
        assert cuerpo["filas"][0]["CODIGO_INTERNO"] == "2-2"
    finally:
        app.dependency_overrides.clear()


def test_resumen_auditoria_cuenta_por_estado_coherencia(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {"ESTADO_COHERENCIA": ["correcto", "correcto", "con_diferencias"]}
        )
        escribir_snapshot({"auditoria": df}, carpeta=carpeta)

        r = cliente.get("/auditoria/resumen")
        assert r.json() == {"correcto": 2, "con_diferencias": 1}
    finally:
        app.dependency_overrides.clear()
