"""Reglas del login, sin FastAPI ni base concreta: `base` es cualquier objeto
con `consultar(sql, params)` / `ejecutar(sql, params)` (ver db.py y la
BaseFalsa de las pruebas). El orden de las comprobaciones es el del dashboard
de Auditoria: bloqueo -> credenciales -> vigencia de la clave -> modulo."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import date

from backend.app.auth import config


@dataclass(frozen=True)
class Sesion:
    usuario: str
    nombre: str
    admin: bool


class ErrorLogin(Exception):
    def __init__(self, status: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.status = status
        self.mensaje = mensaje


def hash_clave(clave: str) -> str:
    """sha256(prefijo + clave + sufijo) en hex minuscula -- Util.getSHA256 del ERP."""
    texto = config.CLAVE_PREFIJO + clave + config.CLAVE_SUFIJO
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _bloqueado(base, usuario: str) -> bool:
    filas = base.consultar(
        """SELECT count(*) AS n FROM administrativo.aud_app_login_intento
           WHERE usuario = %s AND exitoso = 0
             AND fecha > now() - make_interval(mins => %s)""",
        (usuario, config.bloqueo_minutos()),
    )
    return int(filas[0]["n"]) >= config.max_intentos()


def _registrar_intento(base, usuario: str, origen_ip: str | None, exitoso: bool) -> None:
    base.ejecutar(
        """INSERT INTO administrativo.aud_app_login_intento (usuario, origen_ip, exitoso)
           VALUES (%s, %s, %s)""",
        (usuario, origen_ip, 1 if exitoso else 0),
    )


def tiene_modulo(base, usuario: str, admin: bool) -> bool:
    """El administrador del ERP entra sin modulo; el resto necesita MODULO_APP
    asignado (lo asigna el admin desde /admin/permisos del dashboard de
    Auditoria de Calidades) y el modulo activo."""
    if admin:
        return True
    filas = base.consultar(
        """SELECT 1 AS tiene
           FROM administrativo.aud_app_usuario_modulo um
           JOIN administrativo.aud_app_modulo m ON m.id_modulo = um.id_modulo
           WHERE um.usuario = %s AND um.id_modulo = %s AND m.sw_activo = 1""",
        (usuario, config.MODULO_APP),
    )
    return bool(filas)


def autenticar(base, usuario: str, clave: str, origen_ip: str | None) -> Sesion:
    usuario = (usuario or "").strip()
    if not usuario or not clave:
        raise ErrorLogin(400, "Ingrese usuario y clave.")

    if _bloqueado(base, usuario):
        raise ErrorLogin(
            429, f"Demasiados intentos fallidos. Espere {config.bloqueo_minutos()} minutos."
        )

    filas = base.consultar(
        """SELECT usuario, clave, nombre, apellido, sw_activo, sw_administrador,
                  sw_obliga_cambio_clave, fecha_proximo_cambio
           FROM administrativo.usuario WHERE usuario = %s""",
        (usuario,),
    )
    u = filas[0] if filas else None
    ok = (
        u is not None
        and u["sw_activo"] == 1
        and secrets.compare_digest(u["clave"] or "", hash_clave(clave))
    )
    if not ok:
        _registrar_intento(base, usuario, origen_ip, False)
        raise ErrorLogin(401, "Usuario o clave incorrectos.")

    # Mismas reglas de vigencia que el ERP: la clave se cambia en GemaNet, no aqui.
    if (
        u["sw_obliga_cambio_clave"] == 1
        or u["fecha_proximo_cambio"] is None
        or u["fecha_proximo_cambio"] < date.today()
    ):
        _registrar_intento(base, usuario, origen_ip, False)
        raise ErrorLogin(
            403, "Su clave requiere actualización. Cámbiela en GemaNet e intente de nuevo."
        )

    admin = u["sw_administrador"] == 1
    # La clave era correcta: el intento cuenta como exitoso aunque falte el
    # modulo -- lo que falta es un permiso, no un secreto, y no debe bloquear.
    _registrar_intento(base, usuario, origen_ip, True)
    if not tiene_modulo(base, usuario, admin):
        raise ErrorLogin(
            403,
            f"Su usuario no tiene asignado el módulo {config.MODULO_APP}. "
            "Pídalo al administrador (Auditoría de Calidades › Permisos).",
        )
    nombre = f"{u['nombre'] or ''} {u['apellido'] or ''}".strip()
    return Sesion(usuario=u["usuario"], nombre=nombre, admin=admin)
