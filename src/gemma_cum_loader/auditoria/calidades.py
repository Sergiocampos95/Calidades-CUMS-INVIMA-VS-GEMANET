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

import re
from dataclasses import dataclass, field

import pandas as pd

from gemma_cum_loader.auditoria.coherencia_invima import (
    ACCION_POR_NATURALEZA,
    CAMPOS_COMPARADOS_COHERENCIA,
    CAMPOS_DERIVADOS,
    PARES_FECHAS_GEMANET_INVIMA,
    SUFIJO_GEMANET,
    SUFIJO_INVIMA,
    SUFIJO_VALIDACION,
)
from gemma_cum_loader.normaliza.codigos import PATRON_CUM

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


# Mismo vocabulario que ETIQUETA_ESTADO_LISTADO_INVIMA en
# frontend/src/pildoras.ts. Se repite aca a proposito: esta cadena viaja al
# Excel de descarga, que nadie abre con el frontend al lado, asi que el valor
# guardado tiene que ser legible por si mismo.
ETIQUETA_LISTADO_INVIMA = {
    "vigente": "Vigente",
    "vencido": "Vencido",
    "renovacion": "En trámite de renovación",
    "otros_estados": "Otro estado",
    "ninguno": "No existe en INVIMA",
}

# Valores de ESTADO_INVIMA_DETALLE que NO agregan nada a su listado: son la
# misma informacion, tal cual la escribe INVIMA en cada Excel (con sus
# abreviaturas). Se comparan en minusculas.
#
# Explicito y por listado a proposito: el criterio tiene que dar el mismo
# resultado para una fila sin importar que otras filas vengan en el lote. Y
# `otros_estados` NO aparece aca justamente porque ahi el detalle siempre
# aporta -- es un archivo heterogeneo (Cancelado, Negado, Perdida Fuerza
# Ejec...) y esconderlo detras de "Otro estado" contradiria la regla de
# coherencia_invima.py de no tapar el valor real con una etiqueta generica.
#
# Si INVIMA cambia como escribe alguno de estos, el efecto es que el detalle
# vuelve a mostrarse entre parentesis: redundante y feo, pero nunca se pierde
# informacion. El fallo va hacia el lado seguro.
DETALLE_REDUNDANTE_POR_LISTADO: dict[str, frozenset[str]] = {
    "vigente": frozenset({"vigente"}),
    "vencido": frozenset({"vencido"}),
    "renovacion": frozenset({"en tramite renov", "en trámite de renovación"}),
}


