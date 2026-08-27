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


@dataclass(frozen=True)
class EstadoRefresco:
    inicio_utc: str
    fin_utc: str
    duracion_segundos: float
    estado: str  # ESTADO_OK | ESTADO_ERROR
    detalle_error: str = ""


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
