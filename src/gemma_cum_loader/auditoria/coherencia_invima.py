"""Auditoria de coherencia: compara, campo por campo, los medicamentos que
YA existen en el Reporte de Gemma Net contra el dato oficial vigente de
INVIMA (mismo `df_invima` que ya usa el resto del pipeline -- via la API de
Socrata o el Excel de respaldo). Distinto de armado/malla.py (que arma
candidatos NUEVOS): esto audita lo que ya esta cargado, para que el equipo
de TIC/admin sepa que medicamento y que campo puntual esta desactualizado o
mal diligenciado en la base de datos -- pedido explicito del usuario:
"cada campo que no este exactamente igual al reporte de invima deberia
reportar esa falta de homogeneidad".

Alcance de la comparacion: solo los campos que existen en ambos lados.
INVIMA no tiene copagos, edades, cuota moderadora, modelo/nivel de
servicio, etc. -- esos son reglas de negocio propias de Pijao Salud, no hay
con que compararlos (ver armado/reglas_negocio.py para esos).

MARCA_MEDICAMENTO y UNIDAD_MEDIDA en el Reporte de Gemma Net estan
guardadas como CODIGO, no como texto -- se resuelven primero contra el
mismo catalogo interno (config/catalogos/) antes de comparar, via
`catalogos.resolver.texto_por_codigo` (lookup inverso).

Limitacion conocida: si INVIMA tiene mas de una fila para el mismo
CODIGO_INTERNO (medicamento combinado, varios principios activos -- ver
ingesta/invima_reader.py), se compara contra la primera. No hay todavia una
regla de negocio para elegir cual fila combinada es la de referencia.

Un CODIGO_INTERNO que no aparece en Vigentes puede significar varias cosas
muy distintas, y el usuario fue explicito en que NO es aceptable tratarlas
igual ("no nos podemos exponer a autorizar medicamentos que no estan
vigentes a dia de hoy"). Prioridad de mayor a menor riesgo/certeza (cada
paso solo se evalua sobre lo que el paso anterior dejo sin resolver):

  1. VENCIDO_EN_INVIMA -- el registro sanitario SI existio, pero su vigencia
     ya expiro (aparece en el dataset "CODIGO UNICO DE MEDICAMENTOS
     VENCIDOS" de INVIMA, `vwwf-4ftk`). Riesgo real de negocio: seguir
     autorizando un medicamento con esta condicion.
  2. ENCONTRADO_EN_OTRO_ESTADO_INVIMA -- aparece en el dataset "OTROS
     ESTADOS" (`spzp-dfuc`), que agrupa registros Cancelado/Suspendido/
     Inactivo/etc. bajo un solo dataset heterogeneo (confirmado con un caso
     real: `ESTADO REGISTRO = "Inactivo"`) -- se trata con el mismo nivel
     de riesgo que vencido, y `ESTADO_INVIMA_DETALLE` lleva el valor real
     reportado por INVIMA (nunca se esconde detras de una etiqueta
     generica, mismo criterio que TIPO_SIN_CORRESPONDENCIA).
  3. EN_TRAMITE_RENOVACION_INVIMA -- aparece en el dataset "TRAMITE DE
     RENOVACION" (`vgr4-gemg`): el registro sanitario esta en proceso de
     renovarse, riesgo medio (no es lo mismo que vencido) -- informativo
     para que negocio le haga seguimiento, no bloqueante por si solo.
  4. SIN_CORRESPONDENCIA_INVIMA -- el codigo no aparece en NINGUNO de los
     datasets consultados. Normalmente un codigo legado de Gemma Net sin
     expediente INVIMA asociado (ver armado/cruce_gemanet.py) -- no es
     evidencia de que el medicamento no sea seguro, solo de que INVIMA no
     lo tiene identificado con ese EXPEDIENTE-CONSECUTIVO.

`df_invima_vencidos`/`df_invima_otros_estados`/`df_invima_renovacion` son
todos opcionales e independientes: si alguno no se pasa (ej. via el Excel
de respaldo, donde el usuario no siempre provee los 3 archivos auxiliares),
esa distincion puntual simplemente no esta disponible para esa corrida y
todo lo no encontrado cae en el siguiente estado de la cascada como antes
-- degradacion explicita, nunca una suposicion silenciosa.
"""

from __future__ import annotations

from enum import Enum

import pandas as pd

from gemma_cum_loader.armado.reglas_negocio import CLASIFICADO_VALORES_VALIDOS, NIVELES_SERVICIO_VALIDOS
from gemma_cum_loader.catalogos.resolver import EntradaCatalogo, sigla_por_codigo
from gemma_cum_loader.normaliza.texto import normalizar, normalizar_entidad
from gemma_cum_loader.validacion.reglas import es_error_excel


class EstadoCoherencia(Enum):
    CORRECTO = "correcto"
    CON_DIFERENCIAS = "con_diferencias"
    VENCIDO_EN_INVIMA = "vencido_en_invima"
    ENCONTRADO_EN_OTRO_ESTADO_INVIMA = "encontrado_en_otro_estado_invima"
    EN_TRAMITE_RENOVACION_INVIMA = "en_tramite_renovacion_invima"
    SIN_CORRESPONDENCIA_INVIMA = "sin_correspondencia_invima"


