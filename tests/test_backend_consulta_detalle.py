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
        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "500-1"})
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_encuentra_por_codigo_exacto_en_ambos_lados(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_universo = pd.DataFrame({"CODIGO_INTERNO": ["500-1"], "PRODUCTO": ["ACETAMINOFEN"], "ESTADO_REGISTRO": ["Vigente"]})
        df_auditoria = pd.DataFrame({"CODIGO_INTERNO": ["500-1"], "DESCRIPCION": ["ACETAMINOFEN"], "CUM_RECONSTRUIDO": [""], "ESTADO_COHERENCIA": ["correcto"]})
        escribir_snapshot({"universo": df_universo, "auditoria": df_auditoria}, carpeta=carpeta)

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "500-1"})
        cuerpo = r.json()
        assert len(cuerpo["invima"]) == 1
        assert len(cuerpo["gemma_net"]) == 1
    finally:
        app.dependency_overrides.clear()


def test_usa_cum_reconstruido_para_encontrar_en_invima(tmp_path):
    """Bug real (2026-09-01): un codigo 'CUM con sufijo ATC'
    (00040284-02-0N03AG01) trae el EXPEDIENTE-CONSECUTIVO real EMBEBIDO,
    distinto del que usa INVIMA como llave ('40284-2'). coherencia_invima.py
    ya lo reconstruye en CUM_RECONSTRUIDO; el endpoint debe usar esa llave
    ADEMAS del codigo crudo al buscar en "universo" -- sin esto, un
    medicamento que SI tiene correspondencia (segun ESTADO_COHERENCIA)
    aparecia como si no existiera en INVIMA."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_universo = pd.DataFrame({"CODIGO_INTERNO": ["40284-2"], "PRODUCTO": ["DEPAKENE JARABE"], "ESTADO_REGISTRO": ["Vigente"]})
        df_auditoria = pd.DataFrame(
            {
                "CODIGO_INTERNO": ["00040284-02-0N03AG01"],
                "DESCRIPCION": ["DEPAKENE JARABE"],
                "CUM_RECONSTRUIDO": ["40284-2"],
                "ESTADO_COHERENCIA": ["con_diferencias"],
            }
        )
        escribir_snapshot({"universo": df_universo, "auditoria": df_auditoria}, carpeta=carpeta)

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "00040284-02-0N03AG01"})
        cuerpo = r.json()
        assert len(cuerpo["invima"]) == 1
        assert cuerpo["invima"][0]["CODIGO_INTERNO"] == "40284-2"
        assert len(cuerpo["gemma_net"]) == 1
    finally:
        app.dependency_overrides.clear()


def test_sin_cum_reconstruido_no_inventa_coincidencias(tmp_path):
    """Un codigo sin correspondencia real (CUM_RECONSTRUIDO vacio) no debe
    matchear ninguna fila de INVIMA por casualidad."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_universo = pd.DataFrame({"CODIGO_INTERNO": ["999-9"], "PRODUCTO": ["OTRO MEDICAMENTO"], "ESTADO_REGISTRO": ["Vigente"]})
        df_auditoria = pd.DataFrame(
            {
                "CODIGO_INTERNO": ["CODIGO-LEGADO-SIN-CUM"],
                "DESCRIPCION": ["ALGO"],
                "CUM_RECONSTRUIDO": [""],
                "ESTADO_COHERENCIA": ["sin_correspondencia_invima"],
            }
        )
        escribir_snapshot({"universo": df_universo, "auditoria": df_auditoria}, carpeta=carpeta)

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "codigo-legado-sin-cum"})
        cuerpo = r.json()
        assert cuerpo["invima"] == []
        assert len(cuerpo["gemma_net"]) == 1
    finally:
        app.dependency_overrides.clear()


def test_multiples_codigos_separados_por_coma(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_universo = pd.DataFrame({"CODIGO_INTERNO": ["500-1", "500-2"], "PRODUCTO": ["A", "B"], "ESTADO_REGISTRO": ["Vigente", "Vigente"]})
        df_auditoria = pd.DataFrame({"CODIGO_INTERNO": ["500-1"], "DESCRIPCION": ["A"], "CUM_RECONSTRUIDO": [""], "ESTADO_COHERENCIA": ["correcto"]})
        escribir_snapshot({"universo": df_universo, "auditoria": df_auditoria}, carpeta=carpeta)

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "500-1, 500-2"})
        cuerpo = r.json()
        assert cuerpo["codigos_consultados"] == ["500-1", "500-2"]
        assert len(cuerpo["invima"]) == 2
    finally:
        app.dependency_overrides.clear()


