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
import logging

import pandas as pd

logger = logging.getLogger(__name__)

from gemma_cum_loader.auditoria.coherencia_invima import (
    ACCION_POR_NATURALEZA,
    CAMPOS_COMPARADOS_COHERENCIA,
    SUFIJO_GEMANET,
    SUFIJO_INVIMA,
    SUFIJO_VALIDACION,
    EstadoCoherencia,
)

# Las columnas GEMANET/INVIMA/VALIDACION de los 7 campos comparables, en un
# solo bloque -- pedido explicito del usuario (2026-08-28): "campos con
# diferencia, dice cuales son los campos pero no lo que contiene... si es
# la descripcion la que esta mal imprimes la desc de invima la desc de
# gema y el resultado". CAMPOS_CON_DIFERENCIA ya dice CUALES difieren; esto
# muestra los tres valores de CADA campo comparable, no solo de los que
# difieren en esa fila -- asi se ve tambien que el resto SI coincide.
COLUMNAS_TRIO_CAMPOS_COMPARADOS = tuple(
    f"{campo}{sufijo}"
    for campo in CAMPOS_COMPARADOS_COHERENCIA
    for sufijo in (SUFIJO_GEMANET, SUFIJO_INVIMA, SUFIJO_VALIDACION)
)

# La tabla y columnas REALES de Gemma Net (ver ingesta/gemanet_sql.py --
# mismo SELECT que ya usa el reporte, verificado contra la base real). Solo
# Gemma Net: INVIMA no tiene una base propia que consultar, solo el
# catalogo ya descargado -- aclarado explicitamente por el usuario.
_TABLA_VERIFICACION_GEMANET = "administrativo.tb_medicamento"
_COLUMNAS_VERIFICACION_GEMANET = (
    "codigo_interno",
    "descripcion",
    "concentracion",
    "principio_activo",
    "forma_farmaceutica",
    "codigo_atc",
    "marca_medicamento",
    "consecutivo_unidad_medida",
)


def _consultas_verificacion_gemanet(codigos_internos: pd.Series) -> pd.Series:
    """Una consulta SQL de solo lectura por fila -- para corroborar el dato
    directo en Gemma Net sin esperar a nadie (pedido del usuario,
    2026-08-28: "para corroborar un dato... o para extraer el dato
    minimamente de gemma net ya que invima no se puede"). Vectorizado:
    string concat sobre toda la columna, no un bucle por fila."""
    columnas = ", ".join(_COLUMNAS_VERIFICACION_GEMANET)
    # Comillas simples escapadas (duplicadas) -- el CODIGO_INTERNO nunca
    # deberia traer una, pero la consulta se pega tal cual en un cliente
    # SQL ajeno: mejor una consulta siempre valida que una que rompa por un
    # caracter raro en un dato real.
    codigos_escapados = codigos_internos.astype(str).str.replace("'", "''", regex=False)
    return (
        f"SELECT {columnas} FROM {_TABLA_VERIFICACION_GEMANET} WHERE codigo_interno = '"
        + codigos_escapados
        + "';"
    )


def _con_columnas_derivadas(auditoria: pd.DataFrame) -> pd.DataFrame:
    """Agrega CONSEJO (que hacer, segun NATURALEZA_HALLAZGO -- pedido del
    usuario: "un consejo... con logica segun su caso", el mismo filtro
    "Que hacer con cada hallazgo" que ya existia), CONSULTA_VERIFICACION_SQL
    y DETALLE_DIFERENCIAS (lista de campos con diferencia para drilldown).
    Copia el DataFrame antes de tocarlo: la version que llega aca es la
    compartida entre requests (ver el cache de `leer_tabla` en
    almacen_snapshots.py), nunca se muta in place."""
    auditoria = auditoria.copy()
    if "CODIGO_INTERNO" in auditoria.columns:
        auditoria["CONSULTA_VERIFICACION_SQL"] = _consultas_verificacion_gemanet(
            auditoria["CODIGO_INTERNO"]
        )
    if "NATURALEZA_HALLAZGO" in auditoria.columns:
        auditoria["CONSEJO"] = auditoria["NATURALEZA_HALLAZGO"].map(
            lambda n: ACCION_POR_NATURALEZA.get(n, "")
        )
    # Columna de drilldown para ver detalle de campos con diferencia
    if "CAMPOS_CON_DIFERENCIA" in auditoria.columns:
        auditoria["DETALLE_DIFERENCIAS"] = auditoria["CAMPOS_CON_DIFERENCIA"].apply(
            lambda campos: f"Ver ({len(str(campos).split(',')) if pd.notna(campos) and campos != '' else 0} campos)"
        )
    return auditoria


def _columna_texto(df: pd.DataFrame, nombre: str) -> pd.Series:
    if nombre not in df.columns:
        return pd.Series("", index=df.index, dtype="object")
    return df[nombre].fillna("").astype(str).str.strip()


