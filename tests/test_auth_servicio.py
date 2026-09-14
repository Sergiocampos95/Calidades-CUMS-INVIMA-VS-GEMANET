"""Login calcado de auditoria_calidades/dashboard/app/auth.py: mismas reglas,
mismo orden. La base se inyecta (regla del proyecto: las pruebas nunca tocan
un servicio externo)."""

import hashlib
from datetime import date, timedelta

import pytest

from backend.app.auth.config import CLAVE_PREFIJO, CLAVE_SUFIJO, MODULO_APP
from backend.app.auth.servicio import (
    ErrorLogin,
    Sesion,
    autenticar,
    hash_clave,
    tiene_modulo,
)


class BaseFalsa:
    """Responde a las 4 consultas del servicio mirando un fragmento del SQL."""

    def __init__(self, usuarios=None, modulos=None, fallos_recientes=0):
        self.usuarios = usuarios or {}
        self.modulos = set(modulos or [])
        self.fallos_recientes = fallos_recientes
        self.intentos = []

    def consultar(self, sql, params=()):
        if "aud_app_login_intento" in sql:
            return [{"n": self.fallos_recientes}]
        if "FROM administrativo.usuario" in sql:
            u = self.usuarios.get(params[0])
            return [u] if u else []
        if "aud_app_usuario_modulo" in sql:
            return [{"tiene": 1}] if (params[0], params[1]) in self.modulos else []
        raise AssertionError(f"consulta inesperada: {sql}")

    def ejecutar(self, sql, params=()):
        assert "aud_app_login_intento" in sql
        self.intentos.append(params)
        return 1


def _usuario(clave="secreta", **extra):
    base = {
        "usuario": "jperez", "clave": hash_clave(clave), "nombre": "Juan", "apellido": "Perez",
        "sw_activo": 1, "sw_administrador": 0, "sw_obliga_cambio_clave": 0,
        "fecha_proximo_cambio": date.today() + timedelta(days=30),
    }
    base.update(extra)
    return base


def test_el_hash_es_sha256_con_los_comodines_del_erp():
    esperado = hashlib.sha256((CLAVE_PREFIJO + "abc" + CLAVE_SUFIJO).encode("utf-8")).hexdigest()
    assert hash_clave("abc") == esperado


def test_credenciales_correctas_con_modulo_devuelven_la_sesion_y_registran_el_intento():
    base = BaseFalsa({"jperez": _usuario()}, modulos={("jperez", MODULO_APP)})
    sesion = autenticar(base, "jperez", "secreta", "10.0.0.1")
    assert sesion == Sesion(usuario="jperez", nombre="Juan Perez", admin=False)
    assert base.intentos == [("jperez", "10.0.0.1", 1)]


def test_clave_incorrecta_es_401_y_queda_registrada_como_fallo():
    base = BaseFalsa({"jperez": _usuario()})
    with pytest.raises(ErrorLogin) as e:
        autenticar(base, "jperez", "otra", "10.0.0.1")
    assert e.value.status == 401
    assert base.intentos == [("jperez", "10.0.0.1", 0)]


def test_usuario_inexistente_o_inactivo_es_401():
    base = BaseFalsa({"jperez": _usuario(sw_activo=0)})
    with pytest.raises(ErrorLogin) as e:
        autenticar(base, "jperez", "secreta", None)
    assert e.value.status == 401
    with pytest.raises(ErrorLogin) as e:
        autenticar(base, "nadie", "secreta", None)
    assert e.value.status == 401


def test_bloqueado_tras_demasiados_fallos_es_429_antes_de_mirar_la_clave():
    base = BaseFalsa({"jperez": _usuario()}, fallos_recientes=5)
    with pytest.raises(ErrorLogin) as e:
        autenticar(base, "jperez", "secreta", None)
    assert e.value.status == 429
    assert base.intentos == []


@pytest.mark.parametrize("extra", [
    {"sw_obliga_cambio_clave": 1},
    {"fecha_proximo_cambio": None},
    {"fecha_proximo_cambio": date.today() - timedelta(days=1)},
])
def test_clave_vencida_u_obligada_a_cambio_es_403_y_se_cambia_en_gemanet(extra):
    base = BaseFalsa({"jperez": _usuario(**extra)}, modulos={("jperez", MODULO_APP)})
    with pytest.raises(ErrorLogin) as e:
        autenticar(base, "jperez", "secreta", None)
    assert e.value.status == 403
    assert "GemaNet" in e.value.mensaje
    assert base.intentos == [("jperez", None, 0)]


def test_sin_el_modulo_cums_es_403_aunque_la_clave_sea_correcta():
    base = BaseFalsa({"jperez": _usuario()})
    with pytest.raises(ErrorLogin) as e:
        autenticar(base, "jperez", "secreta", None)
    assert e.value.status == 403
    assert "CUMS" in e.value.mensaje
    # La clave era correcta: no cuenta para el bloqueo.
    assert base.intentos == [("jperez", None, 1)]


def test_el_administrador_del_erp_entra_sin_modulo():
    base = BaseFalsa({"admin": _usuario(usuario="admin", sw_administrador=1)})
    sesion = autenticar(base, "admin", "secreta", None)
    assert sesion.admin is True
    assert tiene_modulo(base, "admin", admin=True) is True


def test_tiene_modulo_consulta_la_asignacion():
    base = BaseFalsa(modulos={("jperez", MODULO_APP)})
    assert tiene_modulo(base, "jperez", admin=False) is True
    assert tiene_modulo(base, "otro", admin=False) is False
