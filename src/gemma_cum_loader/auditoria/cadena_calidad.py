"""Cadena de tablas de calidad H1..H6, encadenadas por teoria de conjuntos.

Pedido explicito de negocio (ing. Sergio, via el usuario, 2026-08-27): poder
verificar COMO se llega a cada porcentaje de calidad de la auditoria, no solo
el numero agregado. La forma que pidio es una secuencia de tablas cada vez
mas estricta:

    H1: valida CODIGO_INTERNO (Gemma Net) contra su equivalente INVIMA
        (EXPEDIENTE-CONSECUTIVO) -- si el medicamento tiene correspondencia.
    H2: agrega DESCRIPCION.
    H3: agrega AC (PRINCIPIO_ACTIVO).
    H4: agrega CONCENTRACION.
    H6: agrega UNIDAD_MEDIDA.

Cada tabla acumula las columnas de validacion de la anterior mas una nueva
(aclarado con el usuario: "en H3 se cargarian estos 2 [COD y DESC] que ya se
cargaron, y asi consecutivamente" -- no es solo un filtro de filas, es
tambien una acumulacion de columnas), y trae el porcentaje total de esa
calidad puntual sobre el universo que le corresponde.

H5 (laboratorio) queda fuera a proposito: el usuario dijo explicitamente que
ese campo del pedido de Sergio "hay que validarlo, esto solo fue un ejemplo"
-- MARCA_MEDICAMENTO/TITULAR_INVIMA ya existe en la auditoria pero no esta
confirmado que sea lo mismo que "laboratorio" para el negocio. Sin decisiones
a ciegas: se documenta como pendiente en vez de asumir.

Este modulo NO recalcula nada de `coherencia_invima.auditar_coherencia()`:
solo lee columnas que esa funcion ya dejo en el DataFrame resultado (el
trio {CAMPO}_GEMANET/{CAMPO}_INVIMA/{CAMPO}_VALIDACION, ESTADO_COHERENCIA,
NOVEDAD_VIGENCIA_INVIMA, DETALLE_VIGENCIA_INVIMA). Recalcular el merge o
`similitud_de_campo` por cada una de las 6 tablas seria 6x el costo ya
medido (~0.35 s los 7 campos, ver `coherencia_invima.similitud_de_campo`) --
se llama una sola vez, aca solo se combinan mascaras booleanas vectorizadas.

Criterio de "pasa" un eslabon (aclarado como default, no confirmado por
Sergio -- ver design/metodologia_registros_evaluados.md y la sesion que
origino este modulo): solo VALIDACION_COINCIDE cuenta como "pasa". Un campo
"sin dato en Gemma Net" o "sin comparar" NO pasa. Si el negocio pide otro
criterio, se cambia `_PASA_VALIDACION` sin tocar la forma del modulo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from gemma_cum_loader.auditoria.coherencia_invima import (
    CAMPOS_COMPARADOS_COHERENCIA,
    PREFIJO_SIMILITUD,
    SUFIJO_GEMANET,
    SUFIJO_INVIMA,
    SUFIJO_VALIDACION,
    VALIDACION_COINCIDE,
    EstadoCoherencia,
)

# El nombre de negocio (H1..H6) para cada eslabon, y el campo que agrega
# sobre el anterior. `None` para H1: no agrega un campo del trio, evalua la
# correspondencia misma (si el CODIGO_INTERNO de Gemma Net tiene equivalente
# EXPEDIENTE-CONSECUTIVO en INVIMA -- lo que auditar_coherencia ya resuelve
# como ESTADO_COHERENCIA != sin_correspondencia_invima).
#
# H5 (laboratorio) queda excluido a proposito -- ver docstring del modulo.
# Si Sergio confirma el campo, agregarlo aca es la unica linea que hace
# falta tocar en este modulo.
CADENA_CALIDAD_DEFAULT: tuple[tuple[str, str | None], ...] = (
    ("H1", None),
    ("H2", "DESCRIPCION"),
    ("H3", "PRINCIPIO_ACTIVO"),
    ("H4", "CONCENTRACION"),
    ("H6", "UNIDAD_MEDIDA"),
)

# Vocabulario del estado acumulado por fila -- texto, no booleano, mismo
# criterio que VALIDACION_* en coherencia_invima.py: un valor que se puede
# filtrar y mostrar en una tabla, no un 0/1 que hay que traducir aparte.
ESTADO_CADENA_PASA = "pasa"
ESTADO_CADENA_NO_PASA = "no_pasa"

_PASA_VALIDACION = VALIDACION_COINCIDE


@dataclass(frozen=True)
class EslabonCalidad:
    """Una tabla de la cadena (H1..H6): que campos acumula, cuantas filas
    entraron a evaluarse, que porcentaje paso, y la tabla navegable."""

    nombre: str
    campo_nuevo: str | None
    campos_acumulados: tuple[str, ...]
    columnas_trio: tuple[str, ...]
    columna_estado: str
    universo: int
    porcentaje_total: float | None
    df_tabla: pd.DataFrame = field(repr=False)


def _tiene_correspondencia(auditoria: pd.DataFrame) -> pd.Series:
    """H1: si el CODIGO_INTERNO de Gemma Net cruzo con INVIMA. No es un
    trio {CAMPO}_GEMANET/_INVIMA/_VALIDACION -- CODIGO_INTERNO es la llave
    del cruce, no un campo comparable (ver CAMPOS_COMPARADOS_COHERENCIA en
    coherencia_invima.py). Se deriva de ESTADO_COHERENCIA, que ya distingue
    sin_correspondencia_invima de cualquier otro estado."""
    return auditoria["ESTADO_COHERENCIA"] != EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value


def _pasa_campo(auditoria: pd.DataFrame, campo: str) -> pd.Series:
    """Vectorizado: una fila "pasa" el eslabon de `campo` si su veredicto
    (columna {campo}_VALIDACION, ya calculada por auditar_coherencia) es
    VALIDACION_COINCIDE. "sin dato en Gemma Net" y "sin comparar" no pasan
    -- no hay evidencia de que el campo este correcto, asi que no se asume."""
    columna = f"{campo}{SUFIJO_VALIDACION}"
    return auditoria[columna] == _PASA_VALIDACION


def construir_cadena_calidad(
    auditoria: pd.DataFrame,
    cadena: tuple[tuple[str, str | None], ...] = CADENA_CALIDAD_DEFAULT,
) -> list[EslabonCalidad]:
    """Arma la cadena H1..H6 sobre el DataFrame que ya devolvio
    `auditar_coherencia()`. Cada eslabon es la interseccion (AND vectorizado,
    sin bucle por fila) del eslabon anterior con la condicion nueva -- por
    eso cada `pasa_acumulada` siguiente es subconjunto estricto de la
    anterior, la propiedad de teoria de conjuntos que pidio el negocio.

    `campo_nuevo` faltante en `auditoria` (ej. si se corrio con un subset de
    columnas) se reporta como eslabon vacio en vez de reventar en silencio:
    universo 0, porcentaje_total None, tabla vacia -- degradacion explicita.
    """
    eslabones: list[EslabonCalidad] = []
    pasa_acumulada = pd.Series(True, index=auditoria.index)
    campos_acumulados: tuple[str, ...] = ()
    columnas_trio_acumuladas: tuple[str, ...] = ()

    for nombre, campo_nuevo in cadena:
        universo_previo = pasa_acumulada
        universo = int(universo_previo.sum())

        if campo_nuevo is None:
            # H1: no hay campo del trio que agregar, la condicion ES la
            # correspondencia con INVIMA.
            pasa_incremental = _tiene_correspondencia(auditoria)
            nuevas_columnas: tuple[str, ...] = (
                "ESTADO_COHERENCIA",
                "NOVEDAD_VIGENCIA_INVIMA",
                "DETALLE_VIGENCIA_INVIMA",
            )
        elif campo_nuevo not in CAMPOS_COMPARADOS_COHERENCIA:
            # Degradacion explicita: un campo que no es comparable en esta
            # auditoria (ej. "laboratorio" mientras siga sin confirmar) no
            # se adivina -- el eslabon queda documentado como vacio.
            pasa_incremental = pd.Series(False, index=auditoria.index)
            nuevas_columnas = ()
        else:
            pasa_incremental = _pasa_campo(auditoria, campo_nuevo)
            # SIMILITUD_{campo} al final del cuarteto -- el veredicto
            # (_VALIDACION) dice SI hay un problema, el porcentaje dice si
            # es una tilde o son dos medicamentos distintos (pedido del
            # usuario, 2026-08-27: "ver tambien el porcentaje de calidad
            # por cada campo"). No es una columna nueva: ya la calcula
            # auditar_coherencia() via similitud_de_campo(), solo faltaba
            # incluirla aca.
            nuevas_columnas = (
                f"{campo_nuevo}{SUFIJO_GEMANET}",
                f"{campo_nuevo}{SUFIJO_INVIMA}",
                f"{campo_nuevo}{SUFIJO_VALIDACION}",
                f"{PREFIJO_SIMILITUD}{campo_nuevo}",
            )

        pasa_acumulada = universo_previo & pasa_incremental
        campos_acumulados = campos_acumulados + ((campo_nuevo,) if campo_nuevo else ())
        columnas_trio_acumuladas = columnas_trio_acumuladas + nuevas_columnas

        # Vacio, no 0 %, cuando no hay universo que evaluar -- mismo
        # criterio no negociable que PORCENTAJE_CALIDAD.
        porcentaje_total = (
            round(float(pasa_incremental[universo_previo].sum()) / universo * 100, 1)
            if universo > 0
            else None
        )

        columna_estado = f"ESTADO_CADENA_{nombre}"
        estado_columna = pd.Series(ESTADO_CADENA_NO_PASA, index=auditoria.index, dtype="object")
        estado_columna[pasa_acumulada] = ESTADO_CADENA_PASA

        # DESCRIPCION, no PRODUCTO -- PRODUCTO es un campo del lado INVIMA
        # (universo_invima_clasificado), auditoria trae el lado Gemma Net,
        # donde el texto identificador es DESCRIPCION (ver
        # CAMPOS_COMPARADOS_COHERENCIA en coherencia_invima.py). Bug real
        # (2026-08-27): con "PRODUCTO" el filtro `if c in auditoria.columns`
        # lo descartaba en silencio -- df_tabla nunca tuvo columna
        # identificadora, se veia como una columna de guiones en la UI.
        columnas_tabla = [c for c in ("CODIGO_INTERNO", "DESCRIPCION") if c in auditoria.columns]
        columnas_tabla += [c for c in columnas_trio_acumuladas if c in auditoria.columns]
        df_tabla = auditoria[columnas_tabla].copy()
        df_tabla[columna_estado] = estado_columna

        eslabones.append(
            EslabonCalidad(
                nombre=nombre,
                campo_nuevo=campo_nuevo,
                campos_acumulados=campos_acumulados,
                columnas_trio=columnas_trio_acumuladas,
                columna_estado=columna_estado,
                universo=universo,
                porcentaje_total=porcentaje_total,
                df_tabla=df_tabla,
            )
        )

    return eslabones
