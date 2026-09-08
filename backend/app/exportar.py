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

# El PIPE es el delimitador de todo lo que exporta Gemma CUM en texto plano
# (.csv y .txt) -- decision del usuario (2026-09-07): "el delimitador que
# debemos usar es el de pipeline, ya que el punto y coma es propenso a
# errores".
#
# Medido sobre las 199.613 filas del snapshot real, cuantas celdas de texto ya
# CONTIENEN cada candidato (y por tanto obligan a comillas o parten una
# columna de mas si alguien separa a mano):
#
#     coma           231.410      <- lo que usaba el .csv
#     punto y coma    62.777      <- el que el usuario descarto, con razon
#     tab                 27      <- lo que usaba el .txt
#     pipe                26      <- este
#
# La coma era el problema real: DESCRIPCION, VIGENCIA_NO_CONFIRMABLE y
# DETALLE_VIGENCIA_INVIMA la traen adentro constantemente. `to_csv` entrecomilla
# esos valores, asi que el archivo nunca estuvo mal formado -- pero cualquiera
# que lo abriera con un split ingenuo (o con un importador mal configurado)
# obtenia columnas corridas, y eso es justo lo que se venia reportando.
#
# 26 celdas todavia traen un pipe: `to_csv` las entrecomilla igual, asi que el
# archivo sigue siendo correcto. No hay separador de un caracter con cero
# apariciones, y elegir el de menos es lo mas que se puede hacer sin inventar
# un formato propio.
#
# Ademas cierra el circulo con la lectura: `cruce_gemanet._DELIMITADORES_CANDIDATOS`
# ya prueba "|" PRIMERO, asi que un archivo exportado por la app y vuelto a
# cargar se detecta bien sin configurar nada.
DELIMITADOR_EXPORTACION = "|"


def bytes_desde_escritor(escritor: Callable[[Path], None]) -> bytes:
    with tempfile.TemporaryDirectory() as directorio_temporal:
        ruta = Path(directorio_temporal) / "salida.xlsx"
        escritor(ruta)
        return ruta.read_bytes()
