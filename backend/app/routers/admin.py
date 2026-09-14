"""GET /admin/usuarios y POST /admin/usuarios/{usuario}/modulo -- asignar o
retirar el modulo de esta app (MODULO_APP) a usuarios del ERP, desde la
propia app. Solo administradores.

Calca /admin/permisos del dashboard de Auditoria de Calidades pero acotado a
UN modulo: los demas modulos siguen administrandose alla. Escribe solo en
administrativo.aud_app_usuario_modulo (mismas columnas: quien asigno y
cuando); nunca toca administrativo.usuario, que es replica de solo lectura.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.auth import config
from backend.app.auth.db import BaseAuth, ErrorBaseAuth
from backend.app.auth.dependencias import (
    exigir_admin,
    exigir_encabezado_fetch,
    obtener_base,
)
from backend.app.auth.servicio import Sesion
from backend.app.schemas import CambioPermiso, UsuarioPermiso

router = APIRouter(prefix="/admin", tags=["administracion"], dependencies=[Depends(exigir_admin)])

_SQL_USUARIOS = """
    SELECT u.usuario, u.nombre, u.apellido, u.sw_administrador,
           um.usuario_asigna, um.fecha_asigna
    FROM administrativo.usuario u
    LEFT JOIN administrativo.aud_app_usuario_modulo um
           ON um.usuario = u.usuario AND um.id_modulo = %s
    WHERE u.sw_activo = 1
    ORDER BY u.sw_administrador DESC, u.usuario
"""
_SQL_USUARIO_ACTIVO = "SELECT usuario FROM administrativo.usuario WHERE usuario = %s AND sw_activo = 1"
_SQL_ASIGNAR = """
    INSERT INTO administrativo.aud_app_usuario_modulo (usuario, id_modulo, usuario_asigna)
    VALUES (%s, %s, %s)
    ON CONFLICT (usuario, id_modulo) DO NOTHING
"""
_SQL_RETIRAR = "DELETE FROM administrativo.aud_app_usuario_modulo WHERE usuario = %s AND id_modulo = %s"


def _fila(u: dict) -> UsuarioPermiso:
    admin = u["sw_administrador"] == 1
    return UsuarioPermiso(
        usuario=u["usuario"],
        nombre=f"{u['nombre'] or ''} {u['apellido'] or ''}".strip(),
        admin=admin,
        # Un admin del ERP entra sin modulo (ver servicio.tiene_modulo): se
        # muestra como "tiene" para que la pantalla no invite a asignarselo.
        tiene_modulo=admin or u.get("usuario_asigna") is not None,
        asignado_por=u.get("usuario_asigna"),
        fecha_asignacion=str(u["fecha_asigna"])[:16] if u.get("fecha_asigna") else None,
    )


def _error_base(exc: ErrorBaseAuth) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="No se pudo consultar la base de usuarios de GemaNet. Intente de nuevo en un momento.",
    )


@router.get("/usuarios", response_model=list[UsuarioPermiso])
def listar_usuarios(base: BaseAuth = Depends(obtener_base)) -> list[UsuarioPermiso]:
    """Todos los usuarios ACTIVOS del ERP (unos 250: cabe entero, sin paginar)
    con su estado frente al modulo de esta app."""
    try:
        return [_fila(u) for u in base.consultar(_SQL_USUARIOS, (config.MODULO_APP,))]
    except ErrorBaseAuth as exc:
        raise _error_base(exc) from exc


@router.post(
    "/usuarios/{usuario}/modulo",
    response_model=UsuarioPermiso,
    dependencies=[Depends(exigir_encabezado_fetch)],
)
def cambiar_modulo(
    usuario: str,
    cambio: CambioPermiso,
    sesion: Sesion = Depends(exigir_admin),
    base: BaseAuth = Depends(obtener_base),
) -> UsuarioPermiso:
    usuario = usuario.strip()
    try:
        existe = base.consultar(_SQL_USUARIO_ACTIVO, (usuario,))
        if not existe:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"El usuario '{usuario}' no existe o esta inactivo en GemaNet.",
            )
        if cambio.asignado:
            base.ejecutar(_SQL_ASIGNAR, (usuario, config.MODULO_APP, sesion.usuario))
        else:
            base.ejecutar(_SQL_RETIRAR, (usuario, config.MODULO_APP))
        fila = next(
            (u for u in base.consultar(_SQL_USUARIOS, (config.MODULO_APP,)) if u["usuario"] == usuario),
            None,
        )
    except ErrorBaseAuth as exc:
        raise _error_base(exc) from exc
    if fila is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"El usuario '{usuario}' no existe.")
    return _fila(fila)
