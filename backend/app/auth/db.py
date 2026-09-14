"""Acceso a Tableros_BI para el login. Aparte de `integraciones/gemanet_db.py`
a proposito: aquel abre la conexion en `read_only` como red de seguridad, y el
login necesita ESCRIBIR en aud_app_login_intento (el rol de la app es dueno de
esa tabla). Mismo DSN (GEMANET_DB_DSN). Una conexion por llamada: el login es
infrecuente y la sesion, una vez creada, no toca la base salvo la
re-verificacion del modulo cada 5 min."""

from __future__ import annotations

import os

NOMBRE_VARIABLE_ENTORNO = "GEMANET_DB_DSN"
TIMEOUT_MS = 30_000


class ErrorBaseAuth(Exception):
    """No se pudo consultar la base de usuarios."""


class BaseAuth:
    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn

    def _conectar(self):
        dsn = self._dsn or os.environ.get(NOMBRE_VARIABLE_ENTORNO, "").strip()
        if not dsn:
            raise ErrorBaseAuth(
                f"No hay credenciales de la base de Gemma Net ({NOMBRE_VARIABLE_ENTORNO})."
            )
        import psycopg
        from psycopg.rows import dict_row

        # El enlace a Tableros_BI cruza WAN/NAT: sin keepalives una conexion
        # ociosa muere en silencio (leccion del dashboard de Auditoria).
        return psycopg.connect(
            dsn,
            connect_timeout=10,
            options=f"-c statement_timeout={TIMEOUT_MS}",
            keepalives=1,
            keepalives_idle=60,
            keepalives_interval=10,
            keepalives_count=3,
            row_factory=dict_row,
        )

    def consultar(self, sql: str, params: tuple = ()) -> list[dict]:
        try:
            with self._conectar() as con:
                return list(con.execute(sql, params).fetchall())
        except ErrorBaseAuth:
            raise
        except Exception as exc:
            raise ErrorBaseAuth(f"Fallo consultando la base de usuarios: {exc}") from exc

    def ejecutar(self, sql: str, params: tuple = ()) -> int:
        try:
            with self._conectar() as con:
                return con.execute(sql, params).rowcount
        except ErrorBaseAuth:
            raise
        except Exception as exc:
            raise ErrorBaseAuth(f"Fallo escribiendo en la base de usuarios: {exc}") from exc
