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
            "DESCRIPCION": ["ACETAMINOFEN 500MG TABLETA", "IBUPROFENO 400MG TABLETA", "NAPROXENO 250MG TABLETA"],
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


def test_columnas_trio_y_columna_estado_expuestas_en_h1(tmp_path):
    """Bug real (2026-08-27): el frontend re-derivaba las columnas a mano a
    partir de campos_acumulados, que para H1 esta vacio -- se perdian
    ESTADO_COHERENCIA/NOVEDAD_VIGENCIA_INVIMA/DETALLE_VIGENCIA_INVIMA, justo
    la vigencia que hay que poder ver. Ahora el backend expone las columnas
    reales de la tabla, y el frontend las usa tal cual."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        cadena = {e["nombre"]: e for e in cliente.get("/auditoria/cadena").json()}
        h1 = cadena["H1"]
        assert set(h1["columnas_trio"]) == {
            "ESTADO_COHERENCIA",
            "NOVEDAD_VIGENCIA_INVIMA",
            "DETALLE_VIGENCIA_INVIMA",
        }
        assert h1["columna_estado"] == "ESTADO_CADENA_H1"
    finally:
        app.dependency_overrides.clear()


def test_tabla_de_un_eslabon_trae_descripcion_no_producto(tmp_path):
    """PRODUCTO es un campo del lado INVIMA (universo); auditoria trae el
    lado Gemma Net, donde el texto identificador es DESCRIPCION. Bug real:
    pedir "PRODUCTO" se descartaba en silencio y la tabla quedaba sin
    columna identificadora (se veia como una columna de guiones)."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        r = cliente.get("/auditoria/cadena/H1")
        fila = r.json()["filas"][0]
        assert "DESCRIPCION" in fila
        assert "PRODUCTO" not in fila
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
