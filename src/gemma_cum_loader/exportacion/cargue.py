"""Arma y escribe el archivo de cargue que se sube a Gemma Net, en Excel.

Estructura de 37 campos, orden y encabezados confirmados dos veces: contra
el export real de la plataforma (LISTADO_MEDICAMENTOS12082026.xlsx) y contra
el encabezado pipe-delimitado que el usuario confirmo como "la estructura de
carga que exige Gemma Net". `CAMPOS_CARGUE_GEMANET` reproduce ese orden con
nombres internos; `NOMBRE_DISPLAY` mapea a los encabezados reales (con
tildes y sufijos como "(SI/NO)") para el Excel de salida.

De esos 37 campos, 11 se derivan del catalogo INVIMA + la resolucion de
catalogos de este proyecto (`CAMPO_ORIGEN`). Los otros 26
(`CAMPOS_PENDIENTES_REGLA_NEGOCIO`) no existen en ningun archivo de INVIMA:
se completan con `armado.reglas_negocio.ReglasNegocio`, derivada de la malla
de referencia real -- nunca quedan vacios ni se inventan a ciegas aqui. Ver
armado/reglas_negocio.py para el diagnostico completo de por que cada uno de
esos 26 campos se puede completar con seguridad (o no).

POS y CODIGO_INTERNO_MODELO_SERVICIO son la excepcion dentro de la
excepcion: no tienen un valor de negocio unico, se clasifican por
EXPEDIENTE (ver ReglasNegocio.clasificar). Por eso `preparar_filas_cargue`
NUNCA los completa con un valor incierto -- si el EXPEDIENTE de un
candidato no tiene una clasificacion 100% consistente en la malla de
referencia, esa fila completa queda fuera del Excel. "Listo para cargue" es
binario: o el candidato tiene los 37 campos con certeza, o no esta listo y
`evaluar_candidatos_cargue` dice exactamente por que.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from gemma_cum_loader.armado.reglas_negocio import (
    ClasificacionExpediente,
    ReglasNegocio,
)

CAMPOS_CARGUE_GEMANET = [
    "DESCRIPCION", "GRUPO_MEDICAMENTO", "CODIGO_INTERNO", "CONCENTRACION", "POS",
    "CLASIFICADO", "MARCA_MEDICAMENTO", "EXPEDIENTE", "EDAD_MINIMA", "EDAD_MAXIMA",
    "MAXIMA_VECES_DIA", "MAXIMA_VECES_MESES", "MAXIMA_VECES_ANO", "MAXIMA_VECES_VIDA",
    "TIEMPO_LIMITE_DIAS", "CONSECUTIVO", "CRES", "GENERA_COPAGO_RS", "GENERA_COPAGO_RC",
    "GENERA_CUOTA_MODERADORA", "ACTIVO", "POSOLOGIA", "DIAS", "UNIDAD_MEDIDA",
    "AUTOMATICO", "CAMBIO_CANTIDAD", "VALOR", "REGULADO", "VALOR_REGULADO",
    "RESTRINGIDO", "FORMA_FARMACEUTICA", "PRINCIPIO_ACTIVO", "CODIGO_ATC",
    "FECHA_INICIO", "FECHA_FIN", "CODIGO_INTERNO_MODELO_SERVICIO", "CODIGO_NIVEL_SERVICIO",
]

CAMPOS_PENDIENTES_REGLA_NEGOCIO = [
    "GRUPO_MEDICAMENTO", "POS", "CLASIFICADO", "EDAD_MINIMA", "EDAD_MAXIMA",
    "MAXIMA_VECES_DIA", "MAXIMA_VECES_MESES", "MAXIMA_VECES_ANO", "MAXIMA_VECES_VIDA",
    "TIEMPO_LIMITE_DIAS", "CRES", "GENERA_COPAGO_RS", "GENERA_COPAGO_RC",
    "GENERA_CUOTA_MODERADORA", "ACTIVO", "POSOLOGIA", "DIAS", "AUTOMATICO",
    "CAMBIO_CANTIDAD", "VALOR", "REGULADO", "VALOR_REGULADO", "RESTRINGIDO",
    "FECHA_INICIO", "FECHA_FIN", "CODIGO_INTERNO_MODELO_SERVICIO", "CODIGO_NIVEL_SERVICIO",
]

# campo de salida -> columna de origen en el resultado de pipeline.procesar_invima_vigentes().
# Ausente de este mapeo == mismo nombre en origen y destino.
CAMPO_ORIGEN = {
    "MARCA_MEDICAMENTO": "marca_codigo",
    "UNIDAD_MEDIDA": "unidad_codigo",
    "CODIGO_ATC": "ATC",
}

# encabezados reales confirmados por el usuario -- texto exacto, no Title Case inventado
NOMBRE_DISPLAY = {
    "DESCRIPCION": "DESCRIPCIÓN",
    "GRUPO_MEDICAMENTO": "GRUPO MEDICAMENTO",
    "CODIGO_INTERNO": "CÓDIGO INTERNO",
    "CONCENTRACION": "CONCENTRACIÓN",
    "POS": "POS(SI/NO)",
    "CLASIFICADO": "CLASIFICADO(1:SI, 2:NO, 3.MEDICAMENTO ANCESTRAL, 4. PLAN MEDICINAL)",
    "MARCA_MEDICAMENTO": "MARCA MEDICAMENTO",
    "EXPEDIENTE": "EXPEDIENTE",
    "EDAD_MINIMA": "EDAD MÍN. AÑOS",
    "EDAD_MAXIMA": "EDAD MÁX. AÑOS",
    "MAXIMA_VECES_DIA": "MÁX. VECES DÍA",
    "MAXIMA_VECES_MESES": "MÁX. VECES MES",
    "MAXIMA_VECES_ANO": "MÁX. VECES AÑO",
    "MAXIMA_VECES_VIDA": "MÁX. VECES VIDA",
    "TIEMPO_LIMITE_DIAS": "TIEMPO LÍMITE DÍAS",
    "CONSECUTIVO": "CONSECUTIVO",
    "CRES": "CRES(SI/NO)",
    "GENERA_COPAGO_RS": "GENERA COPAGO RS(SI/NO)",
    "GENERA_COPAGO_RC": "GENERA COPAGO RC(SI/NO)",
    "GENERA_CUOTA_MODERADORA": "GENERA CUOTA MODERADORA(SI/NO)",
    "ACTIVO": "ACTIVO(SI/NO)",
    "POSOLOGIA": "POSOLOGÍA",
    "DIAS": "DÍAS",
    "UNIDAD_MEDIDA": "UNIDAD MEDIDA",
    "AUTOMATICO": "AUTOMATICO(SI/NO)",
    "CAMBIO_CANTIDAD": "CAMBIO CANTIDAD(SI/NO)",
    "VALOR": "VALOR",
    "REGULADO": "REGULADO(SI/NO)",
    "VALOR_REGULADO": "VALOR REGULADO",
    "RESTRINGIDO": "RESTRINGIDO(SI/NO)",
    "FORMA_FARMACEUTICA": "FORMA FARMACEUTICA",
    "PRINCIPIO_ACTIVO": "PRINCIPIO ACTIVO",
    "CODIGO_ATC": "CÓDIGO ATC",
    "FECHA_INICIO": "FECHA INICIO(AAAA/MM/DD)",
    "FECHA_FIN": "FECHA FIN(AAAA/MM/DD)",
    "CODIGO_INTERNO_MODELO_SERVICIO": "CÓDIGO INTERNO MODELO SERVICIO",
    "CODIGO_NIVEL_SERVICIO": "CÓDIGO NIVEL SERVICIO",
}


# Los unicos 4 de los 37 campos del cargue que pueden fallar por candidato --
# los otros 33 siempre se completan con certeza (10-11 directo de INVIMA, el
# resto por regla de negocio, ver docstring del modulo). El nombre de cada
# uno es EXACTAMENTE el mismo que su columna en CAMPOS_CARGUE_GEMANET, para
# que "que campo falla" sea el mismo nombre en todos lados (UI, Excel de
# auditoria, este modulo) -- nunca una descripcion distinta segun donde se mire.
CAMPOS_VERIFICABLES_CARGUE = ["UNIDAD_MEDIDA", "MARCA_MEDICAMENTO", "POS", "CODIGO_INTERNO_MODELO_SERVICIO"]


def _motivo_catalogo_no_resuelto(campo_legible: str, apartado_gemma_net: str, sugerencia: str) -> str:
    """`sugerencia` viene de ResolverCatalogo.sugerencias() -- coincidencias
    aproximadas SIN aplicar el umbral de auto-resolucion. Nunca se presenta
    como respuesta confirmada: es una guia de por donde empezar a buscar,
    el llamador siempre debe verificar contra Gemma Net antes de crear nada.
    """
    base = (
        f"{campo_legible} no se encontro en el catalogo interno. Buscar manualmente en "
        f"Gemma Net ({apartado_gemma_net}) si ya esta creada."
    )
    if sugerencia:
        base += (
            f" Como guia -- NO confirmado, verificar igual en Gemma Net: {sugerencia}."
        )
    else:
        base += " No se encontro ninguna coincidencia aproximada en el catalogo de referencia."
    return base


def evaluar_candidatos_cargue(resultado: pd.DataFrame, reglas: ReglasNegocio) -> pd.DataFrame:
    """Una fila por candidato (accion='candidato'), con la clasificacion de
    POS y CODIGO_INTERNO_MODELO_SERVICIO por EXPEDIENTE, y si esta listo
    para el Excel de cargue o no -- "listo" es binario (`listo_para_cargue`).

    Tres columnas describen por que, cada una con un proposito distinto
    (pedido explicito del usuario: un mensaje generico tipo "alguna de estas
    filas" no alcanza para saber que le falta a un medicamento puntual):
    - `motivo_pendiente`: texto para un humano, con la sugerencia aproximada
      si existe (ver `_motivo_catalogo_no_resuelto`).
    - `campos_con_error`: los nombres EXACTOS de campo que fallan, separados
      por coma (ej. "MARCA_MEDICAMENTO, POS") -- mismos nombres que las
      columnas del Excel de cargue, para ubicar el campo puntual sin tener
      que interpretar prosa.
    - `porcentaje_completitud`: de los `CAMPOS_VERIFICABLES_CARGUE` (los
      unicos 4 que pueden fallar; los otros 33 del cargue siempre se
      completan con certeza por regla de negocio), cuantos SI se
      determinaron para esta fila. 100.0 si esta lista.

    Esta es la fuente de verdad tanto para `preparar_filas_cargue` como para
    lo que se le muestra a negocio: nunca debe haber una fila que la UI diga
    "lista" y esta funcion no respalde.

    Rendimiento: a escala real (decenas de miles de candidatos por corrida)
    `DataFrame.iterrows()` es notoriamente lento (reconstruye una Series por
    fila). Se usa `itertuples()` en su lugar (mucho mas liviano) y se
    memoiza `reglas.clasificar()` por EXPEDIENTE dentro de esta misma
    llamada -- varios candidatos (presentaciones distintas) suelen compartir
    EXPEDIENTE, asi que evita repetir la misma consulta a la malla de
    referencia. El resultado fila por fila es identico al bucle anterior.
    """
    listas = resultado[resultado["accion"] == "candidato"].copy()
    if "unidad_sugerencia" not in listas.columns:
        listas["unidad_sugerencia"] = ""
    if "marca_sugerencia" not in listas.columns:
        listas["marca_sugerencia"] = ""

    cache_clasificacion: dict[tuple[str, object], ClasificacionExpediente] = {}

    def _clasificar_cacheado(campo: str, expediente: object) -> ClasificacionExpediente:
        clave = (campo, expediente)
        if clave not in cache_clasificacion:
            cache_clasificacion[clave] = reglas.clasificar(campo, expediente)
        return cache_clasificacion[clave]

    pos, pos_cierto, modelo, modelo_cierto, motivos, campos_error = [], [], [], [], [], []
    for fila in listas.itertuples():
        motivos_fila = []
        campos_error_fila = []

        if fila.unidad_metodo == "sin_resolver":
            campos_error_fila.append("UNIDAD_MEDIDA")
            motivos_fila.append(
                _motivo_catalogo_no_resuelto(
                    "UNIDAD DE MEDIDA", "Mantenimiento Unidades de Medida", fila.unidad_sugerencia
                )
            )
        if fila.marca_metodo == "sin_resolver":
            campos_error_fila.append("MARCA_MEDICAMENTO")
            motivos_fila.append(
                _motivo_catalogo_no_resuelto(
                    "MARCA MEDICAMENTO", "Mantenimiento Marcas de Medicamentos", fila.marca_sugerencia
                )
            )

        clasif_pos = _clasificar_cacheado("POS", fila.EXPEDIENTE)
        clasif_modelo = _clasificar_cacheado("CODIGO_INTERNO_MODELO_SERVICIO", fila.EXPEDIENTE)
        if not clasif_pos.cierta:
            campos_error_fila.append("POS")
            if clasif_pos.motivo:
                motivos_fila.append(clasif_pos.motivo)
        if not clasif_modelo.cierta:
            campos_error_fila.append("CODIGO_INTERNO_MODELO_SERVICIO")
            if clasif_modelo.motivo:
                motivos_fila.append(clasif_modelo.motivo)

        pos.append(clasif_pos.valor)
        pos_cierto.append(clasif_pos.cierta)
        modelo.append(clasif_modelo.valor)
        modelo_cierto.append(clasif_modelo.cierta)
        motivos.append(" | ".join(motivos_fila))
        campos_error.append(campos_error_fila)

    listas["_pos"] = pos
    listas["_modelo_servicio"] = modelo
    listas["listo_para_cargue"] = [len(c) == 0 for c in campos_error]
    listas["motivo_pendiente"] = motivos
    listas["campos_con_error"] = [", ".join(c) for c in campos_error]
    listas["porcentaje_completitud"] = [
        round((len(CAMPOS_VERIFICABLES_CARGUE) - len(c)) / len(CAMPOS_VERIFICABLES_CARGUE) * 100, 1)
        for c in campos_error
    ]
    return listas


def armar_columnas_cargue(evaluados: pd.DataFrame, reglas: ReglasNegocio) -> pd.DataFrame:
    """Arma los 37 campos a partir del resultado de `evaluar_candidatos_cargue`
    -- compartido entre `preparar_filas_cargue` (solo listos) y
    `exportacion.estructura_cargue` (todos, con estado y motivo). No filtra
    nada: quien llama decide que filas de `evaluados` le pasa.
    """
    salida = pd.DataFrame(index=evaluados.index)
    for campo in CAMPOS_CARGUE_GEMANET:
        if campo == "POS":
            salida[campo] = evaluados["_pos"]
        elif campo == "CODIGO_INTERNO_MODELO_SERVICIO":
            salida[campo] = evaluados["_modelo_servicio"]
        elif campo in CAMPOS_PENDIENTES_REGLA_NEGOCIO:
            salida[campo] = reglas.valor(campo)
        else:
            salida[campo] = evaluados[CAMPO_ORIGEN.get(campo, campo)]
    return salida


def preparar_filas_cargue(resultado: pd.DataFrame, reglas: ReglasNegocio) -> pd.DataFrame:
    """Solo las filas que `evaluar_candidatos_cargue` marco `listo_para_cargue`
    -- los 37 campos con certeza, ninguno vacio ni adivinado. El cruce contra
    Gemma Net (fase 6, accion='ya_existe') y la resolucion de catalogo son
    chequeos independientes: una fila puede ser nueva para Gemma Net y aun
    asi no tener marca o unidad resuelta, o no tener POS/modelo de servicio
    ciertos -- cualquiera de esos casos la deja fuera.
    """
    evaluados = evaluar_candidatos_cargue(resultado, reglas)
    listos = evaluados[evaluados["listo_para_cargue"]]
    return armar_columnas_cargue(listos, reglas)


def generar_excel_cargue(df_cargue: pd.DataFrame, ruta: str | Path) -> None:
    df_cargue.rename(columns=NOMBRE_DISPLAY).to_excel(ruta, index=False)
