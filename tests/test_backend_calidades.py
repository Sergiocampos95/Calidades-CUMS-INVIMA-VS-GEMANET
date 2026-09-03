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
            "CODIGO_INTERNO": ["1-1", "2-2", "CODIGO-LEGADO", "3-3"],
            "DESCRIPCION": ["A", "B", "C", "D"],
            "ACTIVO": ["SI", "SI", "NO", "NO"],
            # filtrar_universo_auditable() (coherencia_invima.py) la exige
            # directo, sin el fallback por regex que si tiene es_cum() --
            # "CODIGO-LEGADO" es justo el caso que ese filtro debe excluir.
            "TIPO_CODIGO_INTERNO": ["cum", "cum", "legado", "cum"],
            "ESTADO_COHERENCIA": [
                EstadoCoherencia.CORRECTO.value,
                EstadoCoherencia.VENCIDO_EN_INVIMA.value,
                EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value,
                EstadoCoherencia.CORRECTO.value,
            ],
            # Veredicto de vigencia real de INVIMA.
            "ESTADO_CUM_INVIMA": ["Activo", "Inactivo", "", "Activo"],
            # Metadato de ubicacion.
            # "3-3": inactivo en Gemma Net pero vigente en INVIMA -- la
            # unica excepcion al filtro de "solo activos" (pedido explicito
            # del usuario, ver calidad "Inactivo en Gemma Net pero vigente
            # en INVIMA" en calidades.py). Las otras filas inactivas
            # (ninguna otra en esta muestra) deben seguir invisibles.
            "ESTADO_LISTADO_INVIMA": ["vigente", "vencido", "", "vigente"],
            "NATURALEZA_HALLAZGO": ["", "Vigencia en riesgo", "", ""],
            "CODIGO_DUPLICADO_EN_REPORTE": [False, False, False, False],
            "PORCENTAJE_COMPLETITUD_REPORTE": [100.0, 80.0, 60.0, 100.0],
            "VALORES_FUERA_DE_DOMINIO": ["", "", "", ""],
            "INCONSISTENCIA_NUMERICA": ["", "", "", ""],
            "FORMATO_CODIGO_INTERNO_INVALIDO": ["", "", "", ""],
            "INTEGRIDAD_REFERENCIAL_CATALOGO": ["", "", "", ""],
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


