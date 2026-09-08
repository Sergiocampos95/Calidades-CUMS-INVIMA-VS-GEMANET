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
        # El veredicto de vigencia, del que sale PRIORIDAD_ACCION.
        "ESTADO_CUM_INVIMA": "Activo",
    }
    base.update(overrides)
    return base


def test_resumen_auditoria_cuenta_por_prioridad(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            [
                _fila_auditable("1-1", ESTADO_COHERENCIA="correcto"),
                _fila_auditable("2-2", ESTADO_COHERENCIA="correcto"),
                # INVIMA lo declara Inactivo y aqui sigue activo: nivel 1.
                _fila_auditable(
                    "3-3", ESTADO_COHERENCIA="con_diferencias", ESTADO_CUM_INVIMA="Inactivo"
                ),
            ]
        )
        escribir_snapshot({"auditoria": df}, carpeta=carpeta)

        r = cliente.get("/auditoria/resumen")
        assert r.json() == {"5_informativo": 2, "1_critico": 1}
    finally:
        app.dependency_overrides.clear()


def test_resumen_auditoria_suma_exactamente_el_total_de_la_tabla(tmp_path):
    """Bug real reportado por el usuario (2026-09-07) comparando las dos
    pantallas: la tarjeta "Vencido en INVIMA" decia 540 y al abrirla la tabla
    mostraba 360.

    La causa era que /resumen contaba sobre `_tabla_auditoria` (universo
    auditable, que CONSERVA la excepcion de inactivo-aqui/vigente-en-INVIMA) y
    GET /auditoria sobre los activos, que la descarta. La diferencia exacta
    entre las dos cifras era esa excepcion.

    La invariante que cierra el bug para siempre no es "cuantas filas da cada
    endpoint" sino que la SUMA de las tarjetas sea el total de la tabla: si
    vuelven a divergir, este test falla sin importar por que criterio."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            [
                _fila_auditable("1-1", ESTADO_COHERENCIA="correcto", ACTIVO="Si"),
                # Inactivo y sin vigencia en INVIMA: fuera del universo auditable.
                _fila_auditable(
                    "2-2", ESTADO_COHERENCIA="con_diferencias", ACTIVO="No",
                    ESTADO_LISTADO_INVIMA="vencido", ESTADO_CUM_INVIMA="Inactivo",
                ),
                # Inactivo pero vigente en INVIMA: `filtrar_universo_auditable`
                # lo CONSERVA, y esta vista igual no debe contarlo -- es una
                # lista de trabajo y un inactivo no es una accion pendiente.
                # Contarlo en la tarjeta y no en la tabla era el bug.
                _fila_auditable(
                    "3-3", ESTADO_COHERENCIA="con_diferencias", ACTIVO="No",
                    ESTADO_LISTADO_INVIMA="vigente",
                ),
            ]
        )
        escribir_snapshot({"auditoria": df}, carpeta=carpeta)

        resumen = cliente.get("/auditoria/resumen").json()
        total_tabla = cliente.get("/auditoria").json()["total"]

        assert sum(resumen.values()) == total_tabla
        assert resumen == {"5_informativo": 1}
    finally:
        app.dependency_overrides.clear()


def test_auditoria_filtra_por_nivel_de_prioridad(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            [
                _fila_auditable("1-1", ESTADO_COHERENCIA="correcto"),
                _fila_auditable(
                    "2-2", ESTADO_COHERENCIA="con_diferencias", ESTADO_CUM_INVIMA="Inactivo"
                ),
            ]
        )
        escribir_snapshot({"auditoria": df}, carpeta=carpeta)

        pagina = cliente.get("/auditoria", params={"prioridad": "1_critico"}).json()
        assert pagina["total"] == 1
        assert pagina["filas"][0]["CODIGO_INTERNO"] == "2-2"
    finally:
        app.dependency_overrides.clear()


def test_auditoria_recorta_las_columnas_que_viajan_sin_afectar_la_busqueda(tmp_path):
    """El recorte es de SERIALIZACION, no de filtrado: buscar por un campo que
    no viaja debe seguir encontrando la fila. Si el recorte se aplicara antes
    de `paginar`, la busqueda libre (que mira todas las columnas a proposito)
    dejaria de ver ese campo y la fila desapareceria."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df = pd.DataFrame(
            [
                _fila_auditable("1-1", DESCRIPCION="AMOXICILINA", PRINCIPIO_ACTIVO="AMOXICILINA"),
                _fila_auditable("2-2", DESCRIPCION="IBUPROFENO", PRINCIPIO_ACTIVO="IBUPROFENO"),
            ]
        )
        escribir_snapshot({"auditoria": df}, carpeta=carpeta)

        pedidas = "CODIGO_INTERNO,DESCRIPCION"
        pagina = cliente.get(
            "/auditoria", params={"columnas": pedidas, "q": "IBUPROFENO"}
        ).json()

        assert pagina["total"] == 1, "la busqueda debe ver PRINCIPIO_ACTIVO aunque no viaje"
        assert list(pagina["filas"][0].keys()) == ["CODIGO_INTERNO", "DESCRIPCION"]
    finally:
        app.dependency_overrides.clear()


def test_auditoria_ignora_columnas_inexistentes_en_vez_de_reventar(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": pd.DataFrame([_fila_auditable("1-1")])}, carpeta=carpeta)

        pagina = cliente.get(
            "/auditoria", params={"columnas": "CODIGO_INTERNO,NO_EXISTE"}
        ).json()
        assert list(pagina["filas"][0].keys()) == ["CODIGO_INTERNO"]

        # Ninguna valida: se sirve la tabla completa en vez de una tabla sin
        # columnas, que en pantalla es indistinguible de "no hay datos".
        completa = cliente.get("/auditoria", params={"columnas": "NADA,TAMPOCO"}).json()
        assert "CODIGO_INTERNO" in completa["filas"][0]
    finally:
        app.dependency_overrides.clear()
