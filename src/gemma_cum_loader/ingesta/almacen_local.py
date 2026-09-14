"""La carpeta `data/` como almacen: descubrir lo que ya esta y descargar lo que falta.

Objetivo (pedido explicito del usuario, 2026-08-20): que la Estructura de
Cargue sea el UNICO archivo que alguien sube a mano. Gemma Net se lee de su
base, y los listados de INVIMA se descargan, se organizan aqui y se
diligencian solos en la siguiente corrida.

Por que `data/`: ya existe, ya esta en .gitignore, y los lectores del
proyecto (`leer_catalogo_invima`, `leer_reporte_gemanet`) aceptan una ruta
igual que un archivo subido por Streamlit -- no hay que tocar nada de la
lectura para que esto funcione.

El descubrimiento es por PATRON de nombre y no por nombre exacto porque los
archivos reales llegan con nombres que nadie controla
("ListadoCodigoUnicoVigentes2022.xlsx", "LISTADO_MEDICAMENTOS12082026.xlsx").
Entre varios candidatos gana el mas reciente por fecha de modificacion.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import uuid4

import pandas as pd

RAIZ = Path(__file__).resolve().parents[3]
VARIABLE_CARPETA = "INVIMA_LISTADOS_DIR"


def carpeta_datos() -> Path:
    """La carpeta del servidor donde operaciones deja los 4 listados de INVIMA
    (y donde el worker busca ademas el export de Gemma Net y la malla).

    Hasta el 2026-09-14 era `data/` dentro del repo -- limitacion asumida
    mientras cada analista corria la app en su maquina. En produccion la app
    corre como servicio en Linux y la usan otras areas, asi que la carpeta la
    elige operaciones con `INVIMA_LISTADOS_DIR`; sin la variable se usa
    `~/gemanet/invima`, que existe sin permisos especiales. Se lee en cada
    llamada (no al importar) para que las pruebas puedan cambiarla sin
    recargar el modulo. Es el UNICO punto que sabe de donde salen los
    archivos: el resto del flujo solo recibe rutas.
    """
    configurada = os.environ.get(VARIABLE_CARPETA, "").strip()
    return Path(configurada) if configurada else Path.home() / "gemanet" / "invima"


# Un tipo logico -> los patrones que lo reconocen, en orden de preferencia.
# Los .parquet van primero: son las descargas que hace esta aplicacion, ya
# normalizadas, y cargan mucho mas rapido que releer un Excel de 12 MB.
PATRONES: dict[str, tuple[str, ...]] = {
    "invima_vigentes": ("invima_vigentes_*.parquet", "*vigente*.xlsx"),
    "invima_vencidos": ("invima_vencidos_*.parquet", "*vencid*.xlsx"),
    "invima_otros_estados": ("invima_otros_estados_*.parquet", "*otro*estado*.xlsx"),
    "invima_renovacion": ("invima_renovacion_*.parquet", "*renovacio*.xlsx", "*renovación*.xlsx"),
    "estructura_cargue": ("*structura*argue*.xlsx",),
    "reporte_gemanet": ("*LISTADO_MEDICAMENTOS*.xlsx", "*reporte*gemanet*.xlsx"),
}

# Palabras que DESCALIFICAN a un archivo para un tipo, aunque calce el patron.
# Los 4 listados de INVIMA se llaman casi igual ("ListadoCodigoUnicoVigentes",
# "ListadoCodigounicoOtrosEstado"...) y en Windows el glob ignora mayusculas.
# Caso real (2026-08-20): un patron generico "*ListadoCodigoUnico*" hacia que
# el listado de Otros Estados -- mas reciente -- se eligiera como Vigentes.
# Eso produce "0 filas vigentes despues de depurar", un fallo que aparece
# mucho despues y cuya causa no es obvia. Mejor no proponer nada que proponer
# el archivo equivocado.
EXCLUSIONES: dict[str, tuple[str, ...]] = {
    "invima_vigentes": ("vencid", "otroestado", "otrosestado", "renovacio"),
    "invima_vencidos": ("vigente", "otroestado", "otrosestado", "renovacio"),
    "invima_otros_estados": ("vencid", "renovacio"),
    "invima_renovacion": ("vencid", "otroestado", "otrosestado"),
}

# Nombres que esta aplicacion GENERA como salida. Nunca deben confundirse con
# una entrada: `reporte_cruce_invima.xlsx` contiene el resultado de una corrida
# anterior y tomarlo por un catalogo de INVIMA seria un desastre silencioso.
PREFIJOS_DE_SALIDA = ("reporte_", "auditoria_", "cargue_", "scratch_", "Vigente_", "Hallazgos_")

# Excel deja un archivo de bloqueo "~$nombre.xlsx" mientras el documento esta
# abierto. Calza con cualquier patron y ademas es SIEMPRE el mas reciente, asi
# que sin esto el descubrimiento elegiria un archivo de bloqueo de 1 KB en vez
# del archivo real. Caso visto en produccion: la carpeta de Descargas del
# usuario tenia seis de estos.
PREFIJO_BLOQUEO_EXCEL = "~$"


@dataclass(frozen=True)
class ArchivoDescubierto:
    tipo: str
    ruta: Path
    tamano_mb: float
    modificado: date

    @property
    def nombre(self) -> str:
        return self.ruta.name


@dataclass(frozen=True)
class ResultadoSincronizacion:
    ok: bool
    filas: int
    ruta: Path | None
    mensaje: str


def _ignorable(ruta: Path) -> bool:
    return ruta.name.startswith(PREFIJOS_DE_SALIDA) or ruta.name.startswith(PREFIJO_BLOQUEO_EXCEL)


def descubrir(
    tipo: str,
    carpeta: Path | None = None,
    validador: Callable[[Path], bool] | None = None,
    extensiones: tuple[str, ...] | None = None,
) -> ArchivoDescubierto | None:
    """El archivo mas reciente de ese tipo que ademas sirva, o None.

    `validador` existe porque "el mas reciente" no basta. Caso real
    (2026-08-20): la carpeta tenia dos Estructura Cargue y la MAS NUEVA no
    traia la hoja `plantilla (2)` que el codigo necesita -- elegirla habria
    roto la corrida con un error a mitad de camino. Cuando hay forma de
    comprobar que un archivo sirve, se comprueba antes de proponerlo.

    `extensiones` restringe a ciertos sufijos (ej. `(".xlsx",)`). Lo necesita
    el refresco "desde archivos" (ver `fuente_invima.py`): `PATRONES` mezcla a
    proposito los Excel que baja una persona con los `*.parquet` que el propio
    sistema cachea tras cada lectura exitosa de Socrata, y "el mas reciente"
    entre los dos es casi siempre el parquet de la API -- justo lo que ese
    refresco NO quiere. Filtrar aca y no en el llamador mantiene las
    EXCLUSIONES (los 4 listados se llaman casi igual) en un solo lugar.
    """
    base = carpeta if carpeta is not None else carpeta_datos()
    if not base.is_dir():
        return None

    excluidas = EXCLUSIONES.get(tipo, ())
    candidatos: list[Path] = []
    # fnmatchcase sobre el nombre en minusculas, no `base.glob(patron)`: glob
    # respeta mayusculas en Linux, y los patrones ("*vigente*.xlsx") estan en
    # minusculas mientras INVIMA nombra los archivos "ListadoCodigoUnicoVigentes
    # ...". En Windows daba igual; al correr el worker en Linux (2026-09-14) el
    # refresco moria en "Leyendo INVIMA -- Vigentes" con los 4 archivos en
    # `data/`, y 7 pruebas de descubrimiento fallaban por lo mismo.
    entradas = [p for p in base.iterdir() if p.is_file()]
    for patron in PATRONES.get(tipo, ()):
        for p in entradas:
            if not fnmatch.fnmatchcase(p.name.lower(), patron.lower()) or _ignorable(p):
                continue
            if extensiones is not None and p.suffix.lower() not in extensiones:
                continue
            # Sin espacios ni guiones: los nombres reales varian entre
            # "Otros Estado", "OtrosEstado" y "otros_estado".
            plano = "".join(c for c in p.name.lower() if c.isalnum())
            if any(palabra in plano for palabra in excluidas):
                continue
            candidatos.append(p)
    if validador is not None:
        candidatos = [p for p in candidatos if validador(p)]
    if not candidatos:
        return None

    # Sin duplicados y mas reciente primero: un mismo archivo puede calzar en
    # dos patrones del mismo tipo.
    mejor = max(dict.fromkeys(candidatos), key=lambda p: p.stat().st_mtime)
    st = mejor.stat()
    return ArchivoDescubierto(
        tipo=tipo,
        ruta=mejor,
        tamano_mb=round(st.st_size / 1048576, 2),
        modificado=date.fromtimestamp(st.st_mtime),
    )


def tiene_hoja(ruta: Path, hoja: str) -> bool:
    """Si el Excel trae esa hoja. Abre solo el indice, no los datos."""
    try:
        import openpyxl

        wb = openpyxl.load_workbook(ruta, read_only=True)
        try:
            return hoja in wb.sheetnames
        finally:
            wb.close()
    except Exception:
        # Un archivo que no se puede abrir tampoco sirve -- no proponerlo es
        # la respuesta correcta, y el error real aparecera si el usuario lo
        # elige a mano.
        return False


# Validadores por tipo: solo donde hay algo real que comprobar. La Estructura
# de Cargue necesita `plantilla (2)` (la copia de trabajo del SOP); sin ella
# `derivar_reglas_negocio` falla a mitad de corrida.
VALIDADORES: dict[str, Callable[[Path], bool]] = {
    "estructura_cargue": lambda p: tiene_hoja(p, "plantilla (2)"),
}


def descubrir_todo(carpeta: Path | None = None) -> dict[str, ArchivoDescubierto]:
    hallazgos = {
        tipo: descubrir(tipo, carpeta, VALIDADORES.get(tipo)) for tipo in PATRONES
    }
    return {tipo: a for tipo, a in hallazgos.items() if a is not None}


def guardar_descarga(
    df: pd.DataFrame, tipo: str, carpeta: Path | None = None, fecha: date | None = None
) -> ResultadoSincronizacion:
    """Guarda un catalogo descargado como parquet fechado en `data/`.

    Se NIEGA a guardar un DataFrame vacio. Caso real: el dataset de Vigentes
    de INVIMA (i7cb-raxc) estuvo devolviendo cero filas el 2026-08-20 --
    sobrescribir un archivo bueno con uno vacio dejaria al equipo sin catalogo
    y sin forma de saber por que. Un vacio es un resultado valido de la API,
    pero no es algo que valga la pena guardar.
    """
    if df.empty:
        return ResultadoSincronizacion(
            ok=False,
            filas=0,
            ruta=None,
            mensaje=(
                "La descarga vino sin filas, asi que no se guardo nada. El archivo local "
                "anterior (si existe) queda intacto."
            ),
        )

    base = carpeta if carpeta is not None else carpeta_datos()
    base.mkdir(parents=True, exist_ok=True)
    ruta = base / f"{tipo}_{(fecha or date.today()).strftime('%Y%m%d')}.parquet"

    # Todo a texto antes de parquet: los catalogos traen columnas con tipos
    # mezclados (numeros y texto en la misma columna) y pyarrow las rechaza.
    # Hallazgo real: to_parquet reventaba con "Could not convert ... with type
    # str: tried to convert to int64".
    # Escribir directo sobre el snapshot hace que otra corrida pueda leer un
    # parquet a medio escribir. El archivo temporal queda en el mismo volumen
    # para que `replace()` sea atomico en Windows.
    ruta_temporal = ruta.with_name(f".{ruta.name}.{uuid4().hex}.tmp")
    try:
        df.astype(str).to_parquet(ruta_temporal, index=False)
        ruta_temporal.replace(ruta)
    finally:
        ruta_temporal.unlink(missing_ok=True)
    return ResultadoSincronizacion(
        ok=True,
        filas=len(df),
        ruta=ruta,
        mensaje=f"{len(df):,} filas guardadas en {ruta.name}",
    )


def leer_descarga(ruta: Path) -> pd.DataFrame:
    """Lee un parquet generado por `guardar_descarga`."""
    return pd.read_parquet(ruta)


def guardar_subida(archivo, nombre: str, carpeta: Path | None = None) -> Path | None:
    """Deja una copia de un archivo subido para que la proxima corrida lo
    encuentre sola. Devuelve la ruta guardada, o None si no se pudo.

    Por que una copia y no "recordar la ruta original": el navegador NUNCA le
    da al servidor la ruta real del archivo que el usuario eligio -- la oculta
    a proposito por seguridad. Guardar la ruta es imposible; guardar el
    contenido logra lo mismo que se buscaba (subir una vez y olvidarse) y
    ademas no se rompe si el usuario mueve o renombra el original.

    `carpeta` por defecto es `carpeta_datos()`, que sirve cuando cada analista corre la
    aplicacion en su maquina. Si algun dia se sirve al equipo, este es el
    unico punto que hay que volver por usuario -- el resto del flujo no se
    entera de donde salio el archivo.
    """
    base = carpeta if carpeta is not None else carpeta_datos()
    try:
        base.mkdir(parents=True, exist_ok=True)
        destino = base / nombre
        datos = archivo.getvalue() if hasattr(archivo, "getvalue") else archivo.read()
        if not datos:
            return None
        destino.write_bytes(datos)
        return destino
    except OSError:
        # Guardar es una comodidad: si el disco no deja, la corrida sigue con
        # el archivo en memoria y solo se pierde el automatismo.
        return None