def test_listar_calidades_devuelve_6_con_conteos_correctos(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        r = cliente.get("/auditoria/calidades")
        assert r.status_code == 200
        calidades = {c["nombre"]: c for c in r.json()}
        # Rediseño 2026-09-02: ahora son 6 calidades. La tarjeta de
        # "Inactivo en Gemma Net pero vigente en INVIMA" se integro dentro de
        # "Diferencia de estado o campos". El veredicto de vigencia ahora es
        # ESTADO_CUM_INVIMA, no ESTADO_LISTADO_INVIMA.
        assert len(calidades) == 6
        # La regla vigente del negocio exige CUMs activos y validos. El
        # ejemplo de prueba solo tiene un CUM activo vigente y uno vencido.
        assert calidades["No existe en INVIMA"]["medicamentos"] == 0
        assert calidades["Vigencia confirmada"]["medicamentos"] == 1
        assert calidades["Registro vencido en INVIMA"]["medicamentos"] == 1
        # "3-3": la fila inactiva que deberia ser visible en la tarjeta 6.
        assert calidades["Diferencia de estado o campos"]["medicamentos"] == 1
    finally:
        app.dependency_overrides.clear()


def test_todas_las_calidades_incluyen_estado_listado_invima_en_columnas_y_filas(tmp_path):
    """Pedido explicito del usuario (2026-09-01): ESTADO_LISTADO_INVIMA debe
    estar disponible en CADA calidad -- tanto en la lista de `columnas` que
    describe la calidad como en las filas reales que trae
    /auditoria/calidades/{nombre} -- para poder distinguir vigente/vencido/
    en_tramite_renovacion/otros_estados en cualquier tabla que se abra desde
    la UI, sin tener que adivinar la columna en cada vista."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        r = cliente.get("/auditoria/calidades")
        assert r.status_code == 200
        calidades = r.json()
        assert len(calidades) > 0
        for calidad in calidades:
            assert "ESTADO_LISTADO_INVIMA" in calidad["columnas"], calidad["nombre"]
            if calidad["medicamentos"] == 0:
                continue
            r_detalle = cliente.get(f"/auditoria/calidades/{calidad['nombre']}")
            assert r_detalle.status_code == 200
            for fila in r_detalle.json()["filas"]:
                assert "ESTADO_LISTADO_INVIMA" in fila, calidad["nombre"]
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
        # Los CONTADORES de auto-consistencia (formato, duplicados,
        # completitud) miden el reporte de Gemma Net contra si mismo y ven
        # TODAS las filas del snapshot, incluidas las inactivas: son
        # deteccion de basura, y recortar antes esconderia la fila con el
        # problema (ver el docstring de dimensiones_calidad).
        assert cuerpo["completitud_promedio"] == 85.0
        assert cuerpo["duplicados"] == 0
        # `n_total_auditado` SI es el universo auditable -- es la cifra que la
        # UI muestra como "lo que auditamos". De las 4 filas de la muestra,
        # una no lo es (2026-09-01: el usuario pidio excluir inactivos y todo
        # lo que no sea CUM). Los dos numeros responden preguntas distintas a
        # proposito, por eso no coinciden.
        assert cuerpo["n_total_auditado"] == 3
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


def _auditoria_con_diferencias():
    """Dos CUMs activos con diferencias de tipo distinto, para poder ver que
    las secciones separan de verdad y que el filtro coincide con el conteo."""
    df = _auditoria_muestra()
    df["CAMPOS_CON_DIFERENCIA"] = ["CONCENTRACION, DESCRIPCION", "", "", "DESCRIPCION"]
    df["COHERENCIA_FECHAS_INVIMA"] = ["", "", "", "Falta actualizar FECHA_FIN en Gemma Net"]
    df["INCONSISTENCIA_FECHAS_ACTIVO"] = ["", "", "", ""]
    return df


def test_secciones_de_una_calidad_llegan_agrupadas_por_tipo(tmp_path):
    """Campos primero, fechas despues (orden pedido por el usuario). Se
    verifica el GRUPO y no el orden descendente global: con estos datos de
    muestra los campos pesan mas que las fechas, asi que una asercion de
    "todo descendente" pasaria sin comprobar nada del agrupamiento real."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_con_diferencias()}, carpeta=carpeta)
        r = cliente.get("/auditoria/calidades/Diferencia de estado o campos/secciones")
        assert r.status_code == 200
        secciones = r.json()
        grupos = [s["clave"].split(":", 1)[0] for s in secciones]
        assert grupos == sorted(grupos, key=["campo", "fecha", "interna"].index)
        por_clave = {s["clave"]: s for s in secciones}
        assert por_clave["campo:DESCRIPCION"]["medicamentos"] == 2
        # derivado_de llega ya humanizado desde el backend, para no duplicar
        # el mapa de etiquetas en el frontend.
        assert por_clave["campo:DESCRIPCION"]["derivado_de"] == [
            "Principio activo",
            "Unidad de medida",
        ]
        assert por_clave["campo:CONCENTRACION"]["derivado_de"] == []
    finally:
        app.dependency_overrides.clear()


def test_filtrar_la_tabla_por_seccion_coincide_con_el_conteo_de_la_tarjeta(tmp_path):
    """Si el total paginado no diera lo mismo que la tarjeta, el usuario veria
    un numero en la seccion y otro al abrirla."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_con_diferencias()}, carpeta=carpeta)
        ruta = "/auditoria/calidades/Diferencia de estado o campos"
        for seccion in cliente.get(f"{ruta}/secciones").json():
            r = cliente.get(ruta, params={"seccion": seccion["clave"]})
            assert r.status_code == 200
            assert r.json()["total"] == seccion["medicamentos"]
    finally:
        app.dependency_overrides.clear()


def test_sin_seccion_se_sirve_la_calidad_completa(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_con_diferencias()}, carpeta=carpeta)
        ruta = "/auditoria/calidades/Diferencia de estado o campos"
        completa = cliente.get(ruta).json()["total"]
        una = cliente.get(ruta, params={"seccion": "campo:CONCENTRACION"}).json()["total"]
        assert completa > una
    finally:
        app.dependency_overrides.clear()


def test_calidad_sin_diferencias_no_expone_secciones(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        r = cliente.get("/auditoria/calidades/No existe en INVIMA/secciones")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.clear()


def test_solo_la_calidad_de_diferencias_se_secciona(tmp_path):
    """Decision del usuario (2026-09-02): "era a diferencias". Tecnicamente
    "Vigencia confirmada" tambien da secciones (tiene filas con campos
    distintos), pero ahi el corte confunde: esa tarjeta afirma que la vigencia
    es correcta y colgarle "Fecha fin" al lado la hace leer como si estuviera
    casi toda mal."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_con_diferencias()}, carpeta=carpeta)
        assert cliente.get("/auditoria/calidades/Vigencia confirmada/secciones").json() == []
        assert cliente.get("/auditoria/calidades/Diferencia de estado o campos/secciones").json() != []
    finally:
        app.dependency_overrides.clear()


def test_seccion_en_una_calidad_que_no_se_secciona_no_recorta_la_tabla(tmp_path):
    """Un enlace viejo con ?seccion= no puede dejar una tarjeta mostrando
    menos filas de las que anuncia su propio numero."""
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_con_diferencias()}, carpeta=carpeta)
        ruta = "/auditoria/calidades/Vigencia confirmada"
        completa = cliente.get(ruta).json()["total"]
        con_seccion = cliente.get(ruta, params={"seccion": "campo:CONCENTRACION"}).json()["total"]
        assert con_seccion == completa
    finally:
        app.dependency_overrides.clear()


def test_secciones_de_una_calidad_inexistente_dan_404(tmp_path):
    cliente, carpeta = _cliente(tmp_path)
    try:
        escribir_snapshot({"auditoria": _auditoria_muestra()}, carpeta=carpeta)
        assert cliente.get("/auditoria/calidades/Inventada/secciones").status_code == 404
    finally:
        app.dependency_overrides.clear()