# 9 dimensiones de calidad de dato, pedido explicito del usuario ("Carlos me
# explicaba que hay diferentes tipos de calidades... identifica al menos 8",
# y luego 2026-08-19: "la aplicacion en sus reportes debe entregar calidades
# que sirvan para identificar los fallos y facilite encontrar soluciones")
# -- mapeadas al marco estandar de calidad de datos (DAMA-DMBOK), no
# inventadas ad-hoc, para que cada una tenga un nombre y un criterio
# reconocible. Cada columna de hallazgo es, a proposito, un mensaje
# accionable (que campo/codigo puntual, y donde corregirlo) -- no solo un
# indicador agregado:
#
# 1. EXACTITUD     -- ESTADO_COHERENCIA / CAMPOS_CON_DIFERENCIA / PORCENTAJE_CALIDAD
#                      (¿los 7 campos comparables coinciden con el dato oficial de INVIMA?)
# 2. VIGENCIA       -- VENCIDO_EN_INVIMA / ENCONTRADO_EN_OTRO_ESTADO_INVIMA /
#                      EN_TRAMITE_RENOVACION_INVIMA / ESTADO_INVIMA_DETALLE /
#                      TIPO_SIN_CORRESPONDENCIA
#                      (¿el registro sanitario sigue vigente en INVIMA hoy?)
# 3. CONSISTENCIA   -- INCONSISTENCIA_FECHAS_ACTIVO
#                      (¿ACTIVO/FECHA_INICIO/FECHA_FIN son coherentes ENTRE SI?)
# 4. COMPLETITUD    -- PORCENTAJE_COMPLETITUD_REPORTE (nueva, ver _calcular_completitud_reporte)
#                      (¿cuantos de los campos del cargue estan diligenciados en Gemma Net?)
# 5. UNICIDAD       -- CODIGO_DUPLICADO_EN_REPORTE (nueva, ver _detectar_duplicados_en_reporte)
#                      (¿el CODIGO_INTERNO se repite dentro del propio reporte ya cargado?)
# 6. VALIDEZ DE DOMINIO -- VALORES_FUERA_DE_DOMINIO (nueva, ver _validar_dominio_valores)
#                      (¿CLASIFICADO/CODIGO_NIVEL_SERVICIO/POS/ACTIVO estan dentro de sus
#                      valores permitidos oficiales, o traen algo que no deberia existir?)
# 7. RAZONABILIDAD NUMERICA -- INCONSISTENCIA_NUMERICA (nueva, ver _validar_razonabilidad_numerica)
#                      (¿EDAD_MINIMA<=EDAD_MAXIMA, topes de uso en orden dia<=mes<=año<=vida,
#                      nada negativo?)
# 8. CONFORMIDAD DE FORMATO -- FORMATO_CODIGO_INTERNO_INVALIDO (nueva, ver
#                      _validar_formato_codigo_interno)
#                      (¿CODIGO_INTERNO es un valor real, no un error de formula de Excel
#                      guardado como texto ni un campo vacio?)
# 9. INTEGRIDAD REFERENCIAL DE CATALOGO -- INTEGRIDAD_REFERENCIAL_CATALOGO (nueva,
#                      ver _validar_integridad_referencial_catalogo)
#                      (¿el codigo de MARCA_MEDICAMENTO/UNIDAD_MEDIDA que guarda Gemma
#                      Net existe de verdad en el catalogo interno, o es un codigo
#                      huerfano que hoy se confunde con "no coincide con INVIMA"?)


# campo de salida -> (columna en el Reporte de Gemma Net, columna en INVIMA)
# DESCRIPCION, MARCA_MEDICAMENTO y UNIDAD_MEDIDA se arman aparte (ver abajo)
_CAMPOS_DIRECTOS = {
    "CONCENTRACION": ("CONCENTRACION", "CONCENTRACION"),
    "FORMA_FARMACEUTICA": ("FORMA_FARMACEUTICA", "FORMA_FARMACEUTICA"),
    "PRINCIPIO_ACTIVO": ("PRINCIPIO_ACTIVO", "PRINCIPIO_ACTIVO"),
    "CODIGO_ATC": ("CODIGO_ATC", "ATC"),
}

# Los 7 campos que esta auditoria SI puede comparar contra INVIMA (los mismos
# que arma matriz_diferencias) -- expuesto para que la UI pueda ofrecer un
# filtro "por campo puntual" sobre CAMPOS_CON_DIFERENCIA sin duplicar esta
# lista a mano (ver CAMPOS_VERIFICABLES_CARGUE en exportacion/cargue.py,
# mismo patron).
CAMPOS_COMPARADOS_COHERENCIA = [*_CAMPOS_DIRECTOS.keys(), "DESCRIPCION", "MARCA_MEDICAMENTO", "UNIDAD_MEDIDA"]


def _columna_o_vacia(df: pd.DataFrame, nombre: str) -> pd.Series:
    if nombre in df.columns:
        return df[nombre].fillna("").astype(str)
    return pd.Series("", index=df.index)


def _columna_fecha(df: pd.DataFrame, nombre: str) -> pd.Series:
    """Como _columna_o_vacia pero como fecha (NaT si falta, esta vacia, o
    no se puede interpretar) -- fechas invalidas/no parseables se tratan
    como ausentes, nunca como una inconsistencia por si solas (eso seria un
    problema de formato del archivo, no de logica de negocio)."""
    if nombre in df.columns:
        return pd.to_datetime(df[nombre], errors="coerce")
    return pd.Series(pd.NaT, index=df.index)


def _normalizada(serie: pd.Series) -> pd.Series:
    return serie.map(normalizar)


def _validar_fechas_activo(reporte_gemanet: pd.DataFrame) -> pd.Series:
    """Coherencia interna de Gemma Net -- no depende de INVIMA, valida que
    ACTIVO, FECHA_INICIO y FECHA_FIN sean consistentes ENTRE SI dentro del
    propio reporte. Pedido explicito del usuario: "que valide fechas de
    inicio fin y estado vigencia" como parte de las pruebas de calidad de
    esta auditoria.

    Reglas, cada una independiente (se acumulan si aplica mas de una):
    - FECHA_FIN anterior a FECHA_INICIO: imposible en la realidad, un
      medicamento no puede terminar antes de empezar -- error de dato.
    - ACTIVO=NO sin FECHA_FIN registrada: un medicamento desactivado
      deberia tener la fecha en que se desactivo.
    - ACTIVO=SI con FECHA_FIN ya pasada: contradiccion -- dice estar activo
      pero su propia fecha de fin ya paso.
    """
    fecha_inicio = _columna_fecha(reporte_gemanet, "FECHA_INICIO")
    fecha_fin = _columna_fecha(reporte_gemanet, "FECHA_FIN")
    activo = _columna_o_vacia(reporte_gemanet, "ACTIVO").str.strip().str.upper()
    hoy = pd.Timestamp.now().normalize()

    hallazgos = pd.DataFrame(index=reporte_gemanet.index)
    hallazgos["FECHA_FIN anterior a FECHA_INICIO"] = (
        fecha_inicio.notna() & fecha_fin.notna() & (fecha_fin < fecha_inicio)
    )
    hallazgos["ACTIVO=NO sin FECHA_FIN registrada"] = activo.eq("NO") & fecha_fin.isna()
    hallazgos["ACTIVO=SI pero FECHA_FIN ya paso"] = activo.eq("SI") & fecha_fin.notna() & (fecha_fin < hoy)

    return hallazgos.apply(lambda fila: "; ".join(fila.index[fila]), axis=1)


