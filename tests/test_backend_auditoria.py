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


def test_filtro_por_multiples_estados_coherencia_separados_por_coma(tmp_path):
    """Pedido del usuario (2026-08-28): "mas bien seleccion multiple es lo
    mejor para el caso" -- varios valores separados por coma."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {
                "CODIGO_INTERNO": ["1-1", "2-2", "3-3"],
                "ESTADO_COHERENCIA": ["correcto", "con_diferencias", "vencido_en_invima"],
            }
        )
        escribir_snapshot({"auditoria": df}, carpeta=carpeta)

        r = cliente.get(
            "/auditoria", params={"estado_coherencia": "con_diferencias,vencido_en_invima"}
        )
        codigos = {f["CODIGO_INTERNO"] for f in r.json()["filas"]}
        assert codigos == {"2-2", "3-3"}
    finally:
        app.dependency_overrides.clear()


def test_valores_de_columna_para_el_filtro_estilo_excel(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame({"ESTADO_COHERENCIA": ["correcto", "correcto", "con_diferencias"]})
        escribir_snapshot({"auditoria": df}, carpeta=carpeta)

        r = cliente.get("/auditoria/valores", params={"columna": "ESTADO_COHERENCIA"})
        assert r.json() == [
            {"valor": "correcto", "conteo": 2},
            {"valor": "con_diferencias", "conteo": 1},
        ]
    finally:
        app.dependency_overrides.clear()


def _fila_auditable(codigo_interno, **overrides):
    """`filtrar_universo_auditable` (coherencia_invima.py) exige
    TIPO_CODIGO_INTERNO y ESTADO_LISTADO_INVIMA -- toda fila de estos tests
    de /resumen debe traerlas, o KeyError."""
    base = {
        "CODIGO_INTERNO": codigo_interno,
        "ACTIVO": "Si",
        "TIPO_CODIGO_INTERNO": "cum",
        "ESTADO_LISTADO_INVIMA": "vigente",
    }
    base.update(overrides)
    return base


def test_resumen_auditoria_cuenta_por_estado_coherencia(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            [
                _fila_auditable("1-1", ESTADO_COHERENCIA="correcto"),
                _fila_auditable("2-2", ESTADO_COHERENCIA="correcto"),
                _fila_auditable("3-3", ESTADO_COHERENCIA="con_diferencias"),
            ]
        )
        escribir_snapshot({"auditoria": df}, carpeta=carpeta)

        r = cliente.get("/auditoria/resumen")
        assert r.json() == {"correcto": 2, "con_diferencias": 1}
    finally:
        app.dependency_overrides.clear()


def test_resumen_auditoria_filtra_inactivos_salvo_la_excepcion_vigente(tmp_path):
    """Bug real (2026-09-01): el docstring de /resumen decia que el
    snapshot "auditoria" ya llegaba filtrado al universo auditable desde
    `pipeline.py` -- pero ese filtro se saco de ahi (para que
    /auditoria/dimensiones pueda ver el universo COMPLETO, ver
    pipeline.py) y el router nunca compenso. Resultado medido en
    produccion: "Vencido en INVIMA" mostraba 50.039 en vez de los 371
    activos reales. El router debe filtrar el mismo universo auditable que
    ya usan las calidades (`filtrar_universo_auditable`): activos, mas la
    unica excepcion (inactivo en Gemma Net pero INVIMA lo declara vigente)."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            [
                _fila_auditable("1-1", ESTADO_COHERENCIA="correcto", ACTIVO="Si"),
                # Inactivo y SIN correspondencia vigente en INVIMA -- debe
                # descartarse, es el caso que el bug dejaba pasar.
                _fila_auditable(
                    "2-2", ESTADO_COHERENCIA="con_diferencias", ACTIVO="No",
                    ESTADO_LISTADO_INVIMA="vencido",
                ),
                # Inactivo pero INVIMA SI lo declara vigente -- la unica
                # excepcion, debe contarse igual.
                _fila_auditable(
                    "3-3", ESTADO_COHERENCIA="con_diferencias", ACTIVO="No",
                    ESTADO_LISTADO_INVIMA="vigente",
                ),
            ]
        )
        escribir_snapshot({"auditoria": df}, carpeta=carpeta)

        r = cliente.get("/auditoria/resumen")
        assert r.json() == {"correcto": 1, "con_diferencias": 1}
    finally:
        app.dependency_overrides.clear()
