from fastapi.testclient import TestClient

from backend.app.dependencies import ruta_estado
from backend.app.main import app
from worker.estado import (
    ESTADO_PASO_EN_CURSO,
    ESTADO_PASO_HECHO,
    ESTADO_PASO_PENDIENTE,
    actualizar_paso,
    hay_solicitud_pendiente,
    iniciar_progreso,
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
        r = cliente.post("/refrescar")
        assert r.status_code == 202
        assert hay_solicitud_pendiente(ruta) is True
    finally:
        app.dependency_overrides.clear()


def test_progreso_refleja_los_pasos_de_la_corrida_en_curso(tmp_path):
    cliente, ruta = _cliente(tmp_path)
    try:
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
