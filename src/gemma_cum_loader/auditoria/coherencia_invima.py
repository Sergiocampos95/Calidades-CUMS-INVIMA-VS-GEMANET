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

from collections.abc import Callable
from enum import Enum

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from gemma_cum_loader.armado.reglas_negocio import (
    CLASIFICADO_VALORES_VALIDOS,
    NIVELES_SERVICIO_VALIDOS,
)
from gemma_cum_loader.catalogos.resolver import (
    FALLBACK_CODIGO,
    EntradaCatalogo,
    sigla_por_codigo,
    siglas_por_codigo,
)
from gemma_cum_loader.normaliza.codigos import PATRON_CUM, clasificar_codigos
from gemma_cum_loader.normaliza.texto import normalizar, normalizar_entidad
from gemma_cum_loader.validacion.reglas import es_error_excel


class EstadoCoherencia(Enum):
    CORRECTO = "correcto"
    CON_DIFERENCIAS = "con_diferencias"
    VENCIDO_EN_INVIMA = "vencido_en_invima"
    ENCONTRADO_EN_OTRO_ESTADO_INVIMA = "encontrado_en_otro_estado_invima"
    EN_TRAMITE_RENOVACION_INVIMA = "en_tramite_renovacion_invima"
    # Aparece en Otros Estados pero el propio texto de INVIMA dice "Vigente":
    # el registro sanitario esta al dia y el producto solo no se esta
    # comercializando ahora. No es riesgo de vigencia -- ver
    # _FRAGMENTO_VIGENTE_EN_OTROS_ESTADOS.
    VIGENTE_NO_COMERCIALIZADO_INVIMA = "vigente_no_comercializado_invima"
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
# 10. CONTRASTE DE VIGENCIA -- NOVEDAD_VIGENCIA_INVIMA / DETALLE_VIGENCIA_INVIMA
#                      (ver _contrastar_vigencia_invima; pedido de negocio del
#                      2026-08-20). Las dimensiones 1-9 miran el dato local o lo
#                      comparan campo a campo; esta pregunta algo distinto: ¿que
#                      dice INVIMA de la VIGENCIA de las filas cuya fecha local es
#                      un comodin y no se puede interpretar sola? De ahi salen las
#                      novedades concretas: una fecha que falta aca y existe alla,
#                      un medicamento inactivo en la plataforma pero vigente en
#                      INVIMA, o activo aca e inactivo alla (el de mayor riesgo).
#                      Nunca se corrige nada: se entrega la novedad con las fechas
#                      de los dos lados para que una persona decida.
#
# TIPO_CODIGO_INTERNO -- columna de CONTEXTO, no una dimension #11 (ver
#                      clasificar_codigos() en normaliza/codigos.py). Una
#                      dimension implica un veredicto de bien/mal; aqui no
#                      lo hay -- un codigo_propio de Pijao Salud es un dato
#                      legitimo, no un hallazgo. Por eso NO entra en
#                      PORCENTAJE_CALIDAD, NATURALEZA_HALLAZGO ni
#                      ACCION_SUGERIDA. Investigado contra produccion real
#                      el 2026-08-26 (ver design/tipos_codigo_interno.md);
#                      la capa legada "atc_expediente_consecutivo" (un
#                      tercio del reporte, 0% activa) se reporta ademas como
#                      advertencia agregada (_detectar_capa_legada_atc), no
#                      fila por fila -- y nunca dispara fusion ni
#                      deduplicado de CODIGO_INTERNO.


