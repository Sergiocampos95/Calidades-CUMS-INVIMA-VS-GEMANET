"""Deteccion del tipo de codigo interno.

`es_cum()` es el predicado estricto EXPEDIENTE-CONSECUTIVO del que depende
el resto del sistema (cascada de resolucion, cruce contra INVIMA) -- no se
toca nunca, ni siquiera al ampliar `clasificar_codigo()`. Ver su docstring
para el motivo historico.

`clasificar_codigo()`/`clasificar_codigos()` van mas alla: catalogan que hay
REALMENTE dentro del catch-all que antes se llamaba "ium" a secas.
Investigado contra produccion real el 2026-08-26 (199.611 filas de
`administrativo.tb_medicamento`) -- ver `design/tipos_codigo_interno.md`
para el detalle completo, los conteos medidos y por que el orden de estos
patrones importa. Es informativo: ninguna de estas categorias cambia una
decision de negocio existente (candidato/cuarentena/ya_existe), y ninguna
puede usarse para fusionar CODIGO_INTERNO duplicados -- la familia
`atc_expediente_consecutivo` tiene 90% de gemelo CUM duplicado en la misma
tabla y es exactamente el caso que el proyecto prohibe fusionar a ciegas.
"""

from __future__ import annotations

import re
from typing import Literal

import numpy as np
import pandas as pd

_PATRON_CUM = re.compile(r"^\d+-\d+$")

CodigoTipo = Literal[
    "cum",
    "cum_con_sufijo_atc",
    "atc_expediente_consecutivo",
    "ium",
    "registro_sanitario",
    "forma_cups",
    "codigo_propio",
    "sin_clasificar",
]

# Orden de CORRECTITUD, no de rendimiento -- `clasificar_codigos()` evalua
# todas las condiciones siempre (np.select), asi que reordenar esto no
# acelera nada y SI puede romper una clasificacion. Cada comentario explica
# por que esa posicion es la que evita una colision real, medida:
_PATRONES_TIPO: tuple[tuple[CodigoTipo, re.Pattern[str]], ...] = (
    # 1) CUM: el mismo patron que `es_cum()`, repetido aqui (no importado
    #    como funcion) porque el resto de esta tupla necesita objetos
    #    `re.Pattern` para usarlos con `Series.str.match` vectorizado.
    ("cum", _PATRON_CUM),
    # 2) CUM con sufijo ATC: EXPEDIENTE(8)-CONSECUTIVO(2)-0ATC(7). Va ANTES
    #    de cualquier regla laxa con guion -- si no, cae en "ium"/generico y
    #    se pierden 147 CUM reales (48 activos) que hoy no cruzan contra
    #    INVIMA porque su EXPEDIENTE vive solo dentro del codigo (columna
    #    EXPEDIENTE = "-999" en 143 de las 147). El sufijo ATC exige LETRA
    #    tras el "0" a proposito: "99999999-99-00000001" (relleno de digito
    #    repetido, familia de codigo propio) tiene la misma forma de dos
    #    guiones y NO debe entrar aqui.
    ("cum_con_sufijo_atc", re.compile(r"^\d{8}-\d{2}-0[A-Z]\d{2}[A-Z]{2}\d{2}$", re.IGNORECASE)),
    # 3) Familia ATC+expediente+consecutivo: codigo_atc + 6 digitos finales
    #    del expediente + consecutivo. Empieza por LETRA (el ATC), asi que
    #    nunca colisiona con el IUM (empieza por digito). Es un tercio de
    #    la tabla completa (64.779 filas) y esta 100% inactiva: una capa
    #    legada duplicada, no medicamentos nuevos.
    ("atc_expediente_consecutivo", re.compile(r"^[A-Z]\d{2}[A-Z]{2}\d{2}\d{7,}$", re.IGNORECASE)),
    # 4) IUM real: exactamente 15 caracteres, digito + letra + 13 digitos.
    #    Medido sobre las 85 filas que lo cumplen -- el nombre "ium" antes
    #    describia 199.463 filas ajenas a este patron; ahora describe estas.
    ("ium", re.compile(r"^[0-9][A-Za-z][0-9]{13}$")),
    # 5) Registro sanitario INVIMA usado como codigo (no es CUM ni IUM ni
    #    propio: es otra identidad de INVIMA en el campo equivocado).
    #    Formato moderno AAAAM-NNNNNNN, antiguo M-NNNNN, variante de
    #    dispositivo medico con marcador DM, y el prefijo literal "INVIMA".
    (
        "registro_sanitario",
        re.compile(
            # Los dos primeros ramales llevan `$` propio: sin eso, un
            # codigo mas largo que por casualidad EMPIEZA con la forma
            # AAAAM-NNNNNNN clasificaria mal. El de "INVIMA" queda sin `$`
            # a proposito -- cubre el truncado a 15 caracteres real
            # ("INVIMA 2003M-00") que no tiene un final limpio.
            r"^(\d{4}D?M[- ]?\d{4,10}$|M-\d{4,6}$|INVIMA\b)",
            re.IGNORECASE,
        ),
    ),
    # 6) Forma CUPS: 6 digitos, o el prefijo de manual tarifario ISS/SOAT
    #    (S/M/C) + 5-6 digitos. Deliberadamente MAS estricto que "letra +
    #    alfanumerico": un patron laxo como `^[A-Z][A-Z0-9]{4,6}$` atrapa
    #    "CU1155" y "D00001" (codigo propio, ver 7) antes de que lleguen
    #    ahi. Se llama "forma" y no "es": de 27 filas con esta forma, 21 se
    #    verificaron cruzando contra `tb_cup.codigo_interno`; las otras 6
    #    tienen la forma sin confirmar contra la tabla real.
    ("forma_cups", re.compile(r"^(\d{6}|[SMC]\d{5,6})$", re.IGNORECASE)),
    # 7) Codigo propio de Pijao Salud / Gemma Net: prefijo alfabetico corto
    #    + secuencia numerica (CU=cuidador, D=dispositivo, MED=medicamento
    #    cargado a mano), o texto libre sin ningun digito (nombre comercial
    #    usado como codigo). La sub-familia "relleno de digito repetido"
    #    (ej. "99999999-99-00000001") NO se reconoce aqui a proposito: la
    #    heuristica de "digito repetido" da falsos positivos sobre
    #    expedientes legitimos, asi que cae en sin_clasificar en vez de
    #    adivinar.
    ("codigo_propio", re.compile(r"^([A-Za-z]{1,4}[0-9]+|[^0-9]+)$")),
)