# Los campos del cargue de 37 que SI se esperan diligenciados en el reporte
# ya cargado de Gemma Net -- misma lista de nombres que CAMPOS_CARGUE_GEMANET
# en exportacion/cargue.py, pero declarada aca (no importada) para no acoplar
# este modulo a exportacion/cargue.py -- son 37 nombres estables, el riesgo
# de que diverjan es bajo y el acoplamiento cruzado no vale la pena.
_CAMPOS_COMPLETITUD_REPORTE = [
    "DESCRIPCION", "GRUPO_MEDICAMENTO", "CODIGO_INTERNO", "CONCENTRACION", "POS",
    "CLASIFICADO", "MARCA_MEDICAMENTO", "EXPEDIENTE", "EDAD_MINIMA", "EDAD_MAXIMA",
    "MAXIMA_VECES_DIA", "MAXIMA_VECES_MESES", "MAXIMA_VECES_ANO", "MAXIMA_VECES_VIDA",
    "TIEMPO_LIMITE_DIAS", "CONSECUTIVO", "CRES", "GENERA_COPAGO_RS", "GENERA_COPAGO_RC",
    "GENERA_CUOTA_MODERADORA", "ACTIVO", "POSOLOGIA", "DIAS", "UNIDAD_MEDIDA",
    "AUTOMATICO", "CAMBIO_CANTIDAD", "VALOR", "REGULADO", "VALOR_REGULADO",
    "RESTRINGIDO", "FORMA_FARMACEUTICA", "PRINCIPIO_ACTIVO", "CODIGO_ATC",
    "FECHA_INICIO", "FECHA_FIN", "CODIGO_INTERNO_MODELO_SERVICIO", "CODIGO_NIVEL_SERVICIO",
]

# "-999" confirmado como sentinela real de "sin dato", medido sobre el
# reporte real completo de Gemma Net (data/LISTADO_MEDICAMENTOS12082026.xlsx,
# 199.689 filas, 2026-08-19) -- % de filas con "-999" por campo:
#
#   POSOLOGIA      99.9%   <- el campo entero no se diligencia (ver
#                              _detectar_campos_sistemicamente_no_diligenciados)
#   EXPEDIENTE      0.8%   <- codigo legado sin registro INVIMA (ZIAL, Z-FULL)
#   CONSECUTIVO     0.8%      idem
#   CODIGO_ATC      0.5%
#   CONCENTRACION   0.2%   <- ej. "BARIO SULFATO POLVO O SUSPENSION ORAL"
#
# ACTIVO NO usa este sentinela: trae Si/No reales (55.735 / 143.873). Se
# aclara aqui porque una lectura a ojo del .txt delimitado por "|" desalinea
# facil las columnas y hace parecer que el "-999" de POSOLOGIA pertenece a
# ACTIVO -- de ahi la instruccion del usuario de medir contra el archivo
# real en vez de suponer.
_MARCADORES_VACIOS = {"", "nan", "none", "<na>", "nat", "-999"}


def _calcular_completitud_reporte(reporte_gemanet: pd.DataFrame) -> pd.Series:
    """Calidad #4 -- COMPLETITUD: de los 37 campos del cargue, cuantos estan
    realmente diligenciados (no vacios, no "nan" de texto, no un error de
    Excel) en el reporte YA CARGADO de Gemma Net. Solo cuenta columnas que
    existen en el reporte -- una columna ausente del todo no se penaliza
    aqui (eso ya lo advierte `leer_reporte_gemanet` a otro nivel), esto mide
    completitud DENTRO de lo que el archivo si trae.
    """
    campos_presentes = [c for c in _CAMPOS_COMPLETITUD_REPORTE if c in reporte_gemanet.columns]
    if not campos_presentes:
        return pd.Series(float("nan"), index=reporte_gemanet.index)
    poblado = pd.DataFrame(index=reporte_gemanet.index)
    for campo in campos_presentes:
        valor = _columna_o_vacia(reporte_gemanet, campo).str.strip().str.lower()
        poblado[campo] = ~valor.isin(_MARCADORES_VACIOS) & ~valor.map(es_error_excel)
    return (poblado.sum(axis=1) / len(campos_presentes) * 100).round(1)


# Umbral para considerar que un campo del cargue "no se esta usando" en el
# proceso de origen, en vez de tener datos faltantes puntuales por
# medicamento -- distincion pedida por el usuario al revisar el reporte real
# (2026-08-19). Medido contra el reporte real completo (199.689 filas), dos
# campos superan el umbral:
#
#   POSOLOGIA              99.9% sin dato real ("-999" en 199.452 filas)
#   CODIGO_NIVEL_SERVICIO  98.0% sin dato real (vacio en 195.640 filas; de
#                                lo poblado, la mayoria es "Nivel 1")
#
# Un campo asi ya se refleja fila por fila (completitud / valores fuera de
# dominio), pero se pierde entre cientos de miles de filas -- esta alerta lo
# hace visible a nivel de reporte completo, una sola vez, para que se
# investigue como problema de proceso (¿por que Gemma Net no diligencia este
# campo?) en vez de como un hallazgo puntual mas.
_UMBRAL_CAMPO_SISTEMICAMENTE_VACIO = 90.0


