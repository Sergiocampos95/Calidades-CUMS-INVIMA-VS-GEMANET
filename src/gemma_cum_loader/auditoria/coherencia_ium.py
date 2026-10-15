"""Auditoria de lo que Gemma Net ya carga identificado por IUM, en paralelo
a la auditoria de CUM (`coherencia_invima.py`) -- MODULOS DISTINTOS, decision
explicita del usuario (2026-09-28): "CUMs y IUMs deben ser tratados por
aparte dentro de la misma app". El modulo CUM sigue ignorando los IUM
(`_TIPOS_CODIGO_AUDITABLES` en coherencia_invima.py, ver design/reglas_
negocio.md seccion IUM) -- sus cifras no cambian por la existencia de este
modulo.

Reusa la MISMA logica de comparacion campo a campo que `auditar_coherencia()`
via su parametro `claves_cruce_alternas`: un IUM no es una llave de INVIMA
distinta, es una segunda identidad del mismo CUM (ver `armado/indice_ium.py`
para la evidencia medida). Solo cuando INVIMA le asocia a un IUM EXACTAMENTE
un CUM se puede comparar campo a campo sin adivinar -- medido 2026-09-28: 49
de los 90 IUM que Gemma Net carga hoy caen en ese caso. Ver
`.ai/planes/2026-09-28-modulo-ium-separado.md` para el analisis completo y
las decisiones de negocio que quedaron pendientes (D2, D4, D5, D8).
"""

from __future__ import annotations

import pandas as pd

from gemma_cum_loader.armado.indice_ium import ESTADO_UN_CUM, indice_ium
from gemma_cum_loader.auditoria.coherencia_invima import (
    EntradaCatalogo,
    auditar_coherencia,
)
from gemma_cum_loader.normaliza.codigos import clasificar_codigos

# IUM que Gemma Net carga pero que no aparece en ningun listado de INVIMA
# (distinto de "varios_cum"/"mal_formado", que SI aparecen pero no se
# pueden comparar sin elegir a ciegas).
ESTADO_NO_PUBLICADO = "no_publicado_en_invima"

# Calculadas por auditar_coherencia() pensando en CODIGO_INTERNO = CUM: le
# dirian algo falso a una fila IUM (ej. TIPO_SIN_CORRESPONDENCIA="Codigo
# legado" sobre un IUM valido que simplemente no tiene un unico CUM). Se
# descartan del resultado en vez de mostrar un valor que no significa lo que
# dice (regla 2 del proyecto: degradacion explicita, nunca suposicion
# silenciosa).
_COLUMNAS_SOLO_CUM = (
    "TIPO_SIN_CORRESPONDENCIA",
    "CUM_RECONSTRUIDO",
    "FILA_LEGADA_DUPLICADA",
    "TIPO_CODIGO_INTERNO",
)

# Sin un unico CUM contra el cual decidir, clasificar prioridad o naturaleza
# seria elegir a ciegas -- se blanquean, no se inventan (decision del
# usuario 2026-09-28, ver D3 del plan).
_COLUMNAS_SOLO_SI_UN_CUM = ("PRIORIDAD_ACCION", "NATURALEZA_HALLAZGO", "ACCION_SUGERIDA")

COLUMNAS_IUM_AGREGADAS = ("ESTADO_IUM", "CUM_INVIMA", "N_CUM_INVIMA", "IDENTIDAD_DUPLICADA")

# DESCRIPCION de una fila IUM -- decision D4 del plan, tomada por el usuario
# el 2026-10-15: se compara SOLO contra la forma de la guia, PRINCIPIO_ACTIVO +
# UNIDAD_REFERENCIA ("la que arma INVIMA debe ser de dos campos nomas segun la
# guia, usar mas nos da errores ambiguos [...] no importa si coincide o no, si
# la guia dicta que asi es asi debe ser"). Ver `descripcion_solo_guia` en
# auditar_coherencia.
#
# Antes (2026-10-02) la descripcion quedaba "sin comparar" cuando Gemma Net
# guardaba el nombre oficial del IUM ("MERCAPTOPURINA 50mg/1 U TABLETAS...",
# la concentracion "por unidad" con barra; un patron que reconocia el 98,1 %
# de los 34.643 nombres de la tabla oficial) y se comparaba contra las dos
# formas de un CUM si estaba escrita al estilo CUM. Medido el 2026-10-15 sobre
# los 56 IUM comparables: 36 nombre oficial (sin comparar), 20 estilo CUM (1
# coincidia: 1N1043301000100, "NIFEDIPINO 30MG CAPSULA..."). Con la regla de
# la guia, 0 de los 56 son iguales a PA + UNIDAD_REFERENCIA: es lo esperado y
# es la decision -- la guia dicta la forma.
#
# Unico caso sin comparar: INVIMA no publica UNIDAD_REFERENCIA para ese
# registro, asi que la forma de la guia no se puede armar -- aceptar el
# principio activo solo como descripcion seria decidir a ciegas (mismo
# criterio que `_descripcion_segun_guia_invima`).
# CONCENTRACION, PRINCIPIO_ACTIVO y FORMA_FARMACEUTICA NO van aqui: el plan los
# compara "con la misma funcion" y CONCENTRACION sigue la decision homonima del
# 2026-09-09 (reglas_negocio.md §4) -- su "difiere" es comportamiento aceptado.
CAMPOS_SIN_COMPARAR_IUM = {
    "DESCRIPCION": lambda cruzado: cruzado.get(
        "_DESCRIPCION_GUIA_INVIMA", pd.Series("", index=cruzado.index)
    )
    .fillna("")
    .astype(str)
    .str.strip()
    .eq(""),
}


