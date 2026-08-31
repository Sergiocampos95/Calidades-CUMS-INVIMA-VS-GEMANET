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
    return pd.DataFrame(
        {
            "CODIGO_INTERNO": ["1-1", "2-2", "CODIGO-LEGADO"],
            "DESCRIPCION": ["A", "B", "C"],
            "ACTIVO": ["SI", "SI", "NO"],
            "ESTADO_COHERENCIA": [
                EstadoCoherencia.CORRECTO.value,
                EstadoCoherencia.VENCIDO_EN_INVIMA.value,
                EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value,
            ],
            "NATURALEZA_HALLAZGO": ["", "Vigencia en riesgo", ""],
            "CODIGO_DUPLICADO_EN_REPORTE": [False, False, False],
            "PORCENTAJE_COMPLETITUD_REPORTE": [100.0, 80.0, 60.0],
            "VALORES_FUERA_DE_DOMINIO": ["", "", ""],
            "INCONSISTENCIA_NUMERICA": ["", "", ""],
            "FORMATO_CODIGO_INTERNO_INVALIDO": ["", "", ""],
            "INTEGRIDAD_REFERENCIAL_CATALOGO": ["", "", ""],
        }
    )


def test_sin_snapshot_responde_503_en_las_3_rutas(tmp_path):
    cliente, _ = _cliente(tmp_path)
    try:
        assert cliente.get("/auditoria/calidades").status_code == 503
        assert cliente.get("/auditoria/dimensiones").status_code == 503
        assert cliente.get("/auditoria/naturaleza").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_listar_calidades_devuelve_10_con_conteos_correctos(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        r = cliente.get("/auditoria/calidades")
        assert r.status_code == 200
        calidades = {c["nombre"]: c for c in r.json()}
        assert len(calidades) == 10
        # CODIGO-LEGADO no sigue el formato EXPEDIENTE-CONSECUTIVO, y 500-1 no
        # se encontró en INVIMA — ambos caen en "No se pudo encontrar en INVIMA".
        assert calidades["No se pudo encontrar en INVIMA"]["medicamentos"] == 1
        assert calidades["Registro vencido en INVIMA"]["medicamentos"] == 1
    finally:
        app.dependency_overrides.clear()


def test_obtener_calidad_trae_solo_los_medicamentos_de_esa_calidad(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        r = cliente.get("/auditoria/calidades/Registro vencido en INVIMA")
        assert r.status_code == 200
        codigos = {f["CODIGO_INTERNO"] for f in r.json()["filas"]}
        assert codigos == {"2-2"}
    finally:
        app.dependency_overrides.clear()


def test_calidad_desconocida_da_404(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        assert cliente.get("/auditoria/calidades/no-existe").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_valores_de_columna_de_una_calidad_no_choca_con_su_propia_ruta(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        r = cliente.get(
            "/auditoria/calidades/Registro vencido en INVIMA/valores",
            params={"columna": "CODIGO_INTERNO"},
        )
        assert r.status_code == 200
        assert r.json() == [{"valor": "2-2", "conteo": 1}]
    finally:
        app.dependency_overrides.clear()


def test_dimensiones_calidad(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        r = cliente.get("/auditoria/dimensiones")
        assert r.status_code == 200
        cuerpo = r.json()
        assert cuerpo["n_total_auditado"] == 3
        assert cuerpo["completitud_promedio"] == 80.0
        assert cuerpo["duplicados"] == 0
    finally:
        app.dependency_overrides.clear()


def test_naturaleza_hallazgos_solo_devuelve_conteos_positivos(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        r = cliente.get("/auditoria/naturaleza")
        assert r.status_code == 200
        cuerpo = r.json()
        assert len(cuerpo) == 1
        assert cuerpo[0]["naturaleza"] == "Vigencia en riesgo"
        assert cuerpo[0]["medicamentos"] == 1
        assert "Revisar" in cuerpo[0]["que_hacer"]
    finally:
        app.dependency_overrides.clear()
