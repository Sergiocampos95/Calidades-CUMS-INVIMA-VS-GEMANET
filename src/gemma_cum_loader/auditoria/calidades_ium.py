""""Casos por calidad" para el modulo IUM -- version paralela de
`calidades.py` (CUM), no una extension de ella. Decision del usuario
(2026-09-28/29): "CUMs y IUMs deben ser tratados por aparte... modulos
distintos", y "usaremos la estructura de la logica de los CUMs" para
mostrarlo.

Reusa de `calidades.py` todo lo que es genuinamente igual (la clase
`Calidad`, `_con_columnas_derivadas`, `_columna_texto`, `_no_vacio`,
`_columnas_de_todas_las_secciones`, y el mecanismo completo de secciones
-- `secciones_de_diferencia`/`filtrar_por_seccion`/`columnas_de_seccion`,
que ya son genericos sobre cualquier tabla con CAMPOS_CON_DIFERENCIA/
COHERENCIA_FECHAS_INVIMA, sin cambios). Solo se define aca la mascara
propia de IUM.

Por ahora hay UNA calidad -- "Diferencia de estado o campos" -- porque es
la unica que tiene sentido con el universo de datos real: solo 49 de los 90
IUM que Gemma Net carga (medido 2026-09-28) tienen un unico CUM asociado en
INVIMA y se pueden comparar campo a campo; el resto (varios_cum,
mal_formado, no_publicado_en_invima) no tiene con que comparar, y esa
distincion ya se ve en la vista "IUM ya cargados" (vistas/ium.ts), no
necesita su propia tarjeta de calidad. Las demas calidades de CUM (Vigencia
confirmada, Registro vencido, etc.) no se replican aca: dependerian de
`TIPO_CODIGO_INTERNO`/`ESTADO_LISTADO_INVIMA` de la MISMA forma que ya
prueba `test_coherencia_invima.py`, y a 90 filas la mayoria saldria en cero
o redundante con lo que ya muestra "IUM ya cargados" -- ver
`.ai/planes/2026-09-28-modulo-ium-separado.md`.
"""

from __future__ import annotations

import pandas as pd

from gemma_cum_loader.armado.indice_ium import ESTADO_UN_CUM
from gemma_cum_loader.auditoria.calidades import (
    Calidad,
    _columna_texto,
    _columnas_de_todas_las_secciones,
    _con_columnas_derivadas,
    _no_vacio,
)

NOMBRE_CALIDAD_DIFERENCIAS = "Diferencia de estado o campos"


def _definiciones_ium(
    auditoria: pd.DataFrame,
) -> list[tuple[str, str, tuple[str, ...], str, pd.Series, list[str]]]:
    comparable = (
        auditoria["ESTADO_IUM"].eq(ESTADO_UN_CUM)
        if "ESTADO_IUM" in auditoria.columns
        else pd.Series(False, index=auditoria.index)
    )
    solo_activos = _columna_texto(auditoria, "ACTIVO").str.upper().eq("SI")
    activo_invima = _columna_texto(auditoria, "ESTADO_CUM_INVIMA").eq("Activo")
    inactivo_invima = _columna_texto(auditoria, "ESTADO_CUM_INVIMA").eq("Inactivo")
    listado = _columna_texto(auditoria, "ESTADO_LISTADO_INVIMA")
    en_algun_listado = listado.ne("") & listado.ne("ninguno")

    # Misma factorizacion que calidades.py: discrepancia PURA de vigencia,
    # en las dos direcciones.
    discrepancia_vigencia = (solo_activos & inactivo_invima & listado.ne("vencido")) | (
        ~solo_activos & activo_invima
    )
    diferencia_campos = (
        _no_vacio(auditoria, "CAMPOS_CON_DIFERENCIA")
        | _no_vacio(auditoria, "COHERENCIA_FECHAS_INVIMA")
        | _no_vacio(auditoria, "INCONSISTENCIA_FECHAS_ACTIVO")
    )

    base = [
        "CODIGO_INTERNO",
        "DESCRIPCION",
        "ACTIVO",
        "ESTADO_CUM_INVIMA",
        "ESTADO_INVIMA",
        "CONSEJO",
        "CUM_INVIMA",
        "IDENTIDAD_DUPLICADA",
    ]
    return [
        (
            NOMBRE_CALIDAD_DIFERENCIAS,
            ("Medicamentos que Gemma Net identifica por IUM, comparados contra INVIMA a través "
            "del único CUM que INVIMA le asocia a ese IUM: diferencias en el estado de "
            "vigencia, en alguno de los 7 campos comparados o en las fechas. La descripción "
            "solo se compara si está escrita como la de un CUM; si es el nombre oficial del "
            "IUM queda sin comparar, porque falta definir cómo debe escribirse la de un IUM."),
            (
                ("Solo entran los IUM donde INVIMA asocia un único CUM -- con varios, no se "
                "compara nada (ver «IUM ya cargados» para esos casos)."),
                "Discrepancia de vigencia en cualquier dirección.",
                ("O activo en Gemma Net con al menos un campo que no coincide con INVIMA: "
                "descripción (si está escrita como la de un CUM), principio activo, "
                "concentración, forma farmacéutica, unidad de medida, código ATC o marca."),
                "O activo en Gemma Net con una fecha de inicio o de fin distinta de la de INVIMA.",
            ),
            ("Abrir el tipo de diferencia en la columna de la izquierda para ver, campo por "
            "campo, qué dice Gemma Net y qué dice INVIMA."),
            comparable & en_algun_listado & (discrepancia_vigencia | (solo_activos & diferencia_campos)),
            [
                *base,
                "RESPONSABLE_DISCREPANCIA",
                "DETALLE_DIFERENCIAS",
                "CAMPOS_CON_DIFERENCIA",
                "PORCENTAJE_CALIDAD",
                "FECHA_INICIO",
                "FECHA_ACTIVO_INVIMA",
                "FECHA_FIN",
                "FECHA_VENCIMIENTO_INVIMA",
                "COHERENCIA_FECHAS_INVIMA",
                "INCONSISTENCIA_FECHAS_ACTIVO",
                "CONSULTA_VERIFICACION_SQL",
            ],
        ),
    ]


def calidades_ium(auditoria_ium: pd.DataFrame) -> list[Calidad]:
    """Version IUM de `calidades.calidades_auditoria`: mismo mecanismo
    (mascara booleana + columnas por tarjeta), denominador propio (los IUM
    comparables, `ESTADO_IUM == "un_cum"`, no el universo de CUM)."""
    auditoria = _con_columnas_derivadas(auditoria_ium)
    comparable = (
        auditoria["ESTADO_IUM"].eq(ESTADO_UN_CUM)
        if "ESTADO_IUM" in auditoria.columns
        else pd.Series(False, index=auditoria.index)
    )
    total = int(comparable.sum())
    resultado = []
    for nombre, explica, criterios, que_hacer, mascara, columnas_deseadas in _definiciones_ium(auditoria):
        columnas = tuple(c for c in columnas_deseadas if c in auditoria.columns)
        columnas_para_secciones = tuple(
            c
            for c in _columnas_de_todas_las_secciones()
            if c in auditoria.columns and c not in columnas
        )
        del_df = [*columnas, *columnas_para_secciones]
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
                df_tabla=subconjunto[del_df].copy() if del_df else subconjunto.iloc[:, :0],
                criterios=criterios,
                que_hacer=que_hacer,
            )
        )
    return resultado