def _detectar_campos_sistemicamente_no_diligenciados(reporte_gemanet: pd.DataFrame) -> list[str]:
    """Para cada campo del cargue que SI esta presente en el reporte, calcula
    que porcentaje de filas trae un marcador de "sin dato" (ver
    _MARCADORES_VACIOS, incluye "-999") -- si un campo entero esta vacio en
    casi todas las filas, es una señal de que ese campo no se esta
    diligenciando en el proceso de origen, no de que cada medicamento tenga
    un dato puntual faltante."""
    advertencias: list[str] = []
    for campo in _CAMPOS_COMPLETITUD_REPORTE:
        if campo not in reporte_gemanet.columns or len(reporte_gemanet) == 0:
            continue
        valor = _columna_o_vacia(reporte_gemanet, campo).str.strip().str.lower()
        vacio = valor.isin(_MARCADORES_VACIOS) | valor.map(es_error_excel)
        porcentaje_vacio = vacio.mean() * 100
        if porcentaje_vacio >= _UMBRAL_CAMPO_SISTEMICAMENTE_VACIO:
            advertencias.append(
                f"El campo {campo} no trae dato real en el {porcentaje_vacio:.1f}% de las filas "
                "de este reporte -- parece no estarse diligenciando en el proceso de origen, no "
                "un dato puntual faltante por medicamento."
            )
    return advertencias


def _detectar_duplicados_en_reporte(reporte_gemanet: pd.DataFrame) -> pd.Series:
    """Calidad #5 -- UNICIDAD: a diferencia de `pipeline.py::_reclasificar_
    duplicados` (que solo revisa duplicados entre candidatos NUEVOS), esto
    revisa si el propio reporte YA CARGADO de Gemma Net tiene un
    CODIGO_INTERNO repetido -- una llave que deberia ser unica en la
    plataforma. Puede ser legitimo (medicamento combinado, una fila por
    principio activo) o un error real de cargue duplicado -- esta funcion
    solo senala el hecho, no decide cual es el caso.
    """
    codigo = reporte_gemanet["CODIGO_INTERNO"].astype(str).str.strip()
    return codigo.duplicated(keep=False) & codigo.ne("")


def _validar_dominio_valores(reporte_gemanet: pd.DataFrame) -> pd.Series:
    """Calidad #6 -- VALIDEZ DE DOMINIO: CLASIFICADO, CODIGO_NIVEL_SERVICIO,
    POS y ACTIVO solo pueden tomar un conjunto fijo y conocido de valores
    (ver armado/reglas_negocio.py, donde este mismo catalogo ya se valida
    para la malla de referencia -- aca se aplica al reporte YA CARGADO de
    Gemma Net, que nunca se habia revisado contra este dominio). Un valor
    fuera de ese conjunto es un dato mal diligenciado, no una variante
    valida no contemplada.
    """
    clasificado = _columna_o_vacia(reporte_gemanet, "CLASIFICADO").str.strip()
    nivel_servicio = _columna_o_vacia(reporte_gemanet, "CODIGO_NIVEL_SERVICIO").str.strip()
    pos = _columna_o_vacia(reporte_gemanet, "POS").str.strip().str.upper()
    activo = _columna_o_vacia(reporte_gemanet, "ACTIVO").str.strip().str.upper()

    hallazgos = pd.DataFrame(index=reporte_gemanet.index)
    hallazgos["CLASIFICADO fuera de dominio"] = clasificado.ne("") & ~clasificado.isin(
        CLASIFICADO_VALORES_VALIDOS
    )
    hallazgos["CODIGO_NIVEL_SERVICIO fuera de dominio"] = nivel_servicio.ne("") & ~nivel_servicio.isin(
        NIVELES_SERVICIO_VALIDOS
    )
    hallazgos["POS fuera de dominio (SI/NO)"] = pos.ne("") & ~pos.isin(["SI", "NO"])
    hallazgos["ACTIVO fuera de dominio (SI/NO)"] = activo.ne("") & ~activo.isin(["SI", "NO"])

    return hallazgos.apply(lambda fila: "; ".join(fila.index[fila]), axis=1)


