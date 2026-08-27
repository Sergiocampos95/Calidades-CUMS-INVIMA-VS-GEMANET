import pandas as pd
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app.dependencies import carpeta_snapshots
from backend.app.main import app
from worker.almacen_snapshots import escribir_snapshot


def _cliente(tmp_path):
    carpeta = tmp_path / "snapshots"
    app.dependency_overrides[carpeta_snapshots] = lambda: carpeta
    return TestClient(app), carpeta


def _leer_xlsx(contenido: bytes):
    import io

    return load_workbook(io.BytesIO(contenido))


def test_descargar_candidatos_sin_snapshot_da_503(tmp_path):
    cliente, _ = _cliente(tmp_path)
    try:
        assert cliente.get("/descargas/candidatos").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_descargar_candidatos_arma_un_xlsx_valido_con_una_hoja_por_accion(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {"CODIGO_INTERNO": ["1-1", "2-2"], "accion": ["candidato", "ya_existe"]}
        )
        escribir_snapshot({"candidatos": df}, carpeta=carpeta)

        r = cliente.get("/descargas/candidatos")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
        assert "reporte_cruce_invima.xlsx" in r.headers["content-disposition"]

        libro = _leer_xlsx(r.content)
        assert set(libro.sheetnames) == {"candidato", "ya_existe"}
    finally:
        app.dependency_overrides.clear()


def test_descargar_auditoria_agrupa_por_estado_coherencia(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {"CODIGO_INTERNO": ["1-1", "2-2"], "ESTADO_COHERENCIA": ["correcto", "con_diferencias"]}
        )
        escribir_snapshot({"auditoria": df}, carpeta=carpeta)

        r = cliente.get("/descargas/auditoria")
        assert r.status_code == 200
        libro = _leer_xlsx(r.content)
        assert set(libro.sheetnames) == {"correcto", "con_diferencias"}
    finally:
        app.dependency_overrides.clear()


def test_descargar_cargue_final_vacio_no_revienta(tmp_path):
    """Caso real de hoy: 0 candidatos listos. generar_excel_cargue usa
    to_excel simple (no groupby), asi que un DataFrame vacio debe seguir
    produciendo un .xlsx valido, solo con encabezados."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(columns=["CODIGO_INTERNO", "DESCRIPCION"])
        escribir_snapshot({"cargue_final": df}, carpeta=carpeta)

        r = cliente.get("/descargas/cargue-final")
        assert r.status_code == 200
        libro = _leer_xlsx(r.content)
        hoja = libro[libro.sheetnames[0]]
        assert hoja.max_row == 1  # solo el encabezado
    finally:
        app.dependency_overrides.clear()


def test_descargar_cargue_estructura_sin_malla_da_503_con_motivo(tmp_path):
    cliente, _ = _cliente(tmp_path)
    try:
        r = cliente.get("/descargas/cargue-estructura")
        assert r.status_code == 503
        assert "Estructura Cargue Medicamentos" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()
