from fastapi.testclient import TestClient

from backend.app.dependencies import ruta_estado
from backend.app.main import app
from gemma_cum_loader.ingesta.fuente_invima import FUENTE_DEFECTO
from worker.estado import (
    ESTADO_PASO_EN_CURSO,
    ESTADO_PASO_HECHO,
    ESTADO_PASO_PENDIENTE,
    actualizar_paso,
    fuente_refresco,
    hay_solicitud_pendiente,
    iniciar_progreso,
    registrar_latido_worker,
    solicitar_refresco_manual,
    worker_vivo,
)


def _cliente(tmp_path):
    ruta = tmp_path / "estado.sqlite3"
    app.dependency_overrides[ruta_estado] = lambda: ruta
    return TestClient(app), ruta


def test_progreso_vacio_antes_de_cualquier_corrida(tmp_path):
    cliente, _ = _cliente(tmp_path)
    try:
        r = cliente.get("/refrescar/progreso")
        assert r.status_code == 200
        assert r.json() == {"en_curso": False, "pasos": []}
    finally:
        app.dependency_overrides.clear()


def test_pedir_refresco_escribe_la_solicitud_que_el_worker_revisa(tmp_path):
    cliente, ruta = _cliente(tmp_path)
    try:
        registrar_latido_worker(ruta)
        r = cliente.post("/refrescar")
        assert r.status_code == 202
        assert hay_solicitud_pendiente(ruta) is True
    finally:
        app.dependency_overrides.clear()


def test_una_solicitud_sin_recoger_no_bloquea_el_boton(tmp_path):
    """El defecto que reporto el usuario (2026-09-07): el boton devolvia 409
    "ya hay un refresco en curso" con los 10 pasos en "hecho".

    La causa era que POST miraba `hay_solicitud_pendiente()`, que significa
    "hay una solicitud que el worker no recogio" y NO "hay un refresco
    corriendo". Sin worker vivo nadie la borra, asi que el boton quedaba
    muerto para siempre. Pedir dos veces seguidas tiene que seguir
    funcionando: escribir la bandera es idempotente."""
    cliente, ruta = _cliente(tmp_path)
    try:
        registrar_latido_worker(ruta)
        iniciar_progreso(["Leer INVIMA"], ruta=ruta)
        actualizar_paso("Leer INVIMA", ESTADO_PASO_HECHO, ruta=ruta)
        solicitar_refresco_manual(ruta)  # solicitud vieja, sin recoger

        assert cliente.post("/refrescar").status_code == 202
    finally:
        app.dependency_overrides.clear()


def test_pedir_refresco_durante_una_corrida_real_devuelve_409(tmp_path):
    """El 409 ahora sale del progreso, la misma fuente que ve la barra en
    pantalla -- antes salia de la bandera, que el worker borra a los pocos
    segundos y por eso no protegia durante la corrida."""
    cliente, ruta = _cliente(tmp_path)
    try:
        registrar_latido_worker(ruta)
        iniciar_progreso(["Leer INVIMA", "Auditar"], ruta=ruta)
        actualizar_paso("Leer INVIMA", ESTADO_PASO_EN_CURSO, ruta=ruta)

        r = cliente.post("/refrescar")
        assert r.status_code == 409
        assert cliente.get("/refrescar/progreso").json()["en_curso"] is True
    finally:
        app.dependency_overrides.clear()


def test_los_dos_endpoints_nunca_se_contradicen(tmp_path):
    """La invariante que cierra el defecto: si /progreso dice que NO hay nada
    en curso, POST no puede rechazar por "ya hay un refresco en curso" -- y al
    reves. Se contradecian porque cada uno miraba una senal distinta."""
    cliente, ruta = _cliente(tmp_path)
    try:
        registrar_latido_worker(ruta)
        iniciar_progreso(["Leer INVIMA", "Auditar"], ruta=ruta)
        for estados in ([ESTADO_PASO_EN_CURSO, None], [ESTADO_PASO_HECHO, ESTADO_PASO_HECHO]):
            for nombre, estado in zip(["Leer INVIMA", "Auditar"], estados, strict=True):
                if estado:
                    actualizar_paso(nombre, estado, ruta=ruta)

            en_curso = cliente.get("/refrescar/progreso").json()["en_curso"]
            rechazado = cliente.post("/refrescar").status_code == 409
            assert en_curso == rechazado
    finally:
        app.dependency_overrides.clear()


