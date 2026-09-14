"""Dependencias FastAPI del login: la base (inyectable), la sesion actual y
la defensa CSRF."""

from __future__ import annotations

import time

from fastapi import Depends, HTTPException, Request, status

from backend.app.auth import config
from backend.app.auth.db import BaseAuth, ErrorBaseAuth
from backend.app.auth.servicio import Sesion, tiene_modulo

CLAVE_SESION = "sesion"
# Reloj inyectable (las pruebas lo adelantan para ejercitar la revalidacion).
ahora = time.time


def obtener_base() -> BaseAuth:
    return BaseAuth()


def exigir_encabezado_fetch(request: Request) -> None:
    """Todo POST tiene que traer `X-Requested-With: fetch`. Un formulario
    enviado desde otro sitio no puede ponerlo, asi que junto con
    SameSite=Lax cierra el CSRF sin token por peticion."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get(
        "x-requested-with", ""
    ).lower() != "fetch":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Petición rechazada: falta el encabezado X-Requested-With.",
        )


def guardar_sesion(request: Request, sesion: Sesion) -> None:
    request.session.clear()
    request.session[CLAVE_SESION] = {
        "usuario": sesion.usuario,
        "nombre": sesion.nombre,
        "admin": sesion.admin,
        "modulo_verificado_en": ahora(),
    }


def borrar_sesion(request: Request) -> None:
    request.session.clear()


def usuario_actual(request: Request, base: BaseAuth = Depends(obtener_base)) -> Sesion:
    """La sesion de la cookie, o 401. Cada REVALIDAR_MODULO_SEGUNDOS vuelve a
    comprobar en la base que el usuario conserva el modulo: si se lo
    quitaron, la sesion se borra y responde 403 (decision D6 del plan)."""
    exigir_encabezado_fetch(request)
    datos = request.session.get(CLAVE_SESION)
    if not datos:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Debe iniciar sesión.")
    sesion = Sesion(usuario=datos["usuario"], nombre=datos["nombre"], admin=bool(datos["admin"]))
    if ahora() - float(datos.get("modulo_verificado_en", 0)) > config.REVALIDAR_MODULO_SEGUNDOS:
        try:
            sigue = tiene_modulo(base, sesion.usuario, sesion.admin)
        except ErrorBaseAuth:
            # Si la base no responde no se expulsa a nadie por eso: se
            # reintenta en la proxima peticion.
            return sesion
        if not sigue:
            borrar_sesion(request)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Su usuario ya no tiene el módulo {config.MODULO_APP}. Vuelva a ingresar.",
            )
        datos["modulo_verificado_en"] = ahora()
        request.session[CLAVE_SESION] = datos
    return sesion


def exigir_admin(sesion: Sesion = Depends(usuario_actual)) -> Sesion:
    """Solo administradores del ERP (usuario.sw_administrador = 1): pedir un
    refresco y administrar permisos. Pedido del usuario (2026-09-14)."""
    if not sesion.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un administrador puede hacer esto.",
        )
    return sesion
