"""Elecciones de registro de INVIMA guardadas por el usuario: para un CUM
con varios registros distintos en INVIMA, contra cual cruza la auditoria.

Pedido del usuario (2026-10-14): "debe permitirme cual quiero cruzar", y que
quede GUARDADO -- no solo una vista. El backend escribe (POST/DELETE en
`routers/consulta_detalle.py`) y el worker lee en cada refresco y se lo pasa a
la auditoria (`pipeline.auditar_coherencia_gemanet(elecciones_registro=...)`),
que cruza contra el elegido (ver `auditoria/registros_invima.py`
`aplicar_elecciones_registro`).

Mismo patron que `estado.py`: SQLite chico y transaccional en `data_runtime/`
(no versionado), la unica via entre los procesos del backend y del worker.
Un registro se guarda por su FIRMA (los valores que se comparan), no por su
numero: el numero cambia si INVIMA reordena su archivo.

`historial` es append-only: elegir un registro decide contra que se audita un
medicamento, y quien lo decidio y cuando tiene que quedar a la vista aunque la
eleccion se cambie o se quite despues.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA_ELECCIONES_DEFECTO = RAIZ / "data_runtime" / "elecciones_registro_invima.sqlite3"

ACCION_ELEGIR = "elegir"
ACCION_QUITAR = "quitar"


@dataclass(frozen=True)
class EleccionRegistro:
    """`registro_al_elegir` es el numero que tenia el registro cuando se eligio
    -- informativo: lo que identifica al registro es `firma`."""

    cum: str
    listado: str
    firma: str
    registro_al_elegir: int
    resumen: str
    usuario: str
    fecha_utc: str


def _conectar(ruta: Path) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS elecciones (
            cum TEXT PRIMARY KEY,
            listado TEXT NOT NULL,
            firma TEXT NOT NULL,
            registro_al_elegir INTEGER NOT NULL,
            resumen TEXT NOT NULL DEFAULT '',
            usuario TEXT NOT NULL,
            fecha_utc TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS historial (
            fecha_utc TEXT NOT NULL,
            accion TEXT NOT NULL,
            cum TEXT NOT NULL,
            registro_al_elegir INTEGER,
            resumen TEXT NOT NULL DEFAULT '',
            usuario TEXT NOT NULL
        )
        """
    )
    return con


def guardar_eleccion(
    cum: str,
    listado: str,
    firma: str,
    registro: int,
    resumen: str,
    usuario: str,
    ruta: Path | None = None,
) -> EleccionRegistro:
    """Guarda (o reemplaza) la eleccion del CUM y la anota en el historial."""
    eleccion = EleccionRegistro(
        cum=cum.strip(),
        listado=listado,
        firma=firma,
        registro_al_elegir=int(registro),
        resumen=resumen,
        usuario=usuario,
        fecha_utc=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    con = _conectar(ruta or RUTA_ELECCIONES_DEFECTO)
    try:
        con.execute(
            "INSERT OR REPLACE INTO elecciones "
            "(cum, listado, firma, registro_al_elegir, resumen, usuario, fecha_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                eleccion.cum,
                eleccion.listado,
                eleccion.firma,
                eleccion.registro_al_elegir,
                eleccion.resumen,
                eleccion.usuario,
                eleccion.fecha_utc,
            ),
        )
        con.execute(
            "INSERT INTO historial (fecha_utc, accion, cum, registro_al_elegir, resumen, usuario) VALUES (?, ?, ?, ?, ?, ?)",
            (eleccion.fecha_utc, ACCION_ELEGIR, eleccion.cum, eleccion.registro_al_elegir, resumen, usuario),
        )
        con.commit()
    finally:
        con.close()
    return eleccion


def quitar_eleccion(cum: str, usuario: str, ruta: Path | None = None) -> bool:
    """Vuelve el CUM al cruce de siempre (la primera fila del listado).
    Devuelve si habia una eleccion que quitar."""
    con = _conectar(ruta or RUTA_ELECCIONES_DEFECTO)
    try:
        borradas = con.execute("DELETE FROM elecciones WHERE cum = ?", (cum.strip(),)).rowcount
        if borradas:
            con.execute(
                "INSERT INTO historial (fecha_utc, accion, cum, registro_al_elegir, resumen, usuario) VALUES (?, ?, ?, NULL, '', ?)",
                (datetime.now(UTC).isoformat(timespec="seconds"), ACCION_QUITAR, cum.strip(), usuario),
            )
        con.commit()
        return bool(borradas)
    finally:
        con.close()


def elecciones_vigentes(ruta: Path | None = None) -> dict[str, EleccionRegistro]:
    """Las elecciones guardadas, por CUM. Vacio si todavia no hay ninguna --
    sin archivo no se crea uno: leer no deja rastro en disco."""
    ruta = ruta or RUTA_ELECCIONES_DEFECTO
    if not ruta.is_file():
        return {}
    con = _conectar(ruta)
    try:
        filas = con.execute(
            "SELECT cum, listado, firma, registro_al_elegir, resumen, usuario, fecha_utc FROM elecciones"
        ).fetchall()
    finally:
        con.close()
    return {f[0]: EleccionRegistro(*f) for f in filas}


def firmas_elegidas(ruta: Path | None = None) -> dict[str, str]:
    """CUM -> firma, la forma que consume la auditoria."""
    return {cum: e.firma for cum, e in elecciones_vigentes(ruta).items()}
