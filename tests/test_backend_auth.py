import time

from fastapi.testclient import TestClient

from backend.app.auth import dependencias
from backend.app.auth.dependencias import obtener_base, usuario_actual
from backend.app.main import app
from tests.test_auth_servicio import BaseFalsa, _usuario

ENCABEZADOS = {"X-Requested-With": "fetch"}


def _cliente(base):
    app.dependency_overrides.pop(usuario_actual, None)  # el login de verdad, no la sesion de prueba
    app.dependency_overrides[obtener_base] = lambda: base
    return TestClient(app)


def _limpiar():
    app.dependency_overrides.clear()


def test_sin_sesion_una_ruta_protegida_responde_401():
    cliente = _cliente(BaseFalsa())
    try:
        r = cliente.get("/salud")
        assert r.status_code == 401
        assert "iniciar sesión" in r.json()["detail"]
        assert cliente.get("/auth/sesion").status_code == 401
    finally:
        _limpiar()


def test_login_correcto_deja_cookie_y_abre_las_rutas():
    base = BaseFalsa({"jperez": _usuario()}, modulos={("jperez", "CUMS")})
    cliente = _cliente(base)
    try:
        r = cliente.post("/auth/login", json={"usuario": "jperez", "clave": "secreta"}, headers=ENCABEZADOS)
        assert r.status_code == 200
        assert r.json() == {"usuario": "jperez", "nombre": "Juan Perez", "admin": False}
        assert "gemanet_cums_sesion" in r.cookies
        assert cliente.get("/auth/sesion").json()["usuario"] == "jperez"
        assert cliente.get("/salud").status_code == 200
    finally:
        _limpiar()


def test_login_rechazado_propaga_el_estado_y_el_mensaje():
    cliente = _cliente(BaseFalsa({"jperez": _usuario()}))
    try:
        r = cliente.post("/auth/login", json={"usuario": "jperez", "clave": "mala"}, headers=ENCABEZADOS)
        assert r.status_code == 401
        assert r.json()["detail"] == "Usuario o clave incorrectos."
        assert cliente.get("/auth/sesion").status_code == 401
    finally:
        _limpiar()


def test_post_sin_el_encabezado_fetch_es_403():
    cliente = _cliente(BaseFalsa({"jperez": _usuario()}, modulos={("jperez", "CUMS")}))
    try:
        r = cliente.post("/auth/login", json={"usuario": "jperez", "clave": "secreta"})
        assert r.status_code == 403
        cliente.post("/auth/login", json={"usuario": "jperez", "clave": "secreta"}, headers=ENCABEZADOS)
        assert cliente.post("/refrescar").status_code == 403
    finally:
        _limpiar()


def test_logout_cierra_la_sesion():
    cliente = _cliente(BaseFalsa({"jperez": _usuario()}, modulos={("jperez", "CUMS")}))
    try:
        cliente.post("/auth/login", json={"usuario": "jperez", "clave": "secreta"}, headers=ENCABEZADOS)
        assert cliente.post("/auth/logout", headers=ENCABEZADOS).status_code == 204
        assert cliente.get("/auth/sesion").status_code == 401
    finally:
        _limpiar()


def test_el_modulo_se_revalida_cada_5_minutos_y_un_usuario_revocado_sale(monkeypatch):
    base = BaseFalsa({"jperez": _usuario()}, modulos={("jperez", "CUMS")})
    cliente = _cliente(base)
    try:
        cliente.post("/auth/login", json={"usuario": "jperez", "clave": "secreta"}, headers=ENCABEZADOS)
        base.modulos.clear()  # el admin le quito el modulo
        assert cliente.get("/salud").status_code == 200  # todavia dentro de la ventana
        monkeypatch.setattr(dependencias, "ahora", lambda: time.time() + 301)
        r = cliente.get("/salud")
        assert r.status_code == 403
        assert cliente.get("/auth/sesion").status_code == 401
    finally:
        _limpiar()
