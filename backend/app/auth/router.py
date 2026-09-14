"""POST /auth/login, POST /auth/logout, GET /auth/sesion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend.app.auth.db import BaseAuth, ErrorBaseAuth
from backend.app.auth.dependencias import (
    CLAVE_SESION,
    borrar_sesion,
    exigir_encabezado_fetch,
    guardar_sesion,
    obtener_base,
)
from backend.app.auth.servicio import ErrorLogin, autenticar
from backend.app.schemas import DatosLogin, UsuarioSesion

router = APIRouter(prefix="/auth", tags=["sesion"])


@router.post("/login", response_model=UsuarioSesion, dependencies=[Depends(exigir_encabezado_fetch)])
def login(datos: DatosLogin, request: Request, base: BaseAuth = Depends(obtener_base)) -> UsuarioSesion:
    origen_ip = request.client.host if request.client else None
    try:
        sesion = autenticar(base, datos.usuario, datos.clave, origen_ip)
    except ErrorLogin as exc:
        raise HTTPException(status_code=exc.status, detail=exc.mensaje) from exc
    except ErrorBaseAuth as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo consultar la base de usuarios de GemaNet. Intente de nuevo en un momento.",
        ) from exc
    guardar_sesion(request, sesion)
    return UsuarioSesion(usuario=sesion.usuario, nombre=sesion.nombre, admin=sesion.admin)


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(exigir_encabezado_fetch)]
)
def logout(request: Request) -> Response:
    borrar_sesion(request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sesion", response_model=UsuarioSesion)
def sesion_actual(request: Request) -> UsuarioSesion:
    datos = request.session.get(CLAVE_SESION)
    if not datos:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Debe iniciar sesión.")
    return UsuarioSesion(usuario=datos["usuario"], nombre=datos["nombre"], admin=bool(datos["admin"]))