def test_incluye_estado_y_fechas_de_ambas_fuentes(tmp_path):
    """Reescrito (2026-09-01) para reflejar el contrato REAL del router
    despues de su reescritura completa: no existen las claves inventadas
    ESTADO_GEMMA_NET / ESTADO_INVIMA / FECHA_INICIO_GEMMA_NET /
    FECHA_FIN_GEMMA_NET -- el router pasa las columnas de Gemma Net tal
    cual vienen de la fila de auditoria (FECHA_INICIO, FECHA_FIN, ACTIVO)
    y solo agrega ACTIVO_GEMMA_NET como alias de ACTIVO. Del lado INVIMA,
    las columnas *_INVIMA (ESTADO_LISTADO_INVIMA, ESTADO_INVIMA_DETALLE,
    FECHA_ACTIVO_INVIMA, FECHA_INACTIVO_INVIMA, FECHA_VENCIMIENTO_INVIMA)
    ya vienen calculadas por coherencia_invima.py en la propia fila de
    auditoria, y viajan intactas tanto en "gemma_net" como copiadas hacia
    "invima" cuando ese lado no las trae (confirmado con TestClient antes
    de escribir este assert, no asumido)."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_universo = pd.DataFrame({
            "CODIGO_INTERNO": ["500-1"],
            "PRODUCTO": ["ACETAMINOFEN"],
            "ESTADO_REGISTRO": ["Vigente"],
        })
        df_auditoria = pd.DataFrame({
            "CODIGO_INTERNO": ["500-1"],
            "DESCRIPCION": ["ACETAMINOFEN"],
            "ACTIVO": ["SI"],
            "ESTADO_COHERENCIA": ["correcto"],
            "FECHA_INICIO": ["2024-02-01"],
            "FECHA_FIN": ["2025-06-30"],
            "CUM_RECONSTRUIDO": [""],
            "ESTADO_LISTADO_INVIMA": ["vigente"],
            "ESTADO_INVIMA_DETALLE": ["Vigente"],
            "FECHA_ACTIVO_INVIMA": ["2024-01-15"],
            "FECHA_INACTIVO_INVIMA": [pd.NaT],
            "FECHA_VENCIMIENTO_INVIMA": ["2025-12-31"],
        })
        escribir_snapshot({"universo": df_universo, "auditoria": df_auditoria}, carpeta=carpeta)

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "500-1"})
        cuerpo = r.json()
        fila_gemma = cuerpo["gemma_net"][0]
        fila_invima = cuerpo["invima"][0]

        assert fila_gemma["ACTIVO_GEMMA_NET"] == "SI"
        assert fila_gemma["FECHA_INICIO"] == "2024-02-01"
        assert fila_gemma["FECHA_FIN"] == "2025-06-30"
        assert fila_gemma["ESTADO_LISTADO_INVIMA"] == "vigente"
        assert fila_gemma["FECHA_ACTIVO_INVIMA"] == "2024-01-15"
        assert fila_gemma["FECHA_VENCIMIENTO_INVIMA"] == "2025-12-31"
        # NaT del lado INVIMA se serializa como null, nunca el string "NaT".
        assert fila_gemma["FECHA_INACTIVO_INVIMA"] is None

        # "invima" trae su propio ESTADO_REGISTRO de "universo" (Vigentes),
        # complementado con las columnas *_INVIMA que ya trae auditoria.
        assert fila_invima["ESTADO_REGISTRO"] == "Vigente"
        assert fila_invima["ESTADO_LISTADO_INVIMA"] == "vigente"
        assert fila_invima["FECHA_ACTIVO_INVIMA"] == "2024-01-15"
        assert fila_invima["FECHA_VENCIMIENTO_INVIMA"] == "2025-12-31"
    finally:
        app.dependency_overrides.clear()


def test_fecha_nat_se_serializa_como_null_no_como_texto_nat(tmp_path):
    """Bug real (2026-09-01, ver comentario en _sanitizar_valor): pd.NaT se
    comporta como instancia de datetime para isinstance() pero pd.isna()
    debe evaluarse antes -- de lo contrario el JSON trae el string literal
    "NaT" y el frontend lo muestra en pantalla en vez de tratarlo como
    vacio."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_universo = pd.DataFrame({
            "CODIGO_INTERNO": ["500-1"],
            "PRODUCTO": ["ACETAMINOFEN"],
            "ESTADO_REGISTRO": ["Vigente"],
            "FECHA_ACTIVO": [pd.NaT],
        })
        df_auditoria = pd.DataFrame({
            "CODIGO_INTERNO": ["500-1"],
            "DESCRIPCION": ["ACETAMINOFEN"],
            "ESTADO_COHERENCIA": ["correcto"],
            "CUM_RECONSTRUIDO": [""],
            "FECHA_INICIO": [pd.NaT],
        })
        escribir_snapshot({"universo": df_universo, "auditoria": df_auditoria}, carpeta=carpeta)

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "500-1"})
        cuerpo = r.json()
        assert cuerpo["invima"][0]["FECHA_ACTIVO"] is None
        assert cuerpo["gemma_net"][0]["FECHA_INICIO"] is None
        # Nunca el texto literal "NaT" en el JSON crudo.
        assert "NaT" not in r.text
    finally:
        app.dependency_overrides.clear()


