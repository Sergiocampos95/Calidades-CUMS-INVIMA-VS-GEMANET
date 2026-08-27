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
        assert cliente.get("/universo").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_resumen_universo_cuenta_por_clasificacion_y_suma_el_total(tmp_path):
    """Las 5 categorias tienen que sumar el archivo completo -- cada fila
    de INVIMA recibe la etiqueta del primer filtro que incumple."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {
                "CODIGO_INTERNO": ["1-1", "2-2", "3-3", "4-4"],
                "CLASIFICACION_CREACION": ["candidato", "rol_no_fabricante", "candidato", "cum_inactivo"],
            }
        )
        escribir_snapshot({"universo": df}, carpeta=carpeta)

        r = cliente.get("/universo/resumen")
        cuerpo = r.json()
        assert cuerpo == {"candidato": 2, "rol_no_fabricante": 1, "cum_inactivo": 1}
        assert sum(cuerpo.values()) == len(df)
    finally:
        app.dependency_overrides.clear()


def test_filtro_por_clasificacion(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {
                "CODIGO_INTERNO": ["1-1", "2-2"],
                "CLASIFICACION_CREACION": ["candidato", "muestra_medica"],
            }
        )
        escribir_snapshot({"universo": df}, carpeta=carpeta)

        r = cliente.get("/universo", params={"clasificacion": "muestra_medica"})
        cuerpo = r.json()
        assert cuerpo["total"] == 1
        assert cuerpo["filas"][0]["CODIGO_INTERNO"] == "2-2"
    finally:
        app.dependency_overrides.clear()