def _es_expediente_consecutivo(codigo_interno: pd.Series) -> pd.Series:
    """Valida si el codigo tiene formato EXPEDIENTE-CONSECUTIVO autentico de INVIMA.
    Formato correcto: EXPEDIENTE-CONSECUTIVO = NN-N (2 partes, ambas numericas)
    Ejemplo valido: 224715-1, 42938-5
    Ejemplo invalido: 00226567-03-0D01AA01 (tiene 3 partes y letras = NO es CUM)
                      1 (medicamento ancestral)."""
    def validar(codigo):
        if not codigo or codigo == "":
            return False
        parts = str(codigo).split("-")
        # EXPEDIENTE-CONSECUTIVO INVIMA: exactamente 2 partes, AMBAS numericas
        # Si tiene 3 partes o letras = es un codigo interno de Gemma, no un CUM
        return len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()

    return codigo_interno.apply(validar)


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
    logger.info(f"DEBUG: _definiciones() called with {len(auditoria)} rows")
    estado = auditoria["ESTADO_COHERENCIA"] if "ESTADO_COHERENCIA" in auditoria.columns else pd.Series("", index=auditoria.index)
    solo_activos = _columna_texto(auditoria, "ACTIVO").str.upper().eq("SI")
    es_cum = _es_expediente_consecutivo(auditoria["CODIGO_INTERNO"]) if "CODIGO_INTERNO" in auditoria.columns else pd.Series(False, index=auditoria.index)
    logger.info(f"DEBUG: solo_activos count = {solo_activos.sum()}")
    # CONSEJO y CONSULTA_VERIFICACION_SQL van en TODAS las calidades: toda
    # fila tiene CODIGO_INTERNO (con que armar la consulta) y, si tiene
    # algun hallazgo, una NATURALEZA_HALLAZGO de la que sacar que hacer
    # (pedido explicito del usuario, 2026-08-28).
    base = ["CODIGO_INTERNO", "DESCRIPCION", "ACTIVO", "CONSEJO", "CONSULTA_VERIFICACION_SQL"]
    return [
        (
            "Vigentes y correctos",
            (
                "CUMs ACTIVOS sin diferencias registradas - están correctos "
                "en Gemma Net y vigentes en INVIMA. Solo formato EXPEDIENTE-CONSECUTIVO."
            ),
            estado.eq(EstadoCoherencia.CORRECTO.value) & solo_activos & _columna_texto(auditoria, "INCONSISTENCIA_FECHAS_ACTIVO").eq("") & es_cum,
            [*base, "ESTADO_COHERENCIA"],
        ),
        (
            "CUMs, IUMs, medicinas ancestrales etc que no existen en INVIMA",
            (
                "Medicamentos ACTIVOS en Gemma Net que no aparecen en NINGUNO de los cuatro listados "
                "de INVIMA. Incluye: CUMs válidos, medicamentos ancestrales, plantas medicinales, "
                "suplementos, insumos y otros medicamentos que no son CUMs estándar."
            ),
            estado.eq(EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value) & solo_activos |
            (estado.isin([
                EstadoCoherencia.VIGENTE_NO_COMERCIALIZADO_INVIMA.value,
                EstadoCoherencia.NO_VALIDA_CONTRA_INVIMA.value,
            ]) & solo_activos),
            [*base, "CLASIFICADO", "TIPO_SIN_CORRESPONDENCIA"],
        ),
        (
            "Registro vencido en INVIMA",
            "CUMs ACTIVOS que INVIMA tiene en su listado de vencidos. Solo formato EXPEDIENTE-CONSECUTIVO.",
            estado.eq(EstadoCoherencia.VENCIDO_EN_INVIMA.value) & solo_activos & es_cum,
            [*base, "FECHA_FIN", "DETALLE_VIGENCIA_INVIMA"],
        ),
        (
            "En otro estado en INVIMA",
            (
                "CUMs ACTIVOS en estados especiales (Cancelado, Suspendido, etc.). "
                "Solo formato EXPEDIENTE-CONSECUTIVO. El detalle dice cuál exactamente."
            ),
            estado.eq(EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value) & solo_activos & es_cum,
            [*base, "ESTADO_INVIMA_DETALLE"],
        ),
        (
            "En trámite de renovación",
            "CUMs ACTIVOS cuya renovación está en trámite en INVIMA. Solo formato EXPEDIENTE-CONSECUTIVO. Se espera, no se corrige.",
            estado.eq(EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value) & solo_activos & es_cum,
            [*base, "ESTADO_INVIMA_DETALLE"],
        ),
        (
            "Con algún campo distinto al de INVIMA",
            (
                "CUMs ACTIVOS que existen en INVIMA pero tienen campos con valores distintos. "
                "Solo se incluyen códigos con formato EXPEDIENTE-CONSECUTIVO válido. "
                "Haz clic en 'Ver diferencias' para ver qué campos cambiaron."
            ),
            _no_vacio(auditoria, "CAMPOS_CON_DIFERENCIA") & solo_activos & es_cum,
            [*base, "DETALLE_DIFERENCIAS", "CAMPOS_CON_DIFERENCIA", "PORCENTAJE_CALIDAD", *COLUMNAS_TRIO_CAMPOS_COMPARADOS],
        ),
        (
            "Fechas que se contradicen",
            (
                "CUMs ACTIVOS donde ACTIVO y las fechas de inicio/fin no cuadran entre sí. "
                "No depende de INVIMA: es el dato contra sí mismo. Solo formato EXPEDIENTE-CONSECUTIVO."
            ),
            _no_vacio(auditoria, "INCONSISTENCIA_FECHAS_ACTIVO") & solo_activos & es_cum,
            [*base, "FECHA_INICIO", "FECHA_FIN", "INCONSISTENCIA_FECHAS_ACTIVO"],
        ),
    ]


def calidades_auditoria(auditoria: pd.DataFrame) -> list[Calidad]:
    """Las 6 calidades que el negocio pide poder revisar, cada una con su
    tabla navegable ya filtrada. No recalcula nada de `auditar_coherencia()`
    -- solo combina mascaras booleanas vectorizadas sobre columnas que esa
    funcion ya dejo en el DataFrame (mas CONSEJO/CONSULTA_VERIFICACION_SQL,
    derivadas aca mismo -- ver `_con_columnas_derivadas`)."""
    auditoria = _con_columnas_derivadas(auditoria)
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
