"""Cliente de solo lectura contra la base PostgreSQL de Gemma Net.

Este modulo no sabe nada de medicamentos ni de catalogos: solo conexion,
acotamiento y errores. Ver `catalogos/fuentes.py` para el adaptador que
conoce que tablas alimentan la cascada de resolucion.

SEGURIDAD -- la base (`muzna`, esquema `administrativo`) es **produccion de
Pijao Salud**. El riesgo no es corromper datos (el rol es de solo lectura)
sino consumir recursos de los que dependen las autorizaciones de pacientes
reales. Por eso TODA consulta que pase por aqui lleva, sin excepcion:

  - `read_only = True` en la conexion -- red de seguridad propia, que no
    depende de que el rol siga sin permisos de escritura manana.
  - `statement_timeout` -- una consulta desbocada se corta sola en vez de
    quedarse tomando recursos del servidor.
  - un tope de filas explicito en el llamador.

El DSN se administra por variable de entorno, nunca hardcodeado, nunca
impreso ni logueado -- mismo patron que `integraciones/socrata.py` para el
App Token y que `catalogos/ia_client.py` para ANTHROPIC_API_KEY.
`estado_conexion()` expone solo una version enmascarada, para que la UI pueda
mostrar "hay credenciales configuradas" sin revelarlas.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

NOMBRE_VARIABLE_ENTORNO = "GEMANET_DB_DSN"
TIMEOUT_CONSULTA_MS = 5000
TOPE_FILAS = 5000


class ErrorGemaNetDB(Exception):
    """Fallo de conexion o de la consulta. Un resultado de 0 filas NO es un
    error: es una respuesta valida."""


class ErrorAutenticacionGemaNetDB(ErrorGemaNetDB):
    """Credenciales rechazadas por el servidor."""


class Conexion(Protocol):
    """Lo minimo que necesitamos de una conexion psycopg -- permite inyectar
    un doble en las pruebas sin tocar la base real (regla del proyecto: los
    tests nunca golpean un servicio externo)."""

    def cursor(self) -> Any: ...


@dataclass(frozen=True)
class EstadoConexion:
    configurado: bool
    origen: str  # "entorno" | "no_configurado"
    resumen: str = ""  # "usuario@host/base" -- NUNCA la contrasena


def dsn_desde_entorno() -> str | None:
    dsn = os.environ.get(NOMBRE_VARIABLE_ENTORNO, "").strip()
    return dsn or None


def _resumen_sin_secreto(dsn: str) -> str:
    """"usuario@host/base" a partir del DSN, descartando la contrasena.

    Acepta las dos formas que entiende libpq: clave=valor y URL. Si algo no
    calza se devuelve vacio en vez de arriesgar filtrar parte del secreto --
    el resumen es una comodidad, no vale un escape de credenciales.
    """
    try:
        if dsn.startswith(("postgresql://", "postgres://")):
            cuerpo = dsn.split("://", 1)[1]
            credenciales, _, resto = cuerpo.partition("@")
            usuario = credenciales.split(":", 1)[0] if resto else ""
            host_base = (resto or cuerpo).split("?", 1)[0]
            return f"{usuario}@{host_base}" if usuario else host_base
        campos = dict(
            re.findall(r"(\w+)\s*=\s*([^\s]+)", dsn)
        )
        usuario, host, base = campos.get("user", ""), campos.get("host", ""), campos.get("dbname", "")
        if not (usuario or host):
            return ""
        return f"{usuario}@{host}/{base}".strip("@/")
    except Exception:
        return ""


def estado_conexion() -> EstadoConexion:
    dsn = dsn_desde_entorno()
    if not dsn:
        return EstadoConexion(configurado=False, origen="no_configurado")
    return EstadoConexion(configurado=True, origen="entorno", resumen=_resumen_sin_secreto(dsn))


# Frases con que PostgreSQL rechaza credenciales. Se mira el TEXTO y no solo
# `sqlstate` porque cuando el fallo ocurre al CONECTAR -- que es justo el caso
# de una contrasena mala -- psycopg deja `sqlstate` en None: no llego a haber
# sesion en la que registrarlo. Comprobado el 2026-08-20 con la credencial
# real alterada en un caracter.
_SENALES_AUTENTICACION = (
    "password authentication failed",
    "authentication failed",
    "no pg_hba.conf entry",
    "role ",
)


def _es_fallo_de_autenticacion(exc: Exception) -> bool:
    """Distingue "tus credenciales estan mal" de "el servidor no responde".

    Importa porque la accion es distinta: lo primero lo arregla quien
    configura la variable de entorno; lo segundo hay que esperarlo o
    escalarlo al DBA. Un mensaje generico deja al usuario sin saber cual de
    las dos cosas hacer.
    """
    codigo = str(getattr(exc, "sqlstate", "") or "")
    if codigo.startswith("28"):  # clase 28 = autorizacion invalida
        return True
    texto = str(exc).lower()
    return any(senal in texto for senal in _SENALES_AUTENTICACION)


def consultar(
    sql: str,
    *,
    conexion: Conexion | None = None,
    timeout_ms: int = TIMEOUT_CONSULTA_MS,
    tope_filas: int = TOPE_FILAS,
) -> list[tuple]:
    """Ejecuta una consulta acotada y devuelve hasta `tope_filas`.

    `conexion` inyectable para las pruebas. Si no se pasa, se abre una nueva
    con el DSN del entorno y se cierra al terminar -- no se mantiene una
    conexion viva entre corridas: las conexiones de Postgres son un recurso
    compartido y escaso en un servidor de produccion, y los catalogos se
    cargan una vez por corrida (ademas cacheados en la UI).
    """
    if conexion is not None:
        # Mismo envoltorio de errores que la ruta con DSN: el contrato dice
        # que un fallo sale como ErrorGemaNetDB, y de eso depende que
        # FuenteCatalogosConRespaldo pueda caer al CSV. Sin esto, una
        # excepcion cruda del driver se saltaba el respaldo por completo.
        try:
            return _ejecutar(conexion, sql, timeout_ms, tope_filas)
        except Exception as exc:
            raise ErrorGemaNetDB(f"Fallo la consulta a la base de Gemma Net: {exc}") from exc

    dsn = dsn_desde_entorno()
    if not dsn:
        raise ErrorGemaNetDB(
            f"No hay credenciales de la base de Gemma Net. Configura {NOMBRE_VARIABLE_ENTORNO} "
            "en el entorno."
        )
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - dependencia declarada
        raise ErrorGemaNetDB(f"Falta el driver de PostgreSQL: {exc}") from exc

    try:
        with psycopg.connect(dsn) as con:
            con.read_only = True
            return _ejecutar(con, sql, timeout_ms, tope_filas)
    except psycopg.OperationalError as exc:
        if _es_fallo_de_autenticacion(exc):
            raise ErrorAutenticacionGemaNetDB(
                f"La base rechazo las credenciales de {NOMBRE_VARIABLE_ENTORNO}. "
                "Revisa usuario y contrasena; el servidor si responde."
            ) from exc
        raise ErrorGemaNetDB(f"No se pudo conectar a la base de Gemma Net: {exc}") from exc
    except Exception as exc:
        raise ErrorGemaNetDB(f"Fallo la consulta a la base de Gemma Net: {exc}") from exc


def _ejecutar(conexion: Conexion, sql: str, timeout_ms: int, tope_filas: int) -> list[tuple]:
    with conexion.cursor() as cur:
        cur.execute(f"SET statement_timeout = {int(timeout_ms)}")
        cur.execute(sql)
        return list(cur.fetchmany(tope_filas))
