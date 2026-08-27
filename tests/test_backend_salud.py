"""Pruebas de GET /salud -- siempre contra una carpeta/sqlite de prueba
(tmp_path), nunca la carpeta real `data_runtime/` ni el worker real."""

import pandas as pd
from fastapi.testclient import TestClient

from backend.app.dependencies import carpeta_snapshots, ruta_estado
from backend.app.main import app
from worker.almacen_snapshots import escribir_snapshot
from worker.estado import ESTADO_ERROR, ESTADO_OK, EstadoRefresco, registrar_refresco


def _cliente(tmp_path):
    carpeta = tmp_path / "snapshots"
    sqlite = tmp_path / "estado.sqlite3"
    app.dependency_overrides[carpeta_snapshots] = lambda: carpeta
    app.dependency_overrides[ruta_estado] = lambda: sqlite
    cliente = TestClient(app)
    return cliente, carpeta, sqlite


def test_sin_ningun_refresco_todavia_da_sin_datos(tmp_path):
    cliente, _, _ = _cliente(tmp_path)
    try:
        r = cliente.get("/salud")
        assert r.status_code == 200
        assert r.json()["estado"] == "sin_datos"
    finally:
        app.dependency_overrides.clear()


def test_refresco_reciente_y_exitoso_da_ok(tmp_path):
    cliente, carpeta, sqlite = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": pd.DataFrame({"a": [1]})}, carpeta=carpeta)
        registrar_refresco(
            EstadoRefresco("2026-01-01T00:00:00+00:00", "2026-01-01T00:01:00+00:00", 60.0, ESTADO_OK),
            sqlite,
        )
        r = cliente.get("/salud")
        assert r.json()["estado"] == "ok"
    finally:
        app.dependency_overrides.clear()


def test_snapshot_viejo_da_desactualizado_aunque_el_refresco_haya_sido_ok(tmp_path):
    """Si el snapshot vigente tiene mas de 2x el intervalo del worker, se
    marca "desactualizado" -- aunque el ULTIMO refresco registrado haya
    salido bien (podria ser viejo tambien, o el worker dejo de correr)."""
    import json

    cliente, carpeta, sqlite = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": pd.DataFrame({"a": [1]})}, carpeta=carpeta)
        puntero = carpeta / "actual.json"
        datos = json.loads(puntero.read_text(encoding="utf-8"))
        datos["generado_utc"] = "20200101T000000000000Z"  # hace anos, claramente viejo
        puntero.write_text(json.dumps(datos), encoding="utf-8")
        registrar_refresco(
            EstadoRefresco("2020-01-01T00:00:00+00:00", "2020-01-01T00:01:00+00:00", 60.0, ESTADO_OK),
            sqlite,
        )
        r = cliente.get("/salud")
        assert r.json()["estado"] == "desactualizado"
    finally:
        app.dependency_overrides.clear()


def test_ultimo_refresco_fallido_da_estado_error(tmp_path):
    cliente, carpeta, sqlite = _cliente(tmp_path)
    try:
        # Snapshot bueno de una corrida anterior -- sigue siendo el vigente
        # aunque la corrida MAS RECIENTE haya fallado.
        escribir_snapshot({"auditoria": pd.DataFrame({"a": [1]})}, carpeta=carpeta)
        registrar_refresco(
            EstadoRefresco(
                "2026-01-01T01:00:00+00:00",
                "2026-01-01T01:01:00+00:00",
                12.0,
                ESTADO_ERROR,
                "ErrorGemaNetDB: no responde",
            ),
            sqlite,
        )
        r = cliente.get("/salud")
        cuerpo = r.json()
        assert cuerpo["estado"] == "error"
        assert "no responde" in cuerpo["detalle_error"]
    finally:
        app.dependency_overrides.clear()