def _a_numero(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce")


def _validar_razonabilidad_numerica(reporte_gemanet: pd.DataFrame) -> pd.Series:
    """Calidad #7 -- RAZONABILIDAD NUMERICA: los topes de uso y edades del
    cargue tienen un orden logico obligatorio, sin importar el valor exacto
    de cada uno -- nunca se habia verificado esto contra el reporte ya
    cargado. Valores no numericos/ausentes se tratan como "no aplica" (NaN),
    nunca como una inconsistencia por si solos -- mismo criterio que
    `_validar_fechas_activo` para fechas invalidas.
    """
    edad_min = _a_numero(_columna_o_vacia(reporte_gemanet, "EDAD_MINIMA"))
    edad_max = _a_numero(_columna_o_vacia(reporte_gemanet, "EDAD_MAXIMA"))
    veces_dia = _a_numero(_columna_o_vacia(reporte_gemanet, "MAXIMA_VECES_DIA"))
    veces_mes = _a_numero(_columna_o_vacia(reporte_gemanet, "MAXIMA_VECES_MESES"))
    veces_ano = _a_numero(_columna_o_vacia(reporte_gemanet, "MAXIMA_VECES_ANO"))
    veces_vida = _a_numero(_columna_o_vacia(reporte_gemanet, "MAXIMA_VECES_VIDA"))

    hallazgos = pd.DataFrame(index=reporte_gemanet.index)
    hallazgos["EDAD_MINIMA mayor a EDAD_MAXIMA"] = (
        edad_min.notna() & edad_max.notna() & (edad_min > edad_max)
    )
    hallazgos["MAXIMA_VECES_DIA mayor a MAXIMA_VECES_MESES"] = (
        veces_dia.notna() & veces_mes.notna() & (veces_dia > veces_mes)
    )
    hallazgos["MAXIMA_VECES_MESES mayor a MAXIMA_VECES_ANO"] = (
        veces_mes.notna() & veces_ano.notna() & (veces_mes > veces_ano)
    )
    hallazgos["MAXIMA_VECES_ANO mayor a MAXIMA_VECES_VIDA"] = (
        veces_ano.notna() & veces_vida.notna() & (veces_ano > veces_vida)
    )
    for campo, serie in [
        ("EDAD_MINIMA", edad_min), ("EDAD_MAXIMA", edad_max), ("MAXIMA_VECES_DIA", veces_dia),
        ("MAXIMA_VECES_MESES", veces_mes), ("MAXIMA_VECES_ANO", veces_ano), ("MAXIMA_VECES_VIDA", veces_vida),
    ]:
        hallazgos[f"{campo} negativo"] = serie.notna() & (serie < 0)

    return hallazgos.apply(lambda fila: "; ".join(fila.index[fila]), axis=1)


def _validar_formato_codigo_interno(reporte_gemanet: pd.DataFrame) -> pd.Series:
    """Calidad #8 -- CONFORMIDAD DE FORMATO: CODIGO_INTERNO es la llave de
    toda la fila -- si es un error de formula de Excel guardado como texto
    (#N/A, #NAME?...) o esta vacio, nada mas de la fila es confiable. Mismo
    chequeo que `validacion/reglas.py::filtro_codigo_interno_valido` usa
    para candidatos NUEVOS, aplicado aca al reporte YA CARGADO."""
    codigo = _columna_o_vacia(reporte_gemanet, "CODIGO_INTERNO").str.strip()
    vacio_o_roto = codigo.str.lower().isin(_MARCADORES_VACIOS)
    error_excel = codigo.map(es_error_excel)
    return pd.Series("", index=reporte_gemanet.index).mask(
        vacio_o_roto, "CODIGO_INTERNO vacio o invalido"
    ).mask(error_excel, "CODIGO_INTERNO es un error de formula de Excel guardado como texto")


def _validar_integridad_referencial_catalogo(
    reporte_gemanet: pd.DataFrame,
    catalogo_unidad: list[EntradaCatalogo],
    catalogo_marca: list[EntradaCatalogo],
) -> pd.Series:
    """Calidad #9 -- INTEGRIDAD REFERENCIAL DE CATALOGO (pedido explicito
    del usuario, 2026-08-19: "la aplicacion en sus reportes debe entregar
    calidades que sirvan para identificar los fallos y facilite encontrar
    soluciones"): MARCA_MEDICAMENTO y UNIDAD_MEDIDA en el Reporte de Gemma
    Net son codigos que DEBERIAN existir en el catalogo interno (config/
    catalogos/) -- un codigo que no existe ahi es un problema de
    mantenimiento de catalogo, distinto (y hoy invisible) de "el valor no
    coincide con INVIMA": sin esto, un codigo huerfano se resuelve en
    silencio a texto vacio (ver sigla_por_codigo) y sale como
    CON_DIFERENCIAS -- un diagnostico enganoso, parece un problema de
    digitacion frente a INVIMA cuando en realidad el codigo ni siquiera
    esta en nuestro propio catalogo. El mensaje es accionable: dice
    exactamente que codigo falta y en que archivo agregarlo.

    Hallazgo real contra el reporte de produccion (`data/LISTADO_
    MEDICAMENTOS12082026.xlsx`, verificado 2026-08-19): 1 fila de marca y
    23 de unidad con codigo huerfano, de ~199.590.
    """
    codigos_unidad_validos = {e.codigo for e in catalogo_unidad}
    codigos_marca_validos = {e.codigo for e in catalogo_marca}

    marca = _columna_o_vacia(reporte_gemanet, "MARCA_MEDICAMENTO").map(_a_entero)
    unidad = _columna_o_vacia(reporte_gemanet, "UNIDAD_MEDIDA").map(_a_entero)

    marca_huerfana = marca.notna() & ~marca.isin(codigos_marca_validos)
    unidad_huerfana = unidad.notna() & ~unidad.isin(codigos_unidad_validos)

    resultado = pd.Series("", index=reporte_gemanet.index)
    for idx in reporte_gemanet.index[marca_huerfana | unidad_huerfana]:
        partes = []
        if marca_huerfana.loc[idx]:
            partes.append(
                f"MARCA_MEDICAMENTO (codigo {marca.loc[idx]}) no existe en el catalogo interno "
                "-- verificar/agregar en config/catalogos/marca_medicamento.csv"
            )
        if unidad_huerfana.loc[idx]:
            partes.append(
                f"UNIDAD_MEDIDA (codigo {unidad.loc[idx]}) no existe en el catalogo interno "
                "-- verificar/agregar en config/catalogos/unidad_medida.csv"
            )
        resultado.loc[idx] = "; ".join(partes)
    return resultado


def _aplicar_dataset_auxiliar(
    estado: pd.Series,
    detalle: pd.Series,
    gemanet_codigos: pd.Series,
    df_auxiliar: pd.DataFrame | None,
    estado_valor: str,
) -> tuple[pd.Series, pd.Series]:
    """Marca con `estado_valor` los codigos AUN sin resolver (estado sigue
    en SIN_CORRESPONDENCIA_INVIMA) que SI aparecen en `df_auxiliar`, y deja
    en `detalle` el ESTADO_REGISTRO real reportado por INVIMA para ese
    codigo (primera fila si el dataset trae mas de una) -- nunca sobre-
    escribe un estado ya resuelto por un dataset de mayor prioridad (ver
    orden de llamada en auditar_coherencia: Vencidos, luego Otros Estados,
    luego Tramite de Renovacion)."""
    if df_auxiliar is None or df_auxiliar.empty:
        return estado, detalle
    auxiliar = df_auxiliar.dropna(subset=["CODIGO_INTERNO"]).drop_duplicates(
        subset="CODIGO_INTERNO", keep="first"
    )
    auxiliar_indexado = auxiliar.set_index(auxiliar["CODIGO_INTERNO"].astype(str).str.strip())
    aun_sin_resolver = estado == EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value
    coincide = aun_sin_resolver & gemanet_codigos.isin(auxiliar_indexado.index)
    estado = estado.where(~coincide, estado_valor)
    if "ESTADO_REGISTRO" in auxiliar_indexado.columns:
        valores_detalle = gemanet_codigos.map(auxiliar_indexado["ESTADO_REGISTRO"].astype(str).str.strip())
        detalle = detalle.where(~coincide, valores_detalle)
    return estado, detalle


# Valor real de ESTADO_REGISTRO dentro de Otros Estados que en realidad
# significa lo mismo que el dataset separado de Tramite de Renovacion --
# confirmado contra el archivo real de Otros Estados (2026-08-19,
# ListadoCodigounicoOtrosEstado2022.xlsx): "Temp. no comercializado - En
# Tramite Renov", 2.496 filas de 77.760. Decision confirmada por el
# usuario via AskUserQuestion: se reclasifica como EN_TRAMITE_RENOVACION_
# INVIMA (riesgo medio) en vez de ENCONTRADO_EN_OTRO_ESTADO_INVIMA (riesgo
# alto) -- el propio texto dice que sigue vigente mientras se renueva, no
# es lo mismo que Cancelado/Revocado/Negado/etc. Coincidencia por
# substring normalizado (no exacto) porque el archivo real trae el
# encabezado con un caracter mal codificado ("Tr?mite"/"Tr�mite"
# segun el origen) -- `normalizar()` ya lo reduce a "TRAMITE" de forma
# robusta sin depender de que la tilde este bien codificada.
_FRAGMENTO_RENOVACION_EN_OTROS_ESTADOS = "TRAMITE RENOV"


def _separar_renovacion_de_otros_estados(
    df_otros_estados: pd.DataFrame | None,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Devuelve (otros_estados_sin_el_solape, subset_que_es_renovacion) --
    ver _FRAGMENTO_RENOVACION_EN_OTROS_ESTADOS."""
    if df_otros_estados is None or df_otros_estados.empty or "ESTADO_REGISTRO" not in df_otros_estados.columns:
        return df_otros_estados, None
    es_renovacion = (
        df_otros_estados["ESTADO_REGISTRO"]
        .astype(str)
        .map(normalizar)
        .str.contains(_FRAGMENTO_RENOVACION_EN_OTROS_ESTADOS, na=False)
    )
    return df_otros_estados[~es_renovacion], df_otros_estados[es_renovacion]


def _a_entero(valor: object) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def auditar_coherencia(
    reporte_gemanet: pd.DataFrame,
    df_invima: pd.DataFrame,
    catalogo_unidad: list[EntradaCatalogo],
    catalogo_marca: list[EntradaCatalogo],
    df_invima_vencidos: pd.DataFrame | None = None,
    df_invima_otros_estados: pd.DataFrame | None = None,
    df_invima_renovacion: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Una fila por CODIGO_INTERNO del Reporte de Gemma Net, con
    ESTADO_COHERENCIA (correcto / con_diferencias / vencido_en_invima /
    encontrado_en_otro_estado_invima / en_tramite_renovacion_invima /
    sin_correspondencia_invima), CAMPOS_CON_DIFERENCIA (nombres de campo
    separados por coma, vacio si esta correcto o no hay correspondencia) y
    PORCENTAJE_CALIDAD (0-100, cuantos de los campos comparables SI
    coinciden con INVIMA -- NaN si no hay correspondencia, no hay nada que
    comparar). Un "hallazgo" (con_diferencias) significa que el medicamento
    SI existe y SI tiene correspondencia con INVIMA (mismo EXPEDIENTE-
    CONSECUTIVO) -- es un pedido de actualizacion de dato puntual, no un
    rechazo ni una cuarentena (eso es candidatos nuevos, ver armado/malla.py).

    df_invima_vencidos / df_invima_otros_estados / df_invima_renovacion
    (todos opcionales e independientes entre si): catalogos de los datasets
    "VENCIDOS", "OTROS ESTADOS" y "TRAMITE DE RENOVACION" de INVIMA (misma
    forma que df_invima). Si se proveen, un CODIGO_INTERNO que no aparece en
    df_invima pero SI aparece en alguno de estos se marca con el estado
    correspondiente en vez de SIN_CORRESPONDENCIA_INVIMA -- prioridad
    VENCIDO_EN_INVIMA > ENCONTRADO_EN_OTRO_ESTADO_INVIMA >
    EN_TRAMITE_RENOVACION_INVIMA (ver el docstring del modulo para por que
    esta distincion es un requisito de negocio, no un detalle cosmetico).

    ESTADO_INVIMA_DETALLE: vacio salvo para filas ENCONTRADO_EN_OTRO_ESTADO_
    INVIMA o EN_TRAMITE_RENOVACION_INVIMA, donde lleva el ESTADO_REGISTRO
    real reportado por INVIMA en ese dataset (p.ej. "Inactivo", "Cancelado")
    -- Otros Estados es un dataset heterogeneo por naturaleza, esto evita
    esconder el valor real detras de una etiqueta generica.

    TIPO_SIN_CORRESPONDENCIA (solo poblado cuando ESTADO_COHERENCIA queda en
    sin_correspondencia_invima): distingue un codigo que SIGUE el formato
    EXPEDIENTE-CONSECUTIVO pero no aparece en INVIMA (posible error de
    digitacion o registro anulado -- amerita revision puntual) de uno que
    es codigo legado de texto libre (nunca tuvo expediente INVIMA, no hay
    nada que revisar ahi). Vacio para las demas filas.

    INCONSISTENCIA_FECHAS_ACTIVO: coherencia interna de Gemma Net (no
    depende de INVIMA) entre ACTIVO/FECHA_INICIO/FECHA_FIN -- ver
    `_validar_fechas_activo` -- mas la combinacion de mayor riesgo posible:
    ACTIVO=SI junto con VENCIDO_EN_INVIMA. Vacio si no hay ningun hallazgo;
    varios hallazgos se separan con "; ".
    """
    # sigla_por_codigo, no texto_por_codigo: la sigla ya esta normalizada en
    # la misma forma corta que INVIMA reporta el dato crudo (ej. "MG", no
    # "MG - MILIGRAMO") -- ver su docstring para el bug real que esto corrige.
    sigla_unidad = sigla_por_codigo(catalogo_unidad)
    sigla_marca = sigla_por_codigo(catalogo_marca)

    gemanet = reporte_gemanet.copy()
    gemanet["CODIGO_INTERNO"] = gemanet["CODIGO_INTERNO"].astype(str).str.strip()
    gemanet["_MARCA_TEXTO"] = _columna_o_vacia(gemanet, "MARCA_MEDICAMENTO").map(
        lambda c: sigla_marca.get(_a_entero(c), "")
    )
    gemanet["_UNIDAD_TEXTO"] = _columna_o_vacia(gemanet, "UNIDAD_MEDIDA").map(
        lambda c: sigla_unidad.get(_a_entero(c), "")
    )

    invima = df_invima.drop_duplicates(subset="CODIGO_INTERNO", keep="first").copy()
    invima["_DESCRIPCION_ESPERADA"] = (
        _columna_o_vacia(invima, "PRINCIPIO_ACTIVO").str.strip()
        + " "
        + _columna_o_vacia(invima, "UNIDAD_REFERENCIA").str.strip()
    ).str.strip()

    columnas_invima = ["CODIGO_INTERNO", "TITULAR", "UNIDAD_MEDIDA", "_DESCRIPCION_ESPERADA"] + [
        col_invima for _, col_invima in _CAMPOS_DIRECTOS.values() if col_invima in invima.columns
    ]
    invima_reducido = invima[[c for c in dict.fromkeys(columnas_invima) if c in invima.columns]]
    invima_reducido = invima_reducido.add_suffix("_INVIMA").rename(
        columns={"CODIGO_INTERNO_INVIMA": "CODIGO_INTERNO"}
    )

    combinado = gemanet.merge(invima_reducido, on="CODIGO_INTERNO", how="left", indicator=True)
    tiene_correspondencia = combinado["_merge"] == "both"

    matriz_diferencias = pd.DataFrame(index=combinado.index)
    for campo, (col_gemanet, col_invima) in _CAMPOS_DIRECTOS.items():
        matriz_diferencias[campo] = _normalizada(_columna_o_vacia(combinado, col_gemanet)) != _normalizada(
            _columna_o_vacia(combinado, f"{col_invima}_INVIMA")
        )
    matriz_diferencias["DESCRIPCION"] = _normalizada(
        _columna_o_vacia(combinado, "DESCRIPCION")
    ) != _normalizada(_columna_o_vacia(combinado, "_DESCRIPCION_ESPERADA_INVIMA"))
    # normalizar_entidad, no normalizar: "_MARCA_TEXTO" (sigla_por_codigo del
    # catalogo de marca) ya paso por normalizar_entidad -- comparar contra
    # el TITULAR crudo de INVIMA con la misma normalizacion evita falsos
    # "con_diferencias" por sufijo societario o calificador de planta (ver
    # normalizar_entidad, mismo criterio que usa la resolucion de marca).
    matriz_diferencias["MARCA_MEDICAMENTO"] = combinado["_MARCA_TEXTO"] != _columna_o_vacia(
        combinado, "TITULAR_INVIMA"
    ).map(normalizar_entidad)
    matriz_diferencias["UNIDAD_MEDIDA"] = _normalizada(
        combinado["_UNIDAD_TEXTO"]
    ) != _normalizada(_columna_o_vacia(combinado, "UNIDAD_MEDIDA_INVIMA"))

    campos_con_diferencia = matriz_diferencias.apply(
        lambda fila: ", ".join(fila.index[fila]), axis=1
    )
    campos_con_diferencia = campos_con_diferencia.where(tiene_correspondencia, "")

    # % de calidad: de los campos que SI se pudieron comparar contra INVIMA,
    # cuantos coinciden -- pedido explicito del usuario: aunque un
    # medicamento tenga correspondencia (mismo EXPEDIENTE-CONSECUTIVO), el
    # reporte debe decir que tan alineados estan sus datos con el oficial,
    # no solo "correcto"/"con_diferencias" en blanco y negro. NaN (no 0% ni
    # 100%) cuando no hay correspondencia -- no hay nada que comparar, no es
    # lo mismo que "0% de calidad".
    total_campos_comparables = len(matriz_diferencias.columns)
    campos_ok = total_campos_comparables - matriz_diferencias.sum(axis=1)
    porcentaje_calidad = (campos_ok / total_campos_comparables * 100).round(1)
    porcentaje_calidad = porcentaje_calidad.where(tiene_correspondencia)

    estado = pd.Series(EstadoCoherencia.CORRECTO.value, index=combinado.index)
    estado = estado.where(campos_con_diferencia == "", EstadoCoherencia.CON_DIFERENCIAS.value)
    estado = estado.where(tiene_correspondencia, EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value)

    if df_invima_vencidos is not None and not df_invima_vencidos.empty:
        codigos_vencidos = set(
            df_invima_vencidos["CODIGO_INTERNO"].dropna().astype(str).str.strip()
        )
        es_vencido = (~tiene_correspondencia) & gemanet["CODIGO_INTERNO"].isin(codigos_vencidos)
        estado = estado.where(~es_vencido, EstadoCoherencia.VENCIDO_EN_INVIMA.value)

    # Otros Estados y Tramite de Renovacion solo se evaluan sobre lo que
    # Vencidos dejo sin resolver -- ver _aplicar_dataset_auxiliar y el orden
    # de prioridad documentado en el docstring de esta funcion. Antes de
    # aplicar Otros Estados, se separa el subset que en realidad es
    # renovacion (ver _separar_renovacion_de_otros_estados) para que se
    # evalue junto con el dataset dedicado de Renovacion, no como riesgo alto.
    otros_estados_resto, otros_estados_como_renovacion = _separar_renovacion_de_otros_estados(
        df_invima_otros_estados
    )
    df_renovacion_combinado = pd.concat(
        [d for d in [df_invima_renovacion, otros_estados_como_renovacion] if d is not None and not d.empty],
        ignore_index=True,
    ) if any(d is not None and not d.empty for d in [df_invima_renovacion, otros_estados_como_renovacion]) else None

    estado_invima_detalle = pd.Series("", index=combinado.index)
    estado, estado_invima_detalle = _aplicar_dataset_auxiliar(
        estado, estado_invima_detalle, gemanet["CODIGO_INTERNO"],
        otros_estados_resto, EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value,
    )
    estado, estado_invima_detalle = _aplicar_dataset_auxiliar(
        estado, estado_invima_detalle, gemanet["CODIGO_INTERNO"],
        df_renovacion_combinado, EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value,
    )

    # "sin_correspondencia_invima" a secas no distingue dos poblaciones muy
    # distintas -- ver docstring del modulo y el hallazgo real de fase 6
    # (armado/cruce_gemanet.py: 33.2% de los codigos de Gemma Net son
    # legado en texto libre, sin patron EXPEDIENTE-CONSECUTIVO). Un codigo
    # que SI sigue el patron pero no aparece en INVIMA es una señal
    # distinta -- posible error de digitacion o un registro que ya no
    # existe ahi, no simplemente "nunca tuvo expediente".
    es_sin_correspondencia_final = estado == EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value
    parece_codigo_invima = gemanet["CODIGO_INTERNO"].str.match(r"^\d+-\d+$")
    tipo_sin_correspondencia = pd.Series("", index=combinado.index)
    tipo_sin_correspondencia = tipo_sin_correspondencia.mask(
        es_sin_correspondencia_final & parece_codigo_invima,
        "Formato EXPEDIENTE-CONSECUTIVO, no encontrado en INVIMA -- verificar si el "
        "registro fue anulado o el codigo tiene un error de digitacion",
    )
    tipo_sin_correspondencia = tipo_sin_correspondencia.mask(
        es_sin_correspondencia_final & ~parece_codigo_invima,
        "Codigo legado (no sigue el formato EXPEDIENTE-CONSECUTIVO) -- no se puede "
        "verificar contra INVIMA por este medio",
    )

    # Coherencia interna de fechas/vigencia (no depende de INVIMA, ver
    # _validar_fechas_activo) + la combinacion mas urgente posible: un
    # medicamento que Gemma Net dice ACTIVO=SI pero cuyo registro sanitario
    # ya vencio en INVIMA -- pedido explicito del usuario ("que valide...
    # estado vigencia"). VENCIDO_EN_INVIMA ya es su propio estado (riesgo
    # alto), esto lo hace explicito en una columna aparte para que no dependa
    # de leer ESTADO_COHERENCIA para notar la combinacion con ACTIVO.
    inconsistencia_fechas = _validar_fechas_activo(reporte_gemanet)
    activo_gemanet = _columna_o_vacia(reporte_gemanet, "ACTIVO").str.strip().str.upper()
    activo_vencido_en_invima = activo_gemanet.eq("SI") & (estado.values == EstadoCoherencia.VENCIDO_EN_INVIMA.value)
    inconsistencia_fechas = inconsistencia_fechas.mask(
        activo_vencido_en_invima & (inconsistencia_fechas == ""),
        "ACTIVO=SI pero el registro sanitario esta VENCIDO en INVIMA",
    )
    inconsistencia_fechas = inconsistencia_fechas.mask(
        activo_vencido_en_invima & (inconsistencia_fechas != ""),
        inconsistencia_fechas + "; ACTIVO=SI pero el registro sanitario esta VENCIDO en INVIMA",
    )

    resultado = reporte_gemanet.copy()
    resultado["CODIGO_INTERNO"] = gemanet["CODIGO_INTERNO"].values
    resultado["ESTADO_COHERENCIA"] = estado.values
    resultado["ESTADO_INVIMA_DETALLE"] = estado_invima_detalle.values
    resultado["CAMPOS_CON_DIFERENCIA"] = campos_con_diferencia.values
    resultado["PORCENTAJE_CALIDAD"] = porcentaje_calidad.values
    resultado["TIPO_SIN_CORRESPONDENCIA"] = tipo_sin_correspondencia.values
    resultado["INCONSISTENCIA_FECHAS_ACTIVO"] = inconsistencia_fechas.values
    # Calidades #4-9 -- ver el comentario junto a EstadoCoherencia con el
    # mapeo completo de las 9 dimensiones de calidad de dato.
    resultado["PORCENTAJE_COMPLETITUD_REPORTE"] = _calcular_completitud_reporte(reporte_gemanet).values
    resultado["CODIGO_DUPLICADO_EN_REPORTE"] = _detectar_duplicados_en_reporte(reporte_gemanet).values
    resultado["VALORES_FUERA_DE_DOMINIO"] = _validar_dominio_valores(reporte_gemanet).values
    resultado["INCONSISTENCIA_NUMERICA"] = _validar_razonabilidad_numerica(reporte_gemanet).values
    resultado["FORMATO_CODIGO_INTERNO_INVALIDO"] = _validar_formato_codigo_interno(reporte_gemanet).values
    resultado["INTEGRIDAD_REFERENCIAL_CATALOGO"] = _validar_integridad_referencial_catalogo(
        reporte_gemanet, catalogo_unidad, catalogo_marca
    ).values
    resultado.attrs["advertencias_calidad"] = _detectar_campos_sistemicamente_no_diligenciados(reporte_gemanet)
    return resultado