def test_fila_sintetica_de_invima_para_codigo_vencido_no_presente_en_universo(tmp_path):
    """Caso real que motivo este fix (2026-09-01): 20102710-2 esta VENCIDO
    en INVIMA, asi que no aparece en el snapshot "universo" (solo Vigentes).
    Antes del fix el panel INVIMA quedaba vacio para este codigo aunque la
    propia fila de auditoria ya supiera que existe en un listado distinto
    de Vigentes -- coherencia_invima.py deja ESTADO_LISTADO_INVIMA y las
    fechas *_INVIMA en la fila aunque no haya match en "universo"."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_universo = pd.DataFrame({
            "CODIGO_INTERNO": ["999-9"],
            "PRODUCTO": ["OTRO MEDICAMENTO"],
            "ESTADO_REGISTRO": ["Vigente"],
        })
        df_auditoria = pd.DataFrame({
            "CODIGO_INTERNO": ["20102710-2"],
            "DESCRIPCION": ["ALGO VENCIDO"],
            "CUM_RECONSTRUIDO": [""],
            "ESTADO_COHERENCIA": ["con_diferencias"],
            "ESTADO_LISTADO_INVIMA": ["vencido"],
            "ESTADO_INVIMA_DETALLE": ["Vencido"],
            "FECHA_ACTIVO_INVIMA": ["2010-01-01"],
            "FECHA_INACTIVO_INVIMA": [pd.NaT],
            "FECHA_VENCIMIENTO_INVIMA": ["2020-01-01"],
        })
        escribir_snapshot({"universo": df_universo, "auditoria": df_auditoria}, carpeta=carpeta)

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "20102710-2"})
        cuerpo = r.json()
        assert len(cuerpo["invima"]) == 1
        fila_invima = cuerpo["invima"][0]
        assert fila_invima["ESTADO_LISTADO_INVIMA"] == "vencido"
        assert fila_invima["FECHA_ACTIVO_INVIMA"] == "2010-01-01"
        assert fila_invima["FECHA_VENCIMIENTO_INVIMA"] == "2020-01-01"
    finally:
        app.dependency_overrides.clear()


def test_codigo_sin_ningun_dato_de_invima_no_produce_fila_sintetica(tmp_path):
    """Contraparte del caso anterior: si la fila de auditoria no trae ni
    ESTADO_LISTADO_INVIMA ni fechas *_INVIMA, es porque de verdad no hay
    correspondencia con INVIMA -- no se debe inventar una fila sintetica
    vacia solo porque el codigo no esta en "universo"."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_universo = pd.DataFrame({"CODIGO_INTERNO": ["999-9"], "PRODUCTO": ["OTRO"], "ESTADO_REGISTRO": ["Vigente"]})
        df_auditoria = pd.DataFrame({
            "CODIGO_INTERNO": ["CODIGO-SIN-INVIMA"],
            "DESCRIPCION": ["ALGO"],
            "CUM_RECONSTRUIDO": [""],
            "ESTADO_COHERENCIA": ["sin_correspondencia_invima"],
            "ESTADO_LISTADO_INVIMA": [""],
        })
        escribir_snapshot({"universo": df_universo, "auditoria": df_auditoria}, carpeta=carpeta)

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "CODIGO-SIN-INVIMA"})
        cuerpo = r.json()
        assert cuerpo["invima"] == []
    finally:
        app.dependency_overrides.clear()