def es_cum(codigo: object) -> bool:
    """CUM = patron estricto EXPEDIENTE-CONSECUTIVO (solo digitos a cada lado).

    No usar "tiene guion" ni "no es 100% numerico" como proxy: ese fue el
    criterio que produjo cifras contradictorias entre el reporte original
    (~66.231 alfanumericos) y el diagnostico posterior (199.463) sobre el
    mismo archivo, porque contaban distinto los codigos con guion.
    """
    if codigo is None:
        return False
    return bool(_PATRON_CUM.match(str(codigo).strip()))


def clasificar_codigo(codigo: object) -> CodigoTipo:
    """Clasificacion escalar -- para un codigo suelto o para pruebas.

    En produccion usar `clasificar_codigos()` (vectorizada): esta version
    hace hasta 8 intentos de regex en Python puro por llamada, y una
    auditoria recorre ~200.000 codigos.
    """
    if codigo is None or (isinstance(codigo, float) and pd.isna(codigo)):
        return "sin_clasificar"
    texto = str(codigo).strip()
    if not texto:
        return "sin_clasificar"
    for tipo, patron in _PATRONES_TIPO:
        if patron.match(texto):
            return tipo
    return "sin_clasificar"


def clasificar_codigos(serie: pd.Series) -> pd.Series:
    """Version vectorizada de `clasificar_codigo()`, con el mismo orden de
    patrones -- `np.select` evalua TODAS las condiciones siempre (no hay
    cortocircuito), asi que el orden en `_PATRONES_TIPO` es de correctitud,
    no de velocidad. Nunca usar `.apply()`/`.map()` con `clasificar_codigo`
    sobre una serie completa: eso es exactamente el patron de bucle por
    fila que este proyecto prohibe a esta escala.
    """
    texto = serie.fillna("").astype(str).str.strip()
    condiciones = [texto.str.match(patron) for _, patron in _PATRONES_TIPO]
    valores = [tipo for tipo, _ in _PATRONES_TIPO]
    return pd.Series(
        np.select(condiciones, valores, default="sin_clasificar"),
        index=serie.index,
    )


TIPOS_CODIGO_INTERNO: tuple[CodigoTipo, ...] = tuple(tipo for tipo, _ in _PATRONES_TIPO) + (
    "sin_clasificar",
)


def partir_cum(codigo: str) -> tuple[int, int] | None:
    if not es_cum(codigo):
        return None
    expediente, consecutivo = codigo.strip().split("-")
    return int(expediente), int(consecutivo)