def test_sin_worker_vivo_el_boton_lo_dice_en_vez_de_aceptar_en_silencio(tmp_path):
    """El backend solo DEJA la solicitud; quien la ejecuta es el worker. Si no
    hay worker, un 202 seria mentira: el usuario esperaria un refresco que
    nadie va a correr. Degradacion explicita (regla 2 del proyecto)."""
    cliente, ruta = _cliente(tmp_path)
    try:
        r = cliente.post("/refrescar")
        assert r.status_code == 503
        assert "worker" in r.json()["detail"].lower()
        assert hay_solicitud_pendiente(ruta) is False, "no debe dejar basura que luego bloquee"
    finally:
        app.dependency_overrides.clear()


def test_un_latido_viejo_cuenta_como_worker_caido(tmp_path):
    ruta = tmp_path / "estado.sqlite3"
    registrar_latido_worker(ruta)
    assert worker_vivo(ruta) is True
    # El worker late cada 5 s; con margen 0 hasta el latido recien escrito
    # ya es "viejo" -- es la forma de probar el vencimiento sin dormir.
    assert worker_vivo(ruta, margen_segundos=0) is False


def test_sin_latido_nunca_registrado_el_worker_esta_caido(tmp_path):
    assert worker_vivo(tmp_path / "no_existe.sqlite3") is False


def test_progreso_refleja_los_pasos_de_la_corrida_en_curso(tmp_path):
    cliente, ruta = _cliente(tmp_path)
    try:
        # El latido es parte de "hay una corrida en curso": sin worker vivo no
        # hay nada corriendo, por mas que un paso haya quedado en_curso.
        registrar_latido_worker(ruta)
        iniciar_progreso(["Leer INVIMA", "Auditar", "Guardar"], ruta=ruta)
        actualizar_paso("Leer INVIMA", ESTADO_PASO_HECHO, ruta=ruta)
        actualizar_paso("Auditar", ESTADO_PASO_EN_CURSO, ruta=ruta)

        r = cliente.get("/refrescar/progreso")
        cuerpo = r.json()
        assert cuerpo["en_curso"] is True
        assert [p["nombre"] for p in cuerpo["pasos"]] == ["Leer INVIMA", "Auditar", "Guardar"]
        assert cuerpo["pasos"][0]["estado"] == ESTADO_PASO_HECHO
        assert cuerpo["pasos"][1]["estado"] == ESTADO_PASO_EN_CURSO
        assert cuerpo["pasos"][2]["estado"] == ESTADO_PASO_PENDIENTE
    finally:
        app.dependency_overrides.clear()


def test_en_curso_es_falso_cuando_la_corrida_ya_termino(tmp_path):
    cliente, ruta = _cliente(tmp_path)
    try:
        iniciar_progreso(["Leer INVIMA"], ruta=ruta)
        actualizar_paso("Leer INVIMA", ESTADO_PASO_HECHO, ruta=ruta)

        r = cliente.get("/refrescar/progreso")
        assert r.json()["en_curso"] is False
    finally:
        app.dependency_overrides.clear()


def test_la_fuente_elegida_queda_anotada_para_el_worker(tmp_path):
    """El backend no ejecuta el refresco: solo deja la solicitud. La fuente
    tiene que viajar por el mismo canal o el worker leeria la de siempre."""
    cliente, ruta = _cliente(tmp_path)
    try:
        registrar_latido_worker(ruta)
        r = cliente.post("/refrescar", params={"fuente": "archivos"})
        assert r.status_code == 202
        assert r.json()["fuente"] == "archivos"
        assert fuente_refresco(ruta) == "archivos"
    finally:
        app.dependency_overrides.clear()


