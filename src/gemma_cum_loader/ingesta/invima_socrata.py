"""Adaptador de los datasets de CUM de INVIMA en Datos Abiertos Colombia
(Socrata): "CODIGO UNICO DE MEDICAMENTOS VIGENTES" (`i7cb-raxc`) y su
contraparte "CODIGO UNICO DE MEDICAMENTOS VENCIDOS" (`vwwf-4ftk`). Ambos
confirmados contra la API real de metadatos el 2026-08-14: mismo publicador
(Instituto Nacional de Vigilancia de Medicamentos y Alimentos - INVIMA),
mismas 29 columnas en el mismo orden -- Vencidos es literalmente la misma
estructura, solo que para registros sanitarios cuya vigencia ya expiro.

`leer_catalogo_invima_api()` produce el MISMO DataFrame (mismas columnas
normalizadas, mismo CODIGO_INTERNO) que `ingesta/invima_reader.py::
leer_catalogo_invima` -- el resto del pipeline (armado/malla.py, etc.) no
distingue si el origen fue un archivo subido o esta API. Reemplaza la
descarga manual del Excel para el proceso masivo mensual; la subida de
archivo se mantiene como respaldo si Socrata no esta disponible (decision
del usuario). El parametro `dataset` permite reusar la misma funcion para
Vencidos -- ver `auditoria/coherencia_invima.py`, que la usa para distinguir
un codigo con registro VENCIDO (riesgo real de autorizar un medicamento sin
vigencia) de un codigo legado que nunca tuvo expediente INVIMA.

`consultar_cum()` es la consulta puntual bajo demanda (ej. boton "verificar
contra INVIMA" en la bandeja de cuarentena) -- clasifica el resultado en
los estados que el usuario definio explicitamente, nunca inventa un estado
nuevo.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Any

import pandas as pd

from gemma_cum_loader.integraciones import socrata
from gemma_cum_loader.normaliza.texto import normalizar, normalizar_encabezado

DATASET_CUM_VIGENTES = "i7cb-raxc"
DATASET_CUM_VENCIDOS = "vwwf-4ftk"
# Confirmados via metadata real de Socrata el 2026-08-19 (/api/views/{id}.json):
# mismo publicador (INVIMA) y mismas 29 columnas, mismo orden, que Vigentes/
# Vencidos -- ver auditoria/coherencia_invima.py para como se usan (Tramite de
# Renovacion: riesgo medio, Otros Estados: riesgo alto, agrupa Cancelado/
# Suspendido/etc.). Ambos confirmados vacios (count(*)=0) el mismo dia --
# mismo outage que ya afecta a Vigentes/Vencidos.
DATASET_CUM_RENOVACION = "vgr4-gemg"
DATASET_CUM_OTROS_ESTADOS = "spzp-dfuc"

# campo de la API -> encabezado real del Excel (mismo orden que el dataset
# real, confirmado via /api/views/i7cb-raxc.json el 2026-08-14)
CAMPOS_API = {
    "expediente": "EXPEDIENTE",
    "producto": "PRODUCTO",
    "titular": "TITULAR",
    "registrosanitario": "REGISTRO SANITARIO",
    "fechaexpedicion": "FECHA EXPEDICION",
    "fechavencimiento": "FECHA VENCIMIENTO",
    "estadoregistro": "ESTADO REGISTRO",
    "expedientecum": "EXPEDIENTE CUM",
    "consecutivocum": "CONSECUTIVO",
    "cantidadcum": "CANTIDAD CUM",
    "descripcioncomercial": "DESCRIPCION COMERCIAL",
    "estadocum": "ESTADO CUM",
    "fechaactivo": "FECHA ACTIVO",
    "fechainactivo": "FECHA INACTIVO",
    "muestramedica": "MUESTRA MEDICA",
    "unidad": "UNIDAD",
    "atc": "ATC",
    "descripcionatc": "DESCRIPCION_ATC",
    "viaadministracion": "VIA ADMINISTRACION",
    "concentracion": "CONCENTRACION",
    "principioactivo": "PRINCIPIO ACTIVO",
    "unidadmedida": "UNIDAD MEDIDA",
    "cantidad": "CANTIDAD",
    "unidadreferencia": "UNIDAD REFERENCIA",
    "formafarmaceutica": "FORMA FARMACEUTICA",
    "nombrerol": "NOMBRE ROL",
    "tiporol": "TIPO ROL",
    "modalidad": "MODALIDAD",
    "ium": "IUM",
}


def leer_catalogo_invima_api(
    token: str | None = None,
    sesion: socrata.SesionHTTP | None = None,
    dataset: str = DATASET_CUM_VIGENTES,
) -> pd.DataFrame:
    """Trae TODO el dataset (Vigentes por defecto, o Vencidos pasando
    `dataset=DATASET_CUM_VENCIDOS`) via paginacion y lo arma con la misma
    forma que `invima_reader.leer_catalogo_invima` (Excel). A escala real
    son ~100.000+ filas -- se pagina con $limit/$offset, no hay forma de
    traerlo en una sola llamada.

    Esta funcion SIEMPRE trae el dataset completo sin filtro ($where) --
    a diferencia de `consultar()`/`consultar_todo()` genericos (donde 0
    filas puede ser un resultado valido de una consulta filtrada), aca 0
    filas nunca es legitimo: INVIMA siempre tiene miles de registros
    vigentes y vencidos. Un 200 OK con el dataset completo vacio es una
    señal de problema del lado de Socrata/datos.gov.co (caso real
    verificado 2026-08-18: la vista existia con metadata normal pero el
    recurso de datos devolvia count(*)=0 para Vigentes Y Vencidos a la
    vez), nunca "hoy no hay medicamentos vigentes en Colombia" -- se
    rechaza en vez de dejar seguir el pipeline con un catalogo vacio, que
    haria ver TODO lo cargado en Gemma Net como sin vigencia.
    """
    filas = socrata.consultar_todo(dataset, token=token, sesion=sesion)
    if not filas:
        raise socrata.ErrorSocrata(
            f"El dataset de INVIMA '{dataset}' respondio 0 filas para una sincronizacion "
            "completa (sin filtro) -- esto no es un resultado valido, INVIMA siempre tiene "
            "registros vigentes y vencidos. Probable problema temporal del lado de Socrata/"
            "datos.gov.co, no de esta aplicacion. Reintenta en unos minutos; si persiste, usa "
            "el Excel de respaldo mientras tanto."
        )
    df = pd.DataFrame(filas)
    if df.empty:
        df = pd.DataFrame(columns=list(CAMPOS_API.values()))
    else:
        df = df.rename(columns={api: excel for api, excel in CAMPOS_API.items() if api in df.columns})
    df.columns = [normalizar_encabezado(c) for c in df.columns]

    if "EXPEDIENTE" in df.columns:
        df["EXPEDIENTE"] = pd.to_numeric(df["EXPEDIENTE"], errors="coerce").astype("Int64")
    if "CONSECUTIVO" in df.columns:
        df["CONSECUTIVO"] = pd.to_numeric(df["CONSECUTIVO"], errors="coerce").astype("Int64")
    if {"EXPEDIENTE", "CONSECUTIVO"}.issubset(df.columns):
        df["CODIGO_INTERNO"] = df["EXPEDIENTE"].astype(str) + "-" + df["CONSECUTIVO"].astype(str)

    return df


class EstadoValidacionCUM(Enum):
    VALIDO_VIGENTE = "valido_vigente"
    NO_ENCONTRADO = "no_encontrado"
    FORMATO_INCORRECTO = "formato_incorrecto"
    VACIO = "vacio"
    CON_DIFERENCIAS = "con_diferencias"
    PENDIENTE_REVISION = "pendiente_revision"
    API_NO_CONFIGURADA = "api_no_configurada"
    SERVICIO_NO_DISPONIBLE = "servicio_no_disponible"
    ERROR_AUTENTICACION = "error_autenticacion"


@dataclass(frozen=True)
class ResultadoValidacionCUM:
    codigo_interno: str
    estado: EstadoValidacionCUM
    mensaje: str
    fecha_consulta: dt.datetime
    datos_oficiales: dict[str, Any] | None = None


def consultar_cum(
    codigo_interno: str,
    token: str | None = None,
    sesion: socrata.SesionHTTP | None = None,
) -> ResultadoValidacionCUM:
    """Consulta puntual bajo demanda -- nunca se usa en el proceso masivo
    (eso es `leer_catalogo_invima_api`). El resultado no se guarda dentro de
    ningun registro de medicamento; solo trae estado + fecha + datos
    oficiales de referencia para que el equipo de negocio decida.
    """
    ahora = dt.datetime.now()
    codigo_interno = str(codigo_interno).strip() if codigo_interno else ""

    if not codigo_interno:
        return ResultadoValidacionCUM(
            codigo_interno=codigo_interno,
            estado=EstadoValidacionCUM.VACIO,
            mensaje="El codigo interno esta vacio.",
            fecha_consulta=ahora,
        )

    partes = codigo_interno.rsplit("-", 1)
    if len(partes) != 2 or not partes[0].isdigit() or not partes[1].isdigit():
        return ResultadoValidacionCUM(
            codigo_interno=codigo_interno,
            estado=EstadoValidacionCUM.FORMATO_INCORRECTO,
            mensaje=(
                f"'{codigo_interno}' no sigue el formato EXPEDIENTE-CONSECUTIVO "
                "esperado para un CUM de INVIMA."
            ),
            fecha_consulta=ahora,
        )
    expediente, consecutivo = partes

    if token is None:
        estado_token = socrata.estado_token()
        if not estado_token.configurado:
            return ResultadoValidacionCUM(
                codigo_interno=codigo_interno,
                estado=EstadoValidacionCUM.API_NO_CONFIGURADA,
                mensaje=(
                    f"No hay App Token configurado (variable de entorno "
                    f"{socrata.NOMBRE_VARIABLE_ENTORNO}) -- la integracion con INVIMA "
                    "no esta disponible."
                ),
                fecha_consulta=ahora,
            )

    where = f"expediente='{expediente}' AND consecutivocum='{consecutivo}'"
    try:
        filas = socrata.consultar(
            DATASET_CUM_VIGENTES, {"$where": where}, token=token, sesion=sesion
        )
    except socrata.ErrorAutenticacionSocrata as exc:
        return ResultadoValidacionCUM(
            codigo_interno=codigo_interno,
            estado=EstadoValidacionCUM.ERROR_AUTENTICACION,
            mensaje=str(exc),
            fecha_consulta=ahora,
        )
    except socrata.ErrorSocrata as exc:
        return ResultadoValidacionCUM(
            codigo_interno=codigo_interno,
            estado=EstadoValidacionCUM.SERVICIO_NO_DISPONIBLE,
            mensaje=str(exc),
            fecha_consulta=ahora,
        )

    if not filas:
        # 0 filas para ESTA consulta puntual no siempre significa "este CUM
        # no existe" -- puede significar que el dataset COMPLETO de INVIMA
        # esta vacio ahora mismo (caso real 2026-08-18, ver memoria del
        # proyecto: el recurso respondio 200 OK con 0 filas para TODO,
        # token valido incluido). Sin este chequeo, un problema temporal de
        # INVIMA se leeria como "el medicamento no existe" -- un mensaje
        # equivocado que un usuario podria tomar como base para negar una
        # autorizacion. Se verifica antes de concluir NO_ENCONTRADO.
        try:
            hay_datos_en_general = socrata.hay_datos(DATASET_CUM_VIGENTES, token=token, sesion=sesion)
        except socrata.ErrorSocrata:
            hay_datos_en_general = False
        if not hay_datos_en_general:
            return ResultadoValidacionCUM(
                codigo_interno=codigo_interno,
                estado=EstadoValidacionCUM.SERVICIO_NO_DISPONIBLE,
                mensaje=(
                    "El listado vigente de INVIMA no tiene datos disponibles en este momento "
                    "(no es que este CUM puntual no exista -- el dataset completo esta vacio "
                    "del lado de INVIMA/datos.gov.co). No se puede confirmar ni descartar este "
                    "codigo hasta que se restablezca."
                ),
                fecha_consulta=ahora,
            )
        return ResultadoValidacionCUM(
            codigo_interno=codigo_interno,
            estado=EstadoValidacionCUM.NO_ENCONTRADO,
            mensaje=f"El CUM {codigo_interno} no aparece en el listado vigente de INVIMA.",
            fecha_consulta=ahora,
        )

    return ResultadoValidacionCUM(
        codigo_interno=codigo_interno,
        estado=EstadoValidacionCUM.VALIDO_VIGENTE,
        mensaje="Encontrado en el listado vigente de INVIMA.",
        fecha_consulta=ahora,
        datos_oficiales=filas[0],
    )


def comparar_nombre(nombre_local: str, resultado: ResultadoValidacionCUM) -> EstadoValidacionCUM:
    """Si `resultado` ya es VALIDO_VIGENTE, compara el nombre/producto local
    contra el oficial (normalizado) y degrada a CON_DIFERENCIAS si no
    coinciden -- nunca decide cual es el correcto, solo lo senala.
    """
    if resultado.estado != EstadoValidacionCUM.VALIDO_VIGENTE or not resultado.datos_oficiales:
        return resultado.estado
    producto_oficial = resultado.datos_oficiales.get("producto", "")
    if normalizar(nombre_local) == normalizar(producto_oficial):
        return EstadoValidacionCUM.VALIDO_VIGENTE
    return EstadoValidacionCUM.CON_DIFERENCIAS
