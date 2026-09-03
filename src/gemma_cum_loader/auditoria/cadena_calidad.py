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

El universo de partida de TODA la cadena (antes de H1) es solo CUMs reales
(`_es_cum`, formato EXPEDIENTE-CONSECUTIVO) -- pedido explicito del usuario
(2026-09-01): un codigo que no es CUM (legado, ancestral, IUM...) nunca
puede tener correspondencia con INVIMA, asi que compararlo aca es ilogico y
ni siquiera debe aparecer en las tablas, no solo "fallar" H1. De ahi en
adelante, cada tabla (`df_tabla`) muestra unicamente las filas que siguen
vivas en ESE eslabon (su `universo_previo`) -- H2 en adelante nunca vuelve a
mostrar un medicamento que ya no tuvo correspondencia en H1, porque no hay
nada del lado INVIMA contra que comparar DESCRIPCION/PRINCIPIO_ACTIVO/etc.

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
from gemma_cum_loader.normaliza.codigos import PATRON_CUM

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


# Los mismos dos tipos que `coherencia_invima.filtrar_universo_auditable`
# considera CUM auditable. Ver el mismo bug/fix en calidades.py::
# _TIPOS_CODIGO_INTERNO_CUM -- PATRON_CUM solo no reconoce un CUM con sufijo
# ATC (3 partes, la ultima con letras, ej. "00027649-01-0H02AA02").
# Solo "cum": el codigo legado con sufijo ATC quedo fuera del universo
# auditable (ver _TIPOS_CODIGO_AUDITABLES en coherencia_invima.py).
_TIPOS_CODIGO_INTERNO_CUM = ("cum",)


def _es_cum(auditoria: pd.DataFrame) -> pd.Series:
    """Universo de partida de TODA la cadena: solo codigos con formato
    EXPEDIENTE-CONSECUTIVO autentico. Sin esto, H1 mezclaba CUMs reales
    que no cruzaron con INVIMA (un hallazgo real: dato que deberia coincidir
    y no coincide) con codigos que NUNCA pueden cruzar porque no son CUM
    (legados, ancestrales, IUM...) -- diluia "Correspondencia con INVIMA"
    con casos estructuralmente imposibles de comparar, no con problemas de
    calidad. Pedido explicito del usuario (2026-09-01): "no tienen porque
    verse los medicamentos que no son cums... es ilogico compararlos ya que
    nunca habra ningun cruce".

    Usa TIPO_CODIGO_INTERNO (ya calculado por `auditar_coherencia`) cuando
    esta disponible, en vez de re-parsear PATRON_CUM a mano: asi reconoce
    tambien el CUM con sufijo ATC, que PATRON_CUM sola no matchea -- bug
    corregido (2026-09-01), 79 filas quedaban invisibles en H1..H6 pese a
    ser CUM validos. Cae a PATRON_CUM solo si la columna no existe
    (DataFrames de prueba que no pasaron por `auditar_coherencia`)."""
    if "TIPO_CODIGO_INTERNO" in auditoria.columns:
        return auditoria["TIPO_CODIGO_INTERNO"].isin(_TIPOS_CODIGO_INTERNO_CUM)
    if "CODIGO_INTERNO" not in auditoria.columns:
        return pd.Series(False, index=auditoria.index)
    return auditoria["CODIGO_INTERNO"].fillna("").astype(str).str.strip().str.match(PATRON_CUM)


def _tiene_correspondencia(auditoria: pd.DataFrame) -> pd.Series:
    """H1: si el CODIGO_INTERNO de Gemma Net cruzo con INVIMA. No es un
    trio {CAMPO}_GEMANET/_INVIMA/_VALIDACION -- CODIGO_INTERNO es la llave
    del cruce, no un campo comparable (ver CAMPOS_COMPARADOS_COHERENCIA en
    coherencia_invima.py). Se deriva de ESTADO_COHERENCIA, que ya distingue
    sin_correspondencia_invima de cualquier otro estado. Excluye tambien
    no_valida_contra_invima (ancestrales/plantas): no tienen correspondencia
    porque INVIMA no aplica, es un estado distinto (paso 4, ciclo 2)."""
    estados_sin_correspondencia = {
        EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value,
        EstadoCoherencia.NO_VALIDA_CONTRA_INVIMA.value,
    }
    return ~auditoria["ESTADO_COHERENCIA"].isin(estados_sin_correspondencia)


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

    El universo de PARTIDA (antes de H1) ya no es "todas las filas": es
    `_es_cum()` -- solo codigos con formato EXPEDIENTE-CONSECUTIVO. Un
    codigo que no es CUM nunca puede tener correspondencia con INVIMA (no
    es una cuestion de calidad de dato, es estructural), asi que ni entra a
    H1 ni aparece en ninguna tabla de la cadena. Con esto, "Correspondencia
    con INVIMA" (H1) mide lo que de verdad importa: de los CUMs reales,
    cuantos cruzaron -- no lo diluye con codigos que jamas iban a cruzar.

    `campo_nuevo` faltante en `auditoria` (ej. si se corrio con un subset de
    columnas) se reporta como eslabon vacio en vez de reventar en silencio:
    universo 0, porcentaje_total None, tabla vacia -- degradacion explicita.
    """
    eslabones: list[EslabonCalidad] = []
    pasa_acumulada = _es_cum(auditoria)
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
        # Solo las filas que siguen vivas en ESTE eslabon (`universo_previo`,
        # el mismo conjunto que ya se usa para calcular `universo` arriba) --
        # pedido explicito del usuario (2026-09-01): un medicamento que no es
        # CUM, o que no tiene correspondencia con ninguno de los cuatro
        # listados de INVIMA, no tiene nada que comparar aca y no debe
        # aparecer en la tabla. Antes se mostraban las filas del universo
        # COMPLETO en cada eslabon (bug real: el numero de "universo
        # evaluado" ya excluia esas filas, pero la tabla de abajo seguia
        # trayendo las 199.611 -- el numero y lo que se veia no coincidian).
        df_tabla = auditoria.loc[universo_previo, columnas_tabla].copy()
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
