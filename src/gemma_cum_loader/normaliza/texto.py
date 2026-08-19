"""Normalizacion de texto para comparar valores de catalogo (marca, unidad, forma).

No usar para fechas ni para texto libre de descripciones: esta normalizacion
quita todos los puntos porque asi lo exige el bug real diagnosticado en la
columna AP de la malla de cargue (alias sucios como "mg.", "U.I.").
"""

from __future__ import annotations

import re
import unicodedata

_PUNTOS_RE = re.compile(r"\.")
_ESPACIOS_RE = re.compile(r"\s+")


def normalizar(valor: object) -> str:
    if valor is None:
        return ""
    sin_tildes = unicodedata.normalize("NFKD", str(valor))
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    limpio = sin_tildes.strip().upper()
    limpio = _PUNTOS_RE.sub("", limpio)
    limpio = _ESPACIOS_RE.sub(" ", limpio)
    return limpio.strip()


_SUFIJOS_SOCIETARIOS = {"SA", "SAS", "LTDA", "EU", "CIA", "SCS", "SCA", "SC"}
_PARENTESIS_RE = re.compile(r"\([^)]*\)")


def normalizar_entidad(valor: object) -> str:
    """normalizar() + trunca en la primera palabra que sea un sufijo societario
    colombiano (SA, SAS, LTDA, EU, CIA, SCS, SCA, SC).

    Solo para MARCA MEDICAMENTO (razon social de laboratorio/fabricante), no para
    UNIDAD DE MEDIDA ni MODELO DE SERVICIO. Motivado por el diagnostico contra el
    archivo real: la malla escribe la razon social con el sufijo y calificadores
    de planta/estado a continuacion (ej. "TECNOQUIMICAS S.A. (PLANTA JAMUNDI)",
    "QUIBI S.A. EN REESTRUCTURACION") mientras TABLAS DE REFERENCIA guarda solo
    el nombre base con su propio sufijo ("TECNOQUIMICAS SAS", "QUIBI SAS"). El
    sufijo exacto tambien difiere entre archivos (S.A. vs SAS) porque son el
    mismo tipo de entidad expresado de forma distinta, no una coincidencia textual.

    Deliberadamente NO incluye sufijos extranjeros (AG, INC, LTD, GMBH, NV...):
    una matriz extranjera y una filial colombiana son entidades legales
    distintas y no deben fusionarse solo porque comparten el nombre comercial
    (caso real: "NOVARTIS DE COLOMBIA S.A." vs catalogo "NOVARTIS PHARMA A.G."
    no deben resolver al mismo codigo).
    """
    base = normalizar(valor)
    base = _PARENTESIS_RE.sub("", base)
    base = _ESPACIOS_RE.sub(" ", base).strip()
    palabras = base.split(" ")
    for i, palabra in enumerate(palabras):
        if palabra in _SUFIJOS_SOCIETARIOS:
            return " ".join(palabras[:i]).strip()
    return base


def normalizar_encabezado(columna: object) -> str:
    """Nombre de columna -> MAYUSCULAS_SIN_TILDES_CON_GUION_BAJO.

    Usado al leer cualquier Excel real para tolerar variaciones de
    acentuacion/espacios entre archivos sin depender de que el encabezado
    exacto haya sido verificado caracter por caracter de antemano.
    """
    sin_tildes = unicodedata.normalize("NFKD", str(columna))
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return _ESPACIOS_RE.sub("_", sin_tildes.strip().upper())
