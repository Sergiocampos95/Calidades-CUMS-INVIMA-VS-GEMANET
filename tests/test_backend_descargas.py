import io

import pandas as pd
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app.dependencies import carpeta_snapshots
from backend.app.main import app
from backend.app.schemas import LIMITE_PREVISUALIZACION_DEFECTO
from worker.almacen_snapshots import escribir_snapshot


def _cliente(tmp_path):
    carpeta = tmp_path / "snapshots"
    app.dependency_overrides[carpeta_snapshots] = lambda: carpeta
    return TestClient(app), carpeta


def _leer_xlsx(contenido: bytes):

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


# --- GET /descargas/calidad/{nombre} ---------------------------------------
#
# Alcance CORREGIDO por el usuario a mitad del plan tablas-por-seccion-y-
# exportacion.md (2026-09-04, ver "Decisiones ya tomadas con el usuario"): la
# descarga trae la SECCION COMPLETA que esta abierta en pantalla, no la
# pagina de 1.000 que ve la tabla ni el filtro de columna/busqueda -- "ya no
# hace falta exportar solo lo que se muestra en pantalla sino todo". Estas
# pruebas verifican ESE alcance, no el original (exportar el filtro visible).


def _fila_diferencia_concentracion(codigo: str, concentracion_gemanet: str, concentracion_invima: str) -> dict:
    """Una fila que cae en la calidad "Diferencia de estado o campos",
    seccion campo:CONCENTRACION -- activa, CUM, en el listado de vigentes,
    con SOLO la concentracion distinta entre Gemma Net e INVIMA."""
    return {
        "CODIGO_INTERNO": codigo,
        "DESCRIPCION": f"MEDICAMENTO {codigo}",
        "ACTIVO": "SI",
        "TIPO_CODIGO_INTERNO": "cum",
        "ESTADO_CUM_INVIMA": "Activo",
        "ESTADO_LISTADO_INVIMA": "vigente",
        "CAMPOS_CON_DIFERENCIA": "CONCENTRACION",
        "CONCENTRACION_GEMANET": concentracion_gemanet,
        "CONCENTRACION_INVIMA": concentracion_invima,
        "CONCENTRACION_VALIDACION": "difiere",
    }


def _auditoria_seccion_concentracion_con_n_filas(n: int) -> pd.DataFrame:
    """n medicamentos, todos en la seccion campo:CONCENTRACION -- para poder
    construir una seccion mas grande que LIMITE_PREVISUALIZACION_DEFECTO
    (1.000, la pagina que ve la pantalla) sin necesitar el snapshot real de
    produccion (59.005 filas en la seccion mas grande, ver el plan)."""
    filas = [_fila_diferencia_concentracion(f"{i}-1", f"{i} mg", f"{i + 1} mg") for i in range(n)]
    return pd.DataFrame(filas)


def _auditoria_con_trio_dos_campos() -> pd.DataFrame:
    """Dos medicamentos, cada uno con diferencia en un campo distinto
    (CONCENTRACION y DESCRIPCION), cada uno con su propio trio GEMANET/INVIMA/
    VALIDACION -- para comprobar que descargar la seccion de UN campo no
    arrastra el trio del otro campo (paso 1 del plan, columnas_de_seccion)."""
    return pd.DataFrame(
        {
            "CODIGO_INTERNO": ["1-1", "2-1"],
            "DESCRIPCION": ["ACETAMINOFEN 500MG", "IBUPROFENO 400MG"],
            "ACTIVO": ["SI", "SI"],
            "TIPO_CODIGO_INTERNO": ["cum", "cum"],
            "ESTADO_CUM_INVIMA": ["Activo", "Activo"],
            "ESTADO_LISTADO_INVIMA": ["vigente", "vigente"],
            "CAMPOS_CON_DIFERENCIA": ["CONCENTRACION", "DESCRIPCION"],
            "CONCENTRACION_GEMANET": ["500 mg", ""],
            "CONCENTRACION_INVIMA": ["50 mg", ""],
            "CONCENTRACION_VALIDACION": ["difiere", ""],
            "DESCRIPCION_GEMANET": ["", "IBUPROFENO 400MG"],
            "DESCRIPCION_INVIMA": ["", "IBUPROFENO 400 MG"],
            "DESCRIPCION_VALIDACION": ["", "difiere"],
        }
    )


