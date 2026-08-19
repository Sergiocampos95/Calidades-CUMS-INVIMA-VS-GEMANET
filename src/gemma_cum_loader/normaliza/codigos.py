"""Deteccion del tipo de codigo interno: CUM (expediente-consecutivo) vs. IUM."""

from __future__ import annotations

import re
from typing import Literal

_PATRON_CUM = re.compile(r"^\d+-\d+$")

CodigoTipo = Literal["cum", "ium"]


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
    return "cum" if es_cum(codigo) else "ium"


def partir_cum(codigo: str) -> tuple[int, int] | None:
    if not es_cum(codigo):
        return None
    expediente, consecutivo = codigo.strip().split("-")
    return int(expediente), int(consecutivo)
