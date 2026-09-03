"""Escribe y lee los snapshots que deja el worker, para que Streamlit y el
futuro backend los consuman sin recalcular ni volver a golpear Gemma
Net/INVIMA.

Patron de escritura segura: cada corrida escribe archivos Parquet con
nombre unico (marca de tiempo UTC), nunca sobrescribe uno existente, y solo
al terminar de escribir TODOS actualiza el puntero (`actual.json`) con un
rename atomico (`os.replace`, atomico tanto en Windows como en POSIX). Un
lector nunca puede ver un snapshot a medio escribir: hasta que el rename
termina, el puntero sigue senalando al snapshot anterior (bueno) o no
existe todavia (primera corrida) -- nunca a uno incompleto.

`data_runtime/` (no `data/`, que ya tiene su propio significado de "archivos
reales de INVIMA/Gemma Net que nunca se suben al repo") son artefactos
DERIVADOS y regenerables: se pueden borrar en cualquier momento y el
proximo refresco los reconstruye. Tambien va a `.gitignore`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_SNAPSHOTS_DEFECTO = RAIZ / "data_runtime" / "snapshots"
NOMBRE_PUNTERO = "actual.json"

# Cuantos juegos de snapshots viejos se conservan ademas del vigente -- para
# poder volver atras a mano si un refresco produjo datos malos, sin dejar
# crecer la carpeta sin limite (mismo criterio que ya usa el proyecto para
# el cache de Streamlit, `max_entries=3`).
SNAPSHOTS_A_CONSERVAR = 3


# Contrato de esquema: columnas que el codigo ACTUAL da por sentadas en cada
# tabla logica. Es la regla que pidio el usuario (2026-09-02): "verificar que
# no hayan colisiones con versiones pasadas".
#
# El problema real, repetido varias veces: se agrega una columna a
# `auditar_coherencia`, pero el snapshot en disco lo escribio la version
# ANTERIOR, asi que la columna no existe. Los consumidores que degradan bien
# devuelven 0 en silencio (una calidad vacia, una tarjeta en blanco) y eso se
# lee como "no hay hallazgos" cuando en realidad es "este snapshot es viejo".
# Un dato ausente y un dato en cero no son lo mismo -- regla de diseno #2.
#
# Solo se listan las columnas cuya AUSENCIA cambia una cifra de negocio; no es
# el esquema completo, que crece y cambia todo el tiempo.
COLUMNAS_ESPERADAS: dict[str, tuple[str, ...]] = {
    "auditoria": (
        "ESTADO_COHERENCIA",
        "ESTADO_LISTADO_INVIMA",
        "ESTADO_CUM_INVIMA",
        "TIPO_CODIGO_INTERNO",
        "FECHA_ACTIVO_INVIMA",
        "FECHA_VENCIMIENTO_INVIMA",
        "COHERENCIA_FECHAS_INVIMA",
        "VIGENCIA_NO_CONFIRMABLE",
    ),
    "invima_listados": ("CODIGO_INTERNO", "LISTADO"),
}


def desfases_de_esquema(carpeta: Path | None = None) -> dict[str, list[str]]:
    """Que columnas espera el codigo de hoy y NO trae el snapshot vigente.

    Vacio = el snapshot esta al dia. Con contenido = lo genero una version
    anterior y hay cifras que van a salir mal (en cero, no vacias). La cura es
    correr un refresco; esto solo sirve para no confundir "viejo" con "limpio".
    """
    desfases: dict[str, list[str]] = {}
    for tabla, columnas in COLUMNAS_ESPERADAS.items():
        df = leer_tabla(tabla, carpeta)
        if df is None:
            continue
        faltantes = [c for c in columnas if c not in df.columns]
        if faltantes:
            desfases[tabla] = faltantes
    return desfases


@dataclass(frozen=True)
class Snapshot:
    """Metadata del snapshot vigente: cuando se genero y que archivo
    Parquet corresponde a cada tabla logica (ej. "auditoria", "candidatos")."""

    nombre: str
    generado_utc: str
    tablas: dict[str, str]


def _marca_de_tiempo() -> str:
    # Microsegundos (%f), no solo segundos: dos escrituras dentro del mismo
    # segundo (dos refrescos manuales seguidos, o un reintento) colisionaban
    # en el mismo nombre de archivo y una pisaba la otra en silencio --
    # descubierto por la prueba de poda de snapshots viejos. Sin separador
    # dentro de la marca (nada de "_"): _podar_snapshots_viejos() corta por
    # el ULTIMO "_" del nombre de archivo para recuperarla entera.
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def escribir_snapshot(
    tablas: dict[str, pd.DataFrame], carpeta: Path | None = None
) -> Snapshot:
    """Escribe cada DataFrame de `tablas` (clave = nombre logico, ej.
    "auditoria") como un `.parquet` con nombre unico, y solo AL FINAL
    actualiza el puntero. Si algo revienta a mitad de camino (disco lleno,
    proceso matado), el puntero sigue senalando al snapshot anterior --
    nunca a uno a medio escribir."""
    carpeta = carpeta or CARPETA_SNAPSHOTS_DEFECTO
    carpeta.mkdir(parents=True, exist_ok=True)
    marca = _marca_de_tiempo()

    archivos: dict[str, str] = {}
    for nombre_logico, df in tablas.items():
        nombre_archivo = f"{nombre_logico}_{marca}.parquet"
        # `pipeline.py` deja advertencias en `df.attrs` (ver
        # resultado.attrs["advertencias"] en pipeline.py). to_parquet
        # intenta volcar attrs como metadata JSON del archivo, y revienta
        # si algo ahi adentro no es serializable (ej. un pd.Series) --
        # descubierto corriendo esto contra datos reales. Los snapshots son
        # solo la tabla; las advertencias son un problema de la corrida,
        # no del dato guardado, asi que se excluyen de la escritura sin
        # perderlas para quien siga usando el DataFrame en memoria.
        attrs_originales = dict(df.attrs)
        df.attrs.clear()
        try:
            df.to_parquet(carpeta / nombre_archivo, index=False)
        finally:
            df.attrs.update(attrs_originales)
        archivos[nombre_logico] = nombre_archivo

    snapshot = Snapshot(nombre=marca, generado_utc=marca, tablas=archivos)
    _actualizar_puntero(snapshot, carpeta)
    _podar_snapshots_viejos(carpeta, conservar=SNAPSHOTS_A_CONSERVAR)
    return snapshot


def _actualizar_puntero(snapshot: Snapshot, carpeta: Path) -> None:
    contenido = json.dumps(
        {
            "nombre": snapshot.nombre,
            "generado_utc": snapshot.generado_utc,
            "tablas": snapshot.tablas,
        },
        ensure_ascii=False,
    )
    ruta_final = carpeta / NOMBRE_PUNTERO
    # Nombre temporal unico por proceso: dos corridas del worker no deberian
    # solaparse nunca (ver refresco.py, max_instances=1), pero si alguna vez
    # pasara, no queremos que se pisen el archivo temporal entre si.
    ruta_temporal = carpeta / f".{NOMBRE_PUNTERO}.{os.getpid()}.tmp"
    ruta_temporal.write_text(contenido, encoding="utf-8")
    os.replace(ruta_temporal, ruta_final)


def snapshot_actual(carpeta: Path | None = None) -> Snapshot | None:
    """El snapshot vigente, o `None` si el worker todavia no genero ninguno.

    Degradacion explicita: quien llama decide que hacer con un `None`
    (avisar que no hay datos todavia, calcular en caliente como respaldo,
    etc.) -- esta funcion nunca inventa un snapshot vacio ni asume que "no
    hay" significa "esta vacio pero es valido"."""
    carpeta = carpeta or CARPETA_SNAPSHOTS_DEFECTO
    ruta_puntero = carpeta / NOMBRE_PUNTERO
    if not ruta_puntero.is_file():
        return None
    datos = json.loads(ruta_puntero.read_text(encoding="utf-8"))
    return Snapshot(nombre=datos["nombre"], generado_utc=datos["generado_utc"], tablas=datos["tablas"])


