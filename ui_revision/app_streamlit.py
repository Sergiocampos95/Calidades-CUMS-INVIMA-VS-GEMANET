"""Vista de revision y cargue: corre el pipeline, muestra el resultado y
genera el TXT que se sube a Gemma Net.

Solo pide dos archivos -- Listado Codigo Unico de Medicamentos Vigentes de
INVIMA, y el export de la propia Gemma Net -- via selector nativo del
navegador (st.file_uploader), nunca rutas escritas a mano. La malla y el
catalogo de alias ya no se piden: la primera la arma este pipeline
(gemma_cum_loader.armado.malla), el segundo quedo fuera de alcance por
pedido explicito del usuario.

Estilo tomado de design/design_tokens.json y el mapeo de patrones en
design/components.md (capturas del formulario "Mantenimiento Medicamentos"
de Gemma Net, recibidas 2026-08-13). Estructura del cargue confirmada
contra el export real -- ver exportacion/cargue.py.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st
from openpyxl.utils.exceptions import InvalidFileException

# Errores que SOLO significan "el archivo esta corrupto/incompleto/no es un
# .xlsx valido" -- nunca los lanza nuestro propio codigo de negocio. Se
# capturan aparte (mensaje claro, sin traceback crudo) sin ocultar un bug
# real: cualquier otra excepcion sigue propagandose tal cual.
_ERRORES_ARCHIVO_CORRUPTO = (zipfile.BadZipFile, ET.ParseError, InvalidFileException)

from gemma_cum_loader.armado.malla import CLASIFICACIONES_CREACION, universo_invima_clasificado
from gemma_cum_loader.armado.reglas_negocio import ReglasNegocio, derivar_reglas_negocio, leer_malla_referencia
from gemma_cum_loader.catalogos.ia_client import ClienteExplicacionIA, ExplicacionIA
from gemma_cum_loader.exportacion.cargue import (
    CAMPOS_VERIFICABLES_CARGUE,
    evaluar_candidatos_cargue,
    generar_excel_cargue,
    preparar_filas_cargue,
)
from gemma_cum_loader.exportacion.estructura_cargue import (
    armar_estructura_cargue,
    generar_excel_estructura_cargue,
    nombre_periodo,
)
from gemma_cum_loader.auditoria.coherencia_invima import CAMPOS_COMPARADOS_COHERENCIA, EstadoCoherencia
from gemma_cum_loader.ingesta.invima_reader import (
    leer_catalogo_invima,
    leer_catalogo_invima_otros_estados,
    leer_catalogo_invima_renovacion,
    leer_catalogo_invima_vencidos,
)
from gemma_cum_loader.ingesta.invima_socrata import (
    DATASET_CUM_OTROS_ESTADOS,
    DATASET_CUM_RENOVACION,
    DATASET_CUM_VENCIDOS,
    DATASET_CUM_VIGENTES,
    EstadoValidacionCUM,
    ResultadoValidacionCUM,
    consultar_cum,
    leer_catalogo_invima_api,
)
from gemma_cum_loader.integraciones import socrata
from gemma_cum_loader.pipeline import (
    auditar_coherencia_gemanet,
    guardar_reporte,
    procesar_desde_catalogo_invima,
)

_MENSAJE_ESTADO_CUM = {
    EstadoValidacionCUM.VALIDO_VIGENTE: ("success", "Válido y vigente en INVIMA."),
    EstadoValidacionCUM.NO_ENCONTRADO: ("error", "No se encontró en el listado vigente de INVIMA."),
    EstadoValidacionCUM.FORMATO_INCORRECTO: ("error", "Formato de código incorrecto."),
    EstadoValidacionCUM.VACIO: ("warning", "El código está vacío."),
    EstadoValidacionCUM.CON_DIFERENCIAS: ("warning", "Encontrado, pero con diferencias frente al dato local."),
    EstadoValidacionCUM.PENDIENTE_REVISION: ("warning", "Pendiente de revisión."),
    EstadoValidacionCUM.API_NO_CONFIGURADA: ("warning", "La integración con INVIMA no está configurada."),
    EstadoValidacionCUM.SERVICIO_NO_DISPONIBLE: ("error", "El servicio de INVIMA no está disponible en este momento."),
    EstadoValidacionCUM.ERROR_AUTENTICACION: ("error", "El App Token fue rechazado por Socrata."),
}

_MENSAJE_ESTADO_COHERENCIA = {
    EstadoCoherencia.CORRECTO.value: "Correcto — coincide con el dato oficial de INVIMA.",
    EstadoCoherencia.CON_DIFERENCIAS.value: "Con diferencias frente al dato oficial de INVIMA — revisar campos.",
    EstadoCoherencia.VENCIDO_EN_INVIMA.value: (
        "⚠ Registro sanitario VENCIDO en INVIMA — riesgo de autorizar un medicamento sin vigencia."
    ),
    EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value: (
        "⚠ Encontrado en Otros Estados de INVIMA (Cancelado/Suspendido/Inactivo/etc.) — "
        "ver ESTADO_INVIMA_DETALLE para el valor exacto."
    ),
    EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value: (
        "En trámite de renovación en INVIMA — riesgo medio, la renovación está en curso."
    ),
    EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value: (
        "Sin correspondencia en ningún dataset de INVIMA — probable código legado sin expediente INVIMA."
    ),
}

_ETIQUETA_CLASIFICACION_CREACION = {
    "candidato": "Candidato",
    "rol_no_fabricante": "Rol ≠ FABRICANTE",
    "cum_inactivo": "CUM inactivo",
    "registro_no_vigente": "Registro no vigente",
    "muestra_medica": "Muestra médica",
}

RAIZ = Path(__file__).resolve().parent.parent
RUTA_TOKENS = RAIZ / "design" / "design_tokens.json"


def _cargar_tokens() -> dict:
    with open(RUTA_TOKENS, encoding="utf-8") as f:
        return json.load(f)


def _inyectar_css(tokens: dict) -> None:
    color = tokens["color"]
    tipografia = tokens["tipografia"]
    forma = tokens["forma"]
    st.markdown(
        f"""
        <style>
        .stApp {{ background-color: {color["fondo_pagina"]["valor"]}; }}
        .barra-superior {{
            background-color: {color["primario"]["valor"]};
            color: white;
            padding: 0.75rem 1.25rem;
            border-radius: {forma["radio_input_px"]}px;
            display: flex;
            align-items: center;
            gap: 0.6rem;
            font-family: {tipografia["familia"]};
            margin-bottom: 1rem;
        }}
        .barra-superior .logo {{
            background-color: {color["acento_logo"]["valor"]};
            color: white;
            border-radius: 999px;
            width: 28px;
            height: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
        }}
        .barra-superior .titulo {{
            font-size: {tipografia["tamano_titulo_px"]}px;
            font-weight: {tipografia["peso_titulo"]};
        }}
        div[data-testid="stMetric"] {{
            background-color: {color["fondo_input"]["valor"]};
            border: 1px solid {color["borde_input"]["valor"]};
            border-radius: {forma["radio_input_px"]}px;
            padding: 0.75rem;
        }}
        .stButton > button {{
            background-color: {color["fondo_boton"]["valor"]};
            color: {color["texto_boton"]["valor"]};
            border-radius: {forma["radio_boton_px"]}px;
            border: none;
        }}
        /* Streamlit atenua (opacity baja) TODA la pagina mientras corre
        cualquier accion, marcando los elementos con data-stale="true" --
        pedido explicito del usuario: que el resto de la pantalla se vea
        normal, el aviso de "cargando" debe quedar solo en el spinner
        puntual de la accion en curso (st.spinner), no en toda la app. */
        div[data-stale="true"], div[data-stale="true"] * {{
            opacity: 1 !important;
            transition: none !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _indicador_token(estado: socrata.EstadoToken) -> str:
    """Icono chico de estado, no una explicacion tecnica en pantalla -- quien
    diligencia la carga no necesita saber que es un "App Token" de Socrata
    ni donde se configura, solo si la conexion con INVIMA esta lista o
    limitada. Pedido explicito del usuario: esa informacion tecnica "no la
    va a ver alguien que diligencie esta subida" -- el detalle completo
    queda en el tooltip (`_ayuda_token`), visible solo al pasar el mouse.
    """
    return "🟢 Conexión con INVIMA lista" if estado.configurado else "🔴 Conexión con INVIMA limitada"


def _ayuda_token(estado: socrata.EstadoToken) -> str:
    if estado.configurado:
        return (
            f"App Token configurado (variable de entorno) — terminado en "
            f"...{estado.token_enmascarado[-4:]}."
        )
    return (
        f"No hay App Token en la variable de entorno {socrata.NOMBRE_VARIABLE_ENTORNO}. La "
        "consulta funciona igual de forma anónima, pero con un límite de consultas mucho más "
        "bajo en Socrata — configura el token antes de una corrida real con 100.000+ filas."
    )


def _barra_superior() -> None:
    st.markdown(
        """
        <div class="barra-superior">
            <div class="logo">g</div>
            <div class="titulo">Gemma CUM Loader — Cruce contra catalogo INVIMA</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


_MAX_VALORES_FILTRO = 200  # mas que esto, un multiselect es inmanejable, no un filtro util


def _tabla_filtrable(
    df: pd.DataFrame,
    columnas_filtro: list[str],
    key_prefix: str,
    columnas_mostrar: list[str] | None = None,
    height: int | None = None,
) -> pd.DataFrame:
    """Toda tabla de medicamentos se muestra con (1) un cuadro de búsqueda
    libre -- escribir a mano cualquier texto (código, expediente, nombre...)
    -- y (2) un multiselect de filtro por cada columna en `columnas_filtro`,
    para acotar por categoría -- pedido explícito del usuario: nunca
    mostrar la tabla en crudo, y poder escribir la búsqueda a mano, no solo
    elegir de una lista fija. Devuelve el DataFrame ya filtrado, para que
    quien llama pueda reusarlo (ej. las explicaciones de IA en la bandeja
    de cuarentena solo deben cubrir lo que el usuario dejó visible, no la
    tabla completa).

    Columnas con más de `_MAX_VALORES_FILTRO` valores distintos (ej.
    CODIGO_INTERNO en un lote de 100.000 filas) no se ofrecen como filtro
    de categoría -- un multiselect con esa cardinalidad no es utilizable;
    para esos casos, la búsqueda libre es la forma de acotar.
    """
    columnas_busqueda = columnas_mostrar or list(df.columns)
    busqueda = st.text_input(
        "🔎 Buscar (código, expediente, nombre... cualquier texto)",
        key=f"{key_prefix}_busqueda",
        placeholder="Escribe aquí y la tabla se acota sola",
    )
    filtrado = df
    if busqueda.strip():
        texto = busqueda.strip().lower()
        coincide = pd.Series(False, index=filtrado.index)
        for columna in columnas_busqueda:
            if columna in filtrado.columns:
                coincide = coincide | filtrado[columna].astype(str).str.lower().str.contains(
                    texto, na=False, regex=False
                )
        filtrado = filtrado[coincide]

    columnas_validas = [c for c in columnas_filtro if c in df.columns and df[c].nunique() <= _MAX_VALORES_FILTRO]
    if columnas_validas:
        widgets = st.columns(len(columnas_validas))
        for widget, campo in zip(widgets, columnas_validas, strict=True):
            valores = sorted(df[campo].dropna().astype(str).unique())
            seleccion = widget.multiselect(
                f"Filtrar por {campo}", valores, default=valores, key=f"{key_prefix}_{campo}"
            )
            filtrado = filtrado[filtrado[campo].astype(str).isin(seleccion)]
    salida = filtrado[columnas_mostrar] if columnas_mostrar else filtrado
    st.dataframe(salida, use_container_width=True, height=height)
    return filtrado


_ICONO_SEVERIDAD_ALERTA = {"error": "🔴", "warning": "🟡"}


def _mostrar_tarjetas_alerta(alertas: list[tuple[str, str, str]]) -> None:
    """Muestra cada advertencia como una tarjeta compacta (icono + título
    corto de una línea) en vez del párrafo completo en un banner ancho de
    color -- pedido explícito del usuario: los mensajes de advertencia eran
    "innecesariamente detallados" y "poco discretos". El texto largo (el
    "por qué"/"qué hacer") sigue disponible, pero un clic aparte (expander),
    no forzado en pantalla.

    `alertas`: lista de (severidad, título_corto, detalle_largo) --
    severidad es "error" (riesgo alto: vencido/otro estado INVIMA) o
    "warning" (todo lo demás).
    """
    columnas = st.columns(3)
    for i, (severidad, titulo, detalle) in enumerate(alertas):
        with columnas[i % 3], st.container(border=True):
            st.markdown(f"{_ICONO_SEVERIDAD_ALERTA.get(severidad, '🟡')} **{titulo}**")
            if detalle:
                with st.expander("Detalle"):
                    st.caption(detalle)


@st.cache_data(show_spinner=False, ttl=180)
def _hay_datos_invima_api() -> bool:
    """Chequeo liviano y proactivo (no la sincronizacion completa) de si el
    dataset de Vigentes tiene filas AHORA MISMO -- se corre apenas se elige
    la fuente API, antes de subir archivos o de presionar "Procesar", para
    poder recomendar el Excel de respaldo de una vez en vez de que el
    usuario descubra el problema recien despues de una corrida completa.
    ttl=180 (3 min): information corta para no quedar desactualizada si el
    dataset se recupera, pero sin golpear Socrata en cada rerun de Streamlit.
    Cualquier problema de transporte (`ErrorSocrata`) tambien cuenta como
    "no disponible" aca -- este chequeo es solo una senal temprana, la
    sincronizacion real sigue siendo la que decide con `leer_catalogo_invima_api`.
    """
    try:
        return socrata.hay_datos(DATASET_CUM_VIGENTES)
    except socrata.ErrorSocrata:
        return False


@st.cache_data(show_spinner=False, ttl=3600)
def _cargar_invima_desde_api(dataset: str = DATASET_CUM_VIGENTES) -> pd.DataFrame:
    # ttl=3600: no repetir la sincronizacion completa del dataset INVIMA en
    # cada rerun de Streamlit dentro de la misma hora de trabajo
    return leer_catalogo_invima_api(dataset=dataset)


@st.cache_data(show_spinner=False)
def _cargar_invima_desde_archivo(archivo_invima) -> pd.DataFrame:
    return leer_catalogo_invima(archivo_invima)


@st.cache_data(show_spinner=False)
def _cargar_invima_vencidos_desde_archivo(archivo_invima_vencidos) -> pd.DataFrame:
    return leer_catalogo_invima_vencidos(archivo_invima_vencidos)


@st.cache_data(show_spinner=False)
def _cargar_invima_renovacion_desde_archivo(archivo_invima_renovacion) -> pd.DataFrame:
    return leer_catalogo_invima_renovacion(archivo_invima_renovacion)


@st.cache_data(show_spinner=False)
def _cargar_invima_otros_estados_desde_archivo(archivo_invima_otros_estados) -> pd.DataFrame:
    return leer_catalogo_invima_otros_estados(archivo_invima_otros_estados)


@st.cache_data(show_spinner=False)
def _procesar_candidatos(df_invima: pd.DataFrame, archivo_gemma_net) -> pd.DataFrame:
    return procesar_desde_catalogo_invima(df_invima, archivo_gemma_net)


@st.cache_data(show_spinner=False)
def _clasificar_universo_invima(df_invima: pd.DataFrame) -> pd.DataFrame:
    return universo_invima_clasificado(df_invima)


# Streamlit reejecuta TODO el script en cada interaccion de CUALQUIER widget
# de la pagina (ej. escribir en el buscador de otra pestana) -- sin cachear,
# estas funciones (las mas pesadas de la pestana de cargue) se recalculaban
# desde cero en cada una de esas interacciones, aunque nada de lo que
# necesitan haya cambiado. Cachearlas por (resultado, reglas) evita ese
# recalculo innecesario; solo se vuelven a correr si el candidato o la
# malla de referencia realmente cambiaron.
@st.cache_data(show_spinner=False)
def _leer_malla_referencia_cacheada(archivo_malla_referencia) -> pd.DataFrame:
    return leer_malla_referencia(archivo_malla_referencia)


@st.cache_data(show_spinner=False)
def _derivar_reglas_negocio_cacheada(malla_referencia: pd.DataFrame) -> ReglasNegocio:
    return derivar_reglas_negocio(malla_referencia)


@st.cache_data(show_spinner=False)
def _evaluar_candidatos_cargue_cacheado(resultado: pd.DataFrame, reglas: ReglasNegocio) -> pd.DataFrame:
    return evaluar_candidatos_cargue(resultado, reglas)


@st.cache_data(show_spinner=False)
def _armar_estructura_cargue_cacheada(resultado: pd.DataFrame, reglas: ReglasNegocio) -> pd.DataFrame:
    return armar_estructura_cargue(resultado, reglas)


@st.cache_data(show_spinner=False)
def _preparar_filas_cargue_cacheada(resultado: pd.DataFrame, reglas: ReglasNegocio) -> pd.DataFrame:
    return preparar_filas_cargue(resultado, reglas)


# Escribir a .xlsx y releer los bytes es I/O real (no solo calculo) -- sin
# cachear esto, se repetia en cada rerun de Streamlit aunque el DataFrame de
# origen no hubiera cambiado (ej. al escribir en un buscador de otra
# pestana). Cacheado por el contenido del DataFrame, no por la lambda (las
# lambdas no son cacheables de forma util).
@st.cache_data(show_spinner=False)
def _bytes_reporte_cruce(resultado: pd.DataFrame) -> bytes:
    return _exportar_a_bytes(lambda ruta: guardar_reporte(resultado, ruta))


@st.cache_data(show_spinner=False)
def _bytes_estructura_cargue(df_estructura: pd.DataFrame) -> bytes:
    return _exportar_a_bytes(lambda ruta: generar_excel_estructura_cargue(df_estructura, ruta))


@st.cache_data(show_spinner=False)
def _bytes_cargue_final(df_cargue: pd.DataFrame) -> bytes:
    return _exportar_a_bytes(lambda ruta: generar_excel_cargue(df_cargue, ruta))


@st.cache_data(show_spinner=False)
def _bytes_auditoria_coherencia(auditoria: pd.DataFrame) -> bytes:
    return _exportar_a_bytes(lambda ruta: guardar_reporte(auditoria, ruta, columna_hoja="ESTADO_COHERENCIA"))


@st.cache_data(show_spinner=False)
def _auditar_coherencia(
    df_invima: pd.DataFrame,
    archivo_gemma_net,
    df_invima_vencidos: pd.DataFrame | None,
    df_invima_otros_estados: pd.DataFrame | None = None,
    df_invima_renovacion: pd.DataFrame | None = None,
) -> pd.DataFrame:
    return auditar_coherencia_gemanet(
        df_invima,
        archivo_gemma_net,
        df_invima_vencidos,
        df_invima_otros_estados=df_invima_otros_estados,
        df_invima_renovacion=df_invima_renovacion,
    )


def _cliente_ia_disponible() -> ClienteExplicacionIA | None:
    """None si no hay ANTHROPIC_API_KEY en el entorno -- la IA es opcional,
    el pipeline y la bandeja de cuarentena funcionan sin ella."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    if "cliente_ia" not in st.session_state:
        st.session_state["cliente_ia"] = ClienteExplicacionIA()
    return st.session_state["cliente_ia"]


@st.cache_data(show_spinner=False)
def _explicar_motivo_cacheado(_cliente_ia: ClienteExplicacionIA, accion: str, motivo: str) -> ExplicacionIA:
    """Cacheado por (accion, motivo) -- una llamada a la IA por motivo distinto,
    nunca una por fila, sin importar cuantas filas tenga la malla."""
    return _cliente_ia.explicar_motivo(accion, motivo)


def main() -> None:
    st.set_page_config(page_title="Gemma CUM Loader", layout="wide")
    tokens = _cargar_tokens()
    _inyectar_css(tokens)
    _barra_superior()

    with st.expander("Archivos de entrada", expanded=True):
        fuente_invima = st.radio(
            "Listado Código Único de Medicamentos Vigentes — fuente",
            ["API de Socrata (Datos Abiertos Colombia)", "Subir archivo Excel (respaldo)"],
            help="La API consulta en vivo el dataset oficial de INVIMA (i7cb-raxc) -- ya no hace "
            "falta descargar el Excel a mano. La opcion de subir el archivo queda como respaldo "
            "si Socrata no esta disponible.",
        )
        usar_api_invima = fuente_invima.startswith("API")

        estado_token = socrata.estado_token()
        archivo_invima = None
        if usar_api_invima:
            st.caption(_indicador_token(estado_token), help=_ayuda_token(estado_token))
            with st.spinner("Verificando disponibilidad del dataset de INVIMA..."):
                datos_disponibles = _hay_datos_invima_api()
            if not datos_disponibles:
                st.warning(
                    "⚠ El listado de INVIMA no tiene datos disponibles en este momento "
                    "(probable problema temporal del lado de datos.gov.co, no de esta "
                    "aplicación) — usa **\"Subir archivo Excel (respaldo)\"** para no "
                    "bloquear la corrida."
                )
        else:
            archivo_invima = st.file_uploader(
                "Listado Código Único de Medicamentos Vigentes (.xlsx)",
                type=["xlsx"],
                help="Descargado de invima.gov.co, seccion Consultas, registros y documentos asociados.",
            )

        col2, col3 = st.columns(2)
        archivo_gemma_net = col2.file_uploader(
            "Archivo exportado por Gemma Net (.xlsx o .txt)",
            type=["xlsx", "txt", "csv"],
            help="Mantenimientos > Basicas Atencion > Medicamentos > Crear Masivos > Exportar. "
            "Se usa para saber que codigos ya estan cargados y no volver a crearlos.",
        )
        archivo_malla_referencia = col3.file_uploader(
            "Estructura Cargue Medicamentos (.xlsx) — opcional",
            type=["xlsx"],
            help="Solo se usa como referencia para completar los campos de regla de negocio "
            "del cargue final (edad, copagos, cuota moderadora, modelo/nivel de servicio...) "
            "que no existen en INVIMA. Sin este archivo, el resumen y la bandeja de cuarentena "
            "funcionan igual, pero no se puede generar el Excel de cargue.",
        )

    listo_para_procesar = archivo_gemma_net is not None and (usar_api_invima or archivo_invima is not None)
    if st.button("Procesar", type="primary", disabled=not listo_para_procesar):
        st.session_state["procesado"] = True
        st.session_state["archivos"] = (usar_api_invima, archivo_invima, archivo_gemma_net, archivo_malla_referencia)
        st.session_state.pop("auditoria_coherencia", None)

    if not st.session_state.get("procesado"):
        st.info("Selecciona los archivos necesarios y presiona Procesar.")
        return

    usar_api_invima, archivo_invima, archivo_gemma_net, archivo_malla_referencia = st.session_state["archivos"]

    # La navegacion por pestañas se declara ANTES de procesar (pedido explicito
    # del usuario: "los nav deberian estar en una parte superior no tan abajo")
    # -- antes, todo el resumen/metricas de la corrida se imprimia suelto antes
    # de llegar a st.tabs(), empujando la barra de pestañas varias pantallas
    # hacia abajo. Ahora la barra aparece de inmediato tras "Procesar", y el
    # procesamiento (con sus posibles errores/st.stop()) vive dentro de
    # "Resumen de resolucion", la primera pestaña.
    tab_resumen, tab_cuarentena, tab_cargue, tab_consulta, tab_coherencia = st.tabs(
        [
            "Resumen de resolucion",
            "Bandeja de cuarentena",
            "Cargue a Gemma Net",
            "Consultar INVIMA",
            "Auditoría de coherencia",
        ]
    )

    with tab_resumen:
        with st.spinner("Cruzando contra el catalogo INVIMA (puede tardar unos minutos)..."):
            if usar_api_invima:
                try:
                    df_invima = _cargar_invima_desde_api()
                except socrata.ErrorSocrata as exc:
                    st.error(f"No se pudo sincronizar el catálogo de INVIMA vía API: {exc}")
                    st.info(
                        "Mientras se resuelve, usa el Excel de respaldo (\"Subir archivo Excel\" "
                        "en Archivos de entrada) para no bloquear la corrida."
                    )
                    st.stop()
            else:
                try:
                    df_invima = _cargar_invima_desde_archivo(archivo_invima)
                except _ERRORES_ARCHIVO_CORRUPTO as exc:
                    st.error(
                        f"No se pudo leer el archivo Excel de INVIMA ({type(exc).__name__}: {exc}) — "
                        "el archivo llegó incompleto o dañado, no es un problema de esta aplicación."
                    )
                    st.info(
                        "Prueba: (1) vuelve a descargarlo desde invima.gov.co por si la copia local "
                        "quedó corrupta, (2) ábrelo primero en Excel en tu computador para confirmar "
                        "que abre bien antes de subirlo aquí, (3) si es muy grande, revisa que la "
                        "subida haya terminado por completo (una conexión inestable puede cortarla a "
                        "mitad de camino) y vuelve a intentar la subida."
                    )
                    st.stop()
            try:
                resultado = _procesar_candidatos(df_invima, archivo_gemma_net)
            except _ERRORES_ARCHIVO_CORRUPTO as exc:
                st.error(
                    f"No se pudo leer el archivo exportado de Gemma Net ({type(exc).__name__}: {exc}) — "
                    "el archivo llegó incompleto o dañado."
                )
                st.info(
                    "Prueba: vuelve a exportarlo desde Gemma Net (Mantenimientos > Basicas Atencion > "
                    "Medicamentos > Crear Masivos > Exportar) y súbelo de nuevo — si es un archivo "
                    "grande, confirma que la subida haya terminado por completo antes de presionar "
                    "Procesar."
                )
                st.stop()

        for advertencia in resultado.attrs.get("advertencias", []):
            st.warning(advertencia)
        lineas_omitidas = resultado.attrs.get("lineas_omitidas_gemanet", [])
        if lineas_omitidas:
            codigos_recuperados = resultado.attrs.get("codigos_no_verificables_gemanet", [])
            codigos_en_cuarentena = set(
                resultado.loc[resultado["accion"] == "cuarentena", "CODIGO_INTERNO"].astype(str)
            )

            def _estado_linea_omitida(codigo: str) -> str:
                if not codigo:
                    return "Código no recuperable"
                if codigo in codigos_en_cuarentena:
                    return "Coincide con un candidato de esta corrida → en cuarentena"
                return "Código recuperado, sin candidato coincidente en esta corrida"

            df_omitidas = pd.DataFrame(
                {
                    "CODIGO_INTERNO_RECUPERADO": [c or "(no recuperado)" for c in codigos_recuperados],
                    "ESTADO": [_estado_linea_omitida(c) for c in codigos_recuperados],
                    "LINEA_CRUDA": lineas_omitidas,
                }
            )

            with st.expander(f"Ver las {len(lineas_omitidas)} linea(s) que no se pudieron leer del archivo de Gemma Net"):
                st.write(
                    "Cada una de estas líneas es un medicamento cuyo estado real en Gemma Net no se "
                    "pudo confirmar del todo — el archivo trae un separador de más dentro de un valor "
                    "de texto, así que el CODIGO_INTERNO se recupera por posición, no está 100% "
                    "garantizado. **ESTADO** dice qué se pudo determinar para cada una."
                )
                n_om = len(df_omitidas)
                n_cuarentena = int(df_omitidas["ESTADO"].str.startswith("Coincide").sum())
                n_sin_match = int(
                    (df_omitidas["ESTADO"] == "Código recuperado, sin candidato coincidente en esta corrida").sum()
                )
                n_sin_codigo = int((df_omitidas["ESTADO"] == "Código no recuperable").sum())
                o1, o2, o3 = st.columns(3)
                o1.metric("En cuarentena por cruce", f"{n_cuarentena:,}", f"{n_cuarentena / n_om:.0%}")
                o2.metric("Recuperado, sin coincidencia", f"{n_sin_match:,}", f"{n_sin_match / n_om:.0%}")
                o3.metric("Código no recuperable", f"{n_sin_codigo:,}", f"{n_sin_codigo / n_om:.0%}", delta_color="inverse")
                _tabla_filtrable(df_omitidas, columnas_filtro=["ESTADO"], key_prefix="lineas_omitidas", height=300)

        total = len(resultado)
        if total == 0:
            # Diagnostico especifico, no solo el mensaje generico: caso real
            # confirmado (2026-08-19) -- subir por error el archivo de Vencidos/
            # Renovacion/Otros Estados en el campo de Vigentes produce EXACTAMENTE
            # esto (0 filas tras depurar), porque ninguno de esos 3 trae registros
            # con ESTADO REGISTRO=Vigente. Facil de confundir ahora que hay 4
            # archivos de INVIMA con nombres muy parecidos.
            estado_registro_col = (
                df_invima["ESTADO_REGISTRO"].astype(str).str.strip()
                if "ESTADO_REGISTRO" in df_invima.columns
                else pd.Series(dtype=str)
            )
            tiene_vigente = estado_registro_col.str.casefold().eq("vigente").any()
            if not estado_registro_col.empty and not tiene_vigente:
                valor_mas_comun = estado_registro_col.value_counts().idxmax()
                st.error(
                    "0 filas vigentes después de depurar el catálogo INVIMA — el archivo/API usado no "
                    f"trae **ningún** registro con ESTADO REGISTRO=\"Vigente\" (el valor más común "
                    f"encontrado fue \"{valor_mas_comun}\"). Esto normalmente significa que se subió el "
                    "archivo equivocado en el campo de Vigentes de \"Archivos de entrada\" — revisa que "
                    "no sea, por error, el listado de Vencidos, Trámite de Renovación u Otros Estados "
                    "(los 4 archivos de INVIMA tienen nombres muy parecidos)."
                )
            else:
                st.error(
                    "0 filas vigentes después de depurar el catálogo INVIMA (filtro ESTADO REGISTRO="
                    "Vigente + ESTADO CUM=Activo) — esto no es un resultado normal, no hay nada que "
                    "procesar. Revisa que el archivo/API de INVIMA usado tenga datos reales: si veniste "
                    "de la API, confirma que la sincronización realmente trajo filas (no debería llegar "
                    "hasta acá si falló); si veniste del Excel de respaldo, confirma que es el listado "
                    "correcto y no está vacío o con la hoja equivocada."
                )
            st.stop()

        candidatos = int((resultado["accion"] == "candidato").sum())
        ya_existe = int((resultado["accion"] == "ya_existe").sum())
        cuarentena = int((resultado["accion"] == "cuarentena").sum())

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total filas vigentes", f"{total:,}")
        c2.metric("Candidatos a crear", f"{candidatos:,}", f"{candidatos / total:.1%}")
        c3.metric("Ya en Gemma Net", f"{ya_existe:,}", f"{ya_existe / total:.1%}")
        c4.metric("En cuarentena", f"{cuarentena:,}", f"{cuarentena / total:.1%}", delta_color="inverse")

        col_a, col_b = st.columns(2)
        col_a.write("**Metodo de resolucion — UNIDAD DE MEDIDA**")
        col_a.dataframe(resultado["unidad_metodo"].value_counts())
        col_b.write("**Metodo de resolucion — MARCA MEDICAMENTO**")
        col_b.dataframe(resultado["marca_metodo"].value_counts())

        st.divider()
        st.write("**Por qué cada registro de INVIMA sí o no llegó a ser candidato**")
        st.caption(
            "Verificable contra el archivo/API de INVIMA — ningún registro se descarta en "
            "silencio: cada uno queda clasificado con el campo puntual que no cumplió "
            "(rol distinto de FABRICANTE, CUM inactivo, registro no vigente, o muestra médica)."
        )
        with st.spinner("Clasificando el universo de INVIMA..."):
            universo_clasificado = _clasificar_universo_invima(df_invima)
        conteos_clasificacion = universo_clasificado["CLASIFICACION_CREACION"].value_counts()
        cols_clasif = st.columns(len(CLASIFICACIONES_CREACION))
        for col, etiqueta in zip(cols_clasif, CLASIFICACIONES_CREACION, strict=True):
            col.metric(
                _ETIQUETA_CLASIFICACION_CREACION.get(etiqueta, etiqueta),
                f"{int(conteos_clasificacion.get(etiqueta, 0)):,}",
            )
        _tabla_filtrable(
            universo_clasificado,
            columnas_filtro=["CLASIFICACION_CREACION"],
            key_prefix="universo_invima",
            columnas_mostrar=[
                c
                for c in [
                    "EXPEDIENTE",
                    "PRODUCTO",
                    "TITULAR",
                    "ESTADO_CUM",
                    "TIPO_ROL",
                    "ESTADO_REGISTRO",
                    "CLASIFICACION_CREACION",
                ]
                if c in universo_clasificado.columns
            ],
            height=350,
        )

    with tab_cuarentena:
        df_cuarentena = resultado[resultado["accion"] == "cuarentena"]
        st.caption(
            "**_texto_invima** es el dato crudo tal como lo reporta el listado oficial de INVIMA "
            "para ese medicamento — compáralo contra **_sugerencia** (una coincidencia aproximada "
            "de nuestro catálogo interno, nunca confirmada) para decidir más rápido si ya existe "
            "en Gemma Net con otro nombre."
        )
        df_cuarentena_filtrado = _tabla_filtrable(
            df_cuarentena,
            columnas_filtro=["motivo", "unidad_metodo", "marca_metodo"],
            key_prefix="cuarentena",
            columnas_mostrar=[
                c
                for c in [
                    "CODIGO_INTERNO",
                    "DESCRIPCION",
                    "EXPEDIENTE",
                    "unidad_metodo",
                    "unidad_texto_invima",
                    "unidad_sugerencia",
                    "marca_metodo",
                    "marca_texto_invima",
                    "marca_sugerencia",
                    "motivo",
                ]
                if c in df_cuarentena.columns
            ],
            height=420,
        )
        buffer_reporte = _bytes_reporte_cruce(resultado)
        st.download_button(
            "Descargar reporte de revision (.xlsx, una hoja por accion)",
            data=buffer_reporte,
            file_name="reporte_cruce_invima.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.divider()
        usar_ia = st.checkbox(
            "Explicar casos con IA (Claude Haiku 4.5 — solo explica, no cambia ningun resultado)",
            value=False,
        )
        if usar_ia:
            cliente_ia = _cliente_ia_disponible()
            if cliente_ia is None:
                st.warning(
                    "No se encontro ANTHROPIC_API_KEY en el entorno. Exportala en tu "
                    "terminal antes de correr `streamlit run` para habilitar las explicaciones."
                )
            else:
                df_filtrado = df_cuarentena_filtrado

                st.write(
                    "**Explicacion por motivo** — una llamada a la IA por cada motivo "
                    "distinto en la tabla filtrada, no una por fila."
                )
                for motivo_unico in sorted(df_filtrado["motivo"].unique()):
                    explicacion = _explicar_motivo_cacheado(cliente_ia, "cuarentena", motivo_unico)
                    with st.expander(motivo_unico):
                        st.write(explicacion.explicacion)
                        st.caption(f"Consejo: {explicacion.consejo}")

                st.write("**Explicar un caso puntual**")
                codigos_disponibles = df_filtrado["CODIGO_INTERNO"].astype(str).tolist()
                if codigos_disponibles:
                    codigo_elegido = st.selectbox("CODIGO_INTERNO a explicar", codigos_disponibles)
                    if st.button("Explicar este caso"):
                        fila = df_filtrado[df_filtrado["CODIGO_INTERNO"].astype(str) == codigo_elegido].iloc[0]
                        with st.spinner("Consultando IA..."):
                            explicacion_fila = cliente_ia.explicar_fila(
                                "cuarentena", fila["motivo"], fila.to_dict()
                            )
                        st.info(explicacion_fila.explicacion)
                        st.caption(f"Consejo: {explicacion_fila.consejo}")

    with tab_cargue:
        st.caption(
            "Estructura de 37 campos confirmada dos veces: contra el archivo real que exporta "
            "Gemma Net y contra el encabezado de carga que confirmaste. Tabla destino: "
            "`tb_medicamento` (visto en la hoja NO POS del workbook original)."
        )

        if archivo_malla_referencia is None:
            st.warning(
                "Sube la **Estructura Cargue Medicamentos (.xlsx)** en \"Archivos de entrada\" "
                "para poder clasificar POS y Modelo de Servicio por expediente y completar los "
                "demas campos de regla de negocio. Sin ese archivo no se puede generar el Excel "
                "de cargue."
            )
        else:
            try:
                with st.spinner("Leyendo la Estructura Cargue Medicamentos..."):
                    malla_referencia = _leer_malla_referencia_cacheada(archivo_malla_referencia)
            except _ERRORES_ARCHIVO_CORRUPTO as exc:
                st.error(
                    f"No se pudo leer la Estructura Cargue Medicamentos ({type(exc).__name__}: "
                    f"{exc}) — el archivo llegó incompleto o dañado. Vuelve a intentar la subida."
                )
                st.stop()
            with st.spinner("Derivando reglas de negocio de la malla de referencia..."):
                reglas = _derivar_reglas_negocio_cacheada(malla_referencia)

            if reglas.advertencias:
                with st.expander(
                    f"⚠ {len(reglas.advertencias)} campo(s) con inconsistencias en la malla de referencia",
                    expanded=True,
                ):
                    for campo, advertencia in reglas.advertencias.items():
                        st.write(f"**{campo}**: {advertencia}")

            with st.spinner("Evaluando candidatos contra las reglas de cargue..."):
                evaluados = _evaluar_candidatos_cargue_cacheado(resultado, reglas)
            listos = evaluados[evaluados["listo_para_cargue"]]
            pendientes = evaluados[~evaluados["listo_para_cargue"]]

            st.write("**Archivo de auditoría — Estructura de Cargue**")
            st.caption(
                "Reemplaza la copia manual de \"plantilla\" a \"plantilla (2)\" del SOP original: "
                "trae TODOS los candidatos (listos y pendientes) con CÓDIGO_INTERNO y DESCRIPCIÓN "
                "ya concatenados, su ESTADO, y en CÓMO VERIFICAR los pasos exactos para confirmar "
                "cada pendiente contra los archivos oficiales de Pijao Salud a mano."
            )
            with st.spinner("Armando la Estructura de Cargue..."):
                df_estructura = _armar_estructura_cargue_cacheada(resultado, reglas)
            buffer_estructura = _bytes_estructura_cargue(df_estructura)
            st.download_button(
                "Descargar Estructura de Cargue (auditoría)",
                data=buffer_estructura,
                file_name=f"{nombre_periodo()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            st.divider()
            st.write("**Excel de cargue final — solo lo listo para subir**")
            st.write(
                f"**{len(listos):,} de {candidatos:,} candidatos listos para cargue** "
                "(marca y unidad resueltas contra catálogo, POS y Modelo de Servicio "
                "confirmados por expediente — ningún campo adivinado)."
            )

            if len(pendientes) > 0:
                with st.expander(
                    f"🔎 {len(pendientes):,} candidato(s) pendientes de clasificación manual — por qué no están en el Excel",
                    expanded=(len(listos) == 0),
                ):
                    st.write(
                        "**Esta tabla es la lista de tareas pendientes para Autorizaciones.** "
                        "Cada fila es un medicamento nuevo que el programa NO pudo crear solo, "
                        "porque le falta confirmar al menos uno de estos 4 datos: marca, unidad "
                        "de medida, POS, o modelo de servicio. Nunca se adivina — mientras no se "
                        "confirme a mano en Gemma Net, la fila se queda aquí y no entra al Excel "
                        "de cargue."
                    )
                    st.caption(
                        "**CAMPOS_CON_ERROR** = cuál(es) de esos 4 datos le faltan a ESA fila "
                        "puntual. **% COMPLETITUD** = cuántos de los 4 SÍ están confirmados (ej. "
                        "75% = solo falta 1). **DETALLE** explica el motivo exacto y muestra una "
                        "sugerencia aproximada si existe — nunca una respuesta confirmada, siempre "
                        "hay que verificarla en Gemma Net."
                    )
                    campos_elegidos = st.multiselect(
                        "Filtrar por campo con error",
                        CAMPOS_VERIFICABLES_CARGUE,
                        default=CAMPOS_VERIFICABLES_CARGUE,
                        key="pendientes_campo_error",
                        help="Una fila puede fallar en mas de un campo a la vez -- se muestra si "
                        "CUALQUIERA de los campos elegidos falla en esa fila.",
                    )
                    busqueda_pendientes = st.text_input(
                        "🔎 Buscar (código, expediente, nombre... cualquier texto)",
                        key="pendientes_busqueda",
                        placeholder="Escribe aquí y la tabla se acota sola",
                    )
                    pendientes_filtrados = pendientes[
                        pendientes["campos_con_error"].apply(
                            lambda campos: any(c in campos.split(", ") for c in campos_elegidos)
                        )
                    ]
                    if busqueda_pendientes.strip():
                        texto_busqueda = busqueda_pendientes.strip().lower()
                        columnas_busqueda_pendientes = [
                            "CODIGO_INTERNO", "DESCRIPCION", "EXPEDIENTE", "campos_con_error", "motivo_pendiente",
                        ]
                        coincide_busqueda = pd.Series(False, index=pendientes_filtrados.index)
                        for columna in columnas_busqueda_pendientes:
                            if columna in pendientes_filtrados.columns:
                                coincide_busqueda = coincide_busqueda | pendientes_filtrados[columna].astype(
                                    str
                                ).str.lower().str.contains(texto_busqueda, na=False, regex=False)
                        pendientes_filtrados = pendientes_filtrados[coincide_busqueda]
                    st.dataframe(
                        pendientes_filtrados[
                            [
                                "CODIGO_INTERNO",
                                "DESCRIPCION",
                                "EXPEDIENTE",
                                "campos_con_error",
                                "porcentaje_completitud",
                                "motivo_pendiente",
                            ]
                        ].rename(
                            columns={
                                "campos_con_error": "CAMPOS_CON_ERROR",
                                "porcentaje_completitud": "% COMPLETITUD",
                                "motivo_pendiente": "DETALLE",
                            }
                        ),
                        use_container_width=True,
                    )

            if len(listos) == 0:
                st.info(
                    "0 filas en el Excel de cargue en esta corrida. No es un error: ningún "
                    "candidato de este lote tiene POS y Modelo de Servicio confirmados con "
                    "certeza todavía — revisa el detalle de arriba."
                )
            else:
                with st.spinner("Preparando el Excel de cargue final..."):
                    df_cargue = _preparar_filas_cargue_cacheada(resultado, reglas)
                _tabla_filtrable(
                    df_cargue,
                    columnas_filtro=["POS", "FORMA_FARMACEUTICA", "CLASIFICADO", "CODIGO_NIVEL_SERVICIO"],
                    key_prefix="cargue_final",
                    height=420,
                )

                buffer_excel = _bytes_cargue_final(df_cargue)
                st.download_button(
                    "Descargar Excel de cargue",
                    data=buffer_excel,
                    file_name="cargue_gemma_net.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

    with tab_consulta:
        st.caption(
            "Consulta puntual y bajo demanda contra la API oficial de INVIMA — nunca se usa en "
            "el proceso masivo, solo para verificar un caso a mano. El resultado no se guarda en "
            "ningún registro de medicamento, solo se muestra en pantalla."
        )
        estado_token_consulta = socrata.estado_token()
        st.caption(_indicador_token(estado_token_consulta), help=_ayuda_token(estado_token_consulta))
        col_exp, col_cons = st.columns(2)
        expediente_consulta = col_exp.text_input("EXPEDIENTE", placeholder="20227202")
        consecutivo_consulta = col_cons.text_input("CONSECUTIVO", placeholder="1")
        if st.button("Consultar contra INVIMA"):
            expediente_limpio = expediente_consulta.strip()
            consecutivo_limpio = consecutivo_consulta.strip()
            if not expediente_limpio or not consecutivo_limpio:
                st.warning("Ingresa tanto el EXPEDIENTE como el CONSECUTIVO antes de consultar.")
            elif not expediente_limpio.isdigit():
                st.warning(f"EXPEDIENTE debe contener solo números — \"{expediente_limpio}\" no es válido.")
            elif not consecutivo_limpio.isdigit():
                st.warning(f"CONSECUTIVO debe contener solo números — \"{consecutivo_limpio}\" no es válido.")
            else:
                codigo_consulta = f"{expediente_limpio}-{consecutivo_limpio}"
                with st.spinner("Consultando..."):
                    # Chequeo previo, cacheado (ttl=180s, ver _hay_datos_invima_api):
                    # si YA sabemos que el dataset completo de INVIMA esta vacio
                    # ahora mismo (el outage real que venimos monitoreando), no
                    # tiene sentido gastar dos llamadas de red por cada consulta
                    # puntual (la consulta especifica + la verificacion de
                    # "esta vacio de verdad o es solo este codigo" que hace
                    # consultar_cum internamente) -- se corta directo con el
                    # mismo resultado, mucho mas rapido y sin doble round-trip.
                    if not _hay_datos_invima_api():
                        resultado_cum = ResultadoValidacionCUM(
                            codigo_interno=codigo_consulta,
                            estado=EstadoValidacionCUM.SERVICIO_NO_DISPONIBLE,
                            mensaje=(
                                "El listado vigente de INVIMA no tiene datos disponibles en este "
                                "momento (no es que este CUM puntual no exista -- el dataset "
                                "completo esta vacio del lado de INVIMA/datos.gov.co)."
                            ),
                            fecha_consulta=dt.datetime.now(),
                        )
                    else:
                        resultado_cum = consultar_cum(codigo_consulta)
                tipo_mensaje, texto_estado = _MENSAJE_ESTADO_CUM[resultado_cum.estado]
                getattr(st, tipo_mensaje)(f"**{texto_estado}** — {resultado_cum.mensaje}")
                st.caption(f"Consultado: {resultado_cum.fecha_consulta.strftime('%Y-%m-%d %H:%M:%S')}")
                if resultado_cum.datos_oficiales:
                    st.json(resultado_cum.datos_oficiales)

    with tab_coherencia:
        st.caption(
            "Compara, campo por campo, los medicamentos que YA están cargados en Gemma Net "
            "contra el dato oficial de INVIMA — distinto de \"Bandeja de cuarentena\" (esa es "
            "para medicamentos NUEVOS que aún no existen). Aquí un hallazgo ('con diferencias') "
            "significa que el medicamento SÍ existe y SÍ se pudo emparejar con INVIMA — solo que "
            "algún campo suyo quedó desactualizado y conviene corregirlo, no que esté rechazado ni "
            "en cuarentena. Corre sobre el lote completo del archivo exportado de Gemma Net, no "
            "por código individual."
        )
        st.warning(
            "**Riesgo de negocio:** un código sin correspondencia en el listado Vigente de INVIMA "
            "puede significar varias cosas muy distintas — que el registro sanitario **venció**, "
            "que está en **otro estado** (Cancelado/Suspendido/Inactivo/etc.), que está en "
            "**trámite de renovación**, o que es un **código legado** sin expediente INVIMA "
            "asociado. No se pueden tratar igual: no nos podemos exponer a autorizar un "
            "medicamento que ya no está vigente."
        )
        archivo_invima_vencidos = None
        archivo_invima_otros_estados = None
        archivo_invima_renovacion = None
        if not usar_api_invima:
            st.info(
                "Esta corrida usa el Excel de respaldo para Vigentes — las distinciones \"vencido\" / "
                "\"otro estado\" / \"trámite de renovación\" no están disponibles automáticamente en "
                "este modo. Para tenerlas, sube abajo los archivos oficiales correspondientes de "
                "INVIMA a mano (todos opcionales, independientes entre sí), o cambia a la fuente API "
                "de Socrata en \"Archivos de entrada\". Sin ninguno de los tres, todo lo no encontrado "
                "cae en \"sin correspondencia\"."
            )
            archivo_invima_vencidos = st.file_uploader(
                "Listado Código Único de Medicamentos Vencidos (.xlsx) — opcional",
                type=["xlsx"],
                help="Descargado de invima.gov.co, mismo lugar que el listado de Vigentes. Sin "
                "este archivo, la auditoría sigue funcionando igual, solo sin distinguir "
                "\"vencido\" de \"código legado\".",
            )
            archivo_invima_otros_estados = st.file_uploader(
                "Listado Código Único de Medicamentos Otros Estados (.xlsx) — opcional",
                type=["xlsx"],
                help="Agrupa registros Cancelado/Suspendido/Inactivo/etc. Sin este archivo, la "
                "auditoría sigue funcionando igual, solo sin poder distinguir estos casos de "
                "\"código legado\".",
            )
            archivo_invima_renovacion = st.file_uploader(
                "Listado Código Único de Medicamentos en Trámite de Renovación (.xlsx) — opcional",
                type=["xlsx"],
                help="Registros sanitarios cuya renovación está en curso. Sin este archivo, la "
                "auditoría sigue funcionando igual, solo sin distinguir este caso de \"código "
                "legado\".",
            )

        if st.button("Ejecutar auditoría de coherencia (lote completo)"):
            with st.spinner("Auditando coherencia contra INVIMA (puede tardar varios minutos)..."):
                df_invima_vencidos = None
                df_invima_otros_estados = None
                df_invima_renovacion = None
                if usar_api_invima:
                    for etiqueta, dataset, destino in [
                        ("Vencidos", DATASET_CUM_VENCIDOS, "vencidos"),
                        ("Otros Estados", DATASET_CUM_OTROS_ESTADOS, "otros_estados"),
                        ("Trámite de Renovación", DATASET_CUM_RENOVACION, "renovacion"),
                    ]:
                        try:
                            valor = _cargar_invima_desde_api(dataset)
                        except socrata.ErrorSocrata as exc:
                            st.warning(
                                f"No se pudo traer el dataset de {etiqueta} ({exc}) — la auditoría "
                                f"sigue, pero sin poder distinguir \"{etiqueta.lower()}\" de \"sin "
                                "correspondencia\" en esta corrida."
                            )
                            continue
                        if destino == "vencidos":
                            df_invima_vencidos = valor
                        elif destino == "otros_estados":
                            df_invima_otros_estados = valor
                        else:
                            df_invima_renovacion = valor
                else:
                    if archivo_invima_vencidos is not None:
                        try:
                            df_invima_vencidos = _cargar_invima_vencidos_desde_archivo(archivo_invima_vencidos)
                        except (*_ERRORES_ARCHIVO_CORRUPTO, ValueError) as exc:
                            st.warning(
                                f"No se pudo leer el archivo de Vencidos subido ({type(exc).__name__}: "
                                f"{exc}) — la auditoría sigue, pero sin poder distinguir \"vencido\" de "
                                "\"sin correspondencia\" en esta corrida."
                            )
                    if archivo_invima_otros_estados is not None:
                        try:
                            df_invima_otros_estados = _cargar_invima_otros_estados_desde_archivo(
                                archivo_invima_otros_estados
                            )
                        except (*_ERRORES_ARCHIVO_CORRUPTO, ValueError) as exc:
                            st.warning(
                                f"No se pudo leer el archivo de Otros Estados subido "
                                f"({type(exc).__name__}: {exc}) — la auditoría sigue, pero sin poder "
                                "distinguir ese caso de \"sin correspondencia\" en esta corrida."
                            )
                    if archivo_invima_renovacion is not None:
                        try:
                            df_invima_renovacion = _cargar_invima_renovacion_desde_archivo(
                                archivo_invima_renovacion
                            )
                        except (*_ERRORES_ARCHIVO_CORRUPTO, ValueError) as exc:
                            st.warning(
                                f"No se pudo leer el archivo de Trámite de Renovación subido "
                                f"({type(exc).__name__}: {exc}) — la auditoría sigue, pero sin poder "
                                "distinguir ese caso de \"sin correspondencia\" en esta corrida."
                            )
                auditoria = _auditar_coherencia(
                    df_invima,
                    archivo_gemma_net,
                    df_invima_vencidos,
                    df_invima_otros_estados=df_invima_otros_estados,
                    df_invima_renovacion=df_invima_renovacion,
                )
            st.session_state["auditoria_coherencia"] = auditoria

        auditoria = st.session_state.get("auditoria_coherencia")
        if auditoria is None:
            st.info("Presiona el botón para correr la auditoría sobre el archivo de Gemma Net cargado.")
        else:
            conteos = auditoria["ESTADO_COHERENCIA"].value_counts()
            n_correcto = int(conteos.get(EstadoCoherencia.CORRECTO.value, 0))
            n_diferencias = int(conteos.get(EstadoCoherencia.CON_DIFERENCIAS.value, 0))
            n_vencido = int(conteos.get(EstadoCoherencia.VENCIDO_EN_INVIMA.value, 0))
            n_otro_estado = int(conteos.get(EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value, 0))
            n_renovacion = int(conteos.get(EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value, 0))
            n_sin_corresp = int(conteos.get(EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value, 0))

            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Correcto", f"{n_correcto:,}")
            d2.metric("Con diferencias", f"{n_diferencias:,}")
            d3.metric("⚠ Vencido en INVIMA", f"{n_vencido:,}", delta_color="inverse")
            d4.metric("Sin correspondencia", f"{n_sin_corresp:,}")
            e1, e2, e3 = st.columns(3)
            e1.metric("⚠ Otro estado INVIMA", f"{n_otro_estado:,}", delta_color="inverse")
            e2.metric("En trámite de renovación", f"{n_renovacion:,}")
            calidad_promedio = auditoria["PORCENTAJE_CALIDAD"].mean()
            e3.metric(
                "% calidad promedio",
                f"{calidad_promedio:.1f}%" if pd.notna(calidad_promedio) else "—",
                help="Promedio, solo entre los medicamentos que SÍ se pudieron emparejar con "
                "INVIMA, de cuántos de sus campos coinciden exactamente con el dato oficial — "
                "un medicamento 'con diferencias' puede seguir teniendo un % alto si solo le "
                "falla un campo de varios.",
            )

            alertas = []
            if n_vencido > 0:
                alertas.append(("error", f"⚠ {n_vencido:,} vencido(s) en INVIMA", "riesgo de autorización"))
            if n_otro_estado > 0:
                alertas.append(("error", f"⚠ {n_otro_estado:,} en otro estado INVIMA", "Cancelado/Suspendido/Inactivo/etc."))
            n_inconsistencia_fechas = 0
            if "INCONSISTENCIA_FECHAS_ACTIVO" in auditoria.columns:
                n_inconsistencia_fechas = int((auditoria["INCONSISTENCIA_FECHAS_ACTIVO"] != "").sum())
                if n_inconsistencia_fechas > 0:
                    alertas.append(("warning", f"{n_inconsistencia_fechas:,} con fechas/vigencia inconsistentes", "ACTIVO vs FECHA_INICIO/FECHA_FIN no cuadran"))
            for advertencia in auditoria.attrs.get("advertencias", []):
                separador = " — " if " — " in advertencia else " -- " if " -- " in advertencia else ""
                titulo, _, resto = advertencia.partition(separador) if separador else ("", "", advertencia)
                if not titulo:
                    titulo = advertencia if len(advertencia) <= 70 else advertencia[:67] + "..."
                alertas.append(("warning", titulo.strip(" *"), resto or advertencia))

            if alertas:
                _mostrar_tarjetas_alerta(alertas)

            if "PORCENTAJE_COMPLETITUD_REPORTE" in auditoria.columns:
                with st.expander("9 dimensiones de calidad de dato (completitud, unicidad, dominio, razonabilidad, formato, integridad referencial)"):
                    n_total_auditado = len(auditoria)
                    completitud_prom = auditoria["PORCENTAJE_COMPLETITUD_REPORTE"].mean()
                    n_duplicados = int(auditoria["CODIGO_DUPLICADO_EN_REPORTE"].sum())
                    n_fuera_dominio = int((auditoria["VALORES_FUERA_DE_DOMINIO"] != "").sum())
                    n_inconsistencia_num = int((auditoria["INCONSISTENCIA_NUMERICA"] != "").sum())
                    n_formato_invalido = int((auditoria["FORMATO_CODIGO_INTERNO_INVALIDO"] != "").sum())
                    n_integridad_referencial = int((auditoria["INTEGRIDAD_REFERENCIAL_CATALOGO"] != "").sum())

                    q1, q2, q3, q4, q5, q6 = st.columns(6)
                    q1.metric(
                        "Completitud", f"{completitud_prom:.1f}%" if pd.notna(completitud_prom) else "—",
                        help="Promedio de cuántos de los 37 campos del cargue están diligenciados por medicamento.",
                    )
                    q2.metric(
                        "Unicidad", f"{n_duplicados:,}", delta_color="inverse",
                        help="CODIGO_INTERNO repetido dentro del propio reporte de Gemma Net.",
                    )
                    q3.metric(
                        "Validez de dominio", f"{n_fuera_dominio:,}", delta_color="inverse",
                        help="CLASIFICADO / CODIGO_NIVEL_SERVICIO / POS / ACTIVO con un valor fuera de lo permitido.",
                    )
                    q4.metric(
                        "Razonabilidad numérica", f"{n_inconsistencia_num:,}", delta_color="inverse",
                        help="Edades o topes de uso fuera de orden lógico, o negativos.",
                    )
                    q5.metric(
                        "Conformidad de formato", f"{n_formato_invalido:,}", delta_color="inverse",
                        help="CODIGO_INTERNO vacío o guardado como error de fórmula de Excel.",
                    )
                    q6.metric(
                        "Integridad referencial", f"{n_integridad_referencial:,}", delta_color="inverse",
                        help="MARCA_MEDICAMENTO / UNIDAD_MEDIDA con un código que NO existe en el catálogo "
                        "interno (config/catalogos/) — distinto de \"no coincide con INVIMA\", ver columna "
                        "INTEGRIDAD_REFERENCIAL_CATALOGO en la tabla para el mensaje exacto de qué código "
                        "falta y dónde agregarlo.",
                    )
                    st.caption(
                        f"Sobre {n_total_auditado:,} medicamentos auditados. Junto con Exactitud, Vigencia y "
                        "Consistencia (arriba), son las 9 dimensiones de calidad de dato de esta auditoría."
                    )

            if n_sin_corresp > 0 and "TIPO_SIN_CORRESPONDENCIA" in auditoria.columns:
                df_sin_corresp = auditoria[auditoria["ESTADO_COHERENCIA"] == EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value]
                n_posible_error = int(
                    df_sin_corresp["TIPO_SIN_CORRESPONDENCIA"].str.contains("EXPEDIENTE-CONSECUTIVO", na=False).sum()
                )
                n_legado = n_sin_corresp - n_posible_error
                with st.expander(f"Detalle de los {n_sin_corresp:,} \"sin correspondencia\" — no son todos iguales"):
                    e1, e2 = st.columns(2)
                    e1.metric(
                        "Con formato de código INVIMA, no encontrados",
                        f"{n_posible_error:,}",
                        f"{n_posible_error / n_sin_corresp:.0%}",
                        help="Sigue el formato EXPEDIENTE-CONSECUTIVO pero no aparece en INVIMA — "
                        "posible error de digitación o el registro ya no existe ahí. Vale la pena "
                        "revisar estos puntualmente.",
                    )
                    e2.metric(
                        "Código legado (sin formato INVIMA)",
                        f"{n_legado:,}",
                        f"{n_legado / n_sin_corresp:.0%}",
                        help="No sigue el formato EXPEDIENTE-CONSECUTIVO — nunca tuvo un expediente "
                        "INVIMA asociado. No hay nada que verificar contra INVIMA para estos.",
                    )

            estados_disponibles = sorted(auditoria["ESTADO_COHERENCIA"].unique())
            filtro_estado = st.multiselect(
                "Filtrar por estado",
                estados_disponibles,
                default=[
                    e
                    for e in [
                        EstadoCoherencia.VENCIDO_EN_INVIMA.value,
                        EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value,
                        EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value,
                        EstadoCoherencia.CON_DIFERENCIAS.value,
                    ]
                    if e in estados_disponibles
                ]
                or estados_disponibles,
                format_func=lambda e: _MENSAJE_ESTADO_COHERENCIA.get(e, e),
            )
            campos_elegidos_coherencia = st.multiselect(
                "Filtrar por campo con diferencia",
                CAMPOS_COMPARADOS_COHERENCIA,
                default=[],
                key="coherencia_campo_diferencia",
                help="Vacío = no filtra por campo. Si eliges uno o más, solo se muestran filas "
                "donde CUALQUIERA de los campos elegidos tiene una diferencia frente a INVIMA.",
            )
            filtrado_coherencia = auditoria[auditoria["ESTADO_COHERENCIA"].isin(filtro_estado)]
            if campos_elegidos_coherencia:
                filtrado_coherencia = filtrado_coherencia[
                    filtrado_coherencia["CAMPOS_CON_DIFERENCIA"].apply(
                        lambda campos: any(c in campos.split(", ") for c in campos_elegidos_coherencia)
                    )
                ]
            columnas_mostrar = [
                c
                for c in [
                    "CODIGO_INTERNO",
                    "DESCRIPCION",
                    "ESTADO_COHERENCIA",
                    "ESTADO_INVIMA_DETALLE",
                    "PORCENTAJE_CALIDAD",
                    "CAMPOS_CON_DIFERENCIA",
                    "TIPO_SIN_CORRESPONDENCIA",
                    "INCONSISTENCIA_FECHAS_ACTIVO",
                    "PORCENTAJE_COMPLETITUD_REPORTE",
                    "CODIGO_DUPLICADO_EN_REPORTE",
                    "VALORES_FUERA_DE_DOMINIO",
                    "INCONSISTENCIA_NUMERICA",
                    "FORMATO_CODIGO_INTERNO_INVALIDO",
                    "INTEGRIDAD_REFERENCIAL_CATALOGO",
                ]
                if c in auditoria.columns
            ]
            st.dataframe(
                filtrado_coherencia[columnas_mostrar],
                use_container_width=True,
                height=420,
            )

            buffer_coherencia = _bytes_auditoria_coherencia(auditoria)
            st.download_button(
                "Descargar auditoría de coherencia (.xlsx, una hoja por estado)",
                data=buffer_coherencia,
                file_name="auditoria_coherencia_invima.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


def _exportar_a_bytes(escribir) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "salida"
        escribir(ruta)
        return ruta.read_bytes()


if __name__ == "__main__":
    main()