# campo de salida -> (columna en el Reporte de Gemma Net, columna en INVIMA)
# DESCRIPCION, MARCA_MEDICAMENTO y UNIDAD_MEDIDA se arman aparte (ver abajo)
#
# CONCENTRACION de Gemma Net NO guarda una concentracion: guarda la
# PRESENTACION COMERCIAL ("CAJA POR 100 TABLETAS EN BLISTER PVC/ALUMINIO"),
# que en INVIMA vive en DESCRIPCION_COMERCIAL y no en su columna homonima.
# Compararla contra CONCENTRACION de INVIMA -- que si es una concentracion
# ("500 mg") -- fallaba en el 100 % de las filas. Medido el 2026-08-21 sobre
# las 43.266 filas con correspondencia, cruzando cada campo local contra
# TODOS los de INVIMA:
#
#     contra CONCENTRACION de INVIMA          2 exactas ( 0,0 %)  similitud  3,2
#     contra DESCRIPCION_COMERCIAL       42.338 exactas (97,9 %)  similitud 100,0
#
# Era el unico campo que fallaba siempre, y por eso ESTADO_COHERENCIA=correcto
# daba CERO en todo el reporte y PORCENTAJE_CALIDAD no podia pasar de 85,7 %.
# El nombre de salida se deja como CONCENTRACION porque es el que ya usan la
# UI y el Excel de cargue; lo que contiene esta documentado aca.
_CAMPOS_DIRECTOS = {
    "CONCENTRACION": ("CONCENTRACION", "DESCRIPCION_COMERCIAL"),
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

# Campos que NO son un dato independiente: se construyen a partir de otros. Si
# el campo de origen difiere, el derivado difiere por consecuencia -- siempre.
#
# Importa para leer bien el reporte. Medido contra produccion el 2026-08-21:
# de las 12.517 filas con alguna diferencia, 5.319 fallan a la vez en
# PRINCIPIO_ACTIVO y DESCRIPCION, y otras 4.349 solo en DESCRIPCION. Las
# primeras NO tienen dos problemas: tienen uno contado dos veces, y ademas
# quedan penalizadas doble en PORCENTAJE_CALIDAD por la misma causa raiz.
# Corregir el principio activo arregla los dos campos de una vez.
#
# No se descuenta automaticamente del conteo: eso ocultaria que la descripcion
# guardada esta mal, que es un hecho. Se declara para que quien reparte el
# trabajo sepa cual es causa y cual efecto.
CAMPOS_DERIVADOS = {
    "DESCRIPCION": ("PRINCIPIO_ACTIVO", "UNIDAD_MEDIDA"),
}


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


def _columnas_marcadas(df_booleano: pd.DataFrame, separador: str) -> pd.Series:
    """Vectoriza `df.apply(lambda fila: separador.join(fila.index[fila]), axis=1)`.

    `DataFrame.apply(axis=1)` reconstruye una Series de pandas por fila --
    medido a escala real (199.689 filas, ver benchmark de rendimiento en
    README) eso tomaba ~6s POR LLAMADA, y esta funcion se usa 4 veces en la
    auditoria completa. Recorrer directamente el array de numpy subyacente
    evita esa reconstruccion (~35x mas rapido en el mismo benchmark) y
    produce exactamente el mismo resultado: las columnas True de una fila
    booleana son las mismas sin importar si se leen desde una Series o
    desde la fila cruda del array, mismo orden de columnas.
    """
    columnas = df_booleano.columns.to_numpy()
    return pd.Series(
        [separador.join(columnas[fila]) for fila in df_booleano.to_numpy()],
        index=df_booleano.index,
    )


# Fechas comodin de Gemma Net: NO son fechas, son "sin dato" -- el equivalente
# de -999 para los numericos. Origen confirmado por negocio (Carlos, 2026-08-20):
# son residuo de la migracion de Gemma Net de local a la nube, donde al poblar
# los datos se asignaron estos valores frente a los nulos. No son errores de
# digitacion y no se corrigen fila por fila.
#
# Medido sobre la base real (administrativo.tb_medicamento, 199.608 filas):
#
#   2999-12-31   48.498 filas   88% activos  <- "no expira"; el mismo comodin que
#                                               usa la consulta de RIPS de Pijao
#                                               (coalesce(fecha_fin, '2999-12-31'))
#   1900-01-01   13.815 filas   59% activos  <- "sin fecha" (residuo de migracion)
#   NULL          5.797 filas   72% activos  <- "sin fecha"
#   fecha real  128.312 filas  0,6% activos  <- vencido de verdad: cuando la fecha
#                                               es real, el sistema SI la respeta
#
# Compararlas como fechas producia 13.815 hallazgos falsos en la dimension 3.
# 1899-12-30 es el cero del calendario serial de Excel (aparece como minimo de
# fecha_inicio en la base): mismo caso.
# Como enteros AAAAMMDD y no como Timestamp a proposito: `2999-12-31` esta
# FUERA del rango de datetime64[ns] de pandas (tope 2262-04-11), asi que
# construir ese Timestamp lanza OutOfBoundsDatetime. Comparar por componentes
# ademas funciona igual sea cual sea la unidad de la columna (ns, us, s), que
# varia segun venga de Excel o de Postgres.
FECHAS_CENTINELA = frozenset({19000101, 18991230, 29991231})


def _es_fecha_real(serie: pd.Series) -> pd.Series:
    """True donde la fecha es un dato de verdad, no un comodin ni un vacio."""
    if not pd.api.types.is_datetime64_any_dtype(serie):
        serie = pd.to_datetime(serie, errors="coerce")
    aaaammdd = serie.dt.year * 10000 + serie.dt.month * 100 + serie.dt.day
    return serie.notna() & ~aaaammdd.isin(FECHAS_CENTINELA)


def _es_fecha_comodin(serie: pd.Series) -> pd.Series:
    """True solo en el comodin -- distinto de `~_es_fecha_real`, que tambien
    marca el vacio. La diferencia importa: un comodin es una fecha que la
    migracion ESCRIBIO para no dejar la celda en blanco, y un vacio es una
    fecha que nadie diligencio. Se atienden distinto (ver
    `_clasificar_naturaleza_hallazgo`)."""
    if not pd.api.types.is_datetime64_any_dtype(serie):
        serie = pd.to_datetime(serie, errors="coerce")
    aaaammdd = serie.dt.year * 10000 + serie.dt.month * 100 + serie.dt.day
    return serie.notna() & aaaammdd.isin(FECHAS_CENTINELA)


def _unir_no_vacios(df: pd.DataFrame, separador: str, index=None) -> pd.Series:
    """Une los valores no vacios de cada fila, vectorizado.

    Hermano de `_columnas_marcadas`, para cuando lo que hay que unir son los
    VALORES de las celdas y no los nombres de las columnas. Existe por la
    misma razon: `DataFrame.apply(axis=1)` reconstruye una Series de pandas
    por fila. Medido sobre 199.608 filas y 2 columnas -- 4,96 s con `.apply`
    contra 0,12 s asi, 40 veces mas rapido y con el mismo resultado.
    """
    if df.empty or not len(df.columns):
        return pd.Series("", index=index if index is not None else df.index, dtype="object")

    resultado = pd.Series("", index=df.index, dtype="object")
    for columna in df.columns:
        valores = df[columna].fillna("").astype(str)
        # El separador solo entra si YA hay algo a la izquierda y ademas hay
        # algo a la derecha: asi no quedan "; " sueltos al principio ni al
        # final cuando alguna columna viene vacia.
        pegamento = np.where(resultado.ne("") & valores.ne(""), separador, "")
        resultado = resultado + pegamento + valores
    return resultado


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

    Las tres solo miran fechas REALES (ver FECHAS_CENTINELA): un comodin no
    contradice nada, significa "sin dato". Antes se comparaban como fechas y
    eso producia 13.815 hallazgos falsos, casi todos por `1900-01-01`. Que
    falte la fecha de fin NO se reporta aqui -- se contrasta contra INVIMA,
    que es quien puede decir si esa fecha existe (ver
    `_contrastar_vigencia_invima`).
    """
    fecha_inicio = _columna_fecha(reporte_gemanet, "FECHA_INICIO")
    fecha_fin = _columna_fecha(reporte_gemanet, "FECHA_FIN")
    activo = _columna_o_vacia(reporte_gemanet, "ACTIVO").str.strip().str.upper()
    hoy = pd.Timestamp.now().normalize()

    inicio_real = _es_fecha_real(fecha_inicio)
    fin_real = _es_fecha_real(fecha_fin)

    hallazgos = pd.DataFrame(index=reporte_gemanet.index)
    hallazgos["FECHA_FIN anterior a FECHA_INICIO"] = (
        inicio_real & fin_real & (fecha_fin < fecha_inicio)
    )
    hallazgos["ACTIVO=NO sin FECHA_FIN registrada"] = activo.eq("NO") & ~fin_real
    hallazgos["ACTIVO=SI pero FECHA_FIN ya paso"] = activo.eq("SI") & fin_real & (fecha_fin < hoy)

    return _columnas_marcadas(hallazgos, "; ")


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

# MARCA_MEDICAMENTO, UNIDAD_MEDIDA y CODIGO_INTERNO_MODELO_SERVICIO no guardan
# texto sino un codigo de catalogo, y ahi el "sin dato" no se escribe "-999":
# se escribe con el codigo 1, que el catalogo describe literalmente como "SIN
# INFORMACION" (ver resolver.FALLBACK_CODIGO). Es el mismo centinela con otra
# cara, y hasta el 2026-08-21 no se reconocia como tal: la marca de 40.044
# medicamentos --el 93 % de todo lo comparable contra INVIMA-- se reportaba
# como "no coincide con INVIMA" cuando en realidad NO ESTA REGISTRADA. Un
# dato ausente no es un dato equivocado, y confundirlos convertia un unico
# problema de proceso en decenas de miles de hallazgos falsos.
_CAMPOS_CODIGO_DE_CATALOGO = frozenset(
    {"MARCA_MEDICAMENTO", "UNIDAD_MEDIDA", "CODIGO_INTERNO_MODELO_SERVICIO"}
)


def _sin_dato_local(df: pd.DataFrame, campo: str, columna: str | None = None) -> pd.Series:
    """Si el campo NO trae dato en Gemma Net, en cualquiera de sus formas:
    vacio, "-999", un error de Excel, o el codigo 1 de catalogo cuando el
    campo se guarda como codigo (ver `_CAMPOS_CODIGO_DE_CATALOGO`)."""
    crudo = _columna_o_vacia(df, columna or campo).str.strip().str.lower()
    sin_dato = crudo.isin(_MARCADORES_VACIOS) | crudo.map(es_error_excel)
    if campo in _CAMPOS_CODIGO_DE_CATALOGO:
        sin_dato = sin_dato | crudo.map(_a_entero).eq(FALLBACK_CODIGO)
    return sin_dato


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
        poblado[campo] = ~_sin_dato_local(reporte_gemanet, campo)
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
    return [
        f"El campo {campo} no trae dato real en el {porcentaje:.1f}% de las filas "
        "de este reporte -- parece no estarse diligenciando en el proceso de origen, no "
        "un dato puntual faltante por medicamento."
        for campo, porcentaje in _campos_sistemicamente_no_diligenciados(reporte_gemanet).items()
    ]


def _detectar_capa_legada_atc(tipo_codigo_interno: pd.Series) -> list[str]:
    """Advertencia AGREGADA, no por fila -- igual que
    `_detectar_campos_sistemicamente_no_diligenciados()`. La familia
    "atc_expediente_consecutivo" (codigo ATC + expediente + consecutivo) es
    una capa legada de INVIMA: medida contra produccion el 2026-08-26,
    100% inactiva y en el 90% de los casos ya existe como fila CUM
    independiente en el mismo reporte -- ver design/tipos_codigo_interno.md.
    Reportarla fila por fila serian decenas de miles de "hallazgos" que en
    realidad son el mismo hecho de proceso repetido, igual que un campo
    sistemicamente vacio.

    NO fusionar ni deduplicar a partir de esto: `CODIGO_INTERNO` duplicado
    entre un CUM y su gemelo ATC-legado son DOS filas del reporte, cada una
    se audita por separado -- fusionarlas a ciegas es exactamente lo que
    `CLAUDE.md` prohibe (puede perder un principio activo si en realidad son
    medicamentos combinados distintos con la misma coincidencia superficial).
    """
    n = int((tipo_codigo_interno == "atc_expediente_consecutivo").sum())
    if n == 0:
        return []
    total = len(tipo_codigo_interno)
    porcentaje = (n / total * 100) if total else 0.0
    return [
        (
            f"{n:,} de {total:,} codigos ({porcentaje:.1f}%) tienen la forma de una capa "
            "legada de INVIMA (codigo ATC + expediente + consecutivo) -- en la mayoria de "
            "los casos ya existen como una fila CUM independiente en este mismo reporte. "
            "Es informativo: no se fusionan ni se deduplican automaticamente."
        )
    ]


def _campos_sistemicamente_no_diligenciados(reporte_gemanet: pd.DataFrame) -> dict[str, float]:
    """Los nombres de esos campos, con su porcentaje de vacio.

    Separado del texto de la advertencia porque la clasificacion de hallazgos
    tambien los necesita, y por el motivo opuesto: para NO contarlos fila por
    fila. Un campo que nadie diligencia produce un hallazgo en cada uno de los
    199.689 medicamentos, y eso no es informacion -- es el mismo problema
    repetido. Ya se reporta una vez, como problema de proceso, que es lo que
    permite hacer algo al respecto.
    """
    if len(reporte_gemanet) == 0:
        return {}
    encontrados: dict[str, float] = {}
    for campo in _CAMPOS_COMPLETITUD_REPORTE:
        if campo not in reporte_gemanet.columns:
            continue
        porcentaje_vacio = _sin_dato_local(reporte_gemanet, campo).mean() * 100
        if porcentaje_vacio >= _UMBRAL_CAMPO_SISTEMICAMENTE_VACIO:
            encontrados[campo] = porcentaje_vacio
    return encontrados


def _detectar_duplicados_en_reporte(reporte_gemanet: pd.DataFrame) -> pd.Series:
    """Calidad #5 -- UNICIDAD: a diferencia de `pipeline.py::_reclasificar_
    duplicados` (que solo revisa duplicados entre candidatos NUEVOS), esto
    revisa si el propio reporte YA CARGADO de Gemma Net tiene un
    CODIGO_INTERNO repetido -- una llave que deberia ser unica en la
    plataforma. Puede ser legitimo (medicamento combinado, una fila por
    principio activo) o un error real de cargue duplicado -- esta funcion
    solo senala el hecho, no decide cual es el caso.

    Las filas SIN codigo no son un duplicado: son una ausencia, y ya las
    cuenta la dimension de conformidad de formato. Contarlas aqui inflaba el
    hallazgo y lo volvia enganoso -- medido el 2026-08-20: de 98 "duplicados"
    reportados, 87 eran filas con el codigo vacio y solo 11 eran una
    duplicacion real (todas del codigo "1"). La comparacion contra `.ne("")`
    no bastaba porque `astype(str)` convierte los nulos en "<NA>", no en "",
    asi que se reutiliza `_MARCADORES_VACIOS`, que ya conoce todas las formas
    en que este reporte dice "aqui no hay dato".
    """
    # _columna_o_vacia y no astype(str) a secas: con el dtype `str` de pandas,
    # `astype(str)` CONSERVA los nulos como NaN en vez de convertirlos a
    # texto, asi que `.isin(_MARCADORES_VACIOS)` nunca los reconocia y las
    # filas sin codigo seguian contandose como duplicadas entre si.
    codigo = _columna_o_vacia(reporte_gemanet, "CODIGO_INTERNO").str.strip()
    tiene_codigo = ~codigo.str.casefold().isin(_MARCADORES_VACIOS)
    return codigo.duplicated(keep=False) & tiene_codigo


def _validar_dominio_valores(reporte_gemanet: pd.DataFrame) -> pd.Series:
    """Calidad #6 -- VALIDEZ DE DOMINIO: CLASIFICADO, CODIGO_NIVEL_SERVICIO,
    POS y ACTIVO solo pueden tomar un conjunto fijo y conocido de valores
    (ver armado/reglas_negocio.py, donde este mismo catalogo ya se valida
    para la malla de referencia -- aca se aplica al reporte YA CARGADO de
    Gemma Net, que nunca se habia revisado contra este dominio). Un valor
    fuera de ese conjunto es un dato mal diligenciado, no una variante
    valida no contemplada.

    La comparacion IGNORA MAYUSCULAS. El dominio esta declarado como
    "SI"/"NO" y Gemma Net guarda "Si"/"No" en capitalizacion de titulo: una
    comparacion exacta marcaba **199.590 filas perfectamente validas** como
    fuera de dominio -- el 99,95 % del reporte, medido el 2026-08-20. Una
    diferencia de mayusculas no es un dato mal diligenciado; el valor real
    que hay que cazar aqui es el que no existe en el dominio, y esos son 87.
    """
    validos_clasificado = {v.casefold() for v in CLASIFICADO_VALORES_VALIDOS}
    validos_nivel = {v.casefold() for v in NIVELES_SERVICIO_VALIDOS}

    clasificado = _columna_o_vacia(reporte_gemanet, "CLASIFICADO").str.strip()
    nivel_servicio = _columna_o_vacia(reporte_gemanet, "CODIGO_NIVEL_SERVICIO").str.strip()
    pos = _columna_o_vacia(reporte_gemanet, "POS").str.strip().str.upper()
    activo = _columna_o_vacia(reporte_gemanet, "ACTIVO").str.strip().str.upper()

    hallazgos = pd.DataFrame(index=reporte_gemanet.index)
    hallazgos["CLASIFICADO fuera de dominio"] = clasificado.ne("") & ~clasificado.str.casefold().isin(
        validos_clasificado
    )
    hallazgos["CODIGO_NIVEL_SERVICIO fuera de dominio"] = nivel_servicio.ne(
        ""
    ) & ~nivel_servicio.str.casefold().isin(validos_nivel)
    hallazgos["POS fuera de dominio (SI/NO)"] = pos.ne("") & ~pos.isin(["SI", "NO"])
    hallazgos["ACTIVO fuera de dominio (SI/NO)"] = activo.ne("") & ~activo.isin(["SI", "NO"])

    return _columnas_marcadas(hallazgos, "; ")


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

    return _columnas_marcadas(hallazgos, "; ")


# Dimension 10 -- valores de NOVEDAD_VIGENCIA_INVIMA, en orden de prioridad:
# una fila puede cumplir varias condiciones y se reporta la de mayor riesgo.
NOVEDAD_RIESGO_ACTIVO = "riesgo_activo_sin_vigencia"
NOVEDAD_REGISTRO_VENCIDO = "registro_vencido_en_invima"
NOVEDAD_REVISAR_REACTIVACION = "revisar_reactivacion"
NOVEDAD_ACTUALIZAR_FECHA_FIN = "actualizar_fecha_fin"
NOVEDAD_COHERENTE = "coherente"
NOVEDAD_NO_VERIFICABLE = "no_verificable"


def _cantidad_como_texto(serie: pd.Series) -> pd.Series:
    """20.0 -> "20", 2.5 -> "2.5", vacio -> "". INVIMA guarda CANTIDAD como
    numero y Gemma Net la concatena sin el ".0" de los enteros."""
    numeros = pd.to_numeric(serie, errors="coerce")
    return numeros.map(
        lambda v: "" if pd.isna(v) else (str(int(v)) if float(v).is_integer() else str(v))
    )


def _descripcion_esperada_invima(invima: pd.DataFrame) -> pd.Series:
    """Como se veria la DESCRIPCION de Gemma Net armada desde INVIMA.

    Formula verificada contra los datos reales el 2026-08-20:

        PRINCIPIO_ACTIVO + CANTIDAD + UNIDAD_MEDIDA + FORMA_FARMACEUTICA

    Ejemplo: "FLUOXETINA CLORHIDRATO EQUIVALENTE A FLUOXETINA BASE 20MG
    CAPSULA DURA".

    La version anterior usaba `PRINCIPIO_ACTIVO + UNIDAD_REFERENCIA` -- la
    regla de la fase 5 del SOP -- y fallaba en el 100 % de los casos: 0
    coincidencias exactas sobre 43.266 filas comparables, lo que dejaba la
    dimension de Exactitud inservible y hundia PORCENTAJE_CALIDAD de todo el
    reporte. El motivo es que `UNIDAD_REFERENCIA` no es un dato sino una
    frase ("CADA CAPSULA DE GELATINA DURA CONTIENE").

    Medido sobre las 43.266 filas con correspondencia:

        PA + UNIDAD_REFERENCIA (anterior)        0 exactas   similitud 92,5
        PA + CANTIDAD+UNIDAD                     0 exactas   similitud 99,8
        PA + CANTIDAD+UNIDAD + FORMA        32.414 exactas   similitud 99,9

    El 25 % restante son diferencias reales, que es justo lo que la auditoria
    debe reportar.
    """
    return (
        _columna_o_vacia(invima, "PRINCIPIO_ACTIVO").str.strip()
        + " "
        + _cantidad_como_texto(_columna_o_vacia(invima, "CANTIDAD"))
        + _columna_o_vacia(invima, "UNIDAD_MEDIDA").str.strip()
        + " "
        + _columna_o_vacia(invima, "FORMA_FARMACEUTICA").str.strip()
    ).str.strip()


PREFIJO_SIMILITUD = "SIMILITUD_"

# El trio de columnas por campo comparable: lo que dice Gemma Net, lo que dice
# INVIMA y el veredicto. Pedido explicito del usuario (2026-08-21): "una
# columna ejemplo, descripcion gemma, descripcion invima, descripcion
# validada". Los sufijos viven aca -- y no como literales sueltos -- porque la
# UI y la exportacion a Excel arman nombres de columna con ellos.
SUFIJO_GEMANET = "_GEMANET"
SUFIJO_INVIMA = "_INVIMA"
SUFIJO_VALIDACION = "_VALIDACION"

# El veredicto es texto y no booleano a proposito: "sin comparar" no es ni
# verdadero ni falso, y un booleano obligaria a inventarle un valor. Mismo
# criterio que PORCENTAJE_CALIDAD, que queda vacio en vez de 0 %.
VALIDACION_COINCIDE = "coincide"
VALIDACION_DIFIERE = "difiere"
VALIDACION_SIN_COMPARAR = "sin comparar"
# Distinto de "sin comparar": ahi falta el lado de INVIMA, aca falta el
# nuestro. La accion tampoco es la misma -- lo primero no se puede resolver,
# lo segundo se resuelve diligenciando el campo.
VALIDACION_SIN_DATO_LOCAL = "sin dato en Gemma Net"


def similitud_de_campo(local: pd.Series, oficial: pd.Series) -> pd.Series:
    """Cuanto se parecen dos columnas de texto, 0-100, fila por fila.

    Pedido de negocio (ing. Sergio, 2026-08-20): saber "que tanto parecido o
    coincidencia tiene la de nuestra base de datos contra la del INVIMA", no
    solo si difiere. Un binario dice que hay un problema; el porcentaje dice
    si es una tilde de diferencia o si son dos medicamentos distintos -- y eso
    cambia por completo quien tiene que revisarlo y con que urgencia.

    `token_set_ratio` y no `ratio`: compara los conjuntos de palabras, asi que
    no penaliza el orden ni las palabras repetidas. "ACETAMINOFEN 500 MG
    TABLETA" contra "TABLETA ACETAMINOFEN 500MG" es el mismo medicamento
    escrito distinto, y debe dar alto.

    Si alguno de los dos lados esta vacio se devuelve NaN, no 0: "no hay con
    que comparar" no es lo mismo que "no se parece en nada" -- mismo criterio
    que PORCENTAJE_CALIDAD.
    """
    izq = local.fillna("").astype(str).to_numpy()
    der = oficial.fillna("").astype(str).to_numpy()
    # cpdist compara par a par (fila i contra fila i) y libera el GIL con
    # workers=-1. Medido: 199.689 pares en 0,05 s, los 7 campos en ~0,35 s.
    puntajes = process.cpdist(izq, der, scorer=fuzz.token_set_ratio, workers=-1)
    resultado = pd.Series(puntajes, index=local.index, dtype="float64")
    return resultado.where((izq != "") & (der != ""))


def _corte_catalogo_invima(invima: pd.DataFrame) -> pd.Timestamp | None:
    """Hasta que fecha sabe algo el catalogo INVIMA que se esta usando.

    Se toma de FECHA_ACTIVO, que es la ultima novedad que alcanzo a registrar
    el corte. Sirve para NO afirmar cosas que el archivo no puede sustentar:
    un registro que vence despues del corte pudo renovarse sin que esa copia
    se entere. Medido el 2026-08-20 con el listado de 2022: de 73.716
    registros "vencidos a hoy", **los 73.716** vencian despues del corte --
    es decir, el 100 % de ese hallazgo habria sido una afirmacion sin
    respaldo. Devuelve None si no hay como saberlo, y entonces no se afirma.
    """
    if "FECHA_ACTIVO" not in invima.columns:
        return None
    fechas = pd.to_datetime(invima["FECHA_ACTIVO"], errors="coerce")
    return fechas.max() if fechas.notna().any() else None


def _contrastar_vigencia_invima(
    combinado: pd.DataFrame,
    tiene_correspondencia: pd.Series,
    corte_invima: pd.Timestamp | None = None,
    estado_coherencia: pd.Series | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Calidad #10 -- CONTRASTE DE VIGENCIA: que dice INVIMA de las filas cuya
    vigencia local no se puede interpretar sola.

    Pedido de negocio (Carlos, 2026-08-20): las filas con fechas comodin no
    ameritan corregirse una por una -- son residuo de la migracion -- pero SI
    deben contrastarse contra INVIMA, porque una fecha ausente localmente
    puede existir alla (novedad a actualizar) y un medicamento inactivo en la
    plataforma puede estar vigente en INVIMA. La aplicacion no corrige nada:
    entrega la novedad fundamentada con las fechas de ambos lados para que
    una persona decida.

    Como representa INVIMA la vigencia (medido sobre el listado real, era la
    duda abierta): `FECHA_INACTIVO` **nula** significa que el CUM sigue
    activo -- 77.545 de 81.641 activos, el 95 %. `FECHA_VENCIMIENTO` nunca es
    nula: siempre hay vencimiento del registro sanitario. Por eso se comparan
    las dos y significan cosas distintas -- una da la novedad de dato, la
    otra el riesgo de vigencia.

    Devuelve (clasificacion, detalle). El detalle lleva las fechas de los dos
    lados: sin eso la novedad no se puede fundamentar sin abrir otra
    herramienta, que es justo lo que se quiere evitar.
    """
    fin_local = _columna_fecha(combinado, "FECHA_FIN")
    activo_local = _columna_o_vacia(combinado, "ACTIVO").str.strip().str.upper().isin(
        {"SI", "SÍ", "S", "1"}
    )
    fin_local_real = _es_fecha_real(fin_local)

    inactivo_invima = _columna_o_vacia(combinado, "ESTADO_CUM_INVIMA").str.strip().str.upper().eq(
        "INACTIVO"
    )
    activo_invima = _columna_o_vacia(combinado, "ESTADO_CUM_INVIMA").str.strip().str.upper().eq(
        "ACTIVO"
    )
    fecha_inactivo_invima = _columna_fecha(combinado, "FECHA_INACTIVO_INVIMA")
    fecha_vencimiento_invima = _columna_fecha(combinado, "FECHA_VENCIMIENTO_INVIMA")
    inactivo_invima_real = _es_fecha_real(fecha_inactivo_invima)
    hoy = pd.Timestamp.now().normalize()

    clasificacion = pd.Series(NOVEDAD_COHERENTE, index=combinado.index, dtype="object")
    detalle = pd.Series("", index=combinado.index, dtype="object")

    def _fecha(serie: pd.Series, mascara: pd.Series) -> pd.Series:
        return serie[mascara].dt.strftime("%Y-%m-%d").fillna("sin fecha")

    # De menor a mayor prioridad: la ultima asignacion gana, asi la fila queda
    # con el hallazgo mas grave sin tener que ordenar condiciones a mano.
    actualizar = tiene_correspondencia & ~fin_local_real & inactivo_invima_real
    clasificacion[actualizar] = NOVEDAD_ACTUALIZAR_FECHA_FIN
    detalle[actualizar] = (
        "Sin fecha de fin en Gemma Net, pero INVIMA registra que el CUM se inactivo el "
        + _fecha(fecha_inactivo_invima, actualizar)
        + ". Novedad: actualizar FECHA_FIN."
    )

    reactivar = tiene_correspondencia & ~activo_local & activo_invima
    clasificacion[reactivar] = NOVEDAD_REVISAR_REACTIVACION
    detalle[reactivar] = (
        "Inactivo en Gemma Net, pero el CUM sigue Activo en INVIMA (registro sanitario "
        "vigente hasta " + _fecha(fecha_vencimiento_invima, reactivar) + "). "
        "Revisar si corresponde reactivarlo."
    )

    # Solo se afirma "vencido" si el vencimiento cae DENTRO de lo que el
    # catalogo alcanza a saber. Un registro que vence despues del corte pudo
    # renovarse y esta copia no se entera -- afirmarlo seria justo la decision
    # a ciegas que el proyecto prohibe. Sin corte conocido no se afirma nada.
    dentro_del_corte = (
        pd.Series(False, index=combinado.index)
        if corte_invima is None
        else fecha_vencimiento_invima <= corte_invima
    )
    vencido = (
        tiene_correspondencia
        & activo_local
        & _es_fecha_real(fecha_vencimiento_invima)
        & (fecha_vencimiento_invima < hoy)
        & dentro_del_corte
    )
    clasificacion[vencido] = NOVEDAD_REGISTRO_VENCIDO
    detalle[vencido] = (
        "Activo en Gemma Net, pero el registro sanitario vencio en INVIMA el "
        + _fecha(fecha_vencimiento_invima, vencido)
        + ". Riesgo de autorizar un medicamento sin vigencia."
    )

    riesgo = tiene_correspondencia & activo_local & inactivo_invima
    clasificacion[riesgo] = NOVEDAD_RIESGO_ACTIVO
    detalle[riesgo] = (
        "Activo en Gemma Net, pero INVIMA tiene el CUM como Inactivo desde "
        + _fecha(fecha_inactivo_invima, riesgo)
        + ". Riesgo alto: se puede autorizar un medicamento que INVIMA ya desactivo."
    )

    # Sin correspondencia no se afirma nada: no se puede confirmar ni descartar.
    clasificacion[~tiene_correspondencia] = NOVEDAD_NO_VERIFICABLE
    detalle[~tiene_correspondencia] = ""

    # ...salvo que los datasets auxiliares SI sepan de ese codigo. Un medicamento
    # que no esta en Vigentes pero aparece en Vencidos no es "no verificable":
    # INVIMA nos esta diciendo que vencio, y si ademas sigue activo en Gemma Net
    # es el riesgo mas alto de todos. Sin esto, con los 4 listados cargados la
    # auditoria reportaba 49.993 vencidos en ESTADO_COHERENCIA y a la vez los
    # contaba como "no verificable" aqui -- dos respuestas distintas a la misma
    # pregunta en el mismo reporte.
    if estado_coherencia is not None:
        en_vencidos = estado_coherencia.values == EstadoCoherencia.VENCIDO_EN_INVIMA.value

        # Vencido en INVIMA y ACTIVO aca: los dos lados se contradicen, y en la
        # direccion peligrosa.
        vencido_y_activo = en_vencidos & activo_local.values
        clasificacion[vencido_y_activo] = NOVEDAD_RIESGO_ACTIVO
        detalle[vencido_y_activo] = (
            "Activo en Gemma Net, pero INVIMA lo tiene en su listado de VENCIDOS. "
            "Riesgo alto: se puede autorizar un medicamento sin registro vigente."
        )

        # Vencido en INVIMA e INACTIVO aca: los dos lados coinciden en que no
        # esta vigente. No es una novedad, pero TAMPOCO es "no verificable" --
        # sabemos perfectamente que paso. Llamarlo no verificable inflaba esa
        # categoria en ~49.600 filas y contradecia a ESTADO_COHERENCIA.
        vencido_y_coherente = en_vencidos & ~activo_local.values
        clasificacion[vencido_y_coherente] = NOVEDAD_COHERENTE
        detalle[vencido_y_coherente] = (
            "Inactivo en Gemma Net y vencido en INVIMA: los dos lados coinciden. "
            "Sin acción; se conserva para trazabilidad."
        )
        for valor_estado, etiqueta in [
            (EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value, "en trámite de renovación"),
            (EstadoCoherencia.VIGENTE_NO_COMERCIALIZADO_INVIMA.value,
             "vigente pero temporalmente no comercializado"),
            (EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value, "en otro estado"),
        ]:
            marca = estado_coherencia.values == valor_estado
            clasificacion[marca] = NOVEDAD_REVISAR_REACTIVACION
            detalle[marca] = (
                f"No está en el listado Vigente de INVIMA, pero sí aparece {etiqueta}. "
                "Revisar antes de tratarlo como código sin correspondencia."
            )

        # "Revisar reactivacion" solo tiene sentido para lo que esta INACTIVO
        # aca: a lo que ya esta activo no se le puede pedir que se reactive.
        # Si ademas su registro sigue siendo valido en INVIMA (en renovacion o
        # vigente sin comercializar), los dos lados coinciden y no hay novedad.
        #
        # Sin esta separacion la tarjeta "inactivo(s) aqui pero vigente(s) en
        # INVIMA" contaba 38.098 filas de las que 18.360 estaban ACTIVAS:
        # afirmaba lo contrario de lo que pasaba en el 48 % de los casos.
        registro_valido_en_invima = np.isin(
            estado_coherencia.values,
            [
                EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value,
                EstadoCoherencia.VIGENTE_NO_COMERCIALIZADO_INVIMA.value,
            ],
        )
        activo_y_valido = registro_valido_en_invima & activo_local.values
        clasificacion[activo_y_valido] = NOVEDAD_COHERENTE
        detalle[activo_y_valido] = (
            "Activo en Gemma Net y con registro sanitario válido en INVIMA "
            "(en renovación o vigente sin comercializar). Los dos lados coinciden: "
            "sin acción."
        )

        # ...y un medicamento ACTIVO en Gemma Net cuyo registro INVIMA dio por
        # Negado, Cancelado o con perdida de fuerza ejecutoria no es un
        # candidato a reactivar: es el riesgo mas alto que hay, y se estaba
        # etiquetando como leve.
        #
        # Medido contra produccion el 2026-08-24: de los 1.205 activos que
        # caian en "otro estado", 1.177 eran "Temp. no comerc - Vigente" (que
        # ahora tienen su propio estado y no llegan aca) y 28 tenian un
        # registro sin vigencia. Esos 28 quedaban invisibles como riesgo.
        en_otro_estado_sin_vigencia = (
            estado_coherencia.values == EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value
        )
        activo_sin_vigencia = en_otro_estado_sin_vigencia & activo_local.values
        clasificacion[activo_sin_vigencia] = NOVEDAD_RIESGO_ACTIVO
        detalle[activo_sin_vigencia] = (
            "Activo en Gemma Net, pero INVIMA no reconoce su registro como vigente "
            "(Cancelado, Suspendido, Negado, Desistido o con pérdida de fuerza ejecutoria). "
            "Riesgo alto: se puede autorizar un medicamento sin respaldo sanitario."
        )

    return clasificacion, detalle


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


# Codigos que Gemma Net usa para decir "aqui no hay dato": -999 es el centinela
# documentado del sistema y 0 aparece en el reporte real con el mismo sentido
# (medido 2026-08-20: 13 filas con UNIDAD_MEDIDA=0). Ninguno es un codigo de
# catalogo, y tratarlos como tal produciria un "huerfano" enganoso.
_CODIGOS_SIN_DATO_CATALOGO = frozenset({-999, 0})


def _diagnostico_codigo_catalogo(
    serie: pd.Series,
    codigos_validos: set[int],
    campo: str,
    legible: str,
    archivo: str,
) -> pd.Series:
    """Un mensaje por fila (vacio si la fila esta bien) para un codigo de catalogo.

    Distingue DOS fallas que antes no se distinguian -- y una de ellas ni
    siquiera se detectaba:

    1. **Sin dato**: el codigo viene vacio, en -999 o en 0. El medicamento
       quedo cargado en Gemma Net sin marca / sin unidad. Antes esto pasaba
       invisible: la condicion exigia `notna()`, asi que una fila sin codigo
       no entraba en el diagnostico, se resolvia en silencio a texto vacio
       (ver `sigla_por_codigo`) y salia como CON_DIFERENCIAS -- el mismo
       diagnostico enganoso que esta dimension existe para evitar. Medido
       contra produccion el 2026-08-20: 99 filas sin marca y 87 sin unidad
       que no aparecian en ningun reporte.
    2. **Huerfano**: el codigo existe pero no esta en el catalogo interno.
       Es mantenimiento de catalogo, no un dato faltante del medicamento.

    Vectorizado a proposito: sobre 200.000 filas un bucle por indice se nota.
    """
    falta = serie.isna() | serie.isin(_CODIGOS_SIN_DATO_CATALOGO)
    huerfano = ~falta & ~serie.isin(codigos_validos)

    mensajes = pd.Series("", index=serie.index, dtype="object")
    mensajes[falta] = f"{campo} sin dato -- el medicamento esta cargado sin {legible}"
    # int(codigo) y no {codigo} a secas: `.map(_a_entero)` sobre una columna con
    # huecos deja la serie en float64, y el mensaje salia "codigo 10001025.0" --
    # eso no es un codigo, y el mensaje esta para que alguien lo copie tal cual
    # al CSV del catalogo.
    mensajes[huerfano] = serie[huerfano].map(
        lambda codigo: (
            f"{campo} (codigo {int(codigo)}) no existe en el catalogo interno "
            f"-- verificar/agregar en {archivo}"
        )
    )
    return mensajes


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

    Cubre DOS fallas (ver `_diagnostico_codigo_catalogo`): el codigo falta
    -- el medicamento quedo cargado SIN marca o SIN unidad -- o el codigo
    existe pero no esta en el catalogo interno.

    Hallazgo real contra el reporte de produccion (`data/LISTADO_
    MEDICAMENTOS12082026.xlsx`): 1 marca y 23 unidades con codigo huerfano
    (2026-08-19), mas 99 filas sin marca y 87 sin unidad que la version
    anterior no detectaba (2026-08-20).
    """
    marca = _columna_o_vacia(reporte_gemanet, "MARCA_MEDICAMENTO").map(_a_entero)
    unidad = _columna_o_vacia(reporte_gemanet, "UNIDAD_MEDIDA").map(_a_entero)

    hallazgos = pd.DataFrame(
        {
            "marca": _diagnostico_codigo_catalogo(
                marca,
                {e.codigo for e in catalogo_marca},
                "MARCA_MEDICAMENTO",
                "marca",
                "config/catalogos/marca_medicamento.csv",
            ),
            "unidad": _diagnostico_codigo_catalogo(
                unidad,
                {e.codigo for e in catalogo_unidad},
                "UNIDAD_MEDIDA",
                "unidad de medida",
                "config/catalogos/unidad_medida.csv",
            ),
        }
    )
    return _unir_no_vacios(hallazgos, "; ", reporte_gemanet.index)


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

# El caso hermano del anterior, y por la misma razon. Dentro de Otros Estados
# hay filas cuyo ESTADO_REGISTRO dice literalmente "Temp. no comerc - Vigente":
# el registro sanitario esta VIGENTE y lo unico que pasa es que el producto no
# se esta comercializando ahora mismo.
#
# Medido contra produccion el 2026-08-24: de los 10.469 medicamentos que la
# auditoria pintaba en rojo como "otro estado" (riesgo alto), 2.887 -- el
# 27,6 % -- traian este texto. Se estaba marcando como riesgo de vigencia algo
# que INVIMA declara vigente en la misma celda. Decision del usuario: salen de
# riesgo alto. El resto (Perdida Fuerza Ejec, Negado, Desistido, Cancelado,
# Abandono, Suspendido) si son 7.582 casos sin vigencia.
_FRAGMENTO_VIGENTE_EN_OTROS_ESTADOS = "VIGENTE"


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


def _separar_vigentes_de_otros_estados(
    df_otros_estados: pd.DataFrame | None,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Devuelve (los que de verdad no tienen vigencia, los que INVIMA declara
    vigentes) -- ver _FRAGMENTO_VIGENTE_EN_OTROS_ESTADOS.

    Se llama DESPUES de `_separar_renovacion_de_otros_estados`, porque el texto
    de renovacion tambien contiene la palabra vigente en algunas variantes y
    ese caso ya tiene su propio destino.
    """
    if df_otros_estados is None or df_otros_estados.empty or "ESTADO_REGISTRO" not in df_otros_estados.columns:
        return df_otros_estados, None
    es_vigente = (
        df_otros_estados["ESTADO_REGISTRO"]
        .astype(str)
        .map(normalizar)
        .str.contains(_FRAGMENTO_VIGENTE_EN_OTROS_ESTADOS, na=False)
    )
    return df_otros_estados[~es_vigente], df_otros_estados[es_vigente]


def _a_entero(valor: object) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


# Que CLASE de problema es, no en que campo esta. Distincion pedida por el
# usuario el 2026-08-21: hasta ahora todo caia en el mismo saco, y las tres
# cosas se atienden de forma completamente distinta -- una hay que esperarla,
# otra no se corrige fila por fila y solo la tercera pide trabajo manual.
#
# Medido contra produccion el 2026-08-21, sobre los 16.336 hallazgos de
# fechas: 11.526 (el 71 %) se apoyan en una fecha comodin -- 5.826 en
# "2999-12-31" y 5.700 en "1900-01-01" -- y solo 1.636 en una fecha
# realmente en blanco. Tratar esos 11.526 como si cada uno fuera un
# medicamento que alguien debe corregir a mano es lo que hacia el reporte
# inmanejable.
NATURALEZA_VIGENCIA_EN_RIESGO = "Vigencia en riesgo"
NATURALEZA_EN_RENOVACION = "En tramite de renovacion"
NATURALEZA_DESACTUALIZADO = "Dato desactualizado frente a INVIMA"
NATURALEZA_CARGA_INCOMPLETA = "Cargue incompleto"
NATURALEZA_RESIDUAL_MIGRACION = "Residual de la migracion"

# Que hacer con cada uno -- la columna sola dice "que es"; esto dice "y ahora
# que". Va en el reporte para que no haya que explicarlo de viva voz.
ACCION_POR_NATURALEZA = {
    NATURALEZA_VIGENCIA_EN_RIESGO: (
        "Revisar antes de autorizar: el registro sanitario no esta vigente en INVIMA."
    ),
    NATURALEZA_EN_RENOVACION: (
        "Esperar. INVIMA tiene la renovacion en curso y puede volver a estar vigente."
    ),
    NATURALEZA_DESACTUALIZADO: "Actualizar el campo en Gemma Net con el dato oficial.",
    NATURALEZA_CARGA_INCOMPLETA: "Diligenciar los campos que quedaron sin dato.",
    NATURALEZA_RESIDUAL_MIGRACION: (
        "No se corrige fila por fila: son fechas comodin heredadas de la migracion."
    ),
}


def _clasificar_naturaleza_hallazgo(
    estado: pd.Series,
    campos_con_diferencia: pd.Series,
    inconsistencia_fechas: pd.Series,
    hay_campo_sin_dato: pd.Series,
    fecha_comodin: pd.Series,
) -> pd.Series:
    """Una etiqueta por medicamento, la de la accion mas urgente que pide.

    El orden NO es arbitrario: es el orden en que hay que atenderlos. Lo que
    pone en riesgo una autorizacion va primero; lo que solo hay que esperar
    va despues; y el residual de migracion va ultimo justo porque no pide
    nada -- si compitiera hacia arriba taparia hallazgos que si piden trabajo.
    """
    naturaleza = pd.Series("", index=estado.index, dtype="object")
    for mascara, etiqueta in (
        (hay_campo_sin_dato | (inconsistencia_fechas != ""), NATURALEZA_CARGA_INCOMPLETA),
        ((inconsistencia_fechas != "") & fecha_comodin, NATURALEZA_RESIDUAL_MIGRACION),
        (campos_con_diferencia != "", NATURALEZA_DESACTUALIZADO),
        (estado == EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value, NATURALEZA_EN_RENOVACION),
        (
            estado.isin(
                [
                    EstadoCoherencia.VENCIDO_EN_INVIMA.value,
                    EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value,
                ]
            ),
            NATURALEZA_VIGENCIA_EN_RIESGO,
        ),
    ):
        naturaleza[mascara] = etiqueta
    return naturaleza


_SEPARADOR_CLAVE = "\x00"  # no puede aparecer en un dato de texto real


def _coincide_con_alguna_sigla(
    codigos: pd.Series,
    oficial: pd.Series,
    siglas: dict[int, frozenset[str]],
    normalizador: Callable[[str], str],
    alias: dict[str, str] | None = None,
) -> pd.Series:
    """Coincide si el valor de INVIMA calza con CUALQUIERA de las formas que
    el catalogo reconoce para el codigo que guarda Gemma Net.

    MARCA_MEDICAMENTO y UNIDAD_MEDIDA no se guardan como texto sino como
    codigo, y un codigo puede tener varias entradas en el catalogo -- formas
    alternas del mismo concepto, ninguna mas valida que otra. Quedarse con una
    sola (ver `sigla_por_codigo`) convertia en hallazgo lo que solo era una
    forma alterna: 33.677 filas donde el codigo 10001000 se mostraba como
    "MG/CAP" y INVIMA decia "mg" -- el 95 % de las diferencias de unidad, y
    ninguna era un problema del dato.

    Se compara el par (codigo, texto de INVIMA) contra el conjunto de pares
    validos derivado del catalogo, en una sola operacion vectorizada: a
    199.689 filas, resolver esto fila por fila costaria segundos.
    """
    # Los alias son equivalencias AUDITADAS A MANO que la normalizacion de
    # texto no puede deducir sola: "IU" es la sigla inglesa de "UI", "%" es la
    # forma corta de "% PORCIENTO". Ya existian y los usaba la cascada de
    # resolucion, pero la auditoria NO: comparaba los textos crudos y reportaba
    # "difiere" sobre unidades que son la misma.
    #
    # Medido contra produccion el 2026-08-24: de las 984 diferencias de
    # UNIDAD_MEDIDA, 459 -- el 47 % -- eran exactamente esos dos pares:
    # "% PORCIENTO" contra "%" (287) y "UI" contra "IU" (172). Ninguna era un
    # problema del dato.
    #
    # El mapa se invierte (destino -> origenes) porque de un codigo se conoce
    # su sigla, y hay que llegar desde ahi a los textos alternos con que INVIMA
    # puede estar nombrando la misma unidad.
    origenes_por_destino: dict[str, list[str]] = {}
    for origen, destino in (alias or {}).items():
        origenes_por_destino.setdefault(normalizador(destino), []).append(normalizador(origen))

    claves_validas: set[str] = set()
    for codigo, conjunto in siglas.items():
        for sigla in conjunto:
            propia = normalizador(sigla)
            claves_validas.add(f"{codigo}{_SEPARADOR_CLAVE}{propia}")
            for equivalente in origenes_por_destino.get(propia, ()):
                claves_validas.add(f"{codigo}{_SEPARADOR_CLAVE}{equivalente}")
    # Int64 (nullable) antes de pasar a texto: una Series de enteros con algun
    # None la vuelve float64 pandas, y ahi `astype(str)` produce "10001000.0",
    # que no calza con NINGUNA clave. Es un fallo silencioso -- no hay error,
    # simplemente nada coincide nunca.
    clave = (
        codigos.astype("Int64").astype(str) + _SEPARADOR_CLAVE + oficial.astype(str)
    )
    return clave.isin(claves_validas)


def auditar_coherencia(
    reporte_gemanet: pd.DataFrame,
    df_invima: pd.DataFrame,
    catalogo_unidad: list[EntradaCatalogo],
    catalogo_marca: list[EntradaCatalogo],
    df_invima_vencidos: pd.DataFrame | None = None,
    df_invima_otros_estados: pd.DataFrame | None = None,
    df_invima_renovacion: pd.DataFrame | None = None,
    alias_unidad: dict[str, str] | None = None,
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
    # Y el conjunto COMPLETO de siglas de cada codigo, para el veredicto: un
    # codigo con varias entradas no tiene una forma "buena" y las otras malas
    # -- ver `siglas_por_codigo` y `_coincide_con_alguna_sigla`. El singular
    # de arriba se sigue usando para MOSTRAR, que es lo unico que puede hacer.
    siglas_unidad = siglas_por_codigo(catalogo_unidad)
    siglas_marca = siglas_por_codigo(catalogo_marca)

    gemanet = reporte_gemanet.copy()
    gemanet["CODIGO_INTERNO"] = gemanet["CODIGO_INTERNO"].astype(str).str.strip()
    gemanet["_MARCA_TEXTO"] = _columna_o_vacia(gemanet, "MARCA_MEDICAMENTO").map(
        lambda c: sigla_marca.get(_a_entero(c), "")
    )
    gemanet["_UNIDAD_TEXTO"] = _columna_o_vacia(gemanet, "UNIDAD_MEDIDA").map(
        lambda c: sigla_unidad.get(_a_entero(c), "")
    )

    invima = df_invima.drop_duplicates(subset="CODIGO_INTERNO", keep="first").copy()
    invima["_DESCRIPCION_ESPERADA"] = _descripcion_esperada_invima(invima)

    # ESTADO_CUM y las tres fechas alimentan la dimension 10 (contraste de
    # vigencia). No participan de la comparacion campo a campo: viajan para
    # poder decir si una fecha que falta del lado local existe en INVIMA.
    columnas_invima = [
        "CODIGO_INTERNO",
        "TITULAR",
        "UNIDAD_MEDIDA",
        "_DESCRIPCION_ESPERADA",
        "ESTADO_CUM",
        "FECHA_ACTIVO",
        "FECHA_INACTIVO",
        "FECHA_VENCIMIENTO",
    ] + [col_invima for _, col_invima in _CAMPOS_DIRECTOS.values() if col_invima in invima.columns]
    invima_reducido = invima[[c for c in dict.fromkeys(columnas_invima) if c in invima.columns]]
    invima_reducido = invima_reducido.add_suffix("_INVIMA").rename(
        columns={"CODIGO_INTERNO_INVIMA": "CODIGO_INTERNO"}
    )

    combinado = gemanet.merge(invima_reducido, on="CODIGO_INTERNO", how="left", indicator=True)
    tiene_correspondencia = combinado["_merge"] == "both"

    # Los pares (valor local, valor INVIMA) ya normalizados, UNA sola vez: de
    # aqui salen tanto el veredicto binario como el % de similitud. Derivarlos
    # del mismo par es lo que garantiza que no se contradigan -- que un campo
    # aparezca como "difiere" con 100 % de similitud seria incomprensible.
    pares: dict[str, tuple[pd.Series, pd.Series]] = {
        campo: (
            _normalizada(_columna_o_vacia(combinado, col_gemanet)),
            _normalizada(_columna_o_vacia(combinado, f"{col_invima}_INVIMA")),
        )
        for campo, (col_gemanet, col_invima) in _CAMPOS_DIRECTOS.items()
    }
    pares["DESCRIPCION"] = (
        _normalizada(_columna_o_vacia(combinado, "DESCRIPCION")),
        _normalizada(_columna_o_vacia(combinado, "_DESCRIPCION_ESPERADA_INVIMA")),
    )
    # normalizar_entidad, no normalizar: "_MARCA_TEXTO" (sigla_por_codigo del
    # catalogo de marca) ya paso por normalizar_entidad -- comparar contra
    # el TITULAR crudo de INVIMA con la misma normalizacion evita falsos
    # "con_diferencias" por sufijo societario o calificador de planta (ver
    # normalizar_entidad, mismo criterio que usa la resolucion de marca).
    pares["MARCA_MEDICAMENTO"] = (
        combinado["_MARCA_TEXTO"],
        _columna_o_vacia(combinado, "TITULAR_INVIMA").map(normalizar_entidad),
    )
    pares["UNIDAD_MEDIDA"] = (
        _normalizada(combinado["_UNIDAD_TEXTO"]),
        _normalizada(_columna_o_vacia(combinado, "UNIDAD_MEDIDA_INVIMA")),
    )

    # Los valores CRUDOS de cada lado, para poder compararlos a ojo. Pedido
    # explicito del usuario (2026-08-21): "es de mas valor que me muestres el
    # estado de un campo del INVIMA contra el que tiene el medicamento en la
    # db [...] descripcion gemma, descripcion invima, descripcion validada".
    # Saber QUE dice cada lado permite decidir; saber solo que "difieren" no.
    #
    # Se guardan sin normalizar: la normalizacion existe para comparar, no
    # para mostrar. Quien revisa necesita ver lo que hay guardado de verdad,
    # y el veredicto ya tiene en cuenta la normalizacion.
    crudos_invima: dict[str, pd.Series] = {
        campo: _columna_o_vacia(combinado, f"{col_invima}_INVIMA")
        for campo, (_, col_invima) in _CAMPOS_DIRECTOS.items()
    }
    crudos_invima["DESCRIPCION"] = _columna_o_vacia(combinado, "_DESCRIPCION_ESPERADA_INVIMA")
    crudos_invima["MARCA_MEDICAMENTO"] = _columna_o_vacia(combinado, "TITULAR_INVIMA")
    crudos_invima["UNIDAD_MEDIDA"] = _columna_o_vacia(combinado, "UNIDAD_MEDIDA_INVIMA")

    # De MARCA y UNIDAD el reporte guarda un CODIGO, no un texto: mostrar el
    # codigo al lado del titular de INVIMA no dejaria comparar nada. Se
    # muestra el texto ya resuelto contra el catalogo; el codigo crudo sigue
    # en su columna original.
    crudos_gemanet: dict[str, pd.Series] = {
        "MARCA_MEDICAMENTO": combinado["_MARCA_TEXTO"],
        "UNIDAD_MEDIDA": combinado["_UNIDAD_TEXTO"],
    }

    matriz_diferencias = pd.DataFrame(
        {campo: local.ne(oficial) for campo, (local, oficial) in pares.items()},
        index=combinado.index,
    )

    # MARCA y UNIDAD no se guardan como texto sino como CODIGO, y comparar el
    # texto contra INVIMA obliga a elegir una de las varias entradas que ese
    # codigo puede tener en el catalogo. Aca el veredicto se decide sobre el
    # codigo: coincide si INVIMA calza con cualquiera de sus formas. El texto
    # de las columnas *_GEMANET sigue siendo el representativo, para mostrar.
    for campo, columna_codigo, siglas, normalizador, alias_campo in (
        ("MARCA_MEDICAMENTO", "MARCA_MEDICAMENTO", siglas_marca, normalizar_entidad, None),
        ("UNIDAD_MEDIDA", "UNIDAD_MEDIDA", siglas_unidad, normalizar, alias_unidad),
    ):
        local, oficial = pares[campo]
        codigos = _columna_o_vacia(combinado, columna_codigo).map(_a_entero)
        # `local.eq(oficial)` se conserva ademas del conjunto: si el texto que
        # se muestra ya calza, coincide, sin depender de que el codigo se haya
        # podido interpretar.
        coincide = _coincide_con_alguna_sigla(
            codigos, oficial, siglas, normalizador, alias_campo
        ) | local.eq(oficial)
        matriz_diferencias[campo] = ~coincide

    # Un campo sin dato en Gemma Net no "difiere" de INVIMA: no hay nada que
    # comparar. Se saca de las diferencias Y del denominador de
    # PORCENTAJE_CALIDAD, igual que una fila sin correspondencia queda vacia
    # en vez de en 0 %. La ausencia sigue contando, pero donde corresponde:
    # en la dimension de COMPLETITUD (#4) y, si es masiva, en la advertencia
    # de campo sistemicamente no diligenciado. Ver `_sin_dato_local` para el
    # hallazgo que motiva esto (40.044 marcas "SIN INFORMACION").
    columnas_locales = {campo: col_gemanet for campo, (col_gemanet, _) in _CAMPOS_DIRECTOS.items()}
    for campo in ("DESCRIPCION", "MARCA_MEDICAMENTO", "UNIDAD_MEDIDA"):
        columnas_locales[campo] = campo
    matriz_sin_dato = pd.DataFrame(
        {
            campo: _sin_dato_local(combinado, campo, columnas_locales[campo])
            for campo in CAMPOS_COMPARADOS_COHERENCIA
        },
        index=combinado.index,
    )
    matriz_diferencias = matriz_diferencias & ~matriz_sin_dato

    # Una columna SIMILITUD_<CAMPO> por campo comparable: el binario dice que
    # hay un problema, el porcentaje dice si es una tilde o si son dos
    # medicamentos distintos (ver `similitud_de_campo`).
    similitudes = {
        f"{PREFIJO_SIMILITUD}{campo}": similitud_de_campo(local, oficial).where(
            tiene_correspondencia
        )
        for campo, (local, oficial) in pares.items()
    }

    campos_con_diferencia = _columnas_marcadas(matriz_diferencias, ", ")
    campos_con_diferencia = campos_con_diferencia.where(tiene_correspondencia, "")

    # % de calidad: de los campos que SI se pudieron comparar contra INVIMA,
    # cuantos coinciden -- pedido explicito del usuario: aunque un
    # medicamento tenga correspondencia (mismo EXPEDIENTE-CONSECUTIVO), el
    # reporte debe decir que tan alineados estan sus datos con el oficial,
    # no solo "correcto"/"con_diferencias" en blanco y negro. NaN (no 0% ni
    # 100%) cuando no hay correspondencia -- no hay nada que comparar, no es
    # lo mismo que "0% de calidad".
    # El denominador es por fila, no fijo: un campo que Gemma Net no trae no
    # entra en la cuenta -- no se le puede exigir que coincida con INVIMA.
    campos_comparables_fila = len(matriz_diferencias.columns) - matriz_sin_dato.sum(axis=1)
    campos_ok = campos_comparables_fila - matriz_diferencias.sum(axis=1)
    porcentaje_calidad = (campos_ok / campos_comparables_fila * 100).round(1)
    porcentaje_calidad = porcentaje_calidad.where(
        tiene_correspondencia & (campos_comparables_fila > 0)
    )

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
    # Y el caso hermano: los que dicen "Vigente" en su propio texto tampoco son
    # riesgo de vigencia (2.887 filas de las 10.469, ver
    # _FRAGMENTO_VIGENTE_EN_OTROS_ESTADOS).
    otros_estados_resto, otros_estados_vigentes = _separar_vigentes_de_otros_estados(
        otros_estados_resto
    )
    df_renovacion_combinado = pd.concat(
        [d for d in [df_invima_renovacion, otros_estados_como_renovacion] if d is not None and not d.empty],
        ignore_index=True,
    ) if any(d is not None and not d.empty for d in [df_invima_renovacion, otros_estados_como_renovacion]) else None

    estado_invima_detalle = pd.Series("", index=combinado.index)
    # Los vigentes van PRIMERO: si un codigo aparece tanto aqui como en el resto
    # de Otros Estados, la lectura correcta es la que dice que sigue vigente.
    estado, estado_invima_detalle = _aplicar_dataset_auxiliar(
        estado, estado_invima_detalle, gemanet["CODIGO_INTERNO"],
        otros_estados_vigentes, EstadoCoherencia.VIGENTE_NO_COMERCIALIZADO_INVIMA.value,
    )
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
    parece_codigo_invima = gemanet["CODIGO_INTERNO"].str.match(PATRON_CUM)
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
    for nombre_columna, valores in similitudes.items():
        resultado[nombre_columna] = valores.values

    # Un trio por campo comparable: lo que dice Gemma Net, lo que dice INVIMA,
    # y el veredicto. Es lo que convierte el reporte en algo con lo que se
    # puede decidir sin abrir otras dos herramientas al lado.
    for campo in CAMPOS_COMPARADOS_COHERENCIA:
        local = crudos_gemanet.get(campo)
        if local is None:
            local = _columna_o_vacia(combinado, campo)
        resultado[f"{campo}{SUFIJO_GEMANET}"] = local.values
        resultado[f"{campo}{SUFIJO_INVIMA}"] = crudos_invima[campo].values
        # "sin comparar" no es lo mismo que "coincide": sin correspondencia
        # con INVIMA no hay nada contra que validar, igual que
        # PORCENTAJE_CALIDAD queda vacio en vez de 0.
        veredicto = pd.Series(VALIDACION_SIN_COMPARAR, index=combinado.index, dtype="object")
        veredicto[tiene_correspondencia & ~matriz_diferencias[campo]] = VALIDACION_COINCIDE
        veredicto[tiene_correspondencia & matriz_diferencias[campo]] = VALIDACION_DIFIERE
        # Al final: pisa a "coincide", porque un campo sin dato quedo fuera de
        # las diferencias y si no seria indistinguible de uno que si calza.
        veredicto[tiene_correspondencia & matriz_sin_dato[campo]] = VALIDACION_SIN_DATO_LOCAL
        resultado[f"{campo}{SUFIJO_VALIDACION}"] = veredicto.values

    # Aviso TEMPRANO de vencimiento. Todo lo demas mira hacia atras ("esto ya
    # fallo"); esto mira hacia adelante: cuantos dias le quedan al registro
    # sanitario segun INVIMA. Negativo = ya vencio. Se expone como numero para
    # que se pueda acotar por rango ("los que vencen en 6 meses") en vez de
    # tener que esperar a que venzan para enterarse. Vacio si la fecha es un
    # comodin o no hay correspondencia: no se inventa una cuenta regresiva.
    vencimiento = _columna_fecha(combinado, "FECHA_VENCIMIENTO_INVIMA")
    dias_para_vencer = (vencimiento - pd.Timestamp.now().normalize()).dt.days
    dias_para_vencer = dias_para_vencer.where(
        _es_fecha_real(vencimiento) & tiene_correspondencia
    )
    resultado["FECHA_VENCIMIENTO_INVIMA"] = vencimiento.values
    resultado["DIAS_PARA_VENCER_INVIMA"] = dias_para_vencer.values

    novedad_vigencia, detalle_vigencia = _contrastar_vigencia_invima(
        combinado,
        tiene_correspondencia,
        _corte_catalogo_invima(df_invima),
        estado_coherencia=estado,
    )
    resultado["NOVEDAD_VIGENCIA_INVIMA"] = novedad_vigencia.values
    resultado["DETALLE_VIGENCIA_INVIMA"] = detalle_vigencia.values
    resultado["INTEGRIDAD_REFERENCIAL_CATALOGO"] = _validar_integridad_referencial_catalogo(
        reporte_gemanet, catalogo_unidad, catalogo_marca
    ).values

    # De que CLASE es el problema, y por tanto que hay que hacer con el. Sin
    # esto, "esperar a que INVIMA renueve", "no tocar, es residual de la
    # migracion" y "hay que diligenciar esto a mano" salian mezclados en la
    # misma lista, y la unica forma de separarlos era conocer el caso.
    fecha_comodin = _es_fecha_comodin(_columna_fecha(reporte_gemanet, "FECHA_INICIO")) | (
        _es_fecha_comodin(_columna_fecha(reporte_gemanet, "FECHA_FIN"))
    )
    # Sin los campos que NADIE diligencia: incluirlos ponia el 83 % de los
    # medicamentos en "cargue incompleto" -- casi todos por la marca "SIN
    # INFORMACION" -- y una categoria que abarca a casi todos no separa nada.
    # Esos campos ya salen una vez, como advertencia de proceso.
    sistemicos = _campos_sistemicamente_no_diligenciados(reporte_gemanet)
    puntuales = [c for c in matriz_sin_dato.columns if c not in sistemicos]
    hay_campo_sin_dato = (
        matriz_sin_dato[puntuales].any(axis=1)
        if puntuales
        else pd.Series(False, index=matriz_sin_dato.index)
    )
    # Columna de CONTEXTO, no una dimension de calidad #10: no hay veredicto
    # de bien/mal (un codigo_propio es un dato legitimo de Pijao Salud), asi
    # que no entra en PORCENTAJE_CALIDAD, NATURALEZA_HALLAZGO ni
    # ACCION_SUGERIDA. Se asigna ANTES de NATURALEZA_HALLAZGO a proposito,
    # para que sea obvio con solo leer que no participa en el. Investigado
    # contra produccion real el 2026-08-26 -- ver design/tipos_codigo_interno.md.
    tipo_codigo_interno = clasificar_codigos(_columna_o_vacia(reporte_gemanet, "CODIGO_INTERNO"))
    resultado["TIPO_CODIGO_INTERNO"] = tipo_codigo_interno.values

    naturaleza = _clasificar_naturaleza_hallazgo(
        estado,
        campos_con_diferencia,
        inconsistencia_fechas,
        hay_campo_sin_dato,
        pd.Series(fecha_comodin.values, index=estado.index),
    )
    resultado["NATURALEZA_HALLAZGO"] = naturaleza.values
    resultado["ACCION_SUGERIDA"] = naturaleza.map(ACCION_POR_NATURALEZA).fillna("").values
    resultado.attrs["advertencias_calidad"] = _detectar_campos_sistemicamente_no_diligenciados(
        reporte_gemanet
    ) + _detectar_capa_legada_atc(tipo_codigo_interno)
    return resultado
