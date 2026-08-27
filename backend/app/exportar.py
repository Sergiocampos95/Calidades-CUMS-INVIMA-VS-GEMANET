"""Convierte "una funcion que escribe un .xlsx a una ruta" en bytes listos
para responder un request HTTP. Mismo patron que `_exportar_a_bytes` en la
UI de Streamlit -- los generadores reales (`guardar_reporte`,
`generar_excel_cargue`...) siempre escriben a una ruta de archivo, nunca
devuelven bytes directo, asi que esto es el UNICO adaptador que hace falta,
no una reescritura de esos generadores."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path


def bytes_desde_escritor(escritor: Callable[[Path], None]) -> bytes:
    with tempfile.TemporaryDirectory() as directorio_temporal:
        ruta = Path(directorio_temporal) / "salida.xlsx"
        escritor(ruta)
        return ruta.read_bytes()
