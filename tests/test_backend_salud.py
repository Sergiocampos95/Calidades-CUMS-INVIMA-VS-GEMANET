"""Pruebas de GET /salud -- siempre contra una carpeta/sqlite de prueba
(tmp_path), nunca la carpeta real `data_runtime/` ni el worker real."""

import pandas as pd
from fastapi.testclient import TestClient

from backend.app.dependencies import carpeta_snapshots, ruta_estado
from backend.app.main import app
from worker.almacen_snapshots import COLUMNAS_ESPERADAS, escribir_snapshot
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


def _snapshot_al_dia() -> dict:
    """Un snapshot con el esquema que espera el codigo actual."""
    return {
        tabla: pd.DataFrame({c: [""] for c in columnas})
        for tabla, columnas in COLUMNAS_ESPERADAS.items()
    }


def test_snapshot_de_version_anterior_se_reporta_desactualizado(tmp_path):
    """Regla del usuario (2026-09-02): una colision con una version pasada no
    puede pasar desapercibida si ademas el snapshot es antiguo (>50 min). Un
    snapshot al que le faltan columnas produce cifras en cero que se leen como
    "no hay hallazgos", pero si es muy reciente se le da margen al worker para
    que lo refresque en el proximo ciclo."""
    import json

    cliente, carpeta, sqlite = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": pd.DataFrame({"a": [1]})}, carpeta=carpeta)
        # Hacer el snapshot antiguo (>50 min) para que se marque desactualizado
        puntero = carpeta / "actual.json"
        datos = json.loads(puntero.read_text(encoding="utf-8"))
        datos["generado_utc"] = "20200101T000000000000Z"  # hace anos, claramente viejo
        puntero.write_text(json.dumps(datos), encoding="utf-8")
        # Registrar refresco viejo tambien
        registrar_refresco(
            EstadoRefresco("2020-01-01T00:00:00+00:00", "2020-01-01T00:01:00+00:00", 60.0, ESTADO_OK),
            sqlite,
        )
        cuerpo = cliente.get("/salud").json()
        assert cuerpo["estado"] == "desactualizado"
        assert "versión anterior" in cuerpo["detalle_error"]
        assert "Ejecute una actualización" in cuerpo["detalle_error"]
    finally:
        app.dependency_overrides.clear()


def test_refresco_reciente_y_exitoso_da_ok(tmp_path):
    cliente, carpeta, sqlite = _cliente(tmp_path)
    try:
        # El snapshot tiene que traer las columnas que el codigo de HOY
        # espera; si no, /salud lo reporta como desactualizado por colision de
        # versiones (ver COLUMNAS_ESPERADAS en worker/almacen_snapshots.py).
        escribir_snapshot(_snapshot_al_dia(), carpeta=carpeta)
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