def _mapa_activo_por_codigo(reporte_gemanet: pd.DataFrame) -> dict[str, list[bool]]:
    """CODIGO_INTERNO -> lista de si cada fila con ese codigo en el reporte
    COMPLETO de Gemma Net esta activa (`ACTIVO == "SI"`). Lista y no un solo
    booleano porque un mismo CODIGO_INTERNO puede repetirse (medicamento
    combinado, fabricante duplicado) -- informar cuantas hay, nunca elegir
    una al azar."""
    activo = reporte_gemanet.get("ACTIVO", pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    mapa: dict[str, list[bool]] = {}
    for codigo, es_activo in zip(reporte_gemanet["CODIGO_INTERNO"].astype(str).str.strip(), activo):
        mapa.setdefault(codigo, []).append(es_activo == "SI")
    return mapa


def _identidad_duplicada(cum: str, mapa_activo: dict[str, list[bool]]) -> str:
    hermanas = mapa_activo.get(cum)
    if not hermanas:
        return ""
    n_activas = sum(hermanas)
    if len(hermanas) == 1:
        estado = "activo" if hermanas[0] else "inactivo"
        return f"Duplica al CUM {cum} ({estado} en Gemma Net)"
    return f"Duplica al CUM {cum} ({len(hermanas)} filas en Gemma Net, {n_activas} activas)"


def auditar_coherencia_ium(
    reporte_gemanet: pd.DataFrame,
    df_invima: pd.DataFrame,
    catalogo_unidad: list[EntradaCatalogo],
    catalogo_marca: list[EntradaCatalogo],
    df_invima_vencidos: pd.DataFrame | None = None,
    df_invima_otros_estados: pd.DataFrame | None = None,
    df_invima_renovacion: pd.DataFrame | None = None,
    alias_unidad: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Una fila por CODIGO_INTERNO de Gemma Net cuyo tipo (ver
    `normaliza/codigos.py::clasificar_codigos`) es "ium", con las mismas
    columnas que produce `auditar_coherencia()` para CUM (comparacion campo
    a campo, vigencia, fechas...) MAS:

    ESTADO_IUM: "un_cum" (INVIMA le asocia exactamente un CUM -- unico caso
    comparable), "varios_cum" (INVIMA le asocia mas de uno -- requiere
    decision, no se compara), "mal_formado" (no cumple la forma de 15
    caracteres de un IUM real) o "no_publicado_en_invima" (Gemma Net lo
    carga pero no aparece en ningun listado de INVIMA).

    CUM_INVIMA: el o los CODIGO_INTERNO (CUM) que INVIMA asocia a este IUM.

    IDENTIDAD_DUPLICADA: si el CUM de este IUM (solo con ESTADO_IUM ==
    "un_cum") YA existe como fila propia en el reporte completo de Gemma
    Net, dice cual y si esa fila esta activa -- medido 2026-09-28: pasa en
    56 de 57 casos posibles. Vacio si no aplica.

    Para ESTADO_IUM distinto de "un_cum", PRIORIDAD_ACCION, NATURALEZA_
    HALLAZGO y ACCION_SUGERIDA quedan vacios: no hay un unico CUM contra el
    cual decidir esos veredictos -- ver D3 en
    `.ai/planes/2026-09-28-modulo-ium-separado.md`.

    Los listados de INVIMA se pasan COMPLETOS, nunca prefiltrados: la fecha
    de corte de vigencia (`_corte_catalogo_invima`) se calcula sobre el
    catalogo completo, y recortarlo antes moveria esa fecha en silencio.
    """
    tipo = clasificar_codigos(reporte_gemanet["CODIGO_INTERNO"])
    reporte_ium = reporte_gemanet.loc[tipo == "ium"].reset_index(drop=True).copy()
    reporte_ium["CODIGO_INTERNO"] = reporte_ium["CODIGO_INTERNO"].astype(str).str.strip().str.upper()

    columnas_resultado_vacio = list(COLUMNAS_IUM_AGREGADAS) + ["CODIGO_INTERNO"]
    if reporte_ium.empty:
        return pd.DataFrame(columns=columnas_resultado_vacio)

    listados_no_vacios = [
        df
        for df in (df_invima, df_invima_vencidos, df_invima_otros_estados, df_invima_renovacion)
        if df is not None and not df.empty
    ]
    catalogo_para_indice = pd.concat(listados_no_vacios, ignore_index=True) if listados_no_vacios else df_invima
    indice = indice_ium(catalogo_para_indice)

    if indice.attrs.get("sin_fuente_ium"):
        # Degradacion explicita: la fuente no publica IUM. No es que estos
        # IUM "no existan" en INVIMA -- es que la fuente no trae el dato
        # (caso real: el export nuevo del portal para Vigentes no incluye
        # la columna IUM). Nunca se confunde con ESTADO_NO_PUBLICADO fila a
        # fila, que si implica que la fuente SI tiene IUM pero no este.
        resultado = reporte_ium[["CODIGO_INTERNO"]].copy()
        resultado["ESTADO_IUM"] = ESTADO_NO_PUBLICADO
        resultado["CUM_INVIMA"] = [[] for _ in range(len(resultado))]
        resultado["N_CUM_INVIMA"] = 0
        resultado["IDENTIDAD_DUPLICADA"] = ""
        resultado.attrs["sin_fuente_ium"] = True
        return resultado

    indice_para_cruce = indice.rename(columns={"IUM": "CODIGO_INTERNO"})
    fusion = reporte_ium.merge(
        indice_para_cruce[["CODIGO_INTERNO", "CUM_INVIMA", "N_CUM_INVIMA", "ESTADO_IUM"]],
        on="CODIGO_INTERNO",
        how="left",
    )
    fusion["ESTADO_IUM"] = fusion["ESTADO_IUM"].fillna(ESTADO_NO_PUBLICADO)
    fusion["CUM_INVIMA"] = fusion["CUM_INVIMA"].apply(lambda v: v if isinstance(v, list) else [])
    fusion["N_CUM_INVIMA"] = fusion["N_CUM_INVIMA"].fillna(0).astype(int)

    es_un_cum = fusion["ESTADO_IUM"] == ESTADO_UN_CUM
    claves_cruce_alternas = {
        codigo: cums[0]
        for codigo, cums, un_cum in zip(fusion["CODIGO_INTERNO"], fusion["CUM_INVIMA"], es_un_cum)
        if un_cum
    }

    auditoria = auditar_coherencia(
        reporte_ium,
        df_invima,
        catalogo_unidad,
        catalogo_marca,
        df_invima_vencidos=df_invima_vencidos,
        df_invima_otros_estados=df_invima_otros_estados,
        df_invima_renovacion=df_invima_renovacion,
        alias_unidad=alias_unidad,
        claves_cruce_alternas=claves_cruce_alternas,
        campos_sin_comparar=CAMPOS_SIN_COMPARAR_IUM,
        descripcion_solo_guia=True,
    )

    resultado = auditoria.merge(
        fusion[["CODIGO_INTERNO", "ESTADO_IUM", "CUM_INVIMA", "N_CUM_INVIMA"]],
        on="CODIGO_INTERNO",
        how="left",
    )

    mapa_activo = _mapa_activo_por_codigo(reporte_gemanet)
    resultado["IDENTIDAD_DUPLICADA"] = [
        _identidad_duplicada(cums[0], mapa_activo) if estado == ESTADO_UN_CUM and cums else ""
        for estado, cums in zip(resultado["ESTADO_IUM"], resultado["CUM_INVIMA"])
    ]

    for columna in _COLUMNAS_SOLO_CUM:
        if columna in resultado.columns:
            resultado = resultado.drop(columns=columna)

    no_es_un_cum = resultado["ESTADO_IUM"] != ESTADO_UN_CUM
    for columna in _COLUMNAS_SOLO_SI_UN_CUM:
        if columna in resultado.columns:
            resultado.loc[no_es_un_cum, columna] = ""

    return resultado
