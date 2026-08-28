"""Registro de salud del ultimo refresco del worker.

Vive aparte de `almacen_snapshots.py` a proposito: los snapshots son datos
grandes (Parquet, se reescriben enteros cada corrida), esto es un registro
chico y transaccional (SQLite) de "cuando corrio, cuanto tardo, si fallo".
Consultable de forma independiente del backend/frontend -- es la pieza que
sostiene la regla de "degradacion explicita, nunca suposicion silenciosa":
si el worker esta fallando, tiene que quedar registrado en un lugar que
cualquiera pueda mirar, no solo en un log que nadie revisa.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA_ESTADO_DEFECTO = RAIZ / "data_runtime" / "estado_worker.sqlite3"

ESTADO_OK = "ok"
ESTADO_ERROR = "error"

# Estado de un paso individual dentro de una corrida (no de la corrida
# completa -- ver ESTADO_OK/ESTADO_ERROR arriba, que siguen siendo el
# resultado final que ya consume /salud). Pedido del usuario (2026-08-27):
# "una pequeña lista mostrando uno a uno los procesos que se van haciendo y
# su progreso, un ejemplo como cuando uno descarga varias cosas en Google" --
# una lista de pasos con estado discreto, no un porcentaje inventado: leer
# INVIMA/auditar/etc. son llamadas opacas de varios segundos cada una, no
# hay un "40% de esta llamada" real que reportar sin inventarlo.
ESTADO_PASO_PENDIENTE = "pendiente"
ESTADO_PASO_EN_CURSO = "en_curso"
ESTADO_PASO_HECHO = "hecho"
ESTADO_PASO_ERROR = "error"


@dataclass(frozen=True)
class EstadoRefresco:
    inicio_utc: str
    fin_utc: str
    duracion_segundos: float
    estado: str  # ESTADO_OK | ESTADO_ERROR
    detalle_error: str = ""


@dataclass(frozen=True)
class PasoProgreso:
    """Un paso de la corrida MAS RECIENTE (en curso, o la ultima terminada
    si ninguna esta corriendo ahora) -- ver `progreso_actual()`."""

    orden: int
    nombre: str
    estado: str  # ESTADO_PASO_*
    detalle: str = ""


def _conectar(ruta: Path) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS refrescos (
            inicio_utc TEXT NOT NULL,
            fin_utc TEXT NOT NULL,
            duracion_segundos REAL NOT NULL,
            estado TEXT NOT NULL,
            detalle_error TEXT NOT NULL DEFAULT ''
        )
        """
    )
    # progreso_pasos: se REEMPLAZA entera al arrancar cada corrida
    # (iniciar_progreso borra e inserta de nuevo) -- a diferencia de
    # `refrescos`, que es un historial append-only, esto es solo el estado
    # EN VIVO de la corrida vigente/mas reciente. No hace falta guardar
    # progreso de corridas viejas: ya quedan resumidas en `refrescos`.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS progreso_pasos (
            orden INTEGER PRIMARY KEY,
            nombre TEXT NOT NULL,
            estado TEXT NOT NULL,
            detalle TEXT NOT NULL DEFAULT ''
        )
        """
    )
    # control: pares clave/valor de una sola fila cada uno -- hoy solo
    # "solicitud_pendiente" (POST /refrescar la escribe, el worker la lee y
    # la borra). Es la UNICA via de comunicacion entre el proceso del
    # backend y el proceso del worker -- mismo patron de archivo/SQLite que
    # ya usa el resto del proyecto (almacen_snapshots.py), sin agregar un
    # broker ni un segundo servidor HTTP para esto.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS control (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        )
        """
    )
    return con


def registrar_refresco(evento: EstadoRefresco, ruta: Path | None = None) -> None:
    """Agrega una fila -- nunca se sobrescribe el historial, para poder ver
    la tendencia (cuantos refrescos seguidos vienen fallando, por ejemplo)."""
    ruta = ruta or RUTA_ESTADO_DEFECTO
    con = _conectar(ruta)
    try:
        con.execute(
            "INSERT INTO refrescos "
            "(inicio_utc, fin_utc, duracion_segundos, estado, detalle_error) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                evento.inicio_utc,
                evento.fin_utc,
                evento.duracion_segundos,
                evento.estado,
                evento.detalle_error,
            ),
        )
        con.commit()
    finally:
        con.close()


