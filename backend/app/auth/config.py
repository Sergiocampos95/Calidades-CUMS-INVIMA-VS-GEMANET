"""Configuracion del login -- todo por variables de entorno, salvo los comodines
del hash, que son constantes del ERP."""

from __future__ import annotations

import os

# Comodines de Util.getSHA256 del ERP. Tienen que ser IDENTICOS a los de
# auditoria_calidades/dashboard/app/config.py o ningun login funciona. No
# registrar en logs.
CLAVE_PREFIJO = "%&3*,"
CLAVE_SUFIJO = "@$#)?¿"

# El modulo que da acceso a esta app en aud_app_usuario_modulo (ddl/01_modulo_cums.sql).
MODULO_APP = "CUMS"
NOMBRE_COOKIE = "gemanet_cums_sesion"
# Cada cuanto se vuelve a comprobar en la base que el usuario sigue teniendo
# el modulo (decision D6 del plan: no en cada peticion, la base esta al otro
# lado de una WAN y una pantalla dispara varias peticiones).
REVALIDAR_MODULO_SEGUNDOS = 300


def secret_key() -> str:
    valor = os.environ.get("SECRET_KEY", "").strip()
    if not valor:
        raise RuntimeError(
            "Falta SECRET_KEY en el entorno: sin ella no se puede firmar la cookie de sesion. "
            "Ver deploy/env.example."
        )
    return valor


def _entero(nombre: str, defecto: int) -> int:
    try:
        return int(os.environ.get(nombre, "") or defecto)
    except ValueError:
        return defecto


def max_intentos() -> int:
    return _entero("MAX_INTENTOS", 5)


def bloqueo_minutos() -> int:
    return _entero("BLOQUEO_MINUTOS", 15)


def sesion_horas() -> int:
    return _entero("SESION_HORAS", 8)