def test_sin_elegir_fuente_se_usan_los_archivos(tmp_path):
    """La fuente PRIMARIA son los archivos -- decision del usuario
    (2026-09-07): la API todavia no esta soportada de punta a punta, porque
    "Consultar INVIMA" no procesa el JSON de Socrata. El defecto tiene que ser
    la fuente que funciona en TODA la aplicacion, no solo en el refresco."""
    cliente, ruta = _cliente(tmp_path)
    try:
        registrar_latido_worker(ruta)
        assert cliente.post("/refrescar").json()["fuente"] == FUENTE_DEFECTO
        assert fuente_refresco(ruta) == "archivos"
    finally:
        app.dependency_overrides.clear()


def test_una_fuente_desconocida_se_rechaza_sin_dejar_solicitud(tmp_path):
    """Aceptarla y caer a la API en silencio daria un snapshot que se ve
    igual de sano pero con cifras de otra fuente -- imposible de detectar
    mirando la pantalla."""
    cliente, ruta = _cliente(tmp_path)
    try:
        registrar_latido_worker(ruta)
        r = cliente.post("/refrescar", params={"fuente": "excel_viejo"})
        assert r.status_code == 422
        assert hay_solicitud_pendiente(ruta) is False
    finally:
        app.dependency_overrides.clear()


def test_una_corrida_que_aborto_no_bloquea_el_boton(tmp_path):
    """Segundo reporte del mismo sintoma (usuario, 2026-09-07): al caerse la
    VPN a Gemma Net el refresco murio en el primer paso y el boton quedo
    devolviendo 409 sobre una corrida terminada una hora antes.

    `_paso` marca el paso en error y RE-LANZA, asi que `ejecutar_refresco`
    corta ahi: los 9 pasos que quedan en "pendiente" detras del error no se
    van a mover nunca. Un error en cualquier paso significa que la corrida
    termino, no que sigue."""
    cliente, ruta = _cliente(tmp_path)
    try:
        registrar_latido_worker(ruta)
        iniciar_progreso(["Leer Gemma Net", "Leer INVIMA", "Guardar"], ruta=ruta)
        actualizar_paso("Leer Gemma Net", "error", detalle="ErrorGemaNetDB: sin ruta", ruta=ruta)

        assert cliente.get("/refrescar/progreso").json()["en_curso"] is False
        assert cliente.post("/refrescar").status_code == 202
    finally:
        app.dependency_overrides.clear()


def test_un_worker_muerto_a_mitad_de_corrida_no_bloquea_el_boton(tmp_path):
    """El caso que el error NO cubre: si el PROCESO muere de golpe (kill,
    reinicio) no hay excepcion, el paso queda "en_curso" y nadie lo cierra.
    Sin worker vivo no puede haber nada corriendo, por definicion."""
    cliente, ruta = _cliente(tmp_path)
    try:
        iniciar_progreso(["Leer INVIMA", "Guardar"], ruta=ruta)
        actualizar_paso("Leer INVIMA", ESTADO_PASO_EN_CURSO, ruta=ruta)
        # Sin latido: el worker que dejo ese paso a medias ya no existe.

        assert cliente.get("/refrescar/progreso").json()["en_curso"] is False
        # 503 (no hay worker), NUNCA 409: el 409 mandaria a esperar algo que
        # no va a pasar; el 503 dice que hay que arrancar el worker.
        assert cliente.post("/refrescar").status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_la_fuente_api_esta_deshabilitada(tmp_path):
    """Decision del usuario (2026-09-14): los listados se leen de la carpeta del
    servidor; la API queda en el codigo para cuando vuelva a servir."""
    cliente, ruta = _cliente(tmp_path)
    try:
        registrar_latido_worker(ruta)
        r = cliente.post("/refrescar?fuente=api")
        assert r.status_code == 422
        assert "deshabilitada" in r.json()["detail"]
        assert hay_solicitud_pendiente(ruta) is False
    finally:
        app.dependency_overrides.clear()