def ultimo_refresco(ruta: Path | None = None) -> EstadoRefresco | None:
    """El refresco mas reciente registrado, o `None` si el worker todavia no
    corrio ni una vez -- degradacion explicita, nunca se inventa un estado
    "ok" por defecto cuando en realidad no hay ningun dato."""
    ruta = ruta or RUTA_ESTADO_DEFECTO
    if not ruta.is_file():
        return None
    con = _conectar(ruta)
    try:
        fila = con.execute(
            "SELECT inicio_utc, fin_utc, duracion_segundos, estado, detalle_error "
            "FROM refrescos ORDER BY fin_utc DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    if fila is None:
        return None
    return EstadoRefresco(*fila)


def iniciar_progreso(nombres_pasos: list[str], ruta: Path | None = None) -> None:
    """Reinicia la lista de pasos al arrancar una corrida -- todos en
    `ESTADO_PASO_PENDIENTE`. Se llama UNA vez al principio de
    `tareas.ejecutar_refresco()`, antes del primer paso."""
    ruta = ruta or RUTA_ESTADO_DEFECTO
    con = _conectar(ruta)
    try:
        con.execute("DELETE FROM progreso_pasos")
        con.executemany(
            "INSERT INTO progreso_pasos (orden, nombre, estado, detalle) VALUES (?, ?, ?, ?)",
            [(i, nombre, ESTADO_PASO_PENDIENTE, "") for i, nombre in enumerate(nombres_pasos)],
        )
        con.commit()
    finally:
        con.close()


def actualizar_paso(nombre: str, estado: str, detalle: str = "", ruta: Path | None = None) -> None:
    ruta = ruta or RUTA_ESTADO_DEFECTO
    con = _conectar(ruta)
    try:
        con.execute(
            "UPDATE progreso_pasos SET estado = ?, detalle = ? WHERE nombre = ?",
            (estado, detalle, nombre),
        )
        con.commit()
    finally:
        con.close()


def progreso_actual(ruta: Path | None = None) -> list[PasoProgreso]:
    """Los pasos de la corrida mas reciente, en orden -- lista vacia si el
    worker nunca arranco ninguna (degradacion explicita, no se inventa una
    lista de pasos "vacios pero validos")."""
    ruta = ruta or RUTA_ESTADO_DEFECTO
    if not ruta.is_file():
        return []
    con = _conectar(ruta)
    try:
        filas = con.execute(
            "SELECT orden, nombre, estado, detalle FROM progreso_pasos ORDER BY orden"
        ).fetchall()
    finally:
        con.close()
    return [PasoProgreso(*fila) for fila in filas]


def solicitar_refresco_manual(ruta: Path | None = None) -> None:
    """Escribe la senal que `worker/refresco.py::_vigilar_solicitud_manual`
    revisa cada pocos segundos -- lo unico que hace POST /refrescar del
    backend. No corre el pipeline, no bloquea el request: solo un INSERT
    barato."""
    ruta = ruta or RUTA_ESTADO_DEFECTO
    con = _conectar(ruta)
    try:
        con.execute(
            "INSERT INTO control (clave, valor) VALUES ('solicitud_pendiente', '1') "
            "ON CONFLICT(clave) DO UPDATE SET valor = '1'"
        )
        con.commit()
    finally:
        con.close()


def hay_solicitud_pendiente(ruta: Path | None = None) -> bool:
    ruta = ruta or RUTA_ESTADO_DEFECTO
    if not ruta.is_file():
        return False
    con = _conectar(ruta)
    try:
        fila = con.execute(
            "SELECT valor FROM control WHERE clave = 'solicitud_pendiente'"
        ).fetchone()
    finally:
        con.close()
    return fila is not None and fila[0] == "1"


def limpiar_solicitud_pendiente(ruta: Path | None = None) -> None:
    ruta = ruta or RUTA_ESTADO_DEFECTO
    con = _conectar(ruta)
    try:
        con.execute("DELETE FROM control WHERE clave = 'solicitud_pendiente'")
        con.commit()
    finally:
        con.close()
