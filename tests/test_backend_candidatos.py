import pandas as pd
from fastapi.testclient import TestClient

from backend.app.dependencies import carpeta_snapshots
from backend.app.main import app
from worker.almacen_snapshots import escribir_snapshot


def _cliente(tmp_path):
    carpeta = tmp_path / "snapshots"
    app.dependency_overrides[carpeta_snapshots] = lambda: carpeta
    return TestClient(app), carpeta


def test_sin_snapshot_todavia_responde_503_no_lista_vacia(tmp_path):
    """Degradacion explicita: "no hay snapshot" y "cero candidatos" son dos
    cosas distintas -- confundirlas haria pensar que ya se cargo todo."""
    cliente, _ = _cliente(tmp_path)
    try:
        r = cliente.get("/candidatos")
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_lista_candidatos_del_snapshot(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {"CODIGO_INTERNO": ["1-1", "2-2", "3-3"], "accion": ["candidato", "ya_existe", "cuarentena"]}
        )
        escribir_snapshot({"candidatos": df}, carpeta=carpeta)

        r = cliente.get("/candidatos")
        cuerpo = r.json()
        assert cuerpo["total"] == 3
        assert cuerpo["limite_aplicado"] is False
        assert {f["CODIGO_INTERNO"] for f in cuerpo["filas"]} == {"1-1", "2-2", "3-3"}
    finally:
        app.dependency_overrides.clear()


def test_busqueda_libre_filtra_por_cualquier_columna(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {"CODIGO_INTERNO": ["1-1", "2-2"], "accion": ["candidato", "ya_existe"]}
        )
        escribir_snapshot({"candidatos": df}, carpeta=carpeta)

        r = cliente.get("/candidatos", params={"q": "2-2"})
        cuerpo = r.json()
        assert cuerpo["total"] == 1
        assert cuerpo["filas"][0]["CODIGO_INTERNO"] == "2-2"
    finally:
        app.dependency_overrides.clear()


def test_limite_de_previsualizacion_se_respeta_y_se_puede_pedir_todo(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame({"CODIGO_INTERNO": [str(i) for i in range(1500)]})
        escribir_snapshot({"candidatos": df}, carpeta=carpeta)

        recortado = cliente.get("/candidatos").json()
        assert recortado["total"] == 1500
        assert recortado["visibles"] == 1000
        assert recortado["limite_aplicado"] is True

        completo = cliente.get("/candidatos", params={"todo": True}).json()
        assert completo["visibles"] == 1500
        assert completo["limite_aplicado"] is False
    finally:
        app.dependency_overrides.clear()


def test_resumen_candidatos_cuenta_por_accion(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame({"accion": ["candidato", "candidato", "ya_existe", "cuarentena"]})
        escribir_snapshot({"candidatos": df}, carpeta=carpeta)

        r = cliente.get("/candidatos/resumen")
        assert r.json() == {"candidato": 2, "ya_existe": 1, "cuarentena": 1}
    finally:
        app.dependency_overrides.clear()


def test_filtro_por_accion(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {"CODIGO_INTERNO": ["1-1", "2-2"], "accion": ["candidato", "ya_existe"]}
        )
        escribir_snapshot({"candidatos": df}, carpeta=carpeta)

        r = cliente.get("/candidatos", params={"accion": "candidato"})
        cuerpo = r.json()
        assert cuerpo["total"] == 1
        assert cuerpo["filas"][0]["CODIGO_INTERNO"] == "1-1"
    finally:
        app.dependency_overrides.clear()


def test_valores_de_columna_para_el_filtro_estilo_excel(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame({"accion": ["candidato", "candidato", "ya_existe"]})
        escribir_snapshot({"candidatos": df}, carpeta=carpeta)

        r = cliente.get("/candidatos/valores", params={"columna": "accion"})
        assert r.json() == [{"valor": "candidato", "conteo": 2}, {"valor": "ya_existe", "conteo": 1}]
    finally:
        app.dependency_overrides.clear()


def test_ordenar_por_columna(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame({"CODIGO_INTERNO": ["3-3", "1-1", "2-2"]})
        escribir_snapshot({"candidatos": df}, carpeta=carpeta)

        r = cliente.get("/candidatos", params={"ordenar_por": "CODIGO_INTERNO"})
        assert [f["CODIGO_INTERNO"] for f in r.json()["filas"]] == ["1-1", "2-2", "3-3"]
    finally:
        app.dependency_overrides.clear()


def test_resumen_metodos_desglosa_unidad_y_marca(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            {
                "unidad_metodo": ["exacto_sigla", "exacto_sigla", "fuzzy"],
                "marca_metodo": ["sin_resolver", "sin_resolver", "exacto_sigla"],
            }
        )
        escribir_snapshot({"candidatos": df}, carpeta=carpeta)

        r = cliente.get("/candidatos/resumen-metodos")
        cuerpo = r.json()
        assert cuerpo["unidad"] == {"exacto_sigla": 2, "fuzzy": 1}
        assert cuerpo["marca"] == {"sin_resolver": 2, "exacto_sigla": 1}
    finally:
        app.dependency_overrides.clear()