def test_fecha_vencimiento_invima_no_cae_a_fecha_inactivo_invima_como_fallback(tmp_path):
    """FECHA_INACTIVO_INVIMA (baja administrativa del CUM) y
    FECHA_VENCIMIENTO_INVIMA (vencimiento del registro sanitario, que
    siempre existe) son conceptos distintos -- ver docstring de
    _contrastar_vigencia_invima en coherencia_invima.py. El endpoint no
    debe mezclarlas: si ambas vienen pobladas con valores distintos, la
    respuesta debe conservar cada una en su propio campo, no usar
    FECHA_INACTIVO_INVIMA como sustituto de FECHA_VENCIMIENTO_INVIMA."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_auditoria = pd.DataFrame({
            "CODIGO_INTERNO": ["500-1"],
            "DESCRIPCION": ["ACETAMINOFEN"],
            "CUM_RECONSTRUIDO": [""],
            "ESTADO_COHERENCIA": ["correcto"],
            "ESTADO_LISTADO_INVIMA": ["vigente"],
            "FECHA_INACTIVO_INVIMA": ["2019-05-01"],
            "FECHA_VENCIMIENTO_INVIMA": ["2030-12-31"],
        })
        escribir_snapshot({"auditoria": df_auditoria}, carpeta=carpeta)

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "500-1"})
        fila = r.json()["gemma_net"][0]
        assert fila["FECHA_VENCIMIENTO_INVIMA"] == "2030-12-31"
        assert fila["FECHA_INACTIVO_INVIMA"] == "2019-05-01"
        assert fila["FECHA_VENCIMIENTO_INVIMA"] != fila["FECHA_INACTIVO_INVIMA"]
    finally:
        app.dependency_overrides.clear()


def test_snapshot_de_auditoria_corrupto_reporta_error_real_no_lo_esconde(tmp_path):
    """Si "universo" existe pero "auditoria" esta corrupto en disco (ej.
    Parquet truncado), el endpoint NO debe fingir silenciosamente que el
    medicamento no existe en Gemma Net (gemma_net vacio sin explicacion) --
    eso el frontend lo interpreta como "candidato a cargar", un diagnostico
    completamente distinto de "no se pudo leer el snapshot". El error real
    debe viajar en el campo `error` de la respuesta, con status 200 porque
    el otro lado (invima) si respondio correctamente."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_universo = pd.DataFrame({"CODIGO_INTERNO": ["500-1"], "PRODUCTO": ["A"], "ESTADO_REGISTRO": ["Vigente"]})
        df_auditoria = pd.DataFrame({"CODIGO_INTERNO": ["500-1"], "DESCRIPCION": ["A"], "CUM_RECONSTRUIDO": [""], "ESTADO_COHERENCIA": ["correcto"]})
        snap = escribir_snapshot({"universo": df_universo, "auditoria": df_auditoria}, carpeta=carpeta)
        (carpeta / snap.tablas["auditoria"]).write_bytes(b"esto no es un parquet valido")

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "500-1"})
        cuerpo = r.json()
        assert r.status_code == 200
        assert cuerpo["gemma_net"] is None
        assert len(cuerpo["invima"]) == 1
        assert "error" in cuerpo
        assert "auditoria" in cuerpo["error"]
    finally:
        app.dependency_overrides.clear()


