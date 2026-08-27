"""La "tabla de calidades": el entregable que pide el negocio (ing. Sergio,
via el usuario, 2026-08-21): "una tabla de calidades [...] si ya me dices
que hay diferencias pero yo quiero saber que medicamentos, que diferencias
en cada campo". Todas estas cifras ya se calculaban en `coherencia_invima.py`
-- lo que faltaba era poder abrirlas hasta los medicamentos que las
componen, cada una con las columnas que hacen falta para entender ESE
hallazgo puntual (quien mira duplicados necesita el codigo, quien mira
vigencia necesita las fechas -- no las mismas para todos).

Portado de `ui_revision/app_streamlit.py::_calidades()`/`_mostrar_tabla_de_calidades()`
(logica identica, ninguna regla nueva) para que el backend de solo lectura
(Fase 2 de la migracion, ver `backend/app/routers/calidades.py`) pueda
servir lo mismo sin duplicar reglas de negocio ni importar la UI de
Streamlit. Streamlit sigue con su propia copia sin tocar mientras siga en
produccion -- ver la nota de la migracion en `.claude/plans`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from gemma_cum_loader.auditoria.coherencia_invima import EstadoCoherencia
from gemma_cum_loader.normaliza.codigos import PATRON_CUM


def _columna_texto(df: pd.DataFrame, nombre: str) -> pd.Series:
    if nombre not in df.columns:
        return pd.Series("", index=df.index, dtype="object")
    return df[nombre].fillna("").astype(str).str.strip()


def _no_vacio(df: pd.DataFrame, columna: str) -> pd.Series:
    """Filas donde esa columna trae algo. Vacio (nunca True) si la columna
    no existe -- degradacion explicita: sin la columna, no hay hallazgo que
    reportar, no se asume que si lo hay."""
    if columna not in df.columns:
        return pd.Series(False, index=df.index)
    serie = df[columna]
    if serie.dtype == bool:
        return serie
    return serie.fillna("").astype(str).str.strip().ne("")


@dataclass(frozen=True)
class Calidad:
    """Una fila de la tabla de calidades: cuantos medicamentos caen en ella,
    y la tabla navegable con solo las columnas que hacen falta para
    entenderla (no siempre las mismas)."""

    nombre: str
    explica: str
    columnas: tuple[str, ...]
    medicamentos: int
    porcentaje_del_catalogo: float
    df_tabla: pd.DataFrame = field(repr=False)


def _definiciones(auditoria: pd.DataFrame) -> list[tuple[str, str, pd.Series, list[str]]]:
    """(nombre, explica, mascara, columnas) -- mismo orden y mismo texto que
    `_calidades()` en Streamlit, para no inventar vocabulario nuevo."""
    estado = auditoria["ESTADO_COHERENCIA"] if "ESTADO_COHERENCIA" in auditoria.columns else pd.Series("", index=auditoria.index)
    activo = _columna_texto(auditoria, "ACTIVO").str.upper().eq("SI")
    codigo = _columna_texto(auditoria, "CODIGO_INTERNO")
    tiene_formato_invima = codigo.str.match(PATRON_CUM)

    base = ["CODIGO_INTERNO", "DESCRIPCION", "ACTIVO"]
    return [
        (
            "Sin código verificable contra INVIMA",
            (
                "Su código no sigue el formato EXPEDIENTE-CONSECUTIVO, así que no hay con qué "
                "buscarlo en INVIMA. No están mal cargados: no se pueden verificar por este camino."
            ),
            ~tiene_formato_invima,
            [*base, "TIPO_SIN_CORRESPONDENCIA"],
        ),
        (
            "Con formato INVIMA pero no encontrados",
            (
                "Sí tienen forma de código INVIMA y aun así no aparecen en ninguno de los cuatro "
                "listados. Son los que vale la pena revisar uno por uno."
            ),
            tiene_formato_invima & estado.eq(EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value),
            [*base, "TIPO_SIN_CORRESPONDENCIA"],
        ),
        (
            "Código repetido dentro del reporte",
            (
                "El mismo código aparece más de una vez. Puede ser legítimo: un medicamento "
                "combinado trae una fila por principio activo. Nunca se fusionan."
            ),
            _no_vacio(auditoria, "CODIGO_DUPLICADO_EN_REPORTE"),
            [*base, "PRINCIPIO_ACTIVO"],
        ),
        (
            "Formato de código inválido",
            "El código viene vacío o es un error de fórmula heredado de Excel.",
            _no_vacio(auditoria, "FORMATO_CODIGO_INTERNO_INVALIDO"),
            [*base, "FORMATO_CODIGO_INTERNO_INVALIDO"],
        ),
        (
            "Registro vencido en INVIMA",
            "INVIMA lo tiene en su listado de vencidos.",
            estado.eq(EstadoCoherencia.VENCIDO_EN_INVIMA.value),
            [*base, "FECHA_FIN", "DETALLE_VIGENCIA_INVIMA"],
        ),
        (
            "En otro estado en INVIMA",
            (
                "Cancelado, Suspendido, Negado, Desistido, Pérdida de fuerza ejecutoria… El detalle "
                "dice cuál exactamente."
            ),
            estado.eq(EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value),
            [*base, "ESTADO_INVIMA_DETALLE"],
        ),
        (
            "En trámite de renovación",
            "El registro sigue siendo válido mientras INVIMA resuelve. Se espera, no se corrige.",
            estado.eq(EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value),
            [*base, "ESTADO_INVIMA_DETALLE"],
        ),
        (
            "Con algún campo distinto al de INVIMA",
            (
                "Existe en INVIMA y se pudo comparar campo a campo: alguno no coincide. Abajo se "
                "puede ver cuál y qué dice cada lado."
            ),
            _no_vacio(auditoria, "CAMPOS_CON_DIFERENCIA"),
            [*base, "CAMPOS_CON_DIFERENCIA", "PORCENTAJE_CALIDAD"],
        ),
        (
            "Fechas que se contradicen",
            (
                "ACTIVO y las fechas de inicio/fin no cuadran entre sí. No depende de INVIMA: es el "
                "dato contra sí mismo."
            ),
            _no_vacio(auditoria, "INCONSISTENCIA_FECHAS_ACTIVO"),
            [*base, "FECHA_INICIO", "FECHA_FIN", "INCONSISTENCIA_FECHAS_ACTIVO"],
        ),
        (
            "Código de marca o unidad inexistente",
            (
                "Guarda un código de catálogo que no existe en el catálogo. No es una diferencia con "
                "INVIMA: es un código huérfano."
            ),
            _no_vacio(auditoria, "INTEGRIDAD_REFERENCIAL_CATALOGO"),
            [*base, "INTEGRIDAD_REFERENCIAL_CATALOGO"],
        ),
        (
            "Activos aquí sin vigencia en INVIMA",
            (
                "Los únicos sobre los que se puede actuar hoy: están ACTIVOS en Gemma Net y su "
                "registro no está vigente en INVIMA, así que se pueden llegar a autorizar. Es la "
                "cifra que importa para el riesgo, no el total de vencidos."
            ),
            activo
            & estado.isin(
                [
                    EstadoCoherencia.VENCIDO_EN_INVIMA.value,
                    EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value,
                ]
            ),
            [*base, "ESTADO_INVIMA_DETALLE", "FECHA_FIN"],
        ),
    ]


def calidades_auditoria(auditoria: pd.DataFrame) -> list[Calidad]:
    """Las 11 calidades que el negocio pide poder revisar, cada una con su
    tabla navegable ya filtrada. No recalcula nada de `auditar_coherencia()`
    -- solo combina mascaras booleanas vectorizadas sobre columnas que esa
    funcion ya dejo en el DataFrame."""
    total = len(auditoria)
    resultado = []
    for nombre, explica, mascara, columnas_deseadas in _definiciones(auditoria):
        columnas = tuple(c for c in columnas_deseadas if c in auditoria.columns)
        subconjunto = auditoria[mascara]
        medicamentos = int(mascara.sum())
        porcentaje = round(medicamentos / total * 100, 1) if total else 0.0
        resultado.append(
            Calidad(
                nombre=nombre,
                explica=explica,
                columnas=columnas,
                medicamentos=medicamentos,
                porcentaje_del_catalogo=porcentaje,
                df_tabla=subconjunto[list(columnas)].copy() if columnas else subconjunto.iloc[:, :0],
            )
        )
    return resultado
