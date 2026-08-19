"""Fase 6 del SOP: cruza contra el archivo que exporta la propia Gemma Net
(Mantenimientos/Basicas Atencion/Medicamentos/Crear Masivos -> Exportar) para
saber que CODIGO_INTERNO ya estan cargados en la plataforma. Reemplaza el
BUSCARV manual en Excel: antes esto se hacia a mano y el resultado se editaba;
ahora es un paso mas del pipeline y el archivo exportado es una entrada, no
algo que se retoca.

El cruce es por igualdad de texto exacta sobre CODIGO_INTERNO, nunca por el
patron EXPEDIENTE-CONSECUTIVO: verificado contra un export real (199.690
filas), solo 66.8% de los codigos siguen ese patron -- el resto son codigos
legado en texto libre (ej. "ZIAL", "VENDAJE") sin expediente INVIMA asociado.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from gemma_cum_loader.normaliza.texto import normalizar_encabezado
from gemma_cum_loader.validacion.reglas import es_error_excel

_DELIMITADORES_CANDIDATOS = ["|", ";", "\t", ","]


@dataclass(frozen=True)
class CodigosGemaNet:
    codigos: set[str]
    advertencias: list[str] = field(default_factory=list)
    # codigos recuperados de forma aproximada de lineas que no se pudieron
    # leer completas -- no son un cruce confirmado, solo una señal de "esto
    # podria coincidir con algo, no se pudo verificar". Ver leer_codigos_gemanet.
    codigos_no_verificables: set[str] = field(default_factory=set)
    lineas_omitidas: list[str] = field(default_factory=list)
    # mismo orden/largo que lineas_omitidas (a diferencia de
    # codigos_no_verificables, que es un set sin orden) -- "" cuando esa
    # linea puntual no dejo recuperar ningun codigo. Para poder mostrarle a
    # un humano, linea por linea, cual codigo se intento recuperar de cada
    # una (ver la tabla de "lineas no leidas" en la UI).
    codigos_no_verificables_por_linea: list[str] = field(default_factory=list)


# utf-8-sig primero (cubre UTF-8 con o sin BOM), cp1252 despues -- es la
# codificacion "ANSI" por defecto de Excel/Windows en configuracion regional
# latinoamericana (caso real: un .txt exportado con tildes llegaba con
# 0xF3 = "o" en cp1252, invalido como continuacion UTF-8). latin-1 al final
# nunca falla (mapea byte a byte 1:1), es la red de seguridad final.
_ENCODINGS_CANDIDATOS = ("utf-8-sig", "cp1252", "latin-1")


def _decodificar(contenido: bytes) -> str:
    for encoding in _ENCODINGS_CANDIDATOS:
        try:
            return contenido.decode(encoding)
        except UnicodeDecodeError:
            continue
    return contenido.decode("latin-1")  # nunca deberia llegar aqui


def _leer_texto(archivo: Any) -> str:
    if hasattr(archivo, "read"):
        contenido = archivo.read()
        return _decodificar(contenido) if isinstance(contenido, bytes) else contenido
    with open(archivo, "rb") as f:
        return _decodificar(f.read())


def _leer_delimitado(
    contenido: str, delimitador: str
) -> tuple[pd.DataFrame, list[str], list[list[str]]]:
    """Caso real: un .txt de 199.689 filas con una linea que trae 38 campos
    en vez de 37 -- casi seguro un valor de texto (ej. una descripcion) con
    el caracter delimitador adentro, sin comillas. El motor C de pandas
    revienta con ParserError en vez de seguir. Reintenta con el motor python
    y `on_bad_lines` como callback para saltar SOLO esas filas y guardar sus
    tokens crudos (para intentar recuperar el codigo interno despues, ver
    leer_codigos_gemanet), en vez de tumbar la corrida entera o fallar en
    silencio.
    """
    try:
        return pd.read_csv(io.StringIO(contenido), sep=delimitador), [], []
    except pd.errors.ParserError:
        omitidas: list[list[str]] = []

        def _guardar_y_omitir(linea_mala: list[str]) -> None:
            omitidas.append(linea_mala)
            return None

        df = pd.read_csv(
            io.StringIO(contenido),
            sep=delimitador,
            engine="python",
            on_bad_lines=_guardar_y_omitir,
        )
        # texto en lenguaje llano a proposito -- pedido explicito del usuario:
        # quien diligencia una subida no tiene por que entender jerga tecnica
        # ("numero de campos irregular", "ParserError"). El detalle tecnico
        # completo (linea cruda, codigo recuperado) sigue disponible en la
        # tabla de la UI para quien lo necesite, esto es solo el resumen.
        advertencia = (
            f"{len(omitidas)} medicamento(s) del archivo de Gemma Net no se pudieron leer bien "
            "-- probablemente porque el texto de alguno de sus campos (por ejemplo la "
            "descripción) tenía un símbolo que el sistema confunde con un separador de "
            "columnas. Se intentó identificar a cuál medicamento corresponde cada línea para "
            "no asumir por error que no existen todavía -- revisa el detalle abajo."
        )
        return df, [advertencia], omitidas


@dataclass(frozen=True)
class ReporteGemaNet:
    """El reporte completo (todas las columnas), no solo el set de codigos --
    ver `leer_reporte_gemanet`. `leer_codigos_gemanet` (fase 6, cruce de
    existencia) y `auditoria/coherencia_invima.py` (comparacion campo por
    campo de lo que ya existe) comparten esta misma lectura.
    """

    df: pd.DataFrame
    advertencias: list[str] = field(default_factory=list)
    lineas_omitidas_tokens: list[list[str]] = field(default_factory=list)
    delimitador: str = "|"


def leer_reporte_gemanet(archivo: Any) -> ReporteGemaNet:
    """archivo: ruta o objeto tipo-archivo (ej. UploadedFile de Streamlit).

    Soporta .xlsx (el export real de la plataforma) y .txt/.csv delimitado.
    El delimitador de un .txt/.csv se detecta contando ocurrencias en la
    primera linea (no se usa el sniffer de pandas -- con archivos cortos de
    pocas columnas adivina mal). Si no se reconoce una columna CODIGO_INTERNO
    despues de normalizar encabezados, falla con un mensaje claro en vez de
    devolver un reporte vacio silencioso.
    """
    nombre = str(getattr(archivo, "name", archivo)).lower()

    if hasattr(archivo, "seek"):
        archivo.seek(0)

    advertencias: list[str] = []
    lineas_omitidas_tokens: list[list[str]] = []
    delimitador = "|"
    if nombre.endswith(".xlsx"):
        df = pd.read_excel(archivo)
    else:
        contenido = _leer_texto(archivo)
        primera_linea = contenido.splitlines()[0] if contenido else ""
        delimitador = max(_DELIMITADORES_CANDIDATOS, key=primera_linea.count)
        df, advertencias, lineas_omitidas_tokens = _leer_delimitado(contenido, delimitador)

    df.columns = [normalizar_encabezado(c) for c in df.columns]
    if "CODIGO_INTERNO" not in df.columns:
        raise ValueError(
            "El archivo exportado de Gemma Net no tiene una columna "
            "CODIGO_INTERNO reconocible. Columnas encontradas: "
            f"{list(df.columns)}"
        )
    return ReporteGemaNet(
        df=df,
        advertencias=advertencias,
        lineas_omitidas_tokens=lineas_omitidas_tokens,
        delimitador=delimitador,
    )


def leer_codigos_gemanet(archivo: Any) -> CodigosGemaNet:
    """Solo el set de CODIGO_INTERNO (fase 6: ¿ya existe, si o no?) -- para
    el reporte completo con todas las columnas ver `leer_reporte_gemanet`.
    """
    reporte = leer_reporte_gemanet(archivo)
    df, columnas = reporte.df, list(reporte.df.columns)

    codigos = set(df["CODIGO_INTERNO"].dropna().astype(str).str.strip())
    # un "#N/A" o "#NAME?" guardado como texto literal en esa columna (visto
    # en el export real) no es un codigo real -- si se deja pasar, nunca
    # colisiona con nada y solo ensucia el set en silencio
    codigos = {c for c in codigos if c and not es_error_excel(c)}

    codigos_no_verificables: set[str] = set()
    lineas_omitidas: list[str] = []
    codigos_no_verificables_por_linea: list[str] = []
    if reporte.lineas_omitidas_tokens:
        indice_codigo = columnas.index("CODIGO_INTERNO")
        for tokens in reporte.lineas_omitidas_tokens:
            lineas_omitidas.append(reporte.delimitador.join(tokens))
            posible = tokens[indice_codigo].strip() if indice_codigo < len(tokens) else ""
            codigos_no_verificables_por_linea.append(posible)
            if posible:
                codigos_no_verificables.add(posible)

    return CodigosGemaNet(
        codigos=codigos,
        advertencias=reporte.advertencias,
        codigos_no_verificables=codigos_no_verificables,
        lineas_omitidas=lineas_omitidas,
        codigos_no_verificables_por_linea=codigos_no_verificables_por_linea,
    )