def test_snapshots_ambos_corruptos_responde_503_con_error_real(tmp_path):
    """Si NINGUNA fuente se pudo leer (ambas fallaron, no solo faltan), la
    respuesta debe ser 503 -- igual que "sin snapshot todavia" -- pero con
    el mensaje real del error de lectura, no el mensaje generico de "el
    worker no ha corrido todavia" (serian diagnosticos distintos: uno dice
    'corre el worker', el otro 'el disco tiene un problema')."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_auditoria = pd.DataFrame({"CODIGO_INTERNO": ["500-1"], "DESCRIPCION": ["A"], "CUM_RECONSTRUIDO": [""], "ESTADO_COHERENCIA": ["correcto"]})
        snap = escribir_snapshot({"auditoria": df_auditoria}, carpeta=carpeta)
        (carpeta / snap.tablas["auditoria"]).write_bytes(b"esto no es un parquet valido")

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "500-1"})
        cuerpo = r.json()
        assert r.status_code == 503
        assert "auditoria" in cuerpo["error"]
    finally:
        app.dependency_overrides.clear()


def test_codigo_que_no_existe_en_ningun_lado(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_universo = pd.DataFrame({"CODIGO_INTERNO": ["500-1"], "PRODUCTO": ["A"], "ESTADO_REGISTRO": ["Vigente"]})
        df_auditoria = pd.DataFrame({"CODIGO_INTERNO": ["500-1"], "DESCRIPCION": ["A"], "CUM_RECONSTRUIDO": [""], "ESTADO_COHERENCIA": ["correcto"]})
        escribir_snapshot({"universo": df_universo, "auditoria": df_auditoria}, carpeta=carpeta)

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "99999999-99"})
        cuerpo = r.json()
        assert cuerpo["invima"] == []
        assert cuerpo["gemma_net"] is None
    finally:
        app.dependency_overrides.clear()


def test_encuentra_el_registro_real_de_un_cum_que_solo_esta_en_vencidos(tmp_path):
    """El hueco que motivo la tarea (caso real 20102710-2): el snapshot
    "universo" es SOLO Vigentes, asi que un CUM vencido no tenia ninguna fila
    de INVIMA que mostrar aunque la auditoria ya supiera que existe. Ahora el
    worker persiste los 4 listados en "invima_listados" y de ahi sale el
    registro AUTENTICO -- con TITULAR y fechas reales, no una fila sintetica
    reconstruida a partir de las columnas derivadas de la auditoria."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        df_listados = pd.DataFrame(
            {
                "CODIGO_INTERNO": ["20102710-2"],
                "PRODUCTO": ["FINOBES 120 MG."],
                "TITULAR": ["JOINPHARM S.A.S"],
                "ESTADO_REGISTRO": ["Vencido"],
                "ESTADO_CUM": ["Inactivo"],
                "FECHA_ACTIVO": ["2016-07-23"],
                "FECHA_INACTIVO": ["2021-10-01"],
                "LISTADO": ["vencido"],
            }
        )
        df_auditoria = pd.DataFrame(
            {
                "CODIGO_INTERNO": ["20102710-2"],
                "DESCRIPCION": ["ORLISTAT 120MG CAPSULA DURA"],
                "CUM_RECONSTRUIDO": [""],
                "ESTADO_COHERENCIA": ["vencido_en_invima"],
                "ESTADO_LISTADO_INVIMA": ["vencido"],
                "ACTIVO": ["Si"],
                "FECHA_INICIO": ["2016-07-23"],
                "FECHA_FIN": ["2999-12-31"],
            }
        )
        # "universo" (Vigentes) NO trae este codigo, a proposito: es
        # exactamente la situacion de produccion.
        escribir_snapshot(
            {
                "universo": pd.DataFrame({"CODIGO_INTERNO": ["999-9"], "PRODUCTO": ["OTRO"]}),
                "auditoria": df_auditoria,
                "invima_listados": df_listados,
            },
            carpeta=carpeta,
        )

        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "20102710-2"})
        assert r.status_code == 200
        cuerpo = r.json()
        assert len(cuerpo["invima"]) == 1
        fila = cuerpo["invima"][0]
        assert fila["LISTADO"] == "vencido"
        # Lo que la fila sintetica NO podia dar: el registro real de INVIMA.
        assert fila["TITULAR"] == "JOINPHARM S.A.S"
        assert fila["FECHA_ACTIVO"] == "2016-07-23"
        assert fila["FECHA_INACTIVO"] == "2021-10-01"
    finally:
        app.dependency_overrides.clear()


def test_un_cum_vigente_no_sale_duplicado_estando_en_los_dos_snapshots(tmp_path):
    """Un vigente aparece tanto en "invima_listados" como en "universo".
    Debe salir UNA sola vez en el panel, no dos."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot(
            {
                "universo": pd.DataFrame(
                    {"CODIGO_INTERNO": ["500-1"], "PRODUCTO": ["ACETAMINOFEN"], "ESTADO_REGISTRO": ["Vigente"]}
                ),
                "invima_listados": pd.DataFrame(
                    {"CODIGO_INTERNO": ["500-1"], "PRODUCTO": ["ACETAMINOFEN"], "LISTADO": ["vigente"]}
                ),
                "auditoria": pd.DataFrame(
                    {
                        "CODIGO_INTERNO": ["500-1"],
                        "DESCRIPCION": ["ACETAMINOFEN"],
                        "CUM_RECONSTRUIDO": [""],
                        "ESTADO_COHERENCIA": ["correcto"],
                    }
                ),
            },
            carpeta=carpeta,
        )
        r = cliente.get("/consulta-detalle/medicamento", params={"codigo": "500-1"})
        assert len(r.json()["invima"]) == 1
    finally:
        app.dependency_overrides.clear()