def _auditoria_una_diferencia_con_tilde() -> pd.DataFrame:
    """Un solo medicamento con tilde y ene en DESCRIPCION -- para poder
    comprobar que csv/txt viajan con BOM utf-8 (si no, Excel en Windows los
    abre mostrando la tilde mal, regla del proyecto: este equipo abre todo
    en Excel)."""
    df = _auditoria_con_trio_dos_campos()
    df.loc[0, "DESCRIPCION"] = "ACETAMINOFÉN 500MG SOLUCIÓN"
    return df


def test_descarga_de_una_seccion_trae_todas_las_filas_no_solo_la_pagina_de_1000(tmp_path):
    """LA razon de ser del endpoint (alcance corregido por el usuario,
    2026-09-04): sacar un reporte no debe obligar a bajar 9 archivos de
    1.000 filas y unirlos a mano. Se construye una seccion con MAS filas
    que LIMITE_PREVISUALIZACION_DEFECTO (la pagina que sirve la pantalla) y
    se compara ademas contra el `total` que reporta
    /auditoria/calidades/{nombre} para la misma seccion, que es la cifra que
    la tarjeta le promete al usuario."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        n = LIMITE_PREVISUALIZACION_DEFECTO + 200
        escribir_snapshot(
            {"auditoria": _auditoria_seccion_concentracion_con_n_filas(n)}, carpeta=carpeta
        )
        nombre = "Diferencia de estado o campos"

        pagina = cliente.get(
            f"/auditoria/calidades/{nombre}", params={"seccion": "campo:CONCENTRACION"}
        ).json()
        assert pagina["total"] == n
        # La PANTALLA si se recorta a la pagina -- confirma que el caso de
        # prueba realmente ejercita el limite, no solo un numero grande.
        assert pagina["visibles"] == LIMITE_PREVISUALIZACION_DEFECTO

        r = cliente.get(
            f"/descargas/calidad/{nombre}",
            params={"formato": "xlsx", "seccion": "campo:CONCENTRACION"},
        )
        assert r.status_code == 200
        tabla = pd.read_excel(io.BytesIO(r.content))
        assert len(tabla) == n
        assert len(tabla) > LIMITE_PREVISUALIZACION_DEFECTO
    finally:
        app.dependency_overrides.clear()


def test_descarga_de_una_seccion_respeta_sus_8_columnas_y_no_las_38_de_la_tarjeta(tmp_path):
    """El paso 1 del plan recorto la tabla EN PANTALLA de 38 a 8 columnas por
    seccion; la descarga reusa `tabla_calidad_filtrada`, el mismo filtrado --
    sin esta prueba, un cambio que rompiera esa reutilizacion (por ejemplo,
    armar el archivo desde `calidad.df_tabla` en vez de la tabla ya
    recortada) volveria a mandar el trio de TODOS los campos comparados en
    el archivo aunque la pantalla ya se viera bien."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_con_trio_dos_campos()}, carpeta=carpeta)
        r = cliente.get(
            "/descargas/calidad/Diferencia de estado o campos",
            params={"formato": "xlsx", "seccion": "campo:CONCENTRACION"},
        )
        assert r.status_code == 200
        tabla = pd.read_excel(io.BytesIO(r.content))
        # Solo el medicamento "1-1" tiene CONCENTRACION en CAMPOS_CON_DIFERENCIA.
        assert len(tabla) == 1
        assert set(tabla.columns) == {
            "CODIGO_INTERNO",
            "DESCRIPCION",
            "CONCENTRACION_GEMANET",
            "CONCENTRACION_INVIMA",
            "CONCENTRACION_VALIDACION",
            "ACTIVO",
            "ESTADO_CUM_INVIMA",
            "ESTADO_INVIMA",
        }
    finally:
        app.dependency_overrides.clear()


