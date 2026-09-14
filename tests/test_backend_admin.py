"""Administracion > Permisos: asignar / retirar el modulo CUMS a usuarios del
ERP desde esta app (pedido del usuario, 2026-09-14). Solo administradores."""

from fastapi.testclient import TestClient

from backend.app.auth.dependencias import obtener_base, usuario_actual
from backend.app.auth.servicio import Sesion
from backend.app.main import app

ENCABEZADOS = {"X-Requested-With": "fetch"}


class BaseAdminFalsa:
    def __init__(self):
        self.usuarios = [
            {"usuario": "admin1", "nombre": "Ana", "apellido": "Admin", "sw_administrador": 1, "sw_activo": 1},
            {"usuario": "jperez", "nombre": "Juan", "apellido": "Perez", "sw_administrador": 0, "sw_activo": 1},
            {"usuario": "inactivo", "nombre": "Ex", "apellido": "Empleado", "sw_administrador": 0, "sw_activo": 0},
        ]
        self.asignaciones = {}  # usuario -> (usuario_asigna)
        self.escrituras = []

    def consultar(self, sql, params=()):
        if "LEFT JOIN administrativo.aud_app_usuario_modulo" in sql:
            filas = []
            for u in self.usuarios:
                if u["sw_activo"] != 1:
                    continue
                asigna = self.asignaciones.get(u["usuario"])
                filas.append({**u, "usuario_asigna": asigna, "fecha_asigna": "2026-09-14 10:00:00" if asigna else None})
            return filas
        if "FROM administrativo.usuario" in sql and "sw_activo = 1" in sql:
            return [u for u in self.usuarios if u["usuario"] == params[0] and u["sw_activo"] == 1]
        raise AssertionError(sql)

    def ejecutar(self, sql, params=()):
        self.escrituras.append((sql.split()[0], params))
        if sql.lstrip().startswith("INSERT"):
            self.asignaciones[params[0]] = params[2]
            return 1
        if sql.lstrip().startswith("DELETE"):
            return 1 if self.asignaciones.pop(params[0], None) else 0
        raise AssertionError(sql)


def _cliente(base, admin=True):
    app.dependency_overrides[usuario_actual] = lambda: Sesion("admin1", "Ana Admin", admin=admin)
    app.dependency_overrides[obtener_base] = lambda: base
    return TestClient(app)


def test_un_no_administrador_no_ve_ni_toca_los_permisos():
    cliente = _cliente(BaseAdminFalsa(), admin=False)
    try:
        assert cliente.get("/admin/usuarios").status_code == 403
        assert cliente.post("/admin/usuarios/jperez/modulo", json={"asignado": True}, headers=ENCABEZADOS).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_lista_los_usuarios_activos_con_su_estado_del_modulo():
    base = BaseAdminFalsa()
    base.asignaciones["jperez"] = "admin1"
    cliente = _cliente(base)
    try:
        r = cliente.get("/admin/usuarios")
        assert r.status_code == 200
        filas = {u["usuario"]: u for u in r.json()}
        assert set(filas) == {"admin1", "jperez"}  # el inactivo no aparece
        assert filas["admin1"]["admin"] is True and filas["admin1"]["tiene_modulo"] is True
        assert filas["jperez"]["admin"] is False and filas["jperez"]["tiene_modulo"] is True
        assert filas["jperez"]["asignado_por"] == "admin1"
        assert filas["jperez"]["nombre"] == "Juan Perez"
    finally:
        app.dependency_overrides.clear()


def test_asignar_y_retirar_el_modulo():
    base = BaseAdminFalsa()
    cliente = _cliente(base)
    try:
        r = cliente.post("/admin/usuarios/jperez/modulo", json={"asignado": True}, headers=ENCABEZADOS)
        assert r.status_code == 200
        assert r.json()["tiene_modulo"] is True
        assert base.asignaciones["jperez"] == "admin1"  # quien asigna es la sesion
        r = cliente.post("/admin/usuarios/jperez/modulo", json={"asignado": False}, headers=ENCABEZADOS)
        assert r.status_code == 200
        assert r.json()["tiene_modulo"] is False
        assert "jperez" not in base.asignaciones
    finally:
        app.dependency_overrides.clear()


def test_no_se_asigna_a_un_usuario_inexistente_o_inactivo():
    cliente = _cliente(BaseAdminFalsa())
    try:
        assert cliente.post("/admin/usuarios/inactivo/modulo", json={"asignado": True}, headers=ENCABEZADOS).status_code == 404
        assert cliente.post("/admin/usuarios/nadie/modulo", json={"asignado": True}, headers=ENCABEZADOS).status_code == 404
    finally:
        app.dependency_overrides.clear()
