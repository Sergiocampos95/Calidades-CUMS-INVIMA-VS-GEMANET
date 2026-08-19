"""Lector de ListadoCodigoUnicoVigentes*.xlsx (catalogo maestro INVIMA).

Estructura confirmada por diagnostico directo del archivo (corte 16-dic-2022):
hoja unica "Vigente", encabezados en fila 7, 101.183 filas de datos, 29 columnas
(A:AC). Hallazgos que dirigen este modulo:

- EXPEDIENTE no es llave unica (101.183 filas, solo 6.806 expedientes
  distintos: explota por TIPO_ROL FABRICANTE/IMPORTADOR y MODALIDAD).
- EXPEDIENTE+CONSECUTIVO tampoco es unico por la misma razon (44.526
  combinaciones, 56.657 duplicados). Para pruebas de pertenencia (ver
  `universo_codigos_internos`) esto no requiere tiebreak: un set colapsa los
  duplicados sin perder informacion. Solo haria falta escoger una fila
  representativa si se necesita leer un campo (principio activo, ATC) por
  codigo -- y ahi la mayoria de los "duplicados" (57%, verificado contra el
  archivo real) son en realidad medicamentos combinados con una fila por
  principio activo, no fabricantes en competencia: no deben colapsarse a una
  sola fila, se agregan.
- ESTADO_REGISTRO (Vigente/Vencido a nivel de registro sanitario) y
  ESTADO_CUM (Activo/Inactivo a nivel de presentacion comercial) son campos
  distintos: 19.542 filas tienen registro Vigente pero CUM Inactivo. No se
  colapsan en un solo booleano.
- IUM solo cubre ~9,3% de las filas: no es llave alterna universal.

`leer_catalogo_invima_vencidos` (agregada 2026-08-19, pedido explicito del
usuario para poder validar vencidos sin depender de la API durante el
outage), `leer_catalogo_invima_renovacion` y `leer_catalogo_invima_otros_
estados` (agregadas el mismo dia, mismo motivo -- casos reales del usuario:
un codigo solo encontrado en "Tramite de Renovacion", y un archivo de
"Otros Estados" ya descargado): mismo formato de 29 columnas, confirmado
por la metadata real de Socrata para los 3 datasets (`vwwf-4ftk`,
`vgr4-gemg`, `spzp-dfuc` -- ver ingesta/invima_socrata.py).

Los 4 datasets (Vigentes, Vencidos, Renovacion, Otros Estados) ya estan
reconfirmados contra archivos reales del usuario (2026-08-19):
- Otros Estados (`ListadoCodigounicoOtrosEstado2022.xlsx`, 77.760 filas):
  hoja `"Otros Estados"` (coincide con el primer candidato), encabezado en
  fila 7. ESTADO_REGISTRO trae 10 valores reales distintos (Perdida
  Fuerza Ejec, Negado, Cancelado, Temp. no comerc - Vigente, Temp. no
  comercializado - En Tramite Renov, Desistido, Abandono, Suspendido, No
  Aplica Registro, Revocado) -- confirma que es genuinamente heterogeneo,
  tal como se diseño (ver ESTADO_INVIMA_DETALLE en auditoria/coherencia_
  invima.py).
- Vencidos (`ListadoCodigoUnicoVencidos2022.xlsx`, 149.224 filas): hoja
  `"Vencidos"` (coincide con el segundo candidato).
- Renovacion (`ListadoCodigoUnicoRenovacion2022.xlsx`, 57.724 filas): hoja
  `"En tramite"` -- **no** coincidia con ningun candidato original ni con
  el fragmento de busqueda "renov", solo funciono por el fallback de hoja
  unica del libro. Se agrego "En tramite" a HOJAS_CATALOGO_RENOVACION como
  candidato exacto explicito para ser robusto si un futuro archivo de
  Renovacion trae mas de una hoja.
- Vigentes (`ListadoCodigoUnicoVigentes2022.xlsx` de Descargas, 101.183
  filas): confirma el hallazgo original. **Bug real encontrado en
  produccion el mismo dia:** `leer_catalogo_invima` tenia el nombre de
  hoja hardcoded (`sheet_name="Vigente"`, sin tolerancia) a diferencia de
  los otros 3 lectores -- fallo real del usuario: "Worksheet named
  'Vigente' not found" al procesar un archivo Vigentes real cuya hoja
  tenia otro nombre. Ahora usa la misma cascada de tolerancia
  (`_resolver_hoja_auxiliar`, candidatos `HOJAS_CATALOGO_VIGENTES`) que
  los demas -- los 4 lectores son consistentes.

FILA_ENCABEZADO/RANGO_COLUMNAS confirmados correctos sin cambios para los
4. La unica tolerancia que sigue sin verificar contra un caso real es el
propio encabezado/rango de columnas si INVIMA cambia el formato del
archivo -- eso lanzaria un KeyError/columna faltante mas adelante en el
pipeline, no un error silencioso.

Con 3 datasets de la misma forma se cumple la "regla de tres" que el
lector de Vencidos habia dejado pendiente: `_resolver_hoja_vencidos` se
generalizo a `_resolver_hoja_auxiliar` (parametrizada por candidatos de
hoja/fragmento de busqueda/nombre de dataset), y las 3 funciones publicas
son wrappers delgados sobre `_leer_catalogo_invima_auxiliar`. Ninguna
filtra por ESTADO_CUM/TIPO_ROL (eso es logica de negocio de Vigentes) ni
aplica `catalogo_activo_fabricante` -- solo entregan el catalogo
normalizado tal cual, con `ESTADO_REGISTRO` intacto para que la auditoria
pueda mostrar el valor real encontrado (p.ej. "Inactivo"), no solo el
nombre del dataset.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from gemma_cum_loader.normaliza.texto import normalizar_encabezado

FILA_ENCABEZADO = 6  # 0-indexed -> fila 7 de Excel
RANGO_COLUMNAS = "A:AC"

# Candidatos de nombre de hoja para cada archivo -- confirmado con archivos
# reales del usuario (2026-08-19) que el nombre exacto de hoja SI varia
# entre descargas, incluso para Vigentes (antes hardcoded a "Vigente" sin
# tolerancia -- error real en produccion: "Worksheet named 'Vigente' not
# found" con un archivo Vigentes real cuya hoja tenia otro nombre). Todos
# se prueban como coincidencia exacta antes de caer al resto de la cascada
# de tolerancia (ver _resolver_hoja_auxiliar). Confirmado contra archivos
# reales del usuario: Vencidos real trae hoja "Vencidos" (coincide),
# Renovacion real trae hoja "En tramite" (NO coincide con ningun candidato
# ni con el fragmento "renov" -- cae al fallback de hoja unica, que si
# funciona porque esos archivos solo traen 1 hoja).
HOJAS_CATALOGO_VIGENTES = ["Vigente", "Vigentes"]
HOJAS_CATALOGO_VENCIDOS = ["Vencido", "Vencidos"]
HOJAS_CATALOGO_RENOVACION = ["Tramite de Renovacion", "Renovacion", "Renovaciones", "En tramite"]
HOJAS_CATALOGO_OTROS_ESTADOS = ["Otros Estados", "Otro Estado"]


def _normalizar_catalogo_invima(df: pd.DataFrame) -> pd.DataFrame:
    """Normalizacion compartida entre Vigentes y Vencidos: encabezados,
    EXPEDIENTE/CONSECUTIVO a entero nullable, armado de CODIGO_INTERNO.
    `df` ya debe venir de `pd.read_excel(...)` con la hoja/encabezado/rango
    de columnas correctos -- esta funcion no sabe de donde vino.
    """
    df = df.copy()
    df.columns = [normalizar_encabezado(c) for c in df.columns]

    if "EXPEDIENTE" in df.columns:
        df["EXPEDIENTE"] = pd.to_numeric(df["EXPEDIENTE"], errors="coerce").astype("Int64")
    if "CONSECUTIVO" in df.columns:
        df["CONSECUTIVO"] = pd.to_numeric(df["CONSECUTIVO"], errors="coerce").astype("Int64")
    if "COD_MEDICAMENTO_INVIMA" in df.columns:
        df["CODIGO_INTERNO"] = df["COD_MEDICAMENTO_INVIMA"].astype(str)
    elif {"EXPEDIENTE", "CONSECUTIVO"}.issubset(df.columns):
        df["CODIGO_INTERNO"] = df["EXPEDIENTE"].astype(str) + "-" + df["CONSECUTIVO"].astype(str)

    return df


def leer_catalogo_invima(archivo: str | Path | Any) -> pd.DataFrame:
    """Lee el catalogo crudo, sin deduplicar ni filtrar.

    `archivo`: ruta o un objeto tipo-archivo (ej. UploadedFile de Streamlit).
    Si trae `.seek`, se rebobina primero -- Streamlit puede reusar el mismo
    objeto entre reruns con el cursor ya al final de una lectura previa.

    Usar junto con `catalogo_activo_fabricante` para obtener el universo
    cruzable 1:1. Los nombres de columna se normalizan (mayusculas, sin
    tildes, espacios -> guion bajo) porque el encabezado exacto del archivo
    no fue verificado de forma independiente, solo documentado en el
    diagnostico previo.
    """
    if hasattr(archivo, "seek"):
        archivo.seek(0)

    libro = pd.ExcelFile(archivo)
    hoja = _resolver_hoja_auxiliar(libro.sheet_names, HOJAS_CATALOGO_VIGENTES, "vigen", "Vigentes")
    df = pd.read_excel(
        libro,
        sheet_name=hoja,
        header=FILA_ENCABEZADO,
        usecols=RANGO_COLUMNAS,
    )
    return _normalizar_catalogo_invima(df)


def _resolver_hoja_auxiliar(
    hojas_disponibles: list[str],
    candidatos_exactos: list[str],
    fragmento_busqueda: str,
    nombre_dataset: str,
) -> str:
    """Misma cascada de tolerancia que `armado/reglas_negocio.py::
    _resolver_hoja_malla` (probado contra archivos reales para ese caso),
    generalizada aca porque ya son 3 datasets auxiliares (Vencidos,
    Renovacion, Otros Estados) sin archivo real para confirmar el nombre
    exacto de su hoja -- se cumple la regla de tres que el lector de
    Vencidos habia dejado pendiente. Cascada: (1) coincidencia exacta
    contra `candidatos_exactos`, (2) unica hoja que contenga
    `fragmento_busqueda`, (3) unica hoja en todo el libro, (4) error claro
    listando lo encontrado.
    """
    for candidato in candidatos_exactos:
        if candidato in hojas_disponibles:
            return candidato
    candidatas = [h for h in hojas_disponibles if fragmento_busqueda in h.lower()]
    if len(candidatas) == 1:
        return candidatas[0]
    if len(hojas_disponibles) == 1:
        return hojas_disponibles[0]
    raise ValueError(
        f"No se encontro una hoja de datos reconocible en el archivo de "
        f"{nombre_dataset} (se esperaba '{candidatos_exactos[0]}'"
        + (f" o '{candidatos_exactos[1]}'" if len(candidatos_exactos) > 1 else "")
        + f"). Hojas encontradas: {hojas_disponibles}. Sube la hoja que trae "
        "EXPEDIENTE, PRODUCTO, TITULAR, REGISTRO SANITARIO, etc., o "
        f"renombrala a '{candidatos_exactos[0]}'."
    )


def _leer_catalogo_invima_auxiliar(
    archivo: str | Path | Any,
    candidatos_hoja: list[str],
    fragmento_busqueda: str,
    nombre_dataset: str,
) -> pd.DataFrame:
    """Nucleo compartido por `leer_catalogo_invima_vencidos`,
    `leer_catalogo_invima_renovacion` y `leer_catalogo_invima_otros_
    estados` -- mismo formato de 29 columnas que Vigentes (confirmado por
    metadata real de Socrata para los 3 datasets), pero sin un archivo real
    descargado para confirmar el nombre de hoja o la posicion exacta del
    encabezado en ninguno -- ver docstring del modulo. No filtra por
    ESTADO_CUM/TIPO_ROL (eso es logica de negocio de Vigentes); conserva
    ESTADO_REGISTRO intacto para que la auditoria pueda mostrarlo.
    """
    if hasattr(archivo, "seek"):
        archivo.seek(0)

    libro = pd.ExcelFile(archivo)
    hoja = _resolver_hoja_auxiliar(libro.sheet_names, candidatos_hoja, fragmento_busqueda, nombre_dataset)
    df = pd.read_excel(
        libro,
        sheet_name=hoja,
        header=FILA_ENCABEZADO,
        usecols=RANGO_COLUMNAS,
    )
    return _normalizar_catalogo_invima(df)


def leer_catalogo_invima_vencidos(archivo: str | Path | Any) -> pd.DataFrame:
    """Lee el catalogo oficial de Vencidos (respaldo manual, sin API) --
    ver `_leer_catalogo_invima_auxiliar`."""
    return _leer_catalogo_invima_auxiliar(archivo, HOJAS_CATALOGO_VENCIDOS, "venc", "Vencidos")


def leer_catalogo_invima_renovacion(archivo: str | Path | Any) -> pd.DataFrame:
    """Lee el catalogo oficial de Tramite de Renovacion (respaldo manual,
    sin API) -- ver `_leer_catalogo_invima_auxiliar`."""
    return _leer_catalogo_invima_auxiliar(archivo, HOJAS_CATALOGO_RENOVACION, "renov", "Tramite de Renovacion")


def leer_catalogo_invima_otros_estados(archivo: str | Path | Any) -> pd.DataFrame:
    """Lee el catalogo oficial de Otros Estados (respaldo manual, sin API)
    -- ver `_leer_catalogo_invima_auxiliar`. A diferencia de Vencidos/
    Renovacion, este dataset es heterogeneo por naturaleza (agrupa
    Cancelado/Suspendido/Inactivo/etc. bajo un solo dataset) -- por eso es
    especialmente importante que ESTADO_REGISTRO sobreviva intacto, la
    auditoria lo usa para mostrar el valor real en vez de una etiqueta
    generica."""
    return _leer_catalogo_invima_auxiliar(archivo, HOJAS_CATALOGO_OTROS_ESTADOS, "otro", "Otros Estados")


def catalogo_activo_fabricante(df: pd.DataFrame) -> pd.DataFrame:
    """Universo desduplicado 1:1 por CODIGO_INTERNO.

    Filtra ESTADO_CUM=Activo y TIPO_ROL=FABRICANTE. Puede quedar un residual
    de duplicados cuando un mismo producto tiene mas de un fabricante -> eso
    es una decision de negocio pendiente (tiebreak), no se resuelve aqui.
    """
    return df[
        df["ESTADO_CUM"].astype(str).str.upper().eq("ACTIVO")
        & df["TIPO_ROL"].astype(str).str.upper().eq("FABRICANTE")
    ]


def mapa_ium(df: pd.DataFrame) -> pd.DataFrame:
    """Subconjunto con IUM no vacio (~9% del catalogo) - uso exclusivo de flujo_ium."""
    if "IUM" not in df.columns:
        return df.iloc[0:0]
    return df[df["IUM"].notna() & (df["IUM"].astype(str).str.strip() != "")]


def universo_codigos_internos(df: pd.DataFrame) -> set[str]:
    """Set de CODIGO_INTERNO para pruebas de pertenencia (ej. filtro_cruce_invima).

    No requiere desduplicar por fabricante. El universo activo+fabricante
    todavia tiene duplicados por CODIGO_INTERNO despues de filtrar (verificado
    contra el archivo real): 13.009 codigos con mas de una fila. De esos, 57%
    son medicamentos combinados (una fila por principio activo, mismo
    fabricante) y no deben colapsarse a una sola fila -- perderian un
    principio activo. Solo 24% son fabricante duplicado real (mismo producto,
    mismo principio activo, distinto fabricante), donde escoger una fila si
    seria inofensivo. Para una prueba de pertenencia esta distincion no
    importa: el set colapsa ambos casos sin perder informacion porque no se
    lee ningun otro campo de la fila.
    """
    return set(df["CODIGO_INTERNO"].dropna())
