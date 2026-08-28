import pandas as pd
from fastapi.testclient import TestClient

from backend.app.dependencies import carpeta_snapshots
from backend.app.main import app
from worker.almacen_snapshots import escribir_snapshot


def _cliente(tmp_path):
    carpeta = tmp_path / "snapshots"
    app.dependency_overrides[carpeta_snapshots] = lambda: carpeta
    return TestClient(app), carpeta


def test_sin_malla_de_referencia_los_4_endpoints_responden_503(tmp_path):
    """Degradacion explicita: si el worker no encontro la Estructura Cargue
    Medicamentos, ninguna de las 4 tablas existe -- nunca se responde
    '0 listos' como si fuera un resultado real."""
    cliente, _ = _cliente(tmp_path)
    try:
        assert cliente.get("/cargue/estructura").status_code == 503
        assert cliente.get("/cargue/final").status_code == 503
        assert cliente.get("/cargue/resumen").status_code == 503
        assert cliente.get("/cargue/advertencias").status_code == 503
    finally:
        app.dependency_overrides.clear()


def _snapshot_cargue_muestra(carpeta):
    evaluados = pd.DataFrame(
        {
            "CODIGO_INTERNO": ["1-1", "2-2", "3-3"],
            "listo_para_cargue": [True, False, True],
        }
    )
    estructura = pd.DataFrame(
        {
            "CODIGO_INTERNO": ["1-1", "2-2", "3-3"],
            "ESTADO": ["Listo para cargue", "Pendiente de clasificacion manual", "Listo para cargue"],
            "CAMPOS_CON_ERROR": ["", "POS", ""],
        }
    )
    final = pd.DataFrame({"CODIGO_INTERNO": ["1-1", "3-3"], "DESCRIPCION": ["a", "b"]})
    advertencias = pd.DataFrame(
        {"campo": ["CLASIFICADO"], "advertencia": ["solo 80% de la malla coincide"]}
    )
    escribir_snapshot(
        {
            "cargue_evaluados": evaluados,
            "cargue_estructura": estructura,
            "cargue_final": final,
            "cargue_reglas_advertencias": advertencias,
        },
        carpeta=carpeta,
    )


def test_listar_estructura_y_filtrar_por_listo(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        _snapshot_cargue_muestra(carpeta)
        r = cliente.get("/cargue/estructura", params={"listo": True})
        cuerpo = r.json()
        assert cuerpo["total"] == 2
        assert {f["CODIGO_INTERNO"] for f in cuerpo["filas"]} == {"1-1", "3-3"}
    finally:
        app.dependency_overrides.clear()


def test_cargue_final_puede_venir_vacio_sin_ser_un_error(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot(
            {"cargue_final": pd.DataFrame(columns=["CODIGO_INTERNO", "DESCRIPCION"])}, carpeta=carpeta
        )
        r = cliente.get("/cargue/final")
        assert r.status_code == 200
        assert r.json()["total"] == 0
    finally:
        app.dependency_overrides.clear()


def test_valores_de_columna_en_estructura_y_final(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        _snapshot_cargue_muestra(carpeta)
        r = cliente.get("/cargue/estructura/valores", params={"columna": "ESTADO"})
        assert r.json() == [
            {"valor": "Listo para cargue", "conteo": 2},
            {"valor": "Pendiente de clasificacion manual", "conteo": 1},
        ]
        r2 = cliente.get("/cargue/final/valores", params={"columna": "CODIGO_INTERNO"})
        assert {v["valor"] for v in r2.json()} == {"1-1", "3-3"}
    finally:
        app.dependency_overrides.clear()


def test_resumen_cargue_cuenta_listos_y_pendientes(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        _snapshot_cargue_muestra(carpeta)
        r = cliente.get("/cargue/resumen")
        assert r.json() == {"listos": 2, "pendientes": 1}
    finally:
        app.dependency_overrides.clear()


def test_advertencias_devuelve_la_lista_completa(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        _snapshot_cargue_muestra(carpeta)
        r = cliente.get("/cargue/advertencias")
        assert r.json() == [{"campo": "CLASIFICADO", "advertencia": "solo 80% de la malla coincide"}]
    finally:
        app.dependency_overrides.clear()