def _con_columnas_derivadas(auditoria: pd.DataFrame) -> pd.DataFrame:
    """Agrega CONSEJO (que hacer, segun NATURALEZA_HALLAZGO), CONSULTA_VERIFICACION_SQL,
    DETALLE_DIFERENCIAS (lista de campos con diferencia para drilldown), y
    RESPONSABLE_DISCREPANCIA (GyC/TIC, segun la direccion de la discrepancia de
    vigencia).
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
    # ESTADO_INVIMA: UNA sola columna en vez de ESTADO_LISTADO_INVIMA +
    # ESTADO_INVIMA_DETALLE, que en la tabla salian una al lado de la otra
    # diciendo lo mismo ("Vencido" | "Vencido").
    #
    # Medido contra el snapshot: en 116.267 de las 127.734 filas con listado el
    # detalle toma UN solo valor, identico al del listado. Solo en
    # `otros_estados` aporta -- ahi desglosa en 8 (Perdida Fuerza Ejec, Negado,
    # Cancelado...) porque es un archivo heterogeneo por naturaleza. Por eso el
    # detalle va entre parentesis y SOLO cuando dice algo distinto: se conserva
    # el desglose sin repetir la palabra en el 91 % de las filas.
    #
    # Se compone aca, como CONSEJO, y no en el frontend: asi la misma cadena
    # alimenta la tabla, el filtro por columna y el Excel de descarga. Si se
    # armara al pintar, filtrar y descargar seguirian viendo las dos columnas
    # viejas.
    if "ESTADO_LISTADO_INVIMA" in auditoria.columns:
        listado_legible = _columna_texto(auditoria, "ESTADO_LISTADO_INVIMA").map(
            lambda v: ETIQUETA_LISTADO_INVIMA.get(v, v)
        )
        detalle = _columna_texto(auditoria, "ESTADO_INVIMA_DETALLE")
        # El detalle solo se esconde cuando REPITE lo que ya dice el listado.
        # La comparacion es contra una lista explicita por listado y no
        # `detalle == listado_legible` porque INVIMA abrevia: "En tramite
        # renov" contra "En trámite de renovación" no son iguales como cadena
        # y producian el parentesis inutil "En trámite de renovación (En
        # tramite renov)".
        #
        # Antes esto se decidia contando cuantos valores distintos traia cada
        # listado (`nunique > 1`). Se cambio porque el resultado dependia de
        # las OTRAS filas del lote: una sola fila de Vigentes con el campo en
        # blanco o con una variante subia el conteo a 2 y las 43.312 filas
        # vigentes pasaban a mostrar "Vigente (Vigente)"; y al reves, si
        # `otros_estados` llegara homogeneo en una corrida, el detalle real
        # (Cancelado, Negado...) DESAPARECERIA -- contradiciendo la regla de
        # coherencia_invima.py de no esconderlo tras una etiqueta generica.
        # Que el mismo medicamento se lea distinto segun con quien le toco
        # venir en el lote no es un criterio, es una casualidad.
        redundantes = _columna_texto(auditoria, "ESTADO_LISTADO_INVIMA").map(
            lambda v: DETALLE_REDUNDANTE_POR_LISTADO.get(v, frozenset())
        )
        es_redundante = pd.Series(
            [d.strip().casefold() in r for d, r in zip(detalle, redundantes, strict=True)],
            index=auditoria.index,
        )
        aporta = detalle.ne("") & ~es_redundante
        auditoria["ESTADO_INVIMA"] = listado_legible.where(
            ~aporta, listado_legible + " (" + detalle + ")"
        )

    # RESPONSABLE_DISCREPANCIA: quien debe actuar segun la direccion de la discrepancia
    # (solo para tarjetas 2 y 6 que lo usan, otros casos quedan vacío).
    responsable = pd.Series("", index=auditoria.index, dtype="object")
    if all(c in auditoria.columns for c in ["ACTIVO", "ESTADO_CUM_INVIMA", "ESTADO_LISTADO_INVIMA"]):
        activo = _columna_texto(auditoria, "ACTIVO").str.upper().eq("SI")
        activo_invima = _columna_texto(auditoria, "ESTADO_CUM_INVIMA").eq("Activo")
        inactivo_invima = _columna_texto(auditoria, "ESTADO_CUM_INVIMA").eq("Inactivo")
        listado = _columna_texto(auditoria, "ESTADO_LISTADO_INVIMA")
        # Tarjeta 2 completa: siempre GyC (activo aqui, INVIMA no lo confirma vigente)
        es_tarjeta_2 = listado.eq("vencido") & activo
        responsable[es_tarjeta_2] = "GyC"
        # Tarjeta 6, rama activo aqui/inactivo alla: GyC
        activo_inactivo_alla = activo & inactivo_invima & listado.ne("vencido")
        responsable[activo_inactivo_alla] = "GyC"
        # Tarjeta 6, rama inactivo aqui/activo alla: TIC
        inactivo_activo_alla = ~activo & activo_invima
        responsable[inactivo_activo_alla] = "TIC"
    auditoria["RESPONSABLE_DISCREPANCIA"] = responsable
    return auditoria


def _columna_texto(df: pd.DataFrame, nombre: str) -> pd.Series:
    if nombre not in df.columns:
        return pd.Series("", index=df.index, dtype="object")
    return df[nombre].fillna("").astype(str).str.strip()


# Los mismos dos tipos que `coherencia_invima.filtrar_universo_auditable`
# considera CUM auditable (ver `_TIPOS_CODIGO_AUDITABLES` alla). Bug corregido
# (2026-09-01): esta funcion comparaba solo contra PATRON_CUM (NN-N, 2 partes),
# que NO matchea un CUM con sufijo ATC (ej. "00027649-01-0H02AA02", 3 partes,
# la ultima con letras) -- 79 filas que SI son CUM validos (tienen
# TIPO_CODIGO_INTERNO == "cum_con_sufijo_atc") sobrevivian al filtro del
# pipeline pero quedaban invisibles en las 10 calidades porque su propia
# mascara `es_cum` las excluia. `cadena_calidad.py::_es_cum` tenia el mismo
# bug y se corrigio con el mismo criterio.
# Solo "cum": el codigo legado con sufijo ATC quedo fuera del universo
# auditable (ver _TIPOS_CODIGO_AUDITABLES en coherencia_invima.py).
_TIPOS_CODIGO_INTERNO_CUM = ("cum",)


def _es_expediente_consecutivo(auditoria: pd.DataFrame) -> pd.Series:
    """Valida si el codigo tiene formato EXPEDIENTE-CONSECUTIVO autentico de
    INVIMA (NN-N, 2 partes, ambas numericas -- ej. 224715-1, 42938-5 -- o con
    sufijo ATC, ej. 00027649-01-0H02AA02; NO "1", medicamento ancestral).

    Usa TIPO_CODIGO_INTERNO (ya calculado por `auditar_coherencia` via
    `clasificar_codigos`, ver design/tipos_codigo_interno.md) cuando esta
    disponible, en vez de re-parsear el patron a mano: es la MISMA fuente que
    usa `filtrar_universo_auditable` en coherencia_invima.py, y evita que las
    dos definiciones de "es CUM" del sistema se desalineen otra vez. Si la
    columna no existe (DataFrames de prueba viejos sin pasar por
    `auditar_coherencia`), cae a PATRON_CUM solo -- que no reconoce el sufijo
    ATC, degradacion aceptada porque no hay de donde mas sacar el tipo."""
    if "TIPO_CODIGO_INTERNO" in auditoria.columns:
        return auditoria["TIPO_CODIGO_INTERNO"].isin(_TIPOS_CODIGO_INTERNO_CUM)
    return auditoria["CODIGO_INTERNO"].fillna("").astype(str).str.strip().str.match(PATRON_CUM)


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
    """Definiciones de la auditoria del negocio -- REDISEÑO 2026-09-02.

    La regla clave ahora es estricta: ESTADO_CUM_INVIMA ("Activo"/"Inactivo")
    es el veredicto de vigencia real, NO ESTADO_LISTADO_INVIMA (que es solo
    metadato de ubicacion: en cual archivo de INVIMA aparece el registro).

    Solo se cuentan CUMs activos de formato EXPEDIENTE-CONSECUTIVO que
    realmente se pueden revisar. Los legados, medicamentos ancestrales,
    plantas medicinales e IUMs quedan fuera (via `es_cum` y ESTADO_COHERENCIA).

    La tarjeta fusionada "Diferencia de estado o campos" (la 6) incluye AMBOS
    casos: discrepancia de ESTADO_CUM (en cualquier direccion) y diferencias
    de otros campos aunque el estado coincida. Dentro, se distingue responsable
    (GyC vs TIC) segun la direccion.

    Suplementos NO se filtran aca -- no hay senal estructural confiable.
    Ver coherencia_invima.filtrar_universo_auditable para el razonamiento."""
    solo_activos = _columna_texto(auditoria, "ACTIVO").str.upper().eq("SI")
    es_cum = _es_expediente_consecutivo(auditoria) if "CODIGO_INTERNO" in auditoria.columns else pd.Series(False, index=auditoria.index)

    # Variables para las 6 máscaras nuevas (REDISEÑO 2026-09-02):
    activo_invima = _columna_texto(auditoria, "ESTADO_CUM_INVIMA").eq("Activo")
    inactivo_invima = _columna_texto(auditoria, "ESTADO_CUM_INVIMA").eq("Inactivo")
    listado = _columna_texto(auditoria, "ESTADO_LISTADO_INVIMA")
    en_algun_listado = listado.ne("") & listado.ne("ninguno")

    # Formato invalido (exclusión de tarjeta 1):
    formato_codigo_invalido = _no_vacio(auditoria, "FORMATO_CODIGO_INTERNO_INVALIDO")

    # Diferencias de campos / fechas (tarjeta 6):
    diferencia_campos = (
        _no_vacio(auditoria, "CAMPOS_CON_DIFERENCIA")
        | _no_vacio(auditoria, "COHERENCIA_FECHAS_INVIMA")
        | _no_vacio(auditoria, "INCONSISTENCIA_FECHAS_ACTIVO")
    )

    # Los estados van CONTIGUOS y a la izquierda: el estado local, la vigencia
    # real de INVIMA y donde vive el registro. Van en `base` -- y no al final
    # de cada tarjeta -- porque si CONSEJO queda en medio se pierde la lectura
    # de un vistazo.
    #
    # ESTADO_INVIMA_DETALLE y ESTADO_LISTADO_INVIMA se fusionaron en
    # ESTADO_INVIMA (2026-09-04): salian contiguas repitiendo la misma palabra
    # ("Vencido" | "Vencido") en el 91 % de las filas. Ver la composicion en
    # `_con_columnas_derivadas`. Las dos originales siguen en el DataFrame --
    # otras vistas y las descargas las usan -- solo dejan de mostrarse aca.
    base = [
        "CODIGO_INTERNO",
        "DESCRIPCION",
        "ACTIVO",
        "ESTADO_CUM_INVIMA",
        "ESTADO_INVIMA",
        "CONSEJO",
    ]
    return [
        (
            "Vigencia confirmada",
            (
                "CUMs activos en Gemma Net que INVIMA declara vigentes (ESTADO_CUM='Activo') "
                "Y que ademas estan en el listado de VIGENTES. El estado de VIGENCIA es "
                "correcto; algunos pueden requerir actualizar una fecha o algun campo, y eso "
                "no les quita la vigencia."
            ),
            # El listado tiene que ser EXACTAMENTE 'vigente' -- pedido
            # explicito y repetido del usuario (2026-09-02 y 2026-09-03):
            # "en este apartado meramente deben de aparecer los que
            # pertenezcan solo al listado de vigentes".
            #
            # Historia, para que no se vuelva a quitar: entre medio esta
            # mascara estuvo SIN condicion de listado, para que el caso de
            # "gracia de lotes" (activo aqui, ESTADO_CUM='Activo', pero
            # listado='vencido') contara como vigencia confirmada. Eso metia
            # en esta tarjeta 16.479 registros en tramite de renovacion, 10
            # vencidos y 2 en abandono -- medido contra los Excel de 2022 el
            # 2026-09-03, cuando el usuario lo detecto en pantalla. El caso de
            # gracia de lotes NO se pierde: vive en la tarjeta "Registro
            # vencido en INVIMA", que es donde alguien lo encontrara si lo
            # busca a mano en los Excel de INVIMA, con ESTADO_CUM_INVIMA
            # visible para distinguirlo del vencido pleno.
            solo_activos & es_cum & ~formato_codigo_invalido & activo_invima & listado.eq("vigente"),
            [
                *base, "FECHA_VENCIMIENTO_INVIMA",
                "CAMPOS_CON_DIFERENCIA", "COHERENCIA_FECHAS_INVIMA", "CONSULTA_VERIFICACION_SQL",
            ],
        ),
        (
            "Registro vencido en INVIMA",
            (
                "CUMs activos en Gemma Net que estan en el listado de VENCIDOS de INVIMA. "
                "Mira la columna ESTADO_CUM_INVIMA para saber cual de los dos casos es: "
                "'Inactivo' es vencido pleno (hay que inactivarlo en Gemma Net); 'Activo' "
                "es gracia de lotes -- INVIMA lo deja autorizado mientras se agotan las "
                "existencias, y pasara a vencido pleno cuando cambie el estado."
            ),
            # SOLO el listado, sin condicion sobre ESTADO_CUM -- decision del
            # usuario (2026-09-03), la misma del plan aprobado: el listado es
            # la UBICACION real donde alguien encontrara el registro si lo
            # busca a mano en los Excel de INVIMA, asi que los dos sub-casos
            # tienen que convivir aca y distinguirse por ESTADO_CUM_INVIMA.
            #
            # Historia, para que no se vuelva a partir en dos: hubo una version
            # que exigia ademas `inactivo_invima`, dejando la gracia de lotes
            # en "Vigencia confirmada". Al restaurar el filtro de listado en esa
            # tarjeta (que debe traer SOLO listado=='vigente'), esos casos se
            # quedaban SIN NINGUNA tarjeta salvo que tuvieran ademas algun campo
            # distinto -- un agujero silencioso. Medido con los Excel de 2022:
            # 10 filas; con el catalogo en vivo del 2026-09-03: 2.
            solo_activos & es_cum & listado.eq("vencido"),
            [
                *base, "FECHA_VENCIMIENTO_INVIMA", "CONSULTA_VERIFICACION_SQL",
            ],
        ),
        (
            "En trámite de renovación",
            (
                "CUMs activos cuya renovacion sigue en tramite en INVIMA "
                "(ESTADO_CUM='Activo', listado='renovacion')."
            ),
            solo_activos & es_cum & activo_invima & listado.eq("renovacion"),
            [*base, "CONSULTA_VERIFICACION_SQL"],
        ),
        (
            "En otro estado en INVIMA",
            (
                "CUMs activos en estados especiales dentro de INVIMA "
                "(Cancelado, Suspendido, Inactivo, etc., listado='otros_estados')."
            ),
            solo_activos & es_cum & activo_invima & listado.eq("otros_estados"),
            [*base, "CONSULTA_VERIFICACION_SQL"],
        ),
        (
            "No existe en INVIMA",
            (
                "CUMs activos que no aparecen en ninguno de los 4 listados de INVIMA "
                "(vigente, vencido, renovacion, otros_estados)."
            ),
            solo_activos & es_cum & ~en_algun_listado,
            [*base, "CLASIFICADO", "TIPO_SIN_CORRESPONDENCIA", "CONSULTA_VERIFICACION_SQL"],
        ),
        (
            "Diferencia de estado o campos",
            (
                "Medicamentos con discrepancia de estado de vigencia (activo/inactivo) entre "
                "Gemma y INVIMA) o con diferencias en otros campos (CAMPOS_CON_DIFERENCIA, "
                "fechas). Incluye tambien inactivos en Gemma pero activos en INVIMA. "
                "La columna RESPONSABLE_DISCREPANCIA indica si es GyC o TIC."
            ),
            es_cum & en_algun_listado & (
                # Discrepancia de vigencia:
                (solo_activos & inactivo_invima & listado.ne("vencido"))  # Activo aqui, inactivo alla
                | (~solo_activos & activo_invima)  # Inactivo aqui, activo alla
                # O diferencias de otros campos:
                | (solo_activos & diferencia_campos)
            ),
            [
                *base, "RESPONSABLE_DISCREPANCIA",
                "DETALLE_DIFERENCIAS", "CAMPOS_CON_DIFERENCIA", "PORCENTAJE_CALIDAD",
                "FECHA_INICIO", "FECHA_FIN", "FECHA_ACTIVO_INVIMA", "FECHA_INACTIVO_INVIMA",
                "COHERENCIA_FECHAS_INVIMA", "INCONSISTENCIA_FECHAS_ACTIVO", "CONSULTA_VERIFICACION_SQL",
                *COLUMNAS_TRIO_CAMPOS_COMPARADOS,
            ],
        ),
    ]


def calidades_auditoria(auditoria: pd.DataFrame) -> list[Calidad]:
    """Las 6 calidades que el negocio pide poder revisar, cada una con su
    tabla navegable ya filtrada. No recalcula nada de `auditar_coherencia()`
    -- solo combina mascaras booleanas vectorizadas sobre columnas que esa
    funcion ya dejo en el DataFrame (mas CONSEJO/CONSULTA_VERIFICACION_SQL,
    derivadas aca mismo -- ver `_con_columnas_derivadas`).

    REDISEÑO 2026-09-02: el denominador cambia a usar ESTADO_CUM_INVIMA como
    veredicto de vigencia (no ESTADO_LISTADO_INVIMA)."""
    auditoria = _con_columnas_derivadas(auditoria)
    # Denominador = universo AUDITABLE, basado en ESTADO_CUM_INVIMA (veredicto
    # de vigencia real de INVIMA) en lugar de ESTADO_LISTADO_INVIMA (que es
    # solo ubicacion). Un CUM es auditable si: es CUM formato EXPEDIENTE-
    # CONSECUTIVO, ES ACTIVO EN GEMMA NET, O si es INACTIVO EN GEMMA PERO
    # ACTIVO EN INVIMA (la unica excepcion: el caso de mayor riesgo).
    activo_o_vigente_en_invima = _columna_texto(auditoria, "ACTIVO").str.upper().eq("SI") | (
        _columna_texto(auditoria, "ESTADO_CUM_INVIMA").eq("Activo")
    )
    es_cum_auditable = (
        _es_expediente_consecutivo(auditoria)
        if "CODIGO_INTERNO" in auditoria.columns
        else pd.Series(False, index=auditoria.index)
    )
    total = int((es_cum_auditable & activo_o_vigente_en_invima).sum())
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


# ---------------------------------------------------------------------------
# Secciones de diferencia: partir una calidad grande por TIPO de diferencia.
#
# Pedido explicito del usuario (2026-09-02) sobre la tarjeta "Diferencia de
# estado o campos": "son casi 60000 datos en una sola tabla con muchos campos
# [...] informacion correcta pero dificil de analizar". Medido contra la
# corrida real, esa tarjeta de 59.005 filas es en un 97 % un solo problema
# (FECHA_FIN, 57.255) con seis problemas chicos escondidos detras -- mirarla
# entera no deja ver ninguno.
#
# Las secciones NO son excluyentes: una fila con la descripcion Y la
# concentracion distintas cuenta en las dos. Por eso los conteos no suman el
# total de la tarjeta, y quien la lea tiene que saberlo (lo dice la UI).
# ---------------------------------------------------------------------------

#: Las calidades que se parten en secciones. SOLO la de diferencias --
#: decision del usuario (2026-09-02): "era a diferencias".
#:
#: Tecnicamente cualquier calidad se puede seccionar (medido: "Vigencia
#: confirmada" da 9 secciones), pero ahi el corte CONFUNDE en vez de aclarar:
#: esa tarjeta afirma que la vigencia es correcta, y colgarle "Fecha fin
#: 49.016" al lado la hace leer como si estuviera casi toda mal, cuando lo
#: que dice es otra cosa (la vigencia esta bien; algun campo puede requerir
#: actualizacion). El corte por tipo de diferencia solo responde una pregunta
#: real en la tarjeta que EXISTE para las diferencias.
CALIDADES_CON_SECCIONES = ("Diferencia de estado o campos",)


def calidad_admite_secciones(nombre: str) -> bool:
    return nombre in CALIDADES_CON_SECCIONES


#: Como se nombra cada campo comparable en pantalla. El resto de la app ya
#: usa el nombre tecnico; aca se habla como el negocio.
ETIQUETAS_CAMPO_DIFERENCIA = {
    "DESCRIPCION": "Descripcion",
    "PRINCIPIO_ACTIVO": "Principio activo",
    "CONCENTRACION": "Concentracion",
    "UNIDAD_MEDIDA": "Unidad de medida",
    "CODIGO_ATC": "Codigo ATC",
    "FORMA_FARMACEUTICA": "Forma farmaceutica",
    "MARCA_MEDICAMENTO": "Marca",
}


@dataclass(frozen=True)
class SeccionDiferencia:
    """Un tipo de diferencia dentro de una calidad, con cuantos medicamentos
    lo tienen. `derivado_de` no esta vacio cuando el campo NO es un dato
    independiente sino consecuencia de otro (ver CAMPOS_DERIVADOS): sin esa
    marca, "Descripcion" parece el problema mas grande cuando en buena parte
    es el efecto de que el principio activo este mal. No se descuenta del
    conteo -- la descripcion guardada SI esta mal, es un hecho; se declara
    para que quien reparte el trabajo sepa cual es causa y cual efecto."""

    clave: str
    etiqueta: str
    medicamentos: int
    derivado_de: tuple[str, ...] = ()


def _mascara_campo(tabla: pd.DataFrame, campo: str) -> pd.Series:
    """CAMPOS_CON_DIFERENCIA viene como "CONCENTRACION, DESCRIPCION". Se
    compara por token completo, no por substring: un `str.contains(campo)`
    haria que un campo que sea prefijo de otro se lleve las filas del otro."""
    if "CAMPOS_CON_DIFERENCIA" not in tabla.columns:
        return pd.Series(False, index=tabla.index)
    patron = rf"(?:^|,\s*){re.escape(campo)}\s*(?:,|$)"
    return tabla["CAMPOS_CON_DIFERENCIA"].fillna("").astype(str).str.contains(patron, regex=True)


def _mascara_fecha(tabla: pd.DataFrame, campo: str) -> pd.Series:
    """COHERENCIA_FECHAS_INVIMA es texto explicativo ("Falta actualizar
    FECHA_INICIO en Gemma Net: INVIMA reporta..."), no una lista de campos:
    se busca el nombre del campo mencionado dentro del texto."""
    if "COHERENCIA_FECHAS_INVIMA" not in tabla.columns:
        return pd.Series(False, index=tabla.index)
    return tabla["COHERENCIA_FECHAS_INVIMA"].fillna("").astype(str).str.contains(campo, regex=False)


def _registro_secciones(tabla: pd.DataFrame) -> list[tuple[str, str, tuple[str, ...], pd.Series]]:
    """(clave, etiqueta, derivado_de, mascara) para cada seccion posible.

    UNICA fuente de las secciones: contar y filtrar salen de aca, para que no
    puedan discrepar (que la tarjeta diga 901 y la tabla muestre otra cosa)."""
    registro: list[tuple[str, str, tuple[str, ...], pd.Series]] = []
    for campo in CAMPOS_COMPARADOS_COHERENCIA:
        registro.append(
            (
                f"campo:{campo}",
                ETIQUETAS_CAMPO_DIFERENCIA.get(campo, campo),
                tuple(CAMPOS_DERIVADOS.get(campo, ())),
                _mascara_campo(tabla, campo),
            )
        )
    # Inicio antes que Fin. Pedido del usuario (2026-09-03).
    for campo, etiqueta in (("FECHA_INICIO", "Fecha inicio diferencias"), ("FECHA_FIN", "Fecha fin diferencias")):
        registro.append((f"fecha:{campo}", etiqueta, (), _mascara_fecha(tabla, campo)))
    return registro


#: Orden de los grupos en pantalla: primero los campos del medicamento,
#: despues las fechas contra INVIMA. Dentro de cada grupo se ordena de
#: mayor a menor. Por volumen puro, "Fecha fin" (el 97 %) aplastaria arriba y
#: los campos quedarian de octavos, que es justo lo que se queria poder ver.
_ORDEN_GRUPO_SECCION = {"campo": 0, "fecha": 1}


def secciones_de_diferencia(tabla: pd.DataFrame) -> list[SeccionDiferencia]:
    """Las secciones con al menos un medicamento, agrupadas por tipo.

    Se omiten las de conteo 0 a proposito: aca la seccion no es una dimension
    fija del catalogo (donde un 0 SI informa, ver `dimensiones_calidad`) sino
    un corte de ESTA tarjeta, y una calidad como "No existe en INVIMA" no
    tiene ninguna diferencia de campo que mostrar -- diez tarjetas en cero
    serian ruido justo en el espacio que se libero para ganar claridad."""
    secciones = [
        (indice, SeccionDiferencia(clave=clave, etiqueta=etiqueta, medicamentos=int(mascara.sum()), derivado_de=derivado))
        for indice, (clave, etiqueta, derivado, mascara) in enumerate(_registro_secciones(tabla))
    ]
    # Ordena por grupo, manteniendo el orden de insercion dentro de cada grupo
    # (no por cantidad). Esto permite que Fecha inicio vaya antes que Fecha fin
    # aunque fin tenga mas medicamentos. Pedido del usuario (2026-09-03).
    return [
        s for _, s in sorted(
            ((indice, s) for indice, s in secciones if s.medicamentos > 0),
            key=lambda x: (_ORDEN_GRUPO_SECCION.get(x[1].clave.split(":", 1)[0], 9), x[0]),
        )
    ]


def filtrar_por_seccion(tabla: pd.DataFrame, clave: str) -> pd.DataFrame:
    """Las filas de una seccion. Clave desconocida -> se devuelve la tabla
    entera, no un vacio: mejor mostrar de mas que fingir "no hay hallazgos"
    (que es como se lee una tabla vacia) por una clave vieja en un enlace."""
    for clave_registro, _etiqueta, _derivado, mascara in _registro_secciones(tabla):
        if clave_registro == clave:
            return tabla[mascara]
    return tabla


#: Columnas que acompanan a toda seccion: el codigo y la descripcion para
#: identificar el medicamento, y los tres estados que dicen si vale la pena
#: mirarlo (local, veredicto de INVIMA, y donde vive en INVIMA). Van SIEMPRE
#: al final -- pedido del usuario (2026-09-04): "codigo, descripcion, campo
#: validado, estado en Gemma y estado en INVIMA".
_COLUMNAS_IDENTIFICACION_SECCION = ("CODIGO_INTERNO", "DESCRIPCION")
_COLUMNAS_ESTADO_SECCION = ("ACTIVO", "ESTADO_CUM_INVIMA", "ESTADO_INVIMA")


def columnas_de_seccion(clave: str) -> tuple[str, ...]:
    """Las columnas que hacen falta para ENTENDER una seccion puntual, no las
    38 de la tarjeta completa -- pedido del usuario (2026-09-04): la seccion
    Concentracion mostraba el trio de todos los campos comparados (principio
    activo, ATC, fechas...) cuando solo el trio de CONCENTRACION importa aca.
    Medido: 8 columnas utiles de 38 que viajaban (79 % de mas por pagina).

    Deriva el campo de la clave con el MISMO prefijo (`campo:`/`fecha:`) que
    arma `_registro_secciones`, en vez de mantener una lista aparte: asi
    "que secciones existen" y "que columnas trae cada una" no pueden
    discrepar entre si si algun dia se agrega o quita un campo comparado.

    Clave sin reconocer (o vacia) -> tupla vacia. El llamador la interpreta
    como "no recortar nada" -- degradacion explicita, nunca se inventa una
    lista de columnas para una seccion que no existe."""
    if clave.startswith("campo:"):
        campo = clave.removeprefix("campo:")
        if campo not in CAMPOS_COMPARADOS_COHERENCIA:
            return ()
        return (
            *_COLUMNAS_IDENTIFICACION_SECCION,
            f"{campo}{SUFIJO_GEMANET}",
            f"{campo}{SUFIJO_INVIMA}",
            f"{campo}{SUFIJO_VALIDACION}",
            *_COLUMNAS_ESTADO_SECCION,
        )
    if clave.startswith("fecha:"):
        campo = clave.removeprefix("fecha:")
        par = PARES_FECHAS_GEMANET_INVIMA.get(campo)
        if par is None:
            return ()
        columna_invima, _etiqueta_invima = par
        return (
            *_COLUMNAS_IDENTIFICACION_SECCION,
            campo,
            columna_invima,
            "COHERENCIA_FECHAS_INVIMA",
            *_COLUMNAS_ESTADO_SECCION,
        )
    return ()