# Cache de tablas ya leidas -- cada router de backend/app/routers/ llama
# leer_tabla() por su cuenta en cada request, y sin esto cada uno releia el
# Parquet completo del disco cada vez (en auditoria, ~200.000 filas / 535 MB
# en memoria) -- mismo cuello de botella ya corregido una vez en Streamlit
# (commit "cache sin limite") reaparecido aca porque el backend no existia
# todavia en ese momento. Los Parquet de un snapshot son inmutables una vez
# escritos, asi que cachear es seguro: una entrada por (carpeta,
# nombre_logico), y al llegar un snapshot nuevo la marca de tiempo no calza
# mas y la entrada se reemplaza sola -- nunca crece sin limite, acotado por
# la cantidad de tablas logicas distintas que existan (hoy 7).
#
# El DataFrame que devuelve esta funcion queda COMPARTIDO entre requests:
# ningun llamador debe mutarlo in place (filtros booleanos, .copy() explicito
# antes de modificar, etc. -- todos los routers actuales ya lo hacen asi).
_CACHE_TABLAS: dict[tuple[str, str], tuple[str, pd.DataFrame]] = {}


def leer_tabla(nombre_logico: str, carpeta: Path | None = None) -> pd.DataFrame | None:
    """El DataFrame de `nombre_logico` (ej. "auditoria") del snapshot
    vigente, o `None` si no hay snapshot todavia o esa tabla no esta en el
    (mismo criterio de degradacion explicita que `snapshot_actual`)."""
    carpeta = carpeta or CARPETA_SNAPSHOTS_DEFECTO
    actual = snapshot_actual(carpeta)
    if actual is None or nombre_logico not in actual.tablas:
        return None
    clave = (str(carpeta), nombre_logico)
    en_cache = _CACHE_TABLAS.get(clave)
    if en_cache is not None and en_cache[0] == actual.nombre:
        return en_cache[1]
    ruta = carpeta / actual.tablas[nombre_logico]
    if not ruta.is_file():
        return None
    df = pd.read_parquet(ruta)
    _CACHE_TABLAS[clave] = (actual.nombre, df)
    return df


def _podar_snapshots_viejos(carpeta: Path, *, conservar: int) -> None:
    """Conserva solo los ultimos `conservar` juegos de archivos Parquet,
    identificados por su marca de tiempo en el nombre (`{tabla}_{marca}.parquet`).
    Nunca toca `actual.json` -- eso ya se actualizo antes de podar, asi que
    el snapshot vigente esta garantizado entre los que se conservan."""
    marcas = sorted(
        {p.stem.rsplit("_", 1)[-1] for p in carpeta.glob("*.parquet")}, reverse=True
    )
    for marca_vieja in marcas[conservar:]:
        for archivo_viejo in carpeta.glob(f"*_{marca_vieja}.parquet"):
            archivo_viejo.unlink(missing_ok=True)