def test_descarga_calidad_en_xlsx_devuelve_content_type_y_datos_legibles(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_una_diferencia_con_tilde()}, carpeta=carpeta)
        r = cliente.get(
            "/descargas/calidad/Diferencia de estado o campos",
            params={"formato": "xlsx", "seccion": "campo:CONCENTRACION"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
        assert ".xlsx" in r.headers["content-disposition"]
        tabla = pd.read_excel(io.BytesIO(r.content))
        assert tabla.loc[0, "DESCRIPCION"] == "ACETAMINOFÉN 500MG SOLUCIÓN"
    finally:
        app.dependency_overrides.clear()


def test_descarga_calidad_en_csv_lleva_bom_utf8_y_separador_coma(tmp_path):
    """Sin el BOM (utf-8-sig), Excel en Windows abre el CSV interpretando
    cada tilde mal -- este equipo abre todo en Excel (regla del proyecto). Si
    un refactor cambiara a `.encode("utf-8")` a secas, nadie lo nota hasta
    que un usuario ve "DESCRIPCIÃ“N" en pantalla."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_una_diferencia_con_tilde()}, carpeta=carpeta)
        r = cliente.get(
            "/descargas/calidad/Diferencia de estado o campos",
            params={"formato": "csv", "seccion": "campo:CONCENTRACION"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert ".csv" in r.headers["content-disposition"]
        assert r.content.startswith(b"\xef\xbb\xbf")

        primera_linea = r.content.split(b"\n", 1)[0]
        assert b"," in primera_linea
        assert b"\t" not in primera_linea

        tabla = pd.read_csv(io.BytesIO(r.content), sep=",", encoding="utf-8-sig")
        assert tabla.loc[0, "DESCRIPCION"] == "ACETAMINOFÉN 500MG SOLUCIÓN"
    finally:
        app.dependency_overrides.clear()


def test_descarga_calidad_en_txt_lleva_bom_utf8_y_separador_tab(tmp_path):
    """El TAB (en vez de coma) evita que una coma dentro de un valor
    (ej. DESCRIPCION) parta una columna de mas al pegar en otra hoja de
    calculo -- por eso .txt no es simplemente el mismo .csv con otra
    extension, y merece su propia prueba del separador."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_una_diferencia_con_tilde()}, carpeta=carpeta)
        r = cliente.get(
            "/descargas/calidad/Diferencia de estado o campos",
            params={"formato": "txt", "seccion": "campo:CONCENTRACION"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        assert ".txt" in r.headers["content-disposition"]
        assert r.content.startswith(b"\xef\xbb\xbf")

        primera_linea = r.content.split(b"\n", 1)[0]
        assert b"\t" in primera_linea

        tabla = pd.read_csv(io.BytesIO(r.content), sep="\t", encoding="utf-8-sig")
        assert tabla.loc[0, "DESCRIPCION"] == "ACETAMINOFÉN 500MG SOLUCIÓN"
    finally:
        app.dependency_overrides.clear()


def test_descargar_calidad_desconocida_da_404(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_una_diferencia_con_tilde()}, carpeta=carpeta)
        r = cliente.get("/descargas/calidad/no-existe", params={"formato": "xlsx"})
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_descargar_calidad_sin_snapshot_da_503(tmp_path):
    """Mismo criterio que el resto del router: sin snapshot todavia no hay
    nada que exportar, y el mensaje debe decirlo con un 503, no con un xlsx
    vacio que parezca "no hay hallazgos"."""
    cliente, _ = _cliente(tmp_path)
    try:
        r = cliente.get(
            "/descargas/calidad/Diferencia de estado o campos", params={"formato": "xlsx"}
        )
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_descargar_calidad_con_formato_no_reconocido_da_400_no_500(tmp_path):
    """Un typo en el query param (?formato=pdf) tiene que avisar con un 400
    claro y explicito -- nunca reventar en un 500 al intentar tratar "pdf"
    como si fuera uno de los tres formatos soportados."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_una_diferencia_con_tilde()}, carpeta=carpeta)
        r = cliente.get(
            "/descargas/calidad/Diferencia de estado o campos", params={"formato": "pdf"}
        )
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()
