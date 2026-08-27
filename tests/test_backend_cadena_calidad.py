import pandas as pd
from fastapi.testclient import TestClient

from backend.app.dependencies import carpeta_snapshots
from backend.app.main import app
from gemma_cum_loader.auditoria.coherencia_invima import EstadoCoherencia
from worker.almacen_snapshots import escribir_snapshot


def _cliente(tmp_path):
    carpeta = tmp_path / "snapshots"
    app.dependency_overrides[carpeta_snapshots] = lambda: carpeta
    return TestClient(app), carpeta


def _auditoria_muestra():
    # Fila 1-1: pasa TODA la cadena. Fila 2-2: pasa H1 pero se cae en H2
    # (DESCRIPCION difiere). Fila 3-3: no tiene correspondencia con INVIMA,
    # se cae en H1 -- exactamente la propiedad que valida
    # test_cadena_es_subconjunto_estricto en el paquete de coherencia_invima.
    return pd.DataFrame(
        {
            "CODIGO_INTERNO": ["1-1", "2-2", "3-3"],
            "ESTADO_COHERENCIA": [
                EstadoCoherencia.CORRECTO.value,
                EstadoCoherencia.CON_DIFERENCIAS.value,
                EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value,
            ],
            "NOVEDAD_VIGENCIA_INVIMA": ["", "", ""],
            "DETALLE_VIGENCIA_INVIMA": ["", "", ""],
            "DESCRIPCION_VALIDACION": ["coincide", "difiere", "sin comparar"],
            "DESCRIPCION_GEMANET": ["a", "b", "c"],
            "DESCRIPCION_INVIMA": ["a", "x", ""],
            "PRINCIPIO_ACTIVO_VALIDACION": ["coincide", "coincide", "sin comparar"],
            "PRINCIPIO_ACTIVO_GEMANET": ["a", "b", "c"],
            "PRINCIPIO_ACTIVO_INVIMA": ["a", "b", ""],
            "CONCENTRACION_VALIDACION": ["coincide", "coincide", "sin comparar"],
            "CONCENTRACION_GEMANET": ["a", "b", "c"],
            "CONCENTRACION_INVIMA": ["a", "b", ""],
            "UNIDAD_MEDIDA_VALIDACION": ["coincide", "coincide", "sin comparar"],
            "UNIDAD_MEDIDA_GEMANET": ["a", "b", "c"],
            "UNIDAD_MEDIDA_INVIMA": ["a", "b", ""],
        }
    )


def test_sin_snapshot_todavia_responde_503(tmp_path):
    cliente, _ = _cliente(tmp_path)
    try:
        assert cliente.get("/auditoria/cadena").status_code == 503
        assert cliente.get("/auditoria/cadena/H1").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_listar_cadena_devuelve_los_5_eslabones_en_orden(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        r = cliente.get("/auditoria/cadena")
        nombres = [e["nombre"] for e in r.json()]
        assert nombres == ["H1", "H2", "H3", "H4", "H6"]
    finally:
        app.dependency_overrides.clear()


def test_h1_universo_es_todo_y_h2_es_subconjunto(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        cadena = {e["nombre"]: e for e in cliente.get("/auditoria/cadena").json()}
        assert cadena["H1"]["universo"] == 3  # las 3 filas se evaluan en H1
        assert cadena["H2"]["universo"] == 2  # solo las que pasaron H1 (1-1, 2-2)
    finally:
        app.dependency_overrides.clear()


def test_eslabon_desconocido_da_404(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        assert cliente.get("/auditoria/cadena/H99").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_filtro_solo_pasa_en_la_tabla_de_un_eslabon(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        r = cliente.get("/auditoria/cadena/H2", params={"solo_pasa": True})
        codigos = {f["CODIGO_INTERNO"] for f in r.json()["filas"]}
        assert codigos == {"1-1"}  # 2-2 tiene correspondencia (paso H1) pero se cae en H2
    finally:
        app.dependency_overrides.clear()
