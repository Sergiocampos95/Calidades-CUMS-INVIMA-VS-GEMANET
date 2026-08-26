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
import html
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

from gemma_cum_loader.armado.malla import (
    CLASIFICACIONES_CREACION,
    universo_invima_clasificado,
)
from gemma_cum_loader.armado.reglas_negocio import ReglasNegocio, derivar_reglas_negocio, leer_malla_referencia
from gemma_cum_loader.catalogos.ia_client import ClienteExplicacionIA, ExplicacionIA
from gemma_cum_loader.exportacion.cargue import (
    CAMPOS_VERIFICABLES_CARGUE,
    NOMBRE_DISPLAY,
    evaluar_candidatos_cargue,
    generar_excel_cargue,
    preparar_filas_cargue,
)
from gemma_cum_loader.exportacion.estructura_cargue import (
    armar_estructura_cargue,
    generar_excel_estructura_cargue,
    nombre_periodo,
)
from gemma_cum_loader.auditoria.coherencia_invima import (
    ACCION_POR_NATURALEZA,
    CAMPOS_COMPARADOS_COHERENCIA,
    CAMPOS_DERIVADOS,
    PREFIJO_SIMILITUD,
    SUFIJO_GEMANET,
    SUFIJO_INVIMA,
    SUFIJO_VALIDACION,
    EstadoCoherencia,
    _corte_catalogo_invima,
)
from gemma_cum_loader.ingesta.almacen_local import CARPETA_DATOS, descubrir_todo, guardar_subida
from gemma_cum_loader.normaliza.codigos import PATRON_CUM
from gemma_cum_loader.ingesta.gemanet_sql import leer_reporte_gemanet_db
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
from gemma_cum_loader.catalogos.fuentes import FuenteCatalogosConRespaldo, FuenteCatalogosCSV
from gemma_cum_loader.integraciones import gemanet_db, socrata
from gemma_cum_loader.pipeline import (
    auditar_coherencia_gemanet,
    guardar_reporte,
    leer_reporte_gemanet,
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
    # "warning" y no "error", y redactado como estado del servicio y no como
    # falla: el usuario leia el rojo y el lenguaje tecnico como si la
    # aplicacion se hubiera roto. No se rompio nada -- INVIMA no esta
    # publicando datos y la consulta se resuelve contra el listado local.
    EstadoValidacionCUM.SERVICIO_NO_DISPONIBLE: (
        "warning",
        "INVIMA no está publicando datos en este momento — se consulta el listado descargado.",
    ),
    EstadoValidacionCUM.ERROR_AUTENTICACION: ("error", "El App Token fue rechazado por Socrata."),
}

_MENSAJE_ESTADO_COHERENCIA = {
    # "sus datos coinciden" y no "correcto" a secas: esta columna habla de
    # FIDELIDAD del dato, no de si el medicamento se puede usar. El caso
    # 3521-1 lo dejo claro -- inactivo desde 2015 en Gemma Net e inactivo en
    # INVIMA, con las mismas fechas al dia: el registro es impecable y aun asi
    # el medicamento no esta en uso. Leer "Correcto" como "esta bien, esta
    # activo" es un error facil y caro.
    EstadoCoherencia.CORRECTO.value: (
        "Sus datos coinciden con el dato oficial de INVIMA "
        "(esto no dice si el medicamento está activo — eso lo dice el campo ACTIVO)."
    ),
    EstadoCoherencia.CON_DIFERENCIAS.value: "Con diferencias frente al dato oficial de INVIMA — revisar campos.",
    EstadoCoherencia.VENCIDO_EN_INVIMA.value: (
        "⚠ Registro sanitario VENCIDO en INVIMA — riesgo de autorizar un medicamento sin vigencia."
    ),
    EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value: (
        "⚠ Su registro sanitario no está vigente en INVIMA (Cancelado, Suspendido, Negado, "
        "Desistido o con pérdida de fuerza ejecutoria) — ver ESTADO_INVIMA_DETALLE para el "
        "valor exacto."
    ),
    EstadoCoherencia.VIGENTE_NO_COMERCIALIZADO_INVIMA.value: (
        "Vigente en INVIMA, temporalmente sin comercializar. El registro sanitario está al "
        "día: no es un riesgo de vigencia."
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

# Que significa cada clasificacion Y que implica. La etiqueta sola no basta:
# "Rol != FABRICANTE" no dice por que eso excluye al medicamento.
_AYUDA_CLASIFICACION_CREACION = {
    "candidato": "Pasó los cuatro filtros: es un medicamento que la EPS debería tener "
    "cargado.",
    "rol_no_fabricante": "Quien figura en el registro no es el fabricante sino, por ejemplo, "
    "el importador. El mismo producto suele aparecer también bajo su fabricante: cargar "
    "ambos lo duplicaría.",
    "cum_inactivo": "Esa presentación puntual fue descontinuada. El medicamento puede seguir "
    "existiendo en otras presentaciones del mismo expediente.",
    "registro_no_vigente": "El registro sanitario no está vigente. En el listado de Vigentes "
    "esto no puede ocurrir nunca: el filtro aplica a los otros listados de INVIMA.",
    "muestra_medica": "No se comercializa: se entrega como muestra. No entra al catálogo de "
    "la EPS.",
}

# El vocabulario interno traducido, TODO en un solo sitio.
#
# Estos terminos no estaban escritos en ninguna parte de la interfaz --
# `exacto_sigla`, `fuzzy` y `sin_resolver` aparecian CERO veces en el codigo.
# Llegaban a la pantalla porque las tablas se dibujan con los valores crudos
# del dato. Nadie los escribio: nadie los tradujo.
#
# La aplicacion ya sabia hacerlo (ver _ETIQUETA_CLASIFICACION_CREACION), pero
# el unico diccionario que existia cubria cinco valores en un solo lugar. Esto
# generaliza ese mecanismo en vez de inventar uno nuevo.
#
# Criterio de redaccion: decir que PASO y que implica, no como se llama por
# dentro. "Codigo legado" no significa nada para quien no construyo el
# sistema; "se registro antes de que existiera la convencion de INVIMA" si.
_ETIQUETA_VALOR_INTERNO = {
    # como se resolvio un catalogo (unidad de medida / marca)
    "exacto_sigla": "Coincidencia exacta",
    "exacto_descripcion": "Coincidencia exacta (por nombre largo)",
    "alias": "Equivalencia conocida",
    "fuzzy": "Coincidencia aproximada",
    "sin_resolver": "Sin equivalencia en el catálogo",
    # que se decidio sobre un candidato
    "candidato": "Falta cargarlo",
    "ya_existe": "Ya está cargado",
    "cuarentena": "Requiere decisión de una persona",
    "descartado": "Descartado por el filtro",
    # novedades de vigencia contra INVIMA
    "riesgo_activo_sin_vigencia": "Activo aquí, sin vigencia en INVIMA",
    "registro_vencido_en_invima": "Registro vencido en INVIMA",
    "revisar_reactivacion": "Inactivo aquí, con registro vivo en INVIMA",
    "actualizar_fecha_fin": "Falta la fecha de fin que INVIMA sí tiene",
    "coherente": "Los dos lados coinciden",
    "no_verificable": "No se puede verificar contra INVIMA",
    # veredicto de un campo
    "coincide": "Coincide",
    "difiere": "Difiere",
    "sin comparar": "Sin comparar",
    "sin dato en Gemma Net": "Sin dato en Gemma Net",
    # tipo de estructura de CODIGO_INTERNO (normaliza/codigos.py,
    # investigado contra produccion el 2026-08-26 -- ver
    # design/tipos_codigo_interno.md)
    "cum": "CUM (expediente-consecutivo)",
    "cum_con_sufijo_atc": "CUM con sufijo ATC",
    "atc_expediente_consecutivo": "Capa legada ATC+expediente (no medicamento nuevo)",
    "ium": "IUM",
    "registro_sanitario": "Registro sanitario INVIMA usado como código",
    "forma_cups": "Forma de código CUPS (sin verificar contra tb_cup)",
    "codigo_propio": "Código propio de Pijao Salud",
    "sin_clasificar": "Sin clasificar",
}

# Ayuda para los terminos que ni traducidos se explican solos.
_GLOSARIO = {
    "Coincidencia aproximada": "El texto de INVIMA no es idéntico al del catálogo pero se "
    "parece por encima de un umbral alto. Es el único método que no da certeza total.",
    "Equivalencia conocida": "Una equivalencia auditada a mano que la máquina no puede "
    "deducir sola: «IU» es la sigla inglesa de «UI».",
    "Sin equivalencia en el catálogo": "No se encontró correspondencia con suficiente "
    "confianza, así que no se asignó ningún código. No se inventa.",
    "Requiere decisión de una persona": "El proceso no pudo decidir con certeza y lo apartó "
    "en vez de adivinar o descartarlo en silencio.",
}


def _fechas_legibles(df: pd.DataFrame) -> pd.DataFrame:
    """Las columnas de fecha en AAAA-MM-DD, sin ambiguedad de pais.

    El archivo de INVIMA trae las fechas como texto en formato de Estados
    Unidos: "09/15/2027" es mes/dia/año. Aca se nota porque no hay mes 15,
    pero "05/03/2027" seria el 3 de mayo o el 5 de marzo segun quien lo lea,
    y se equivocaria en silencio. AAAA-MM-DD no admite dos lecturas.
    """
    columnas = [c for c in df.columns if c.upper().startswith("FECHA")]
    if not columnas:
        return df
    visible = df.copy()
    for columna in columnas:
        convertidas = pd.to_datetime(visible[columna], errors="coerce", format="mixed")
        # Solo si de verdad son fechas: si no se pudieron interpretar se deja
        # el texto original, que es mas util que una columna vacia.
        if convertidas.notna().any():
            visible[columna] = convertidas.dt.strftime("%Y-%m-%d").fillna(
                visible[columna].astype(str)
            )
    return visible


def _tabla_metodos(destino, serie: pd.Series, total: int) -> None:
    """Como se resolvio un catalogo, en lenguaje de negocio y con el total.

    Antes se dibujaba `serie.value_counts()` en crudo: la columna se llamaba
    `unidad_metodo` y sus valores eran `exacto_sigla`, `fuzzy`,
    `sin_resolver`. Ademas no decia su suma, que es justamente la prueba de
    que no se perdio ninguna fila por el camino.
    """
    conteo = serie.value_counts()
    tabla = pd.DataFrame(
        {
            "Cómo se resolvió": [_legible(v) for v in conteo.index],
            "Medicamentos": conteo.to_numpy(),
            "%": (conteo.to_numpy() / total * 100).round(1) if total else 0.0,
        }
    )
    _mostrar_tabla_estandar(tabla, variante="resumen", destino=destino)
    destino.caption(f"Suman {int(conteo.sum()):,} de {total:,}: no se perdió ninguna fila.")


def _legible(valor: object) -> str:
    """Traduce un valor interno a lenguaje de negocio; lo deja igual si no lo
    conoce. Pensado para `format_func` y para `.map()` sobre una columna."""
    texto = str(valor)
    return _ETIQUETA_VALOR_INTERNO.get(texto, texto)


def _traducir_columnas(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    """Copia del DataFrame con esas columnas traducidas para mostrar.

    Copia y no en sitio: el valor interno sigue siendo el que usan los filtros,
    la exportacion y el resto del sistema. Aqui solo cambia lo que se lee.
    """
    presentes = [c for c in columnas if c in df.columns]
    if not presentes:
        return df
    visible = df.copy()
    for columna in presentes:
        visible[columna] = visible[columna].map(_legible)
    return visible

RAIZ = Path(__file__).resolve().parent.parent
RUTA_TOKENS = RAIZ / "design" / "design_tokens.json"

# La navegación tiene una única fuente de verdad: las seis secciones, sus
# grupos y, donde corresponde, las cinco sub-vistas que ya usaba el cuerpo de
# `main`. Las claves se conservan para no perder una selección hecha durante
# la sesión al cambiar de sección.
SUBVISTAS_POR_SECCION = {
    "Resumen de resolución": {
        "grupo": "candidatos",
        "clave": "resumen_vista",
        "etiqueta": "Qué quieres ver",
        "opciones": ("Resumen", "Cómo se resolvió", "Detalle por registro"),
    },
    "Casos que requieren decisión": {
        "grupo": "candidatos",
        # Una sola opcion: "Explicar con IA" se quito a pedido del usuario
        # (2026-08-26, "de momento no se requiere"). La logica que la
        # alimentaba (_cliente_ia_disponible, _explicar_motivo_cacheado)
        # sigue en el archivo por si se reactiva, solo no tiene entrada de
        # navegacion ni se ejecuta.
        "clave": "cuarentena_vista",
        "etiqueta": "Qué quieres hacer",
        "opciones": ("Bandeja de casos",),
    },
    "Cargue a Gemma Net": {
        "grupo": "candidatos",
        "clave": "cargue_vista",
        "etiqueta": "Qué quieres ver",
        "opciones": ("Auditoría de estructura", "Excel de cargue final"),
    },
    "Por qué no se cargó": {
        "grupo": "candidatos",
        "clave": "diagnostico_origen",
        "etiqueta": "Qué quieres revisar",
        "opciones": (
            "Candidatos nuevos que no se cargaron",
            "Ya cargados con diferencias frente a INVIMA",
            "Novedades de vigencia contra INVIMA",
        ),
    },
    "Consultar INVIMA": {
        "grupo": "cargados",
        "clave": None,
        "etiqueta": None,
        "opciones": (),
    },
    "Auditoría de coherencia": {
        "grupo": "cargados",
        "clave": "vista_auditoria",
        "etiqueta": "¿Que necesitas hacer ahora?",
        "opciones": (
            "Priorizar lo que requiere accion",
            "Entender la calidad del catalogo",
            "Explorar todos los hallazgos",
        ),
    },
}


def _activar_seccion(seccion: str) -> None:
    """Actualiza la sección antes de dibujar la pantalla de la interacción."""
    st.session_state["seccion_activa"] = seccion


def _activar_subvista(clave: str, opcion: str) -> None:
    """Guarda la opción elegida sin reiniciar los demás controles de la vista."""
    st.session_state[clave] = opcion


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
        /* Navegación lateral de dos niveles. Estos selectores se limitan al
        sidebar para no cambiar los botones de acción del resto de la pantalla. */
        section[data-testid="stSidebar"] div[data-testid="stButton"] {{
            margin: 0.1rem 0;
        }}
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button {{
            width: 100%;
            justify-content: flex-start;
            background-color: transparent;
            color: {color["texto_label"]["valor"]};
            border: 1px solid transparent;
            border-radius: {forma["radio_input_px"]}px;
            padding: 0.55rem 0.7rem;
            text-align: left;
            transition: background-color 0.15s ease, border-color 0.15s ease;
        }}
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {{
            background-color: {color["fondo_input"]["valor"]};
            border-color: {color["borde_input"]["valor"]};
        }}
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:focus-visible {{
            outline: 3px solid {color["primario"]["valor"]};
            outline-offset: 2px;
        }}
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"] {{
            background-color: {color["fondo_boton"]["valor"]};
            border-color: {color["primario"]["valor"]};
            box-shadow: inset 4px 0 0 {color["primario"]["valor"]};
            color: {color["texto_titulo"]["valor"]};
            font-weight: {tipografia["peso_titulo"]};
        }}
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:hover {{
            background-color: {color["primario_hover"]["valor"]};
            border-color: {color["primario_hover"]["valor"]};
            color: white;
        }}
        /* El selector de fuente conserva el aspecto de los campos de Gemma
        Net y su foco visible. Se limita a su clave para no cambiar los
        botones de acción de la pantalla. */
        .st-key-fuente_catalogos_elegida [data-baseweb="select"] > div {{
            background-color: {color["fondo_input"]["valor"]};
            border-color: {color["borde_input"]["valor"]};
            border-radius: {forma["radio_input_px"]}px;
        }}
        .st-key-fuente_catalogos_elegida [data-baseweb="select"] > div:focus-within {{
            outline: 3px solid {color["primario"]["valor"]};
            outline-offset: 2px;
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
        /* Icono "?" de _mostrar_detalle_alerta: HTML puro (atributo title),
        no un boton -- por eso el cursor "help" y el color, no hay estado
        hover/focus de Streamlit que estilar aqui. */
        .icono-ayuda {{
            cursor: help;
            color: {color["primario"]["valor"]};
            font-size: 0.85rem;
            opacity: 0.8;
        }}
        /* Tablas estandar: el contenedor separa el bloque de datos del resto
        de la pantalla y la cabecera azul deja clara la jerarquía. Se usan
        exclusivamente los tokens ya definidos para Gemma Net. */
        div[data-testid="stDataFrame"] {{
            border: 1px solid {color["borde_input"]["valor"]};
            border-radius: {forma["radio_input_px"]}px;
            overflow: hidden;
            background-color: {color["fondo_pagina"]["valor"]};
        }}
        div[data-testid="stDataFrame"] [data-testid="stElementToolbar"] {{
            background-color: {color["fondo_input"]["valor"]};
        }}
        div[data-testid="stDataFrame"] thead tr th,
        div[data-testid="stDataFrame"] [role="columnheader"] {{
            background-color: {color["primario"]["valor"]} !important;
            color: {color["fondo_pagina"]["valor"]} !important;
            font-family: {tipografia["familia"]};
            font-size: {tipografia["tamano_label_px"]}px;
            font-weight: {tipografia["peso_titulo"]} !important;
        }}
        div[data-testid="stDataFrame"] td,
        div[data-testid="stDataFrame"] [role="gridcell"] {{
            font-family: {tipografia["familia"]};
            font-size: {tipografia["tamano_input_px"]}px;
        }}
        /* Streamlit usa una grilla virtual en algunas versiones; cuando el
        DOM expone filas/celdas, este alternado facilita seguir una fila sin
        introducir un color ajeno a los tokens. */
        div[data-testid="stDataFrame"] tbody tr:nth-child(even) td,
        div[data-testid="stDataFrame"] [role="row"]:nth-child(even) [role="gridcell"] {{
            background-color: {color["fondo_input"]["valor"]} !important;
        }}
        /* Avisos (st.warning/info/error/success) nunca de borde a borde --
        pedido explicito del usuario: "ocupan de lado a lado la pantalla lo
        cual es estorboso". Se acota su ancho maximo; siguen alineados a la
        izquierda como el resto del contenido, no centrados. Se cubren varios
        selectores porque el testid del contenedor de alerta cambio entre
        versiones de Streamlit. */
        div[data-testid="stAlertContainer"], div[data-testid="stAlert"], .stAlert {{
            max-width: 900px;
            border-radius: {forma["radio_input_px"]}px;
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


_MAX_OPCIONES_CATEGORIA = 60

# Separador con el que la auditoria y el cruce unen varios valores en una sola
# celda (ver `_columnas_marcadas` en auditoria/coherencia_invima.py).
_SEPARADOR_LISTA = ", "


def _valores_de_columna_lista(texto: pd.Series) -> list[str] | None:
    """Los valores SUELTOS de una columna que guarda listas, o None si no lo es.

    `CAMPOS_CON_DIFERENCIA` no guarda un campo sino la lista de campos que
    fallan, unida en un texto ("CONCENTRACION, DESCRIPCION"). Pedirle sus
    valores distintos no daba 7 opciones sino **37 combinaciones** medidas
    sobre produccion el 2026-08-21, cuatro de ellas con una sola fila.

    Peor que incomodo, inducia a error: elegir "CONCENTRACION" devolvia las
    536 filas donde ese campo falla SOLO, no las 922 donde falla. Aqui se
    ofrecen los valores individuales y se filtra por "contiene cualquiera".

    Se reconoce como lista cuando hay celdas con el separador y el total de
    valores sueltos es mucho menor que el de combinaciones -- que es
    justamente la senal de que las opciones son combinatorias.
    """
    no_vacias = texto[texto.str.strip() != ""]
    if no_vacias.empty or not no_vacias.str.contains(_SEPARADOR_LISTA, regex=False).any():
        return None
    sueltos = sorted({
        parte.strip()
        for celda in no_vacias.unique()
        for parte in celda.split(_SEPARADOR_LISTA)
        if parte.strip()
    })
    if not sueltos or len(sueltos) > _MAX_OPCIONES_CATEGORIA:
        return None
    return sueltos


def _es_columna_de_fecha(serie: pd.Series) -> bool:
    """Si la columna son fechas, aunque lleguen como texto.

    Los lectores de INVIMA devuelven FECHA_EXPEDICION y compañía como `str`,
    asi que mirar solo el dtype dejaba el control de rango de fechas muerto:
    caian en el filtro de texto y no habia forma de pedir "de fecha a fecha".
    Se comprueba parseando una muestra, no la columna entera -- sobre 100.000
    filas eso costaria mas que el filtro.
    """
    if pd.api.types.is_datetime64_any_dtype(serie):
        return True
    muestra = serie.dropna().astype(str).head(200)
    if muestra.empty:
        return False
    convertidas = pd.to_datetime(muestra, errors="coerce", format="mixed")
    return convertidas.notna().mean() >= 0.8


_ETIQUETA_COLUMNA_FILTRO = {
    "ESTADO_COHERENCIA": "Estado frente a INVIMA",
    "CAMPOS_CON_DIFERENCIA": "Campos con diferencia",
    "CAMPOS_CON_ERROR": "Campos pendientes",
    "DETALLE": "Motivo del pendiente",
    "CLASIFICACION_CREACION": "Resultado de la revisión",
    "NOVEDAD_VIGENCIA_INVIMA": "Novedad de vigencia",
    "CODIGO_NIVEL_SERVICIO": "Nivel de servicio",
    "campos_con_error": "Campos pendientes",
    "motivo": "Motivo que requiere decisión",
    "motivo_pendiente": "Motivo del pendiente",
    "unidad_metodo": "Resultado de la unidad",
    "marca_metodo": "Resultado de la marca",
    "accion": "Decisión del proceso",
    "TIPO_CODIGO_INTERNO": "Tipo de estructura del código",
}


def _etiqueta_columna_filtro(columna: str) -> str:
    """Un nombre util para negocio, tambien cuando no tiene etiqueta fija."""
    return _ETIQUETA_COLUMNA_FILTRO.get(
        columna, NOMBRE_DISPLAY.get(columna, columna.replace("_", " ").title())
    )


def _etiqueta_valor_filtro(valor: object) -> str:
    """Traduce estados internos antes de ponerlos en un selector."""
    texto = str(valor)
    return _MENSAJE_ESTADO_COHERENCIA.get(texto, _legible(valor))


_LIMITE_PREVISUALIZACION_MEDICAMENTOS = 1_000
_ALTURA_TABLA_RESUMEN = 260
_ALTURA_TABLA_MEDICAMENTOS = 420

_ETIQUETA_COLUMNA_TABLA = {
    "%": "Porcentaje",
    "% COMPLETITUD": "% de completitud",
    "Accion": "Qué hacer",
    "accion": "Decisión del proceso",
    "motivo": "Motivo que requiere decisión",
    "motivo_pendiente": "Motivo del pendiente",
    "campos_con_error": "Campos por confirmar",
    "CAMPOS_CON_ERROR": "Campos por confirmar",
    "unidad_metodo": "Resultado de la unidad",
    "unidad_texto_invima": "Unidad reportada por INVIMA",
    "unidad_sugerencia": "Unidad sugerida para revisar",
    "marca_metodo": "Resultado de la marca",
    "marca_texto_invima": "Marca reportada por INVIMA",
    "marca_sugerencia": "Marca sugerida para revisar",
    "PORCENTAJE_CALIDAD": "% de coincidencia con INVIMA",
    "PORCENTAJE_COMPLETITUD_REPORTE": "% de completitud del reporte",
    "porcentaje_completitud": "% de completitud",
    "TIPO_SIN_CORRESPONDENCIA": "Resultado de la búsqueda en INVIMA",
    "DETALLE_VIGENCIA_INVIMA": "Detalle de vigencia frente a INVIMA",
    "ESTADO_INVIMA_DETALLE": "Estado reportado por INVIMA",
    "INCONSISTENCIA_FECHAS_ACTIVO": "Fechas y estado activo no son coherentes",
    "CODIGO_DUPLICADO_EN_REPORTE": "Código repetido en el reporte",
    "VALORES_FUERA_DE_DOMINIO": "Valores no permitidos",
    "INCONSISTENCIA_NUMERICA": "Valores numéricos incoherentes",
    "FORMATO_CODIGO_INTERNO_INVALIDO": "Código con formato inválido",
    "INTEGRIDAD_REFERENCIAL_CATALOGO": "Código de catálogo inexistente",
    "LINEA_CRUDA": "Contenido de la fila",
    "CODIGO_INTERNO_RECUPERADO": "Código recuperado",
    "ESTADO": "Resultado",
    "DETALLE": "Detalle",
    "NATURALEZA_HALLAZGO": "Clase de hallazgo",
    "TIPO_CODIGO_INTERNO": "Tipo de estructura del código",
}

_ETIQUETA_ESTADO_COHERENCIA_TABLA = {
    EstadoCoherencia.CORRECTO.value: "Datos coinciden con INVIMA",
    EstadoCoherencia.CON_DIFERENCIAS.value: "Hay diferencias frente a INVIMA",
    EstadoCoherencia.VENCIDO_EN_INVIMA.value: "Registro vencido en INVIMA",
    EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value: "Registro en otro estado en INVIMA",
    EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value: "En trámite de renovación",
    EstadoCoherencia.VIGENTE_NO_COMERCIALIZADO_INVIMA.value: "Vigente, sin comercialización temporal",
    EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value: "Sin correspondencia en INVIMA",
}

_COLUMNAS_TEXTO_AMPLIO = {
    "Qué significa",
    "Accion",
    "DETALLE",
    "motivo",
    "motivo_pendiente",
    "LINEA_CRUDA",
    "DETALLE_VIGENCIA_INVIMA",
    "ESTADO_INVIMA_DETALLE",
    "INTEGRIDAD_REFERENCIAL_CATALOGO",
}


def _etiqueta_columna_tabla(columna: str) -> str:
    """Devuelve encabezados que una persona de negocio puede reconocer."""
    if columna.endswith(SUFIJO_GEMANET):
        campo = columna.removesuffix(SUFIJO_GEMANET)
        return f"{_etiqueta_columna_filtro(campo)} en Gemma Net"
    if columna.endswith(SUFIJO_INVIMA):
        campo = columna.removesuffix(SUFIJO_INVIMA)
        return f"{_etiqueta_columna_filtro(campo)} en INVIMA"
    if columna.endswith(SUFIJO_VALIDACION):
        campo = columna.removesuffix(SUFIJO_VALIDACION)
        return f"Resultado de {_etiqueta_columna_filtro(campo).lower()}"
    if columna.startswith(PREFIJO_SIMILITUD):
        campo = columna.removeprefix(PREFIJO_SIMILITUD)
        return f"% de similitud de {_etiqueta_columna_filtro(campo).lower()}"
    return _ETIQUETA_COLUMNA_TABLA.get(
        columna,
        _etiqueta_columna_filtro(columna),
    )


def _es_columna_porcentaje(columna: str) -> bool:
    nombre = columna.upper()
    return (
        columna.strip().startswith("%")
        or "PORCENTAJE" in nombre
        or columna.startswith(PREFIJO_SIMILITUD)
    )


def _previsualizacion_tabla(df: pd.DataFrame) -> pd.DataFrame:
    """Prepara solo la porción que se muestra, nunca el DataFrame exportable."""
    vista = _fechas_legibles(df)
    columnas_internas = [
        columna
        for columna in (
            "accion",
            "unidad_metodo",
            "marca_metodo",
            "NOVEDAD_VIGENCIA_INVIMA",
        )
        if columna in vista.columns
    ]
    if columnas_internas:
        vista = vista.copy()
        for columna in columnas_internas:
            vista[columna] = vista[columna].map(_legible)
    if "CLASIFICACION_CREACION" in vista.columns:
        # CLASIFICACION_CREACION NO pasa por _legible(): su valor "candidato"
        # significa algo distinto del "candidato" de la decision de cargue
        # (ver _ETIQUETA_VALOR_INTERNO), y _legible() no sabe de que columna
        # viene el valor -- confundia "Candidato" con "Falta cargarlo" y
        # dejaba "cum_inactivo"/"muestra_medica" sin traducir. Bug real
        # reportado por el usuario (2026-08-26, captura de "Detalle por
        # registro"). _ETIQUETA_CLASIFICACION_CREACION es el diccionario
        # correcto -- el mismo que ya usan las tarjetas de metricas arriba.
        vista = vista.copy()
        vista["CLASIFICACION_CREACION"] = vista["CLASIFICACION_CREACION"].map(
            lambda valor: _ETIQUETA_CLASIFICACION_CREACION.get(str(valor), _legible(valor))
        )
    if "ESTADO_COHERENCIA" in vista.columns:
        vista = vista.copy()
        vista["ESTADO_COHERENCIA"] = vista["ESTADO_COHERENCIA"].map(
            lambda valor: _ETIQUETA_ESTADO_COHERENCIA_TABLA.get(str(valor), _legible(valor))
        )
    return vista


def _configuracion_columnas_tabla(df: pd.DataFrame) -> dict[str, object]:
    """Aplica los mismos encabezados y formatos a cada tabla de la interfaz."""
    configuracion: dict[str, object] = {}
    for columna, serie in df.items():
        etiqueta = _etiqueta_columna_tabla(columna)
        if _es_columna_porcentaje(columna) and pd.api.types.is_numeric_dtype(serie):
            configuracion[columna] = st.column_config.NumberColumn(etiqueta, format="%.1f %%")
        elif pd.api.types.is_integer_dtype(serie):
            configuracion[columna] = st.column_config.NumberColumn(etiqueta, format="%d")
        elif pd.api.types.is_float_dtype(serie):
            configuracion[columna] = st.column_config.NumberColumn(etiqueta, format="%.2f")
        elif columna in _COLUMNAS_TEXTO_AMPLIO:
            configuracion[columna] = st.column_config.TextColumn(etiqueta, width="large")
        else:
            configuracion[columna] = st.column_config.TextColumn(etiqueta)
    return configuracion


def _mostrar_tabla_estandar(
    df: pd.DataFrame,
    *,
    variante: str,
    destino=st,
) -> None:
    """Muestra resúmenes o medicamentos con un único contrato visual.

    La variante de medicamentos recorta exclusivamente la previsualización:
    `df` no se modifica, por lo que quien llama conserva todas las filas para
    descargas y demás decisiones de negocio.
    """
    if variante not in {"resumen", "medicamentos"}:
        raise ValueError("La tabla debe ser de resumen o de medicamentos.")

    total = len(df)
    if variante == "medicamentos":
        envio_navegador = df.head(_LIMITE_PREVISUALIZACION_MEDICAMENTOS)
        visibles = len(envio_navegador)
        if total > visibles:
            mensaje = (
                f"Total: {total:,} medicamentos · visibles en pantalla: {visibles:,}. "
                "Para que la bandeja siga ágil, se muestran los primeros 1.000; "
                "la lista completa permanece disponible para descargar."
            )
        else:
            mensaje = (
                f"Total: {total:,} medicamentos · visibles en pantalla: {visibles:,}. "
                "Todos los resultados actuales caben en esta vista."
            )
        destino.caption(mensaje)
        altura = _ALTURA_TABLA_MEDICAMENTOS
    else:
        envio_navegador = df
        altura = _ALTURA_TABLA_RESUMEN

    vista = _previsualizacion_tabla(envio_navegador)
    destino.dataframe(
        vista,
        use_container_width=True,
        height=altura,
        hide_index=True,
        column_config=_configuracion_columnas_tabla(vista),
    )


def _buscar_texto_libre(
    df: pd.DataFrame, busqueda: str, columnas: list[str] | None = None
) -> pd.DataFrame:
    """Busca localmente en las columnas que ya estan en memoria."""
    texto = busqueda.strip().lower()
    if not texto:
        return df
    columnas_presentes = columnas or list(df.columns)
    coincide = pd.Series(False, index=df.index)
    for columna in columnas_presentes:
        if columna in df.columns:
            coincide = coincide | df[columna].astype(str).str.lower().str.contains(
                texto, na=False, regex=False
            )
    return df[coincide]


def _buscar_auditoria(df: pd.DataFrame, busqueda: str) -> pd.DataFrame:
    """Compatibilidad para consumidores del filtro acotado de auditoria."""
    return _buscar_texto_libre(
        df,
        busqueda,
        [
            columna
            for columna in ("CODIGO_INTERNO", "DESCRIPCION", "EXPEDIENTE", "CONSECUTIVO")
            if columna in df.columns
        ],
    )


_PREFIJO_OPCIONES_FILTRO = "_opc_filtro_"
_PREFIJO_FILTRO_RESULTADO = "_filtro_res_"


def _opciones_filtro(
    df: pd.DataFrame,
    columna: str | None,
    opciones: list[str] | None = None,
    *,
    clave_cache: str | None = None,
) -> list[str]:
    """Opciones manejables de una categoria o de una columna tipo lista.

    `clave_cache`, cuando se pasa, memoiza el resultado en `session_state`
    por el resto de la corrida (via `_derivado`). Pedido explicito
    (2026-08-26): "en todas las tablas... deberemos cargar absolutamente
    todos los filtros para que cuando cambiemos la configuracion... no
    empiece las mismas validaciones". Calcular las opciones escanea la
    columna completa (`.unique()`) y sin esto se repetia en CADA rerun de la
    seccion -- escribir en el buscador, abrir un popover -- aunque el
    DataFrame base de esa tabla no cambia mientras se sigue viendo la misma
    vista. `len(df)` entra en la clave como huella barata del subconjunto:
    dos vistas con el mismo `key_prefix` pero distinto DataFrame de fondo
    (ej. `_panel_prioridades_auditoria`, que reusa un unico key_prefix para
    cualquier calidad elegida) no deben compartir cache.
    """
    if opciones is not None:
        return list(dict.fromkeys(opciones))
    if columna is None or columna not in df.columns:
        return []

    def _calcular() -> list[str]:
        texto = df[columna].fillna("").astype(str)
        valores_sueltos = _valores_de_columna_lista(texto)
        if valores_sueltos is not None:
            return valores_sueltos
        valores = sorted(valor for valor in texto.unique() if valor.strip())
        return valores if len(valores) <= _MAX_OPCIONES_CATEGORIA else []

    if clave_cache is None:
        return _calcular()
    return _derivado(f"{_PREFIJO_OPCIONES_FILTRO}{clave_cache}_{columna}_{len(df)}", _calcular)


def _migrar_seleccion_compatible(
    clave: str, opciones: list[str], clave_anterior: str | None
) -> None:
    """Pasa una seleccion del filtro anterior a su equivalente estandar."""
    if clave_anterior is None or clave_anterior not in st.session_state:
        return
    actual = st.session_state.get(clave, [])
    actuales = actual if isinstance(actual, list) else [actual]
    if clave in st.session_state and all(valor in opciones for valor in actuales):
        return
    anterior = st.session_state[clave_anterior]
    anteriores = anterior if isinstance(anterior, list) else [anterior]
    compatibles = [valor for valor in anteriores if valor in opciones]
    if compatibles:
        st.session_state[clave] = compatibles


def _multiseleccion_compatible(
    etiqueta: str,
    opciones: list[str],
    *,
    clave: str,
    iniciales: list[str],
    ayuda: str,
    formato=None,
) -> list[str]:
    """Conserva una seleccion previa solo si sigue siendo una opcion valida."""
    if clave in st.session_state:
        anterior = st.session_state[clave]
        anteriores = anterior if isinstance(anterior, list) else [anterior]
        validos = [valor for valor in anteriores if valor in opciones]
        if validos != anteriores:
            st.session_state[clave] = validos
        iniciales = validos
    else:
        iniciales = [valor for valor in iniciales if valor in opciones]
    return st.multiselect(
        etiqueta,
        opciones,
        default=iniciales,
        key=clave,
        help=ayuda,
        format_func=formato or _etiqueta_valor_filtro,
    )


def _filtrar_por_valores(
    df: pd.DataFrame, columna: str, elegidos: list[str]
) -> pd.DataFrame:
    """Filtra valores simples o listas de campos sin cambiar su significado."""
    if not elegidos or columna not in df.columns:
        return df
    texto = df[columna].fillna("").astype(str)
    if columna in {"CAMPOS_CON_DIFERENCIA", "CAMPOS_CON_ERROR", "campos_con_error"} or (
        _valores_de_columna_lista(texto) is not None
    ):
        # CAMPOS_CON_DIFERENCIA y campos_con_error significan "contiene
        # cualquiera": una fila puede tener mas de un campo pendiente.
        return _filtrar_por_campos(df, columna, elegidos)
    return df[texto.isin(elegidos)]


def _filtrar_exploracion_auditoria(
    auditoria: pd.DataFrame, estados: list[str], campos: list[str]
) -> pd.DataFrame:
    """Compatibilidad vectorizada con la exploracion de auditoria anterior."""
    filtrado = auditoria[auditoria["ESTADO_COHERENCIA"].isin(estados)]
    return _filtrar_por_campos(filtrado, "CAMPOS_CON_DIFERENCIA", campos)


def _filtrar_por_columnas_con_dato(
    df: pd.DataFrame, columnas: list[str]
) -> pd.DataFrame:
    """Conserva filas que traen dato en cualquiera de las columnas elegidas."""
    if not columnas:
        return df
    coincide = pd.Series(False, index=df.index)
    for columna in columnas:
        if columna not in df.columns:
            continue
        serie = df[columna]
        if pd.api.types.is_bool_dtype(serie):
            coincide = coincide | serie.fillna(False)
        else:
            coincide = coincide | serie.fillna("").astype(str).str.strip().ne("")
    return df[coincide]


def _filtros_estandar(
    df: pd.DataFrame,
    *,
    key_prefix: str,
    columnas_busqueda: list[str] | None = None,
    columna_categoria: str | None = None,
    columna_campo: str | None = None,
    columna_tipo: str | None = None,
    opciones_categoria: list[str] | None = None,
    opciones_campo: list[str] | None = None,
    opciones_tipo: list[str] | None = None,
    categorias_iniciales: list[str] | None = None,
    campos_iniciales: list[str] | None = None,
    tipos_iniciales: list[str] | None = None,
    etiqueta_categoria: str | None = None,
    etiqueta_campo: str | None = None,
    etiqueta_tipo: str | None = None,
    clave_busqueda: str | None = None,
    clave_categoria: str | None = None,
    clave_campo: str | None = None,
    clave_tipo: str | None = None,
    formato_categoria=None,
) -> pd.DataFrame:
    """El unico patron de filtro para tablas de medicamentos.

    La busqueda queda siempre a la vista. Los otros filtros se guardan en
    popovers cerrados: una categoria relevante, un campo para acotar y,
    donde aplica, el tipo de estructura de CODIGO_INTERNO (`columna_tipo`,
    tercer popover OPCIONAL -- con `None` el comportamiento es identico al
    de antes, ni un tercer `st.columns` se dibuja). Todo opera sobre el
    DataFrame recibido, que ya esta en memoria; cambiar un filtro no vuelve
    a leer archivos, consultar la base ni llamar a IA.
    """
    if df.empty:
        return df

    clave_busqueda = clave_busqueda or f"{key_prefix}_busqueda"
    clave_categoria = clave_categoria or f"{key_prefix}_categoria"
    # Esta era la clave del selector de campos de _filtros_avanzados. Se
    # conserva para que una sesion abierta no pierda una seleccion compatible.
    clave_campo = clave_campo or f"{key_prefix}_campos_filtro"
    clave_tipo = clave_tipo or f"{key_prefix}_tipo_codigo"
    busqueda = st.text_input(
        "🔎 Buscar medicamento",
        key=clave_busqueda,
        placeholder="Código, expediente, nombre o cualquier dato conocido",
        help="Busca en la lista ya cargada; no vuelve a consultar ninguna fuente.",
    )

    categorias = _opciones_filtro(
        df, columna_categoria, opciones_categoria, clave_cache=key_prefix
    )
    if columna_campo is not None:
        campos = _opciones_filtro(df, columna_campo, opciones_campo, clave_cache=key_prefix)
    else:
        campos = list(dict.fromkeys(opciones_campo or []))
    tipos = (
        _opciones_filtro(df, columna_tipo, opciones_tipo, clave_cache=key_prefix)
        if columna_tipo is not None
        else []
    )
    _migrar_seleccion_compatible(
        clave_categoria,
        categorias,
        f"{key_prefix}_f_{columna_categoria}" if columna_categoria is not None else None,
    )
    _migrar_seleccion_compatible(
        clave_campo,
        campos,
        f"{key_prefix}_f_{columna_campo}" if columna_campo is not None else None,
    )

    if columna_tipo is not None:
        col_categoria, col_campo, col_tipo = st.columns(3)
    else:
        col_categoria, col_campo = st.columns(2)
        col_tipo = None
    with col_categoria, st.popover(
        f"Filtrar por {etiqueta_categoria or _etiqueta_columna_filtro(columna_categoria or 'categoría')}",
        use_container_width=True,
    ):
        categorias_elegidas = _multiseleccion_compatible(
            etiqueta_categoria or _etiqueta_columna_filtro(columna_categoria or "Categoría"),
            categorias,
            clave=clave_categoria,
            iniciales=categorias_iniciales if categorias_iniciales is not None else categorias,
            ayuda="Elige uno o varios estados o categorías. Vacío significa no acotar por este dato.",
            formato=formato_categoria or _etiqueta_valor_filtro,
        )
    with col_campo, st.popover(
        f"Acotar por {etiqueta_campo or _etiqueta_columna_filtro(columna_campo or 'campo')}",
        use_container_width=True,
    ):
        campos_elegidos = _multiseleccion_compatible(
            etiqueta_campo or _etiqueta_columna_filtro(columna_campo or "Campo"),
            campos,
            clave=clave_campo,
            iniciales=campos_iniciales or [],
            ayuda=(
                "Una fila se conserva si contiene cualquiera de los campos elegidos."
                if columna_campo is not None
                else "Una fila se conserva si trae dato en cualquiera de las columnas elegidas."
            ),
            formato=_etiqueta_columna_filtro,
        )
    tipos_elegidos: list[str] = []
    if columna_tipo is not None:
        with col_tipo, st.popover(
            f"Filtrar por {etiqueta_tipo or _etiqueta_columna_filtro(columna_tipo)}",
            use_container_width=True,
        ):
            tipos_elegidos = _multiseleccion_compatible(
                etiqueta_tipo or _etiqueta_columna_filtro(columna_tipo),
                tipos,
                clave=clave_tipo,
                iniciales=tipos_iniciales if tipos_iniciales is not None else tipos,
                ayuda="Elige uno o varios tipos de estructura de CODIGO_INTERNO. Vacío "
                "significa no acotar por este dato.",
            )

    def _calcular_filtrado() -> pd.DataFrame:
        resultado = _buscar_texto_libre(df, busqueda, columnas_busqueda)
        if columna_categoria is not None:
            resultado = _filtrar_por_valores(resultado, columna_categoria, categorias_elegidas)
        if columna_campo is not None:
            resultado = _filtrar_por_valores(resultado, columna_campo, campos_elegidos)
        else:
            resultado = _filtrar_por_columnas_con_dato(resultado, campos_elegidos)
        if columna_tipo is not None:
            resultado = _filtrar_por_valores(resultado, columna_tipo, tipos_elegidos)
        return resultado

    # Memoiza el RESULTADO del filtrado, no solo sus opciones -- con varias
    # tablas de medicamentos abiertas a la vez (una por tarjeta de hallazgo,
    # ver _mostrar_tarjetas_alerta), cualquier clic en OTRA parte de la
    # pantalla vuelve a correr Streamlit entero y, sin esto, recalculaba de
    # cero cada tabla ya abierta aunque sus filtros no cambiaran. Pedido
    # explicito (2026-08-26): "mejores mas la capacidad del programa para
    # guardar en cache la informacion cargada para que no sea inutilizable".
    # `len(df)` en la clave es la misma huella barata que `_opciones_filtro`
    # (ver su docstring): distingue subconjuntos distintos que comparten
    # `key_prefix`, a costo de no distinguir dos subconjuntos con el mismo
    # tamaño -- aceptado ahi, se reusa aqui por consistencia.
    clave_resultado = (
        f"{_PREFIJO_FILTRO_RESULTADO}{key_prefix}_{len(df)}_{busqueda}_"
        f"{tuple(sorted(categorias_elegidas))}_{tuple(sorted(campos_elegidos))}_"
        f"{tuple(sorted(tipos_elegidos))}"
    )
    filtrado = _derivado(clave_resultado, _calcular_filtrado)
    st.caption(f"{len(filtrado):,} medicamento(s) con los filtros actuales.")
    return filtrado


@st.fragment
def _tabla_filtrable(
    df: pd.DataFrame,
    columnas_filtro: list[str],
    key_prefix: str,
    columnas_mostrar: list[str] | None = None,
    *,
    columna_categoria: str | None = None,
    columna_campo: str | None = None,
    columna_tipo: str | None = None,
    opciones_campo: list[str] | None = None,
    opciones_tipo: list[str] | None = None,
    categorias_iniciales: list[str] | None = None,
    campos_iniciales: list[str] | None = None,
    tipos_iniciales: list[str] | None = None,
    clave_campo: str | None = None,
    formato_categoria=None,
) -> pd.DataFrame:
    """Dibuja una tabla de medicamentos solo despues de aplicar el patron comun.

    `@st.fragment` (2026-08-26, pedido explicito del usuario tras medir que el
    computo en si ya era rapido -- ~0.1-0.3s por rerun completo incluso a
    200.000 filas -- pero CADA interaccion dentro de esta tabla (escribir en
    el buscador, abrir un filtro) igual reejecutaba TODO `main()`: el sidebar
    entero, las alertas de otras secciones, etc. Con el fragmento, escribir o
    filtrar aqui solo reejecuta esta funcion, no la pagina completa. Seguro
    para los llamadores que capturan el DataFrame devuelto (ej. el boton
    "Preparar esta lista (.xlsx)"): ese boton vive FUERA del fragmento, asi
    que un clic en el dispara igual un rerun completo que reconstruye el
    valor con los filtros mas recientes -- nunca se sirve un Excel con
    filtros viejos.
    """
    if df.empty:
        return df

    categoria = columna_categoria or next(
        (columna for columna in columnas_filtro if columna in df.columns), None
    )
    if columna_campo is None and opciones_campo is None:
        opciones_campo = [
            columna
            for columna in (columnas_filtro[1:] or (columnas_mostrar or list(df.columns)))
            if columna in df.columns and columna != categoria
        ]
    filtrado = _filtros_estandar(
        df,
        key_prefix=key_prefix,
        columnas_busqueda=columnas_mostrar,
        columna_categoria=categoria,
        columna_campo=columna_campo,
        columna_tipo=columna_tipo,
        opciones_campo=opciones_campo,
        opciones_tipo=opciones_tipo,
        categorias_iniciales=categorias_iniciales,
        campos_iniciales=campos_iniciales,
        tipos_iniciales=tipos_iniciales,
        clave_campo=clave_campo,
        formato_categoria=formato_categoria,
    )
    if filtrado.empty:
        st.caption("No hay medicamentos con esos criterios.")
        return filtrado

    columnas_visibles = _columnas_visibles(filtrado, columnas_mostrar, key_prefix, clave_campo)
    if categoria in filtrado.columns and categoria not in columnas_visibles:
        columnas_visibles.append(categoria)
    if columna_campo in filtrado.columns and columna_campo not in columnas_visibles:
        columnas_visibles.append(columna_campo)
    if columna_tipo in filtrado.columns and columna_tipo not in columnas_visibles:
        columnas_visibles.append(columna_tipo)
    salida = filtrado[columnas_visibles]
    _mostrar_tabla_estandar(salida, variante="medicamentos")
    return filtrado


def _columnas_visibles(
    df: pd.DataFrame,
    columnas_mostrar: list[str] | None,
    key_prefix: str,
    clave_campo: str | None = None,
) -> list[str]:
    """Incluye en la tabla las columnas elegidas para acotar cuando aplican."""
    if columnas_mostrar is None:
        return list(df.columns)
    elegidas = st.session_state.get(clave_campo or f"{key_prefix}_campos_filtro", []) or []
    visibles = list(columnas_mostrar)
    visibles += [columna for columna in elegidas if columna in df.columns and columna not in visibles]
    return [columna for columna in visibles if columna in df.columns]


def _descarga_diferida(etiqueta: str, generar, nombre_archivo: str, clave: str) -> None:
    """Descarga en dos pasos: preparar y luego bajar.

    `st.download_button` exige los bytes POR ADELANTADO, asi que generaba el
    Excel completo aunque nadie fuera a descargarlo. Medido el 2026-08-20:
    abrir la pestaña de auditoria costaba **114,7 segundos** construyendo un
    archivo de 45,7 MB con 199.689 filas que en la mayoria de las visitas
    nadie pedia. El reporte de cruce sumaba otros 8,8 s.

    Con dos pasos, quien solo consulta en pantalla no paga nada, y quien
    descarga lo paga una vez y sabiendo que va a tardar. El costo es un clic
    de mas; la alternativa era minuto y medio de espera en cada visita.
    """
    listo = st.session_state.get(clave)
    if listo is None:
        if st.button(etiqueta, key=f"{clave}_preparar"):
            with st.spinner("Generando el archivo, puede tardar..."):
                st.session_state[clave] = generar()
            st.rerun()
        return
    st.download_button(
        f"⬇ Descargar {nombre_archivo} ({len(listo) / 1048576:,.1f} MB)",
        data=listo,
        file_name=nombre_archivo,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{clave}_bajar",
    )


_ICONO_SEVERIDAD_ALERTA = {"error": "🔴", "warning": "🟡"}


def _mostrar_detalle_alerta(detalle: str, etiqueta: str) -> None:
    """Icono chico "❓" con tooltip nativo al pasar el mouse -- NO un
    desplegable, y ahora tampoco un `st.button`. Pedido explicito (2026-08-25):
    los expanders/popovers "solo desperdician espacio". Pedido explicito
    ADEMAS (2026-08-26): "si le doy clic [...] empieza a hacer algun proceso
    [...] es innecesario y solo gasta recursos" -- tenia razon: un
    `st.button`, aunque no se lea su valor, SI dispara un rerun completo de
    Streamlit al hacer clic. Un tooltip que solo debe aparecer al pasar el
    mouse no necesita ningun widget interactivo. Esto es HTML/CSS puro
    (atributo `title`, soportado nativamente por el navegador): cero clics,
    cero reruns, cero costo. El texto largo NO se pierde -- sigue siendo el
    mismo `detalle`, solo que ahora nunca ejecuta Python al mostrarse.

    `etiqueta` se conserva en la firma por compatibilidad con los llamadores
    existentes aunque ya no se use (era el label del boton) -- no vale la
    pena tocar cada sitio que llama a esta funcion por un parametro que ya
    no hace nada.

    Bug real reportado por el usuario (2026-08-26, captura de Auditoria):
    varios `detalle` traen "\\n\\n" (mensajes con "Detalle tecnico:" en su
    propia linea). `st.markdown` primero pasa el texto por su parser de
    Markdown -- una linea en blanco ahi es una marca de parrafo nuevo, y
    corta el tag `<span title="...">` a la mitad; el navegador ya no lo ve
    como UNA etiqueta HTML valida y termina mostrando el `<span...` crudo
    como texto. `" ".join(detalle.split())` colapsa cualquier salto de
    linea a un espacio ANTES de armar el HTML, asi el string que llega a
    `st.markdown` es siempre una sola linea -- nunca hay parrafo que
    Markdown pueda cortar. El tooltip pierde los saltos de linea visuales,
    pero un `title` nativo del navegador ya envuelve el texto solo.
    """
    del etiqueta
    detalle_una_linea = " ".join(detalle.split())
    st.markdown(
        f'<span class="icono-ayuda" title="{html.escape(detalle_una_linea)}">❓</span>',
        unsafe_allow_html=True,
    )


_COLUMNAS_DRILLDOWN_ALERTA = [
    "CODIGO_INTERNO",
    "DESCRIPCION",
    "ESTADO_COHERENCIA",
    "ESTADO_INVIMA_DETALLE",
    "NOVEDAD_VIGENCIA_INVIMA",
    "DETALLE_VIGENCIA_INVIMA",
    "TIPO_CODIGO_INTERNO",
]


def _mostrar_tarjetas_alerta(
    alertas: list[
        tuple[str, str, str]
        | tuple[str, str, str, pd.DataFrame]
        | tuple[str, str, str, pd.DataFrame, list[str]]
    ],
    *,
    grupo: str = "alerta",
) -> None:
    """Muestra cada advertencia como una tarjeta compacta (icono + título
    corto de una línea) en vez del párrafo completo en un banner ancho de
    color -- pedido explícito del usuario: los mensajes de advertencia eran
    "innecesariamente detallados" y "poco discretos". El texto largo (el
    "por qué"/"qué hacer") sigue disponible, pero un clic aparte, no forzado
    en pantalla. Los detalles extensos se muestran en una tarjeta emergente.

    `alertas`: lista de (severidad, título_corto, detalle_largo) o, cuando
    hay un subconjunto de medicamentos detrás del hallazgo, (severidad,
    título_corto, detalle_largo, subconjunto) o, si además conviene mostrar
    alguna columna puntual de ese hallazgo (ej. el campo vacío que lo causó),
    (severidad, título_corto, detalle_largo, subconjunto, columnas_extra).
    Pedido explícito (2026-08-26): "se muestre la información de los
    medicamentos que salieron seleccionados según su validación" -- el
    subconjunto YA está calculado por el llamador (una máscara sobre
    `auditoria`, que ya vive en `session_state`), así que mostrarlo es un
    filtrado en memoria, no un recálculo: "cargado junto con el apartado",
    sin costo de eficiencia aparte del de dibujar la tabla que el usuario
    pida ver. Cada cifra distinta trae SU PROPIO subconjunto -- no hay una
    tabla general compartida entre tarjetas.

    `grupo` entra en la clave del toggle "Ver medicamentos" para que dos
    grupos de tarjetas distintos (vigencia, calidad...) en la misma pantalla
    no colisionen aunque reusen el mismo índice de posición.

    Una tarjeta por fila, a todo el ancho -- pedido explícito del usuario
    (2026-08-26): "las tablas de cada cifra deben ir ligadas, o sea dentro
    del cuadro de la cifra ahí se debe de imprimir la tabla". Antes la
    grilla de 3 columnas dibujaba las tarjetas primero y las tablas
    activadas DESPUÉS, en una segunda pasada separada al final -- quedaban
    visualmente sueltas de la tarjeta que las explicaba. Ahora cada tarjeta
    dibuja su propia tabla adentro, en el momento en que se activa el
    toggle, sin una segunda pasada.
    """
    for i, alerta in enumerate(alertas):
        severidad, titulo, detalle = alerta[0], alerta[1], alerta[2]
        subconjunto = alerta[3] if len(alerta) > 3 else None
        columnas_extra = alerta[4] if len(alerta) > 4 else []
        with st.container(border=True):
            st.markdown(f"{_ICONO_SEVERIDAD_ALERTA.get(severidad, '🟡')} **{titulo}**")
            if detalle:
                _mostrar_detalle_alerta(detalle, "Detalle")
            if subconjunto is not None and not subconjunto.empty:
                ver = st.toggle(
                    f"Ver medicamentos ({len(subconjunto):,})",
                    key=f"ver_meds_{grupo}_{i}",
                )
                if ver:
                    # columnas_extra primero -- es el dato puntual que
                    # explica POR QUE esta fila esta en esta tarjeta
                    # especifica (ej. el campo vacio).
                    columnas_todas = list(
                        dict.fromkeys(columnas_extra + _COLUMNAS_DRILLDOWN_ALERTA)
                    )
                    columnas_presentes = [
                        c for c in columnas_todas if c in subconjunto.columns
                    ]
                    _tabla_auditoria_esencial(
                        subconjunto,
                        columnas_presentes,
                        clave=f"tabla_{grupo}_{i}",
                        vacio="Ningún medicamento con esos criterios en la corrida actual.",
                    )


def _mensaje_breve(
    resumen: str,
    detalle: str = "",
    *,
    tipo: str = "caption",
    etiqueta: str = "Ver detalle",
) -> None:
    """Deja UNA linea en pantalla y manda el resto a un detalle bajo clic.

    Pedido explicito del usuario: los mensajes informativos debian quedar
    "mas simples que detallados". El texto largo NO se borra -- casi todo
    explica una regla de negocio real (por que un codigo sin correspondencia
    no es lo mismo que uno vencido, por que la plantilla se copia, etc.) y
    perderlo empobreceria la aplicacion. Solo deja de imponerse a quien
    unicamente quiere leer la pantalla y seguir trabajando.

    `tipo` es el metodo de streamlit para la linea corta ("caption", "info",
    "warning", "error", "write"): el color se conserva donde comunica algo.
    """
    getattr(st, tipo)(resumen)
    if detalle:
        _mostrar_detalle_alerta(detalle, etiqueta)


_ETIQUETA_ARCHIVO = {
    "invima_vigentes": "INVIMA Vigentes",
    "invima_vencidos": "INVIMA Vencidos",
    "invima_otros_estados": "INVIMA Otros Estados",
    "invima_renovacion": "INVIMA Renovación",
    "estructura_cargue": "Estructura de Cargue",
    "reporte_gemanet": "Reporte de Gemma Net",
}


def _recordar_subida(archivo, carpeta: str = "data") -> object:
    """Guarda una copia del archivo subido y devuelve la ruta, si se pudo.

    Asi subir una vez basta: la proxima corrida lo encuentra solo. Si no se
    puede escribir, se devuelve el archivo en memoria y la corrida sigue --
    solo se pierde el automatismo, no el trabajo.
    """
    guardado = guardar_subida(archivo, archivo.name)
    if guardado is None:
        return archivo
    st.caption(f"Guardado en `{carpeta}/{guardado.name}` — la próxima corrida lo carga solo.")
    return str(guardado)


@st.cache_data(show_spinner=False, ttl=3600)
def _fecha_invima_publicada(dataset: str):
    """Cuando actualizo INVIMA ese dataset. Cacheado 1h: es un dato de
    contexto y no vale una llamada de red por cada rerun de Streamlit."""
    return socrata.fecha_ultima_actualizacion(dataset)


def _avisar_desactualizacion_invima(df_invima: pd.DataFrame | None = None) -> None:
    """Que tan viejo esta el listado local frente a lo que publica INVIMA.

    `df_invima` es el catalogo YA CARGADO. Se pide asi a proposito: la version
    anterior leia el Excel completo solo para sacar una fecha, y eso costaba
    **8,6 segundos en cada carga de la pagina**, antes de mostrar nada. El
    corte solo se calcula donde el catalogo ya esta en memoria (la auditoria);
    en el arranque se muestra unicamente la fecha de publicacion, que es una
    consulta de metadatos cacheada 1 hora.
    """
    publicada = _fecha_invima_publicada(DATASET_CUM_VIGENTES)
    if publicada is None:
        return
    if df_invima is None:
        st.caption(f"INVIMA publicó su última actualización el {publicada}.")
        return

    corte = _corte_catalogo_invima(df_invima)
    if corte is None:
        st.caption(f"INVIMA publicó su última actualización el {publicada}.")
        return

    # .date(): _corte_catalogo_invima devuelve un Timestamp de pandas y
    # `publicada` es un datetime.date -- restarlos directo lanza TypeError.
    corte_dia = corte.date()
    atraso = (publicada - corte_dia).days
    if atraso > 30:
        _mensaje_breve(
            f"El listado de INVIMA usado está **{atraso // 30} meses** por detrás de la fuente.",
            f"Corte del archivo: {corte_dia}. Última publicación de INVIMA: {publicada}. "
            "Descarga el listado nuevo de invima.gov.co y déjalo en `data/`.",
            tipo="warning",
            etiqueta="Por qué importa",
        )
    else:
        st.caption(f"Listado al día — corte {corte_dia}, INVIMA publicó el {publicada}.")


def _ruta_detectada(hallados: dict, tipo: str) -> str | None:
    """La ruta como texto, o None. Los lectores del proyecto aceptan una ruta
    igual que un archivo subido, asi que no hace falta nada mas."""
    encontrado = hallados.get(tipo)
    return str(encontrado.ruta) if encontrado is not None else None


def _panel_archivos_detectados(hallados: dict) -> None:
    """Tabla compacta de lo que se encontro en `data/`.

    Nombre, tamaño y fecha: lo justo para confirmar de un vistazo que es el
    archivo correcto, que fue el pedido -- automatizar la seleccion sin
    perder la posibilidad de verificarla. Nada mas: el detalle largo estorba
    a quien solo va a procesar.
    """
    filas = [
        {
            "Archivo": _ETIQUETA_ARCHIVO.get(tipo, tipo),
            "Nombre": a.nombre,
            "Tamaño": f"{a.tamano_mb:,.1f} MB",
            "Fecha": a.modificado.strftime("%Y-%m-%d"),
        }
        for tipo, a in hallados.items()
    ]
    _mostrar_tabla_estandar(pd.DataFrame(filas), variante="resumen")


def _conteo_por_campo(serie: pd.Series, campos: list[str]) -> dict[str, int]:
    """Cuantas filas mencionan cada campo en una columna de nombres separados
    por coma (`campos_con_error`, `CAMPOS_CON_DIFERENCIA`).

    Se compara contra la lista de campos conocidos en vez de partir el texto:
    los nombres son fijos y asi un campo con cero fallas igual aparece en el
    resultado -- un cero es informacion ("este campo nunca falla"), no una
    fila que se pueda omitir.
    """
    texto = serie.fillna("").astype(str)
    return {campo: int(texto.str.contains(campo, regex=False).sum()) for campo in campos}


def _filtrar_por_campos(df: pd.DataFrame, columna: str, campos: list[str]) -> pd.DataFrame:
    """Filas cuya `columna` (lista separada por `_SEPARADOR_LISTA`) menciona
    al menos uno de `campos`.

    Coincidencia LITERAL (`regex=False`), no un patron `\\b...\\b`: `campo`
    no siempre es un identificador corto (DESCRIPCION, MARCA_MEDICAMENTO) --
    para columnas de motivo/error puede ser una oracion libre con
    parentesis, puntos o signos de porcentaje ("codigo 200) | TRAVENOL
    LABORATORIES INC. (61%"). Eso rompia de DOS formas con el regex
    anterior, vistas en produccion el 2026-08-25: como texto no es un regex
    valido (PyArrow revienta con "Invalid regular expression", mas
    estricto que el `re` de Python con parentesis sin cerrar), y aunque se
    escapara con `re.escape()`, `\\b` no encuentra limite de palabra al
    final de un texto que termina en un signo de puntuacion -- el filtro
    devolvia 0 filas en silencio, sin avisar. Ningun campo de la lista fija
    (`CAMPOS_COMPARADOS_COHERENCIA`) es substring de otro, asi que la
    coincidencia literal no gana falsos positivos ahi tampoco.
    """
    if not campos:
        return df
    texto = df[columna].fillna("").astype(str)
    coincide = pd.Series(False, index=df.index)
    for campo in campos:
        coincide = coincide | texto.str.contains(campo, regex=False)
    return df[coincide]


def _no_vacio(df: pd.DataFrame, columna: str) -> pd.Series:
    """Filas donde esa columna trae algo. Vacio si la columna no existe."""
    if columna not in df.columns:
        return pd.Series(False, index=df.index)
    serie = df[columna]
    if serie.dtype == bool:
        return serie
    return serie.fillna("").astype(str).str.strip().ne("")


def _calidades(auditoria: pd.DataFrame) -> list[dict]:
    """Las calidades que el negocio pide poder revisar, cada una con su lista.

    Pedido explicito (2026-08-21): "una tabla de calidades [...] si ya me dices
    que hay diferencias pero yo quiero saber que medicamentos, que diferencias
    en cada campo". Todas estas cifras YA se calculaban; lo que faltaba era
    poder abrirlas hasta los medicamentos que las componen.

    Cada entrada trae la mascara y las columnas que hacen falta para entender
    ESE hallazgo -- no las mismas para todos: quien mira duplicados necesita
    el codigo, quien mira vigencia necesita las fechas.
    """
    estado = auditoria["ESTADO_COHERENCIA"]
    activo = _columna_texto(auditoria, "ACTIVO").str.upper().eq("SI")
    codigo = _columna_texto(auditoria, "CODIGO_INTERNO")
    tiene_formato_invima = codigo.str.match(PATRON_CUM)

    base = ["CODIGO_INTERNO", "DESCRIPCION", "ACTIVO"]
    return [
        {
            "nombre": "Sin código verificable contra INVIMA",
            "explica": "Su código no sigue el formato EXPEDIENTE-CONSECUTIVO, así que no hay "
            "con qué buscarlo en INVIMA. No están mal cargados: no se pueden verificar "
            "por este camino.",
            "mascara": ~tiene_formato_invima,
            "columnas": [*base, "TIPO_SIN_CORRESPONDENCIA"],
        },
        {
            "nombre": "Con formato INVIMA pero no encontrados",
            "explica": "Sí tienen forma de código INVIMA y aun así no aparecen en ninguno de "
            "los cuatro listados. Son los que vale la pena revisar uno por uno.",
            "mascara": tiene_formato_invima
            & estado.eq(EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value),
            "columnas": [*base, "TIPO_SIN_CORRESPONDENCIA"],
        },
        {
            "nombre": "Código repetido dentro del reporte",
            "explica": "El mismo código aparece más de una vez. Puede ser legítimo: un "
            "medicamento combinado trae una fila por principio activo. Nunca se fusionan.",
            "mascara": _no_vacio(auditoria, "CODIGO_DUPLICADO_EN_REPORTE"),
            "columnas": [*base, "PRINCIPIO_ACTIVO"],
        },
        {
            "nombre": "Formato de código inválido",
            "explica": "El código viene vacío o es un error de fórmula heredado de Excel.",
            "mascara": _no_vacio(auditoria, "FORMATO_CODIGO_INTERNO_INVALIDO"),
            "columnas": [*base, "FORMATO_CODIGO_INTERNO_INVALIDO"],
        },
        {
            "nombre": "Registro vencido en INVIMA",
            "explica": "INVIMA lo tiene en su listado de vencidos.",
            "mascara": estado.eq(EstadoCoherencia.VENCIDO_EN_INVIMA.value),
            "columnas": [*base, "FECHA_FIN", "DETALLE_VIGENCIA_INVIMA"],
        },
        {
            "nombre": "En otro estado en INVIMA",
            "explica": "Cancelado, Suspendido, Negado, Desistido, Pérdida de fuerza ejecutoria… "
            "El detalle dice cuál exactamente.",
            "mascara": estado.eq(EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value),
            "columnas": [*base, "ESTADO_INVIMA_DETALLE"],
        },
        {
            "nombre": "En trámite de renovación",
            "explica": "El registro sigue siendo válido mientras INVIMA resuelve. Se espera, "
            "no se corrige.",
            "mascara": estado.eq(EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value),
            "columnas": [*base, "ESTADO_INVIMA_DETALLE"],
        },
        {
            "nombre": "Con algún campo distinto al de INVIMA",
            "explica": "Existe en INVIMA y se pudo comparar campo a campo: alguno no coincide. "
            "Abajo se puede ver cuál y qué dice cada lado.",
            "mascara": _no_vacio(auditoria, "CAMPOS_CON_DIFERENCIA"),
            "columnas": [*base, "CAMPOS_CON_DIFERENCIA", "PORCENTAJE_CALIDAD"],
        },
        {
            "nombre": "Fechas que se contradicen",
            "explica": "ACTIVO y las fechas de inicio/fin no cuadran entre sí. No depende de "
            "INVIMA: es el dato contra sí mismo.",
            "mascara": _no_vacio(auditoria, "INCONSISTENCIA_FECHAS_ACTIVO"),
            "columnas": [*base, "FECHA_INICIO", "FECHA_FIN", "INCONSISTENCIA_FECHAS_ACTIVO"],
        },
        {
            "nombre": "Código de marca o unidad inexistente",
            "explica": "Guarda un código de catálogo que no existe en el catálogo. No es una "
            "diferencia con INVIMA: es un código huérfano.",
            "mascara": _no_vacio(auditoria, "INTEGRIDAD_REFERENCIAL_CATALOGO"),
            "columnas": [*base, "INTEGRIDAD_REFERENCIAL_CATALOGO"],
        },
        {
            "nombre": "⚠ Activos aquí sin vigencia en INVIMA",
            "explica": "Los únicos sobre los que se puede actuar hoy: están ACTIVOS en Gemma "
            "Net y su registro no está vigente en INVIMA, así que se pueden llegar a "
            "autorizar. Es la cifra que importa para el riesgo, no el total de vencidos.",
            "mascara": activo
            & estado.isin(
                [
                    EstadoCoherencia.VENCIDO_EN_INVIMA.value,
                    EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value,
                ]
            ),
            "columnas": [*base, "ESTADO_INVIMA_DETALLE", "FECHA_FIN"],
        },
    ]


def _columna_texto(df: pd.DataFrame, nombre: str) -> pd.Series:
    if nombre not in df.columns:
        return pd.Series("", index=df.index, dtype="object")
    return df[nombre].fillna("").astype(str).str.strip()


def _mostrar_tabla_de_calidades(auditoria: pd.DataFrame) -> None:
    """La tabla de calidades: cada cifra se puede abrir hasta sus medicamentos.

    Es el entregable que pide el negocio. La diferencia con las tarjetas de
    arriba no es el calculo -- es el mismo -- sino que aqui cada fila lleva a
    la lista, con busqueda, filtros y descarga.
    """
    calidades = _calidades(auditoria)
    total = len(auditoria)

    resumen = pd.DataFrame(
        [
            {
                "Calidad": c["nombre"],
                "Medicamentos": int(c["mascara"].sum()),
                "% del catálogo": round(int(c["mascara"].sum()) / total * 100, 1) if total else 0.0,
                "Qué significa": c["explica"],
            }
            for c in calidades
        ]
    )
    _mostrar_tabla_estandar(resumen, variante="resumen")

    _mensaje_breve(
        "Falta una calidad que hoy no se puede responder: **vencidos que se siguen "
        "formulando**.",
        "Se sabe cuáles están vencidos y cuáles están ACTIVOS, pero *activo* no es lo mismo "
        "que *formulándose*: eso vive en las autorizaciones y dispensaciones, en otras tablas "
        "de la base. Se deja explícito en vez de aproximarlo con el dato que sí hay.",
        etiqueta="Por qué no está",
    )

    st.divider()
    nombres = [c["nombre"] for c in calidades]
    elegida = st.selectbox(
        "Abrir una calidad y ver los medicamentos que la componen",
        nombres,
        key="calidad_elegida",
    )
    calidad = next(c for c in calidades if c["nombre"] == elegida)
    subconjunto = auditoria[calidad["mascara"]]

    _mensaje_breve(
        f"**{len(subconjunto):,} medicamentos.** {calidad['explica']}",
        "La lista de abajo se puede buscar, filtrar por cualquier campo y descargar. "
        "Cada columna que uses para filtrar se agrega a la tabla, para que puedas "
        "comprobar el filtro en vez de tener que creerle.",
        tipo="info",
        etiqueta="Cómo usar esta lista",
    )

    if subconjunto.empty:
        st.caption("Ningún medicamento cae en esta calidad en la corrida actual.")
        return

    columnas = [c for c in calidad["columnas"] if c in subconjunto.columns]
    visible = _tabla_filtrable(
        subconjunto,
        columnas_filtro=[columnas[-1]] if columnas else [],
        key_prefix=f"calidad_{nombres.index(elegida)}",
        columnas_mostrar=columnas,
        columna_categoria=(
            "ESTADO_COHERENCIA" if "ESTADO_COHERENCIA" in subconjunto.columns else None
        ),
        columna_campo=(
            "CAMPOS_CON_DIFERENCIA" if "CAMPOS_CON_DIFERENCIA" in subconjunto.columns else None
        ),
        columna_tipo=(
            "TIPO_CODIGO_INTERNO" if "TIPO_CODIGO_INTERNO" in subconjunto.columns else None
        ),
        opciones_campo=(
            CAMPOS_COMPARADOS_COHERENCIA
            if "CAMPOS_CON_DIFERENCIA" in subconjunto.columns
            else None
        ),
    )
    _descarga_diferida(
        "Preparar esta calidad (.xlsx)",
        lambda: _exportar_a_bytes(
            lambda w: visible.to_excel(w, index=False, sheet_name="calidad")
        ),
        f"calidad_{nombres.index(elegida) + 1}.xlsx",
        f"descarga_calidad_{nombres.index(elegida)}",
    )


@st.fragment
def _tabla_auditoria_esencial(
    df: pd.DataFrame,
    columnas: list[str],
    *,
    clave: str,
    vacio: str,
    columna_categoria: str | None = None,
    columna_campo: str | None = None,
    columna_tipo: str | None = None,
    opciones_campo: list[str] | None = None,
    categorias_iniciales: list[str] | None = None,
    clave_campo: str | None = None,
) -> pd.DataFrame:
    """Tabla de auditoria con el mismo patron de filtros de toda la app.

    `@st.fragment`: ver el docstring de `_tabla_filtrable` -- mismo motivo y
    misma garantia de seguridad para los llamadores que capturan el
    resultado (el boton de descarga vive fuera del fragmento).

    `columna_tipo` se autodetecta a TIPO_CODIGO_INTERNO cuando la columna
    esta presente -- las tablas de auditoria siempre la traen (viene de
    Gemma Net, ver auditar_coherencia()); se puede desactivar pasando ""
    explicitamente si alguna vez hiciera falta.
    """
    categoria = columna_categoria or (
        "ESTADO_COHERENCIA" if "ESTADO_COHERENCIA" in df.columns else None
    )
    campo = columna_campo or (
        "CAMPOS_CON_DIFERENCIA" if "CAMPOS_CON_DIFERENCIA" in df.columns else None
    )
    tipo = (
        columna_tipo
        if columna_tipo is not None
        else ("TIPO_CODIGO_INTERNO" if "TIPO_CODIGO_INTERNO" in df.columns else None)
    ) or None
    filtrado = _filtros_estandar(
        df,
        key_prefix=clave,
        columnas_busqueda=[
            columna
            for columna in ("CODIGO_INTERNO", "DESCRIPCION", "EXPEDIENTE", "CONSECUTIVO")
            if columna in df.columns
        ],
        columna_categoria=categoria,
        columna_campo=campo,
        columna_tipo=tipo,
        opciones_campo=opciones_campo,
        categorias_iniciales=categorias_iniciales,
        clave_campo=clave_campo,
    )
    if filtrado.empty:
        st.caption(vacio)
        return filtrado
    presentes = [columna for columna in columnas if columna in filtrado.columns]
    if categoria in filtrado.columns and categoria not in presentes:
        presentes.append(categoria)
    if campo in filtrado.columns and campo not in presentes:
        presentes.append(campo)
    if tipo in filtrado.columns and tipo not in presentes:
        presentes.append(tipo)
    _mostrar_tabla_estandar(filtrado[presentes], variante="medicamentos")
    return filtrado


def _panel_prioridades_auditoria(auditoria: pd.DataFrame) -> None:
    """Prioriza una accion y lleva directo a los medicamentos que la requieren."""
    calidades = _calidades(auditoria)
    relevantes = [
        calidad
        for calidad in calidades
        if calidad["nombre"]
        in {
            "⚠ Activos aquí sin vigencia en INVIMA",
            "Registro vencido en INVIMA",
            "En otro estado en INVIMA",
            "Con formato INVIMA pero no encontrados",
            "Con algún campo distinto al de INVIMA",
        }
    ]
    resumen = pd.DataFrame(
        [
            {
                "Prioridad": calidad["nombre"],
                "Medicamentos": int(calidad["mascara"].sum()),
                "Accion": calidad["explica"],
            }
            for calidad in relevantes
        ]
    )
    _mostrar_tabla_estandar(resumen, variante="resumen")
    opciones = [calidad["nombre"] for calidad in relevantes]
    elegida = st.selectbox("Ver medicamentos de esta prioridad", opciones, key="prioridad_auditoria")
    calidad = next(calidad for calidad in relevantes if calidad["nombre"] == elegida)
    visible = _tabla_auditoria_esencial(
        auditoria[calidad["mascara"]],
        calidad["columnas"],
        clave="prioridad_auditoria",
        vacio="No hay medicamentos en esta prioridad en la corrida actual.",
    )
    if not visible.empty:
        _descarga_diferida(
            "Preparar esta lista (.xlsx)",
            lambda: _exportar_a_bytes(
                lambda ruta: visible.to_excel(ruta, index=False, sheet_name="prioridad")
            ),
            "prioridad_auditoria.xlsx",
            "descarga_prioridad_auditoria",
        )


def _panel_entender_auditoria(auditoria: pd.DataFrame) -> None:
    """Resume la calidad sin mezclarla con las decisiones de prioridad."""
    total = len(auditoria)
    completitud = auditoria["PORCENTAJE_COMPLETITUD_REPORTE"].mean()
    dimensiones = [
        ("Completitud", completitud, "Promedio de campos diligenciados."),
        ("Duplicados", int(auditoria["CODIGO_DUPLICADO_EN_REPORTE"].sum()), "CODIGO_INTERNO repetido."),
        (
            "Dominio",
            int((auditoria["VALORES_FUERA_DE_DOMINIO"] != "").sum()),
            "Valores fuera de los dominios permitidos.",
        ),
        (
            "Formato",
            int((auditoria["FORMATO_CODIGO_INTERNO_INVALIDO"] != "").sum()),
            "Codigos vacios o errores de formula.",
        ),
        (
            "Catalogos",
            int((auditoria["INTEGRIDAD_REFERENCIAL_CATALOGO"] != "").sum()),
            "Codigos de marca o unidad inexistentes.",
        ),
    ]
    st.caption(
        f"Indicadores sobre {total:,} medicamentos. No cambian la prioridad: describen "
        "la calidad del dato que ya esta cargado."
    )
    columnas = st.columns(len(dimensiones))
    for columna, (nombre, valor, ayuda) in zip(columnas, dimensiones, strict=True):
        texto = f"{valor:.1f}%" if nombre == "Completitud" and pd.notna(valor) else f"{valor:,}"
        columna.metric(nombre, texto, help=ayuda)

    if "TIPO_CODIGO_INTERNO" in auditoria.columns:
        _mostrar_distribucion_tipo_codigo_interno(auditoria)


# Capa legada de INVIMA (codigo ATC + expediente + consecutivo): medida
# contra produccion el 2026-08-26 en 0% activa y con gemelo CUM duplicado en
# el 90% de los casos -- pura trazabilidad, sin funcion legible hoy. Pedido
# de negocio explicito (2026-08-26): lo que no esta vigente no deberia
# estorbar el flujo de trabajo, asi que no se muestra expandida por
# defecto -- sigue siendo filtrable a mano en cualquier tabla.
_TIPO_CAPA_LEGADA = "atc_expediente_consecutivo"


def _mostrar_distribucion_tipo_codigo_interno(auditoria: pd.DataFrame) -> None:
    """Cuantos codigos hay de cada tipo de estructura -- catalogo investigado
    contra produccion el 2026-08-26 (design/tipos_codigo_interno.md). Se
    puede filtrar por esto en "Explorar todos los hallazgos" y en la tabla
    de calidades (columna TIPO_CODIGO_INTERNO)."""
    conteo = auditoria["TIPO_CODIGO_INTERNO"].value_counts()
    n_legado = int(conteo.get(_TIPO_CAPA_LEGADA, 0))
    conteo_principal = conteo.drop(labels=[_TIPO_CAPA_LEGADA], errors="ignore")
    resumen = pd.DataFrame(
        [
            {"Tipo": _legible(tipo), "Medicamentos": int(n)}
            for tipo, n in conteo_principal.items()
        ]
    )
    st.caption("Tipos de estructura de CODIGO_INTERNO en este reporte:")
    _mostrar_tabla_estandar(resumen, variante="resumen")
    if n_legado:
        with st.expander(
            f"+ {n_legado:,} en una capa legada de INVIMA (inactiva, no participa en la prioridad)"
        ):
            st.caption(
                "\"Capa legada ATC+expediente\": código ATC + expediente + consecutivo. "
                "Medido contra producción: 0% activa, y en el 90% de los casos ya existe "
                "como fila CUM independiente en este mismo reporte. Se conserva por "
                "trazabilidad — no aparece en la lista principal ni cuenta para las "
                "tarjetas de \"Priorizar lo que requiere acción\", pero sigue disponible "
                "en el filtro de esta y otras tablas si necesitás revisarla a propósito."
            )
    _mensaje_breve(
        "Paquetes e insumos no aparecen en esta lista.",
        "No tienen un patrón de código propio -- solo se distinguen cruzando contra "
        "las tablas `tb_cup`/`tb_insumo` de Gemma Net, que esta aplicación hoy no "
        "consulta. Quedan dentro de las categorías por forma de código (ej. "
        "`codigo_propio`, `sin_clasificar`) hasta que se implemente ese cruce.",
        tipo="caption",
        etiqueta="Por qué no hay categoría \"paquete\" o \"insumo\"",
    )


def _avisar_campos_derivados(elegidos: list[str], df: pd.DataFrame, columna: str) -> None:
    """Avisa cuando un campo elegido se DERIVA de otro que tambien falla.

    La descripcion se construye con el principio activo, la cantidad, la
    unidad y la forma. Si el principio activo difiere, la descripcion difiere
    por consecuencia: son el mismo problema contado dos veces, y sin decirlo
    parecen dos frentes de trabajo distintos.
    """
    if columna not in df.columns:
        return
    texto = df[columna].fillna("").astype(str)
    for campo in elegidos:
        origenes = CAMPOS_DERIVADOS.get(campo)
        if not origenes:
            continue
        falla_el_derivado = texto.str.contains(rf"\b{campo}\b", regex=True, na=False)
        juntos = {
            origen: int(
                (
                    falla_el_derivado
                    & texto.str.contains(rf"\b{origen}\b", regex=True, na=False)
                ).sum()
            )
            for origen in origenes
        }
        detalle = ", ".join(
            f"{n:,} también fallan en {NOMBRE_DISPLAY.get(o, o)}" for o, n in juntos.items() if n
        )
        if not detalle:
            continue
        _mensaje_breve(
            f"**{NOMBRE_DISPLAY.get(campo, campo)} no es un dato independiente: se construye "
            f"a partir de otros campos.**",
            f"De los que fallan aquí, {detalle}. En esos casos no hay dos problemas sino uno: "
            "corregir el campo de origen arregla los dos. Conviene atacar primero el origen.",
            tipo="info",
            etiqueta="Por qué importa",
        )


def _columnas_de_detalle(df: pd.DataFrame, campo: str) -> list[str]:
    """Las columnas que muestran el ERROR de un campo, no solo su nombre.

    La auditoria ya produce por cada campo comparable el valor de Gemma Net,
    el de INVIMA, el veredicto y el porcentaje de parecido (ver SUFIJO_* y
    PREFIJO_SIMILITUD en auditoria/coherencia_invima.py). Decir que
    "UNIDAD_MEDIDA difiere" sin decir que dice cada lado obliga a ir a
    buscarlo por fuera; con el par al lado se decide en el sitio.

    Devuelve solo las que existan: el flujo de candidatos no las produce.
    """
    candidatas = [
        f"{campo}{SUFIJO_GEMANET}",
        f"{campo}{SUFIJO_INVIMA}",
        f"{campo}{SUFIJO_VALIDACION}",
        f"{PREFIJO_SIMILITUD}{campo}",
    ]
    return [c for c in candidatas if c in df.columns]


def _diagnostico_por_campo(
    df: pd.DataFrame,
    *,
    columna: str,
    campos: list[str],
    key_prefix: str,
    columnas_extra: list[str],
    nombre_archivo: str,
    total: int,
    leyenda: str,
) -> None:
    """Metricas por campo + tabla filtrada por los campos elegidos.

    Compartido por los dos origenes de la pestaña (candidatos pendientes y
    diferencias de la auditoria) porque la pregunta es la misma -- "¿quien
    falla en ESTE campo?" -- y solo cambian la columna de origen y la lista de
    campos. `campos` sale de CAMPOS_VERIFICABLES_CARGUE o de
    CAMPOS_COMPARADOS_COHERENCIA: las mismas listas que usa el resto del
    sistema, para que el nombre del campo sea identico en la UI, el Excel y
    el codigo.
    """
    conteos = _conteo_por_campo(df[columna], campos)
    st.caption(f"{len(df):,} de {total:,} {leyenda} tienen al menos un campo con problema.")

    columnas_metricas = st.columns(len(campos))
    for col, campo in zip(columnas_metricas, campos, strict=True):
        n = conteos[campo]
        col.metric(
            NOMBRE_DISPLAY.get(campo, campo),
            f"{n:,}",
            f"{n / len(df) * 100:.0f}%" if len(df) else None,
            delta_color="off",
        )

    # El selector de campos conserva su clave existente. Al volver a ejecutar
    # por una seleccion, el valor ya esta disponible para agregar sus detalles
    # a la tabla sin crear un tercer control de filtro.
    elegidos = [
        campo for campo in st.session_state.get(f"{key_prefix}_campos", []) if campo in campos
    ]

    # Al elegir un campo se traen SUS columnas de detalle: que dice Gemma Net,
    # que dice INVIMA y el veredicto. Sin esto la tabla decia "UNIDAD_MEDIDA"
    # y no que valor tenia cada lado, asi que no se podia corregir nada sin ir
    # a buscarlos por fuera. El dato ya se calculaba y viajaba al Excel: solo
    # faltaba mostrarlo (pedido del usuario, 2026-08-24).
    detalle_campos = [c for campo in elegidos for c in _columnas_de_detalle(df, campo)]
    if detalle_campos:
        st.caption(
            "Se agregaron las columnas de detalle de los campos elegidos: lo que dice Gemma "
            "Net, lo que dice INVIMA y el veredicto."
        )
    _avisar_campos_derivados(elegidos, df, columna)

    sugeridas = [
        c
        for c in [
            "CODIGO_INTERNO",
            "DESCRIPCION",
            "EXPEDIENTE",
            "CONSECUTIVO",
            "CODIGO_INTERNO_MODELO_SERVICIO",
            columna,
            *detalle_campos,
            *columnas_extra,
        ]
        if c in df.columns
    ]
    columnas_guardadas = st.session_state.get(f"{key_prefix}_columnas", [])
    columnas_mostrar = [
        campo for campo in columnas_guardadas if campo in df.columns
    ] or sugeridas
    categoria = next(
        (
            campo
            for campo in (
                "ESTADO_COHERENCIA",
                "ACTIVO",
                "motivo_pendiente",
                "NOVEDAD_VIGENCIA_INVIMA",
            )
            if campo in df.columns and campo != columna
        ),
        None,
    )

    visible = _tabla_filtrable(
        df,
        columnas_filtro=[columna],
        key_prefix=key_prefix,
        columnas_mostrar=columnas_mostrar,
        columna_categoria=categoria,
        columna_campo=columna,
        # Solo los "ya cargados con diferencias" vienen de la auditoria y
        # traen TIPO_CODIGO_INTERNO -- los candidatos pendientes de Cargue
        # vienen de INVIMA y no la tienen, asi que el filtro se autodetecta
        # en vez de forzarse en los dos origenes que comparten esta funcion.
        columna_tipo="TIPO_CODIGO_INTERNO" if "TIPO_CODIGO_INTERNO" in df.columns else None,
        opciones_campo=campos,
        clave_campo=f"{key_prefix}_campos",
    )

    _descarga_diferida(
        "Preparar esta lista (.xlsx)",
        lambda: _exportar_a_bytes(lambda w: visible.to_excel(w, index=False, sheet_name="hallazgos")),
        nombre_archivo,
        f"{key_prefix}_descarga",
    )


def _alerta_desde_advertencia(advertencia: str, severidad: str = "warning") -> tuple[str, str, str]:
    """Parte una advertencia larga en (severidad, titulo corto, detalle largo).

    El titulo es lo que va antes del separador ("--" o su version con raya);
    el resto queda tras el clic del expander. Vivia suelto dentro de la
    pestana de auditoria: se extrajo para que TODAS las pestanas partan las
    advertencias igual -- la de Resumen las volcaba crudas en un banner, que
    es justo lo que _mostrar_tarjetas_alerta existe para evitar.
    """
    separador = " — " if " — " in advertencia else " -- " if " -- " in advertencia else ""
    titulo, _, resto = advertencia.partition(separador) if separador else ("", "", advertencia)
    if not titulo:
        titulo = advertencia if len(advertencia) <= 70 else advertencia[:67] + "..."
    return (severidad, titulo.strip(" *"), resto or advertencia)


def _alerta_fallo_lectura(titulo: str, que_hacer: str, exc: Exception) -> None:
    """Un fallo de lectura de archivo como tarjeta compacta.

    El usuario de negocio ve UNA linea en su idioma; la clase de excepcion y
    el mensaje crudo de la libreria (BadZipFile, ParseError...) quedan tras el
    expander. Pedido explicito del usuario: ese detalle tecnico "no lo debe
    contemplar un usuario". Se conserva -- no se borra -- porque es lo unico
    que permite diagnosticar un archivo dañado cuando alguien reporta el fallo.
    """
    _mostrar_tarjetas_alerta(
        [("error", titulo, f"{que_hacer}\n\nDetalle tecnico: {type(exc).__name__}: {exc}")]
    )


# Campos que se muestran de una coincidencia hallada en el Excel de respaldo:
# los mismos que permiten decidir a mano si el CUM sirve (quien lo titula, si el
# registro sigue vigente y hasta cuando), no la fila cruda de 30 columnas.
_CAMPOS_RESPALDO_CUM = [
    "CODIGO_INTERNO",
    "PRODUCTO",
    "TITULAR",
    "ESTADO_REGISTRO",
    "ESTADO_CUM",
    "FECHA_VENCIMIENTO",
    "PRINCIPIO_ACTIVO",
    "CONCENTRACION",
    "FORMA_FARMACEUTICA",
]


def _consultar_cum_en_respaldo(archivo_invima, codigo_interno: str) -> None:
    """Busca un CUM en el Excel de respaldo cuando la API esta caida.

    Se pinta como un bloque APARTE y rotulado, nunca como si fuera la
    respuesta de la API: el archivo es una foto con fecha y puede estar
    desactualizado, asi que afirmar "vigente en INVIMA" con base en el seria
    justo la decision a ciegas que el proyecto prohibe. El usuario ve que se
    verifico, contra que archivo y de cuando es ese archivo.

    Antes esta salida no existia: sin API la consulta terminaba en "servicio
    no disponible" aunque el respaldo estuviera cargado y pudiera responder.
    """
    st.divider()
    st.caption("Verificación contra el archivo de respaldo (la API no respondió)")
    try:
        df_respaldo = _cargar_invima_desde_archivo(archivo_invima)
    except _ERRORES_ARCHIVO_CORRUPTO as exc:
        _alerta_fallo_lectura(
            "No se pudo leer el archivo de respaldo",
            "El archivo llegó incompleto o dañado, así que tampoco se pudo verificar por ahí.",
            exc,
        )
        return

    codigos = df_respaldo["CODIGO_INTERNO"].astype(str).str.strip()
    coincidencias = df_respaldo[codigos == codigo_interno.strip()]

    corte = ""
    if "FECHA_ACTIVO" in df_respaldo.columns:
        fechas = pd.to_datetime(df_respaldo["FECHA_ACTIVO"], errors="coerce")
        if fechas.notna().any():
            corte = f" — foto con corte al {fechas.max().date()}"

    if coincidencias.empty:
        _mensaje_breve(
            f"**{codigo_interno} no aparece en el archivo de respaldo**{corte}.",
            "Si el registro sanitario es posterior a esa fecha, el archivo no puede confirmarlo. "
            "Hay que reintentar contra la API cuando INVIMA se restablezca.",
            tipo="warning",
            etiqueta="Por qué esto no es concluyente",
        )
        return

    st.success(
        f"**{codigo_interno} sí aparece en el archivo de respaldo**{corte}. "
        "Es un dato de archivo, no una confirmación en vivo de INVIMA."
    )
    columnas = [c for c in _CAMPOS_RESPALDO_CUM if c in coincidencias.columns]
    filtros = [
        columna
        for columna in ("ESTADO_REGISTRO", "ESTADO_CUM", "FORMA_FARMACEUTICA")
        if columna in coincidencias.columns
    ]
    _tabla_filtrable(
        coincidencias,
        columnas_filtro=filtros,
        key_prefix="consulta_respaldo",
        columnas_mostrar=columnas,
        columna_categoria=filtros[0] if filtros else None,
        columna_campo=filtros[1] if len(filtros) > 1 else None,
    )


# Campos del reporte de Gemma Net que responden "como quedo cargado este
# codigo": si esta activo, con que vigencia y con que datos clinicos.
_CAMPOS_GEMANET_CUM = [
    "CODIGO_INTERNO",
    "DESCRIPCION",
    "PRINCIPIO_ACTIVO",
    "CONCENTRACION",
    "FORMA_FARMACEUTICA",
    "ACTIVO",
    "FECHA_INICIO",
    "FECHA_FIN",
    "POS",
]


@st.cache_data(show_spinner=False)
def _cargar_gemanet_desde_archivo(archivo_gemma_net) -> pd.DataFrame:
    """Solo el DataFrame del reporte: la consulta puntual no necesita las
    advertencias ni las lineas omitidas que trae ReporteGemaNet. Cacheado
    porque el archivo ronda las 200.000 filas y la pestaña de consulta se
    usa varias veces seguidas sobre el mismo archivo."""
    return leer_reporte_gemanet(archivo_gemma_net).df


def _consultar_cum_en_gemanet(archivo_gemma_net, codigo_interno: str) -> None:
    """Dice si el codigo YA esta cargado en Gemma Net.

    Es una pregunta DISTINTA de la que responde INVIMA y por eso va en su
    propio bloque rotulado: INVIMA dice si el medicamento es valido y
    vigente; esto dice si ya existe en la plataforma y como quedo. Un codigo
    puede estar cargado y vencido, o vigente y sin cargar.

    Las filas repetidas se muestran TODAS por separado, nunca fusionadas: un
    CODIGO_INTERNO duplicado suele ser un medicamento combinado y unir las
    filas perderia un principio activo (regla del proyecto).
    """
    st.divider()
    st.caption("Estado en el archivo cargado de Gemma Net (¿ya existe en la plataforma?)")
    try:
        df_gemanet = _cargar_gemanet_desde_archivo(archivo_gemma_net)
    except _ERRORES_ARCHIVO_CORRUPTO as exc:
        _alerta_fallo_lectura(
            "No se pudo leer el archivo de Gemma Net",
            "No se pudo comprobar si el código ya está cargado en la plataforma.",
            exc,
        )
        return

    codigos = df_gemanet["CODIGO_INTERNO"].astype(str).str.strip()
    coincidencias = df_gemanet[codigos == codigo_interno.strip()]

    if coincidencias.empty:
        _mensaje_breve(
            f"**{codigo_interno} no está cargado en Gemma Net.**",
            f"No aparece en el archivo exportado ({len(df_gemanet):,} registros). Si INVIMA lo da "
            "por válido, es candidato a cargue.",
            tipo="info",
            etiqueta="Qué significa",
        )
        return

    activos = ""
    if "ACTIVO" in coincidencias.columns:
        marcados = coincidencias["ACTIVO"].astype(str).str.strip().str.upper()
        n_activos = int(marcados.isin({"SI", "S", "1", "TRUE", "SÍ"}).sum())
        activos = f" — {n_activos} de {len(coincidencias)} marcado(s) como ACTIVO"

    if len(coincidencias) > 1:
        _mensaje_breve(
            f"**{codigo_interno} está cargado {len(coincidencias)} veces en Gemma Net**{activos}.",
            "Se muestran todas las filas sin fusionar: un código repetido suele ser un medicamento "
            "combinado, y unirlas perdería un principio activo.",
            tipo="warning",
            etiqueta="Por qué no se fusionan",
        )
    else:
        st.success(f"**{codigo_interno} ya está cargado en Gemma Net**{activos}.")

    columnas = [c for c in _CAMPOS_GEMANET_CUM if c in coincidencias.columns]
    filtros = [
        columna
        for columna in ("ACTIVO", "POS", "FORMA_FARMACEUTICA")
        if columna in coincidencias.columns
    ]
    _tabla_filtrable(
        coincidencias,
        columnas_filtro=filtros,
        key_prefix="consulta_gemanet",
        columnas_mostrar=columnas,
        columna_categoria=filtros[0] if filtros else None,
        columna_campo=filtros[1] if len(filtros) > 1 else None,
    )


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


def _fuente_catalogos(usar_bd: bool):
    """Un booleano y no el objeto en la firma de las funciones cacheadas:
    st.cache_data hashea sus parametros y una fuente de catalogos no es
    hashable. El objeto se construye aca dentro."""
    return FuenteCatalogosConRespaldo() if usar_bd else FuenteCatalogosCSV()


@st.cache_data(show_spinner=False, ttl=180)
def _estado_catalogos_bd() -> tuple[bool, str]:
    """Chequeo liviano y proactivo de si la base responde AHORA, para poder
    avisar antes de correr el proceso completo en vez de fallar a mitad de
    camino -- mismo criterio que `_hay_datos_invima_api` con Socrata."""
    try:
        gemanet_db.consultar(
            "SELECT count(*) FROM administrativo.tb_marca_medicamento", tope_filas=1
        )
    except gemanet_db.ErrorGemaNetDB as exc:
        return False, str(exc)
    return True, ""


@st.cache_data(show_spinner=False, ttl=600)
def _reporte_gemanet_desde_bd():
    """El reporte leido de la base. Cacheado 10 min: son 199.608 filas por
    red y no cambian de un rerun de Streamlit al siguiente."""
    return leer_reporte_gemanet_db()


@st.cache_data(show_spinner=False, persist="disk", max_entries=3)
def _procesar_candidatos(
    df_invima: pd.DataFrame, archivo_gemma_net, usar_bd: bool = False
) -> pd.DataFrame:
    """`@st.cache_data(persist="disk")` a proposito, sobre el mismo llamador
    que antes NO lo llevaba (ver bitacora 2026-08-25): esta funcion ya solo
    se invoca UNA vez por corrida, protegida por
    `session_state["resultado_candidatos"] is None` en `main()` -- ya no en
    cada rerun. Con eso, el costo de hashear `df_invima` (una vez, no en
    cada clic) es insignificante comparado con lo que ahorra: pedido
    explicito del usuario (2026-08-25) de no repetir el cruce completo
    (~1 minuto) si los archivos de origen no cambiaron, ni entre corridas de
    la misma sesion ni al reiniciar el servidor de Streamlit. `persist="disk"`
    escribe la cache en `~/.streamlit/cache` (fuera del repo, no requiere
    `.gitignore`); la clave es el HASH DEL CONTENIDO de `df_invima` y
    `archivo_gemma_net`, no el nombre de archivo ni la fecha -- si el
    contenido cambia una coma, la clave cambia y se recalcula. Esa es la
    "validacion de que no hubo modificaciones" que pidio el usuario: no hace
    falta violar la regla de degradacion explicita de `CLAUDE.md`, el hash
    de contenido ES la validacion, no una suposicion. `max_entries=3`
    limita cuantas corridas distintas se retienen (evita crecer sin limite
    si se alterna entre fuentes)."""
    return procesar_desde_catalogo_invima(
        df_invima, archivo_gemma_net, fuente_catalogos=_fuente_catalogos(usar_bd)
    )


@st.cache_data(show_spinner=False)
def _clasificar_universo_invima(df_invima: pd.DataFrame) -> pd.DataFrame:
    return universo_invima_clasificado(df_invima)


# Streamlit reejecuta TODO el script en cada interaccion de CUALQUIER widget
# de la pagina (ej. cambiar de sub-vista en Cargue). Estas cuatro funciones
# reciben `ReglasNegocio` (un dict grande de dataclasses) y/o la malla de
# referencia (26 MB) como argumento -- medido el 2026-08-25: Streamlit
# tardaba 1,5-3,5 s SOLO en hashear esos argumentos en cada rerun para
# decidir si habia acierto de `@st.cache_data`, aunque el resultado nunca
# cambia dentro de la misma corrida. Por eso ya NO llevan el decorador: se
# llaman a traves de `_derivado()` (ver mas abajo), que calcula una sola vez
# por corrida y guarda en `session_state` -- mismo principio que
# `resultado_candidatos`/`auditoria_coherencia`, generalizado.
def _leer_malla_referencia_cacheada(archivo_malla_referencia) -> pd.DataFrame:
    return leer_malla_referencia(archivo_malla_referencia)


def _derivar_reglas_negocio_cacheada(malla_referencia: pd.DataFrame) -> ReglasNegocio:
    return derivar_reglas_negocio(malla_referencia)


def _evaluar_candidatos_cargue_cacheado(resultado: pd.DataFrame, reglas: ReglasNegocio) -> pd.DataFrame:
    return evaluar_candidatos_cargue(resultado, reglas)


def _armar_estructura_cargue_cacheada(resultado: pd.DataFrame, reglas: ReglasNegocio) -> pd.DataFrame:
    return armar_estructura_cargue(resultado, reglas)


def _preparar_filas_cargue_cacheada(resultado: pd.DataFrame, reglas: ReglasNegocio) -> pd.DataFrame:
    return preparar_filas_cargue(resultado, reglas)


# Claves que describen la corrida actual (candidatos, auditoria, y todo lo
# derivado de la malla de referencia). `_derivado` las calcula una sola vez;
# `_limpiar_derivados` es el UNICO lugar que las borra, para no depender de
# acordarse de sumar un `pop` suelto por cada clave nueva -- ese fue
# exactamente el riesgo senalado en el diagnostico de rendimiento del
# 2026-08-25: una clave olvidada deja en pantalla el resultado de la fuente
# anterior sin avisar, la suposicion silenciosa que prohibe CLAUDE.md.
_CLAVES_DERIVADAS_DE_LA_CORRIDA = (
    "resultado_candidatos",
    "df_invima_cache",
    "auditoria_coherencia",
    "auditoria_alertas_carga",
    "derivado_malla_referencia",
    "derivado_reglas",
    "derivado_evaluados",
    "derivado_df_estructura",
    "derivado_df_cargue",
)


def _derivado(clave: str, calcular):
    """Calcula `calcular()` una sola vez por corrida y lo guarda en
    `session_state[clave]`; en los reruns siguientes lo devuelve tal cual,
    sin volver a hashear argumentos grandes."""
    if clave not in st.session_state:
        st.session_state[clave] = calcular()
    return st.session_state[clave]


def _limpiar_derivados() -> None:
    for clave in _CLAVES_DERIVADAS_DE_LA_CORRIDA:
        st.session_state.pop(clave, None)
    # Las opciones de filtro y los resultados de filtrado cacheados (ver
    # _opciones_filtro y el cache de _filtros_estandar) usan claves
    # dinamicas -- no caben en la tupla fija de arriba. Se purgan por
    # prefijo para que una corrida nueva no herede opciones ni resultados
    # calculados sobre datos de la corrida anterior.
    prefijos_dinamicos = (_PREFIJO_OPCIONES_FILTRO, _PREFIJO_FILTRO_RESULTADO)
    for clave in [
        clave for clave in st.session_state if clave.startswith(prefijos_dinamicos)
    ]:
        del st.session_state[clave]


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


@st.cache_data(show_spinner=False, persist="disk", max_entries=3)
def _auditar_coherencia(
    df_invima: pd.DataFrame,
    archivo_gemma_net,
    df_invima_vencidos: pd.DataFrame | None,
    df_invima_otros_estados: pd.DataFrame | None = None,
    df_invima_renovacion: pd.DataFrame | None = None,
    usar_bd: bool = False,
) -> pd.DataFrame:
    """`@st.cache_data(persist="disk")` a proposito -- mismo motivo que
    `_procesar_candidatos` (ver su docstring) y el comentario junto a donde
    se llama en `main()`: esta funcion ya solo corre UNA vez por corrida,
    protegida por `session_state["auditoria_coherencia"] is None`. Con eso,
    el costo de cache (hashear los DataFrames de entrada, reconstruir 535 MB
    en un acierto) se paga como mucho una vez por sesion nueva, no en cada
    clic -- y `persist="disk"` evita repetir la auditoria completa (varios
    minutos) entre sesiones o reinicios del servidor si los archivos de
    origen no cambiaron. `max_entries=3` evita que la cache crezca sin
    limite si se alterna entre fuentes distintas."""
    return auditar_coherencia_gemanet(
        df_invima,
        archivo_gemma_net,
        df_invima_vencidos,
        df_invima_otros_estados=df_invima_otros_estados,
        df_invima_renovacion=df_invima_renovacion,
        fuente_catalogos=_fuente_catalogos(usar_bd),
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


def _seccion_resumen_metricas(
    resultado: pd.DataFrame, total: int, candidatos: int, ya_existe: int, cuarentena: int
) -> None:
    """Sub-vista "Resumen": las 4 metricas y, si aplica, las lineas que no se
    pudieron leer del archivo de Gemma Net. Separada de "Cómo se resolvió" y
    "Detalle por registro" -- pedido explicito del usuario: verlas todas
    juntas en una sola pantalla "agota la vista y confunde"."""
    advertencias_resumen = [
        _alerta_desde_advertencia(a) for a in resultado.attrs.get("advertencias", [])
    ]
    if advertencias_resumen:
        _mostrar_tarjetas_alerta(advertencias_resumen)

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
            # Ya estamos dentro de un expander: se acorta en sitio, sin anidar otro.
            st.write(
                "Medicamentos cuyo estado en Gemma Net no se pudo confirmar del todo: el "
                "archivo trae un separador de más dentro de un texto, así que el "
                "CODIGO_INTERNO se recuperó por posición. **ESTADO** dice qué se determinó."
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
            _tabla_filtrable(
                df_omitidas,
                columnas_filtro=["ESTADO"],
                key_prefix="lineas_omitidas",
                columna_categoria="ESTADO",
            )

    c1, c2, c3, c4 = st.columns(4)
    # "Total filas vigentes" NO: el archivo de Vigentes trae 101.183 filas y
    # esta tarjeta muestra 47.767. No estaba mal calculada -- estaba mal
    # nombrada, y quien comparara con el archivo pensaria que se perdieron
    # 53.416 filas. Lo que cuenta es el universo que llego a evaluarse: los
    # que pasaron los 4 filtros de clasificacion.
    c1.metric(
        "Registros evaluados",
        f"{total:,}",
        help="Los registros de INVIMA que pasaron los cuatro filtros (rol, estado del "
        "CUM, vigencia del registro y muestra médica) y llegaron a cruzarse contra "
        "Gemma Net. NO es el total del archivo de INVIMA: ese es mayor, y el desglose "
        "completo está en la sub-vista «Detalle por registro».",
    )
    c2.metric(
        "Candidatos a crear",
        f"{candidatos:,}",
        f"{candidatos / total:.1%}",
        help="Están en INVIMA, cumplen todo, y su código no existe todavía en Gemma Net.",
    )
    c3.metric(
        "Ya en Gemma Net",
        f"{ya_existe:,}",
        f"{ya_existe / total:.1%}",
        help="Su código ya está cargado en la plataforma: no hay nada que crear.",
    )
    c4.metric(
        "En cuarentena",
        f"{cuarentena:,}",
        f"{cuarentena / total:.1%}",
        delta_color="inverse",
        help="No se pudo decidir con certeza y se aparta para que una persona resuelva. "
        "Cero es el mejor resultado posible: significa que el proceso pudo decidir todos "
        "los casos.",
    )
    st.caption(
        f"Las tres últimas son excluyentes y suman la primera: "
        f"{ya_existe:,} + {candidatos:,} + {cuarentena:,} = {total:,}."
    )


def _seccion_resumen_metodos(resultado: pd.DataFrame, total: int) -> None:
    """Sub-vista "Cómo se resolvió": las dos tablas de metodo (unidad/marca),
    apiladas y no lado a lado -- en columnas angostas se volvian ilegibles."""
    st.write("**Cómo se resolvió la UNIDAD DE MEDIDA**")
    _tabla_metodos(st, resultado["unidad_metodo"], total)
    st.divider()
    st.write("**Cómo se resolvió la MARCA**")
    _tabla_metodos(st, resultado["marca_metodo"], total)
    _mensaje_breve(
        "Estas dos tablas no son un dato de negocio: son **el nivel de confianza del "
        "proceso**.",
        "INVIMA escribe la marca y la unidad como texto; Gemma Net las guarda como "
        "código. Hay que traducir, y estas tablas dicen cómo se logró cada traducción. "
        "Decir «resolví 47.767 unidades» sin decir cómo no significa nada; saber que la "
        "gran mayoría fue coincidencia exacta y solo unas pocas por aproximación es lo "
        "que permite confiar en el resultado.",
        etiqueta="Por qué importa esto",
    )


def _seccion_resumen_detalle_registro(df_invima: pd.DataFrame) -> None:
    """Sub-vista "Detalle por registro": por qué cada fila de INVIMA sí o no
    llegó a ser candidato, con la tabla completa del universo clasificado."""
    st.write("**Por qué cada registro de INVIMA sí o no llegó a ser candidato**")
    _mensaje_breve(
        "Ningún registro se descarta en silencio.",
        "Verificable contra el archivo/API de INVIMA: cada registro queda clasificado con el "
        "campo puntual que no cumplió — rol distinto de FABRICANTE, CUM inactivo, registro no "
        "vigente, o muestra médica.",
        etiqueta="Cómo se clasifica cada uno",
    )
    with st.spinner("Clasificando el universo de INVIMA..."):
        universo_clasificado = _clasificar_universo_invima(df_invima)
    conteos_clasificacion = universo_clasificado["CLASIFICACION_CREACION"].value_counts()
    cols_clasif = st.columns(len(CLASIFICACIONES_CREACION))
    for col, etiqueta in zip(cols_clasif, CLASIFICACIONES_CREACION, strict=True):
        n_clasif = int(conteos_clasificacion.get(etiqueta, 0))
        col.metric(
            _ETIQUETA_CLASIFICACION_CREACION.get(etiqueta, etiqueta),
            f"{n_clasif:,}",
            help=_AYUDA_CLASIFICACION_CREACION.get(etiqueta),
        )
    st.caption(
        f"Cada registro recibe la etiqueta del **primer** filtro que incumple, no de "
        f"todos. Por eso las cinco suman el archivo completo "
        f"({int(conteos_clasificacion.sum()):,} filas) en vez de solaparse."
    )
    # Un cero permanente y sin explicacion invita a pensar que la funcion
    # esta rota. No lo esta: es verdadero por construccion.
    if int(conteos_clasificacion.get("registro_no_vigente", 0)) == 0:
        _mensaje_breve(
            "**«Registro no vigente» da cero, y es lo esperado.**",
            "El archivo que se está usando ES el listado de Vigentes de INVIMA: todas sus "
            "filas tienen, sin excepción, el registro sanitario vigente. Ese filtro no "
            "puede encontrar nada aquí — es verdadero por construcción, no una función "
            "que falle. Se conserva porque el mismo criterio sí encuentra casos en los "
            "otros tres listados de INVIMA.",
            etiqueta="Por qué",
        )
    _tabla_filtrable(
        universo_clasificado,
        columnas_filtro=["CLASIFICACION_CREACION"],
        key_prefix="universo_invima",
        columnas_mostrar=[
            c
            for c in [
                "EXPEDIENTE",
                # CONSECUTIVO va pegado al EXPEDIENTE porque juntos son la
                # llave con la que INVIMA identifica cada fila. Sin el, un
                # expediente con varias presentaciones muestra filas
                # identicas en pantalla (caso real: expediente 3521, 9
                # filas de "ALERCET JARABE" indistinguibles) y no hay como
                # localizarlas a mano en el archivo oficial.
                "CONSECUTIVO",
                "CODIGO_INTERNO",
                "PRODUCTO",
                "TITULAR",
                "ESTADO_CUM",
                "TIPO_ROL",
                "ESTADO_REGISTRO",
                "CLASIFICACION_CREACION",
            ]
            if c in universo_clasificado.columns
        ],
        columna_categoria="CLASIFICACION_CREACION",
        # Mismo diccionario que ya usan las tarjetas de metricas arriba, no
        # _etiqueta_valor_filtro (generico): "candidato" significa algo
        # distinto en CLASIFICACION_CREACION que en la decision de cargue,
        # y confundirlos fue el bug reportado por el usuario (ver
        # _previsualizacion_tabla).
        formato_categoria=lambda v: _ETIQUETA_CLASIFICACION_CREACION.get(str(v), _legible(v)),
    )


def main() -> None:
    st.set_page_config(page_title="Gemma CUM Loader", layout="wide")
    tokens = _cargar_tokens()
    _inyectar_css(tokens)
    _barra_superior()

    # Una vez procesado, este bloque completo deja de dibujarse -- ni
    # siquiera como expander colapsado, que seguia ocupando una fila entera.
    # `editando_fuentes` lo reabre sin tocar `procesado`: si se pusiera
    # `procesado=False` para volver a mostrarlo se perderia la auditoria ya
    # calculada (session_state["auditoria_coherencia"], varios minutos sobre
    # ~200.000 filas -- ver el comentario junto a esa clave mas abajo).
    procesado_ya = st.session_state.get("procesado", False)
    editando_fuentes = st.session_state.get("editando_fuentes", False)
    mostrar_seleccion_fuentes = not procesado_ya or editando_fuentes

    if procesado_ya and not editando_fuentes:
        # Solo una linea, no un panel: la fuente ya elegida sigue siendo
        # visible (degradacion explicita, no silenciosa) pero sin el espacio
        # del expander completo. Revertido al cuerpo principal a pedido
        # explicito del usuario (2026-08-26): lo habia movido al sidebar
        # pensando que ahi seguia leyendose como "el recuadro", pero el
        # usuario aclaro que queria justo esto de vuelta arriba de cada
        # seccion -- lo que debia desaparecer era el formulario de carga de
        # archivos (el expander "Archivos de entrada"), no este resumen.
        _usar_api_prev, _archivo_invima_prev, _archivo_gn_prev, _archivo_malla_prev, _usar_bd_prev, _usar_det_prev = (
            st.session_state["archivos"]
        )
        col_fuente, col_boton_fuente = st.columns([5, 1])
        col_fuente.caption(
            "Fuente: "
            + ("INVIMA API" if _usar_api_prev else "INVIMA archivo")
            + " · "
            + ("Gemma Net en vivo" if _usar_bd_prev else "Gemma Net archivos locales")
        )
        if col_boton_fuente.button("Cambiar fuente de datos", key="btn_cambiar_fuente"):
            st.session_state["editando_fuentes"] = True
            st.rerun()
        usar_api_invima = _usar_api_prev
        archivo_invima = _archivo_invima_prev
        archivo_gemma_net = _archivo_gn_prev
        archivo_malla_referencia = _archivo_malla_prev
        usar_bd_catalogos = _usar_bd_prev
        usar_detectados = _usar_det_prev

    if mostrar_seleccion_fuentes:
        if editando_fuentes:
            st.info(
                "Los resultados de abajo son de la corrida anterior — presiona "
                "\"Procesar\" para rehacerlos con la fuente nueva, o \"Cancelar\" "
                "para dejar todo como estaba."
            )
        with st.expander("Archivos de entrada", expanded=True):
            # Autodescubrimiento en data/: la meta es que nadie tenga que elegir
            # archivos en cada corrida. Se muestran para poder confirmar que son
            # los correctos (pedido explicito: automatizar la seleccion sin
            # perder la verificacion), y se puede desactivar para subirlos a mano.
            detectados = descubrir_todo()
            usar_detectados = False
            if detectados:
                usar_detectados = st.checkbox(
                    f"Usar los {len(detectados)} archivos detectados en `data/`",
                    value=True,
                    key="usar_archivos_detectados",
                )
                _panel_archivos_detectados(detectados)
            elif CARPETA_DATOS.is_dir():
                st.caption(f"No se reconoció ningún archivo de entrada en `{CARPETA_DATOS}`.")
            else:
                st.caption(f"La carpeta `{CARPETA_DATOS}` no existe.")

            # Sin radio de fuente: verificado el 2026-08-20, los 11 datasets de
            # medicamentos de datos.gov.co (los 4 oficiales, sus copias "A" y
            # varios espejos) devuelven CERO filas. Obligar a elegir entre una
            # fuente que funciona y otra que no es una pregunta con una sola
            # respuesta valida. Se muestra la que se va a usar y se puede cambiar.
            archivo_invima = None
            usar_api_invima = False
            detectado_invima = detectados.get("invima_vigentes") if usar_detectados else None

            if detectado_invima is not None:
                archivo_invima = str(detectado_invima.ruta)
                # Sin df: aqui solo se muestra la fecha de publicacion de INVIMA.
                # El corte del archivo local se calcula en la auditoria, donde el
                # catalogo ya esta cargado (ver _avisar_desactualizacion_invima).
                _avisar_desactualizacion_invima()
                if st.toggle("Usar la API de INVIMA en vez del archivo", value=False, key="forzar_api"):
                    usar_api_invima = True
                    archivo_invima = None
            else:
                with st.spinner("Verificando si INVIMA tiene datos disponibles..."):
                    hay_api = _hay_datos_invima_api()
                if hay_api:
                    usar_api_invima = True
                    st.caption(_indicador_token(socrata.estado_token()))
                else:
                    _mensaje_breve(
                        "INVIMA no está publicando datos en línea — sube el listado de Vigentes.",
                        "Se comprobaron los conjuntos de datos oficiales de INVIMA en datos.gov.co y "
                        "todos vienen sin registros; es una interrupción del lado de ellos, no de "
                        "esta aplicación. Con el listado descargado el trabajo continúa igual. El "
                        "archivo que subas queda guardado y en la próxima corrida se carga solo.",
                        tipo="warning",
                        etiqueta="Qué pasó con la API",
                    )
                    subido = st.file_uploader(
                        "Listado Código Único de Medicamentos Vigentes (.xlsx)",
                        type=["xlsx"],
                        key="invima_vigentes_manual",
                    )
                    if subido is not None:
                        archivo_invima = _recordar_subida(subido)

            # Catalogos (marca, unidad, modelo de servicio): la base de Gemma Net
            # es la fuente autoritativa; los CSV son una copia. Verificado el
            # 2026-08-20: leer en vivo elimina los 24 hallazgos de "codigo
            # huerfano" de la auditoria (24 -> 0), porque el CSV de unidad no
            # tiene el codigo 10001025.
            estado_bd = gemanet_db.estado_conexion()
            # Un solo selector para TODO lo que viene de Gemma Net -- catalogos y
            # medicamentos. Antes gobernaba solo los catalogos y los medicamentos
            # se leian de la base igual, hubiera elegido el usuario lo que
            # hubiera elegido: la aplicacion contradecia en silencio la eleccion
            # que ella misma acababa de pedir.
            fuente_catalogos_elegida = st.selectbox(
                "Datos de Gemma Net (medicamentos y catálogos) — fuente",
                ["Base de datos de Gemma Net (en vivo)", "Archivos locales"],
                index=0 if estado_bd.configurado else 1,
                key="fuente_catalogos_elegida",
                help="La base es la fuente oficial y además es más rápida. Los archivos locales "
                "(export de Gemma Net + catálogos CSV) son una copia que puede quedar "
                "desactualizada; sirven cuando no hay credenciales o la base no responde.",
            )
            usar_bd_catalogos = fuente_catalogos_elegida.startswith("Base")
            if usar_bd_catalogos:
                if not estado_bd.configurado:
                    _mensaje_breve(
                        "No hay credenciales configuradas para la base de Gemma Net.",
                        f"Se usará el CSV local. Configura {gemanet_db.NOMBRE_VARIABLE_ENTORNO} "
                        "en el entorno para leer los catálogos en vivo.",
                        tipo="warning",
                        etiqueta="Cómo configurarlas",
                    )
                    usar_bd_catalogos = False
                else:
                    with st.spinner("Verificando la conexión con la base de Gemma Net..."):
                        bd_ok, detalle_bd = _estado_catalogos_bd()
                    if bd_ok:
                        st.caption(f"🟢 Catálogos en vivo — {estado_bd.resumen}")
                    else:
                        _mensaje_breve(
                            "La base de Gemma Net no responde — se usará el CSV local.",
                            f"La corrida sigue, pero con catálogos que pueden estar "
                            f"desactualizados.\n\nDetalle tecnico: {detalle_bd}",
                            tipo="warning",
                            etiqueta="Qué significa",
                        )

            # Solo se pide lo que NO se pudo resolver solo. Cada cargador que
            # desaparece es una eleccion menos por corrida, que es el objetivo.
            archivo_gemma_net = None
            archivo_malla_referencia = None
            faltantes = []

            # Los medicamentos salen de la BASE cuando hay credenciales: leerlos de
            # ahi tarda 9 s contra 24 s del Excel y elimina defectos que solo
            # existen en el export -- 131 filas con columnas corridas, 11
            # duplicados falsos y 18 valores "fuera de dominio", todos medidos.
            # `usar_bd_catalogos` y no `estado_bd.configurado`: si el usuario pidio
            # archivos locales, se respeta -- aunque haya credenciales y aunque la
            # base sea mejor fuente. Ya paso por el respaldo automatico de arriba,
            # asi que aqui llegar en False significa o que lo eligio o que la base
            # fallo, y en el segundo caso ya se aviso.
            if usar_bd_catalogos:
                try:
                    with st.spinner("Leyendo los medicamentos de la base de Gemma Net..."):
                        archivo_gemma_net = _reporte_gemanet_desde_bd()
                    st.caption(
                        f"🟢 {len(archivo_gemma_net.df):,} medicamentos leídos de la base "
                        "— no hace falta el archivo exportado."
                    )
                except gemanet_db.ErrorGemaNetDB as exc:
                    _mensaje_breve(
                        "No se pudo leer los medicamentos de la base — se usará el archivo.",
                        "La corrida sigue con el export de Gemma Net.\n\n"
                        f"Detalle tecnico: {exc}",
                        tipo="warning",
                        etiqueta="Qué pasó",
                    )
            if archivo_gemma_net is None:
                if usar_detectados and "reporte_gemanet" in detectados:
                    archivo_gemma_net = str(detectados["reporte_gemanet"].ruta)
                else:
                    faltantes.append("reporte_gemanet")
            if usar_detectados and "estructura_cargue" in detectados:
                archivo_malla_referencia = str(detectados["estructura_cargue"].ruta)
            else:
                faltantes.append("estructura_cargue")

            if faltantes:
                columnas_faltantes = st.columns(len(faltantes))
                for col, tipo in zip(columnas_faltantes, faltantes, strict=True):
                    if tipo == "reporte_gemanet":
                        archivo_gemma_net = col.file_uploader(
                            "Archivo exportado por Gemma Net (.xlsx o .txt)",
                            type=["xlsx", "txt", "csv"],
                            help="Mantenimientos > Basicas Atencion > Medicamentos > Crear Masivos "
                            "> Exportar. Se usa para saber que codigos ya estan cargados.",
                        )
                    else:
                        archivo_malla_referencia = col.file_uploader(
                            "Estructura Cargue Medicamentos (.xlsx) — opcional",
                            type=["xlsx"],
                            help="Referencia para los campos de regla de negocio del cargue final "
                            "(edad, copagos, modelo/nivel de servicio) que no existen en INVIMA. "
                            "Debe traer la hoja 'plantilla (2)'.",
                        )

        listo_para_procesar = archivo_gemma_net is not None and (
            usar_api_invima or archivo_invima is not None
        )
        col_procesar, col_cancelar = st.columns([1, 1])
        if col_procesar.button("Procesar", type="primary", disabled=not listo_para_procesar):
            st.session_state["procesado"] = True
            st.session_state["editando_fuentes"] = False
            st.session_state["archivos"] = (
                usar_api_invima,
                archivo_invima,
                archivo_gemma_net,
                archivo_malla_referencia,
                usar_bd_catalogos,
                usar_detectados,
            )
            _limpiar_derivados()
            st.rerun()
        if editando_fuentes and col_cancelar.button("Cancelar"):
            st.session_state["editando_fuentes"] = False
            st.rerun()

    if not st.session_state.get("procesado"):
        st.info("Selecciona los archivos necesarios y presiona Procesar.")
        return

    (
        usar_api_invima,
        archivo_invima,
        archivo_gemma_net,
        archivo_malla_referencia,
        usar_bd_catalogos,
        usar_detectados,
    ) = st.session_state["archivos"]

    # Ver la nota junto al boton de auditoria: un panel visible en el sitio
    # en vez de un texto chico que puede quedar fuera de la pantalla.
    # Se guarda el objeto de estado para poder colapsarlo al terminar --
    # `expanded=True` fijo dejaba este bloque ocupando espacio permanente en
    # la parte de arriba de la pantalla incluso despues de terminar, en CADA
    # rerun de Streamlit (se repite en cada clic aunque el calculo interno
    # este cacheado). Pedido explicito del usuario: que un progreso que ya
    # termino no seguir ocupando pantalla.
    #
    # Bloqueado detras de `session_state`, igual que la auditoria mas abajo,
    # y NO solo detras de `@st.cache_data`: medido el 2026-08-25, el cache de
    # Streamlit necesita HASHEAR `df_invima` y `archivo_gemma_net.df` (dos
    # DataFrames de ~200.000 filas) en CADA rerun para decidir si hay
    # acierto de cache -- ~0,07 s cada uno sobre un DataFrame comparable,
    # ~150 ms combinados, en CADA clic de cualquier filtro o pestana de toda
    # la aplicacion, no solo al presionar Procesar. Guardar el resultado ya
    # calculado en `session_state` evita ese hasheo repetido; se limpia al
    # presionar Procesar (ver el `pop` junto al boton, unas lineas arriba).
    if st.session_state.get("resultado_candidatos") is None:
        _status_cruce = st.status(
            "Cruzando el catálogo de INVIMA contra Gemma Net — puede tardar unos minutos.",
            expanded=True,
        )
        with _status_cruce:
            if usar_api_invima:
                try:
                    df_invima = _cargar_invima_desde_api()
                except socrata.ErrorSocrata as exc:
                    _alerta_fallo_lectura(
                        "No se pudo sincronizar el catálogo de INVIMA",
                        "Mientras se resuelve, usa el Excel de respaldo (\"Subir archivo Excel\" "
                        "en Archivos de entrada) para no bloquear la corrida.",
                        exc,
                    )
                    st.stop()
            else:
                try:
                    df_invima = _cargar_invima_desde_archivo(archivo_invima)
                except _ERRORES_ARCHIVO_CORRUPTO as exc:
                    _alerta_fallo_lectura(
                        "El archivo Excel de INVIMA llegó dañado",
                        "El archivo llegó incompleto o dañado; no es un problema de esta "
                        "aplicación.\n\nPrueba: (1) vuelve a descargarlo desde invima.gov.co por "
                        "si la copia local quedó corrupta, (2) ábrelo primero en Excel en tu "
                        "computador para confirmar que abre bien antes de subirlo aquí, (3) si es "
                        "muy grande, revisa que la subida haya terminado por completo (una "
                        "conexión inestable puede cortarla a mitad de camino) y vuelve a intentar "
                        "la subida.",
                        exc,
                    )
                    st.stop()
            try:
                resultado = _procesar_candidatos(df_invima, archivo_gemma_net, usar_bd_catalogos)
            except _ERRORES_ARCHIVO_CORRUPTO as exc:
                _alerta_fallo_lectura(
                    "El archivo exportado de Gemma Net llegó dañado",
                    "El archivo llegó incompleto o dañado.\n\nPrueba: vuelve a exportarlo desde "
                    "Gemma Net (Mantenimientos > Basicas Atencion > Medicamentos > Crear Masivos > "
                    "Exportar) y súbelo de nuevo — si es un archivo grande, confirma que la subida "
                    "haya terminado por completo antes de presionar Procesar.",
                    exc,
                )
                st.stop()
        _status_cruce.update(
            label=f"Catálogo de INVIMA cruzado con Gemma Net — {len(resultado):,} registros evaluados.",
            state="complete",
            expanded=False,
        )
        st.session_state["resultado_candidatos"] = resultado
        st.session_state["df_invima_cache"] = df_invima

    resultado = st.session_state["resultado_candidatos"]
    df_invima = st.session_state["df_invima_cache"]

    # La auditoria corre al ARRANCAR, no detras de un boton.
    #
    # Es el calculo mas pesado (199.611 medicamentos contra cuatro listados de
    # INVIMA) y del que cuelgan tres secciones: la propia auditoria, el
    # diagnostico por campo y las novedades de vigencia. Dejarla tras un boton
    # obligaba a esperarla al entrar a cada una, y a repetir la espera si se
    # perdia el resultado.
    #
    # El RESULTADO se guarda en `session_state`, no se lee de ahi el
    # `st.cache_data` de `_auditar_coherencia`: dentro de UN rerun, leer de
    # `session_state` es gratis (el objeto vivo, sin copiar) contra los 0,73 s
    # medidos el 2026-08-25 de reconstruir el DataFrame de 535 MB desde la
    # cache en cada acierto. Por eso `_auditar_coherencia` solo se llama
    # detras del `if session_state.get(...) is None` de abajo -- una vez por
    # corrida, no en cada clic.
    #
    # Pero SI conviene que esa unica llamada por corrida pase por
    # `@st.cache_data(persist="disk")` (ver la funcion): pedido explicito del
    # usuario (2026-08-25) de no repetir la auditoria completa (varios
    # minutos) si los archivos de origen no cambiaron entre una corrida y la
    # siguiente, incluso reiniciando el servidor. Los 0,73 s de reconstruir
    # desde la cache se pagan UNA vez al entrar a una sesion nueva, no en
    # cada rerun -- sigue siendo insignificante contra los minutos que
    # ahorra.
    # Las rutas de los 3 auxiliares se resuelven ACA, antes de la auditoria, y
    # no en la pestana de cargue -- que es donde estaban y donde se vuelven a
    # asignar mas abajo.
    #
    # Bug real (2026-08-25): la auditoria pasó a correr al arrancar, pero
    # `archivo_invima_vencidos` seguia creandose ~800 lineas mas abajo. En
    # Python una variable asignada en cualquier punto de una funcion es local
    # a TODA la funcion, asi que la rama de archivo reventaba con
    # UnboundLocalError antes de llegar a crearla.
    #
    # No se inicializan en None: eso haria correr la auditoria SIN los tres
    # listados y todo caeria en "sin correspondencia" -- una degradacion
    # silenciosa, que es justo lo que el proyecto prohibe. Se resuelven con la
    # misma deteccion de `data/` que usa el bloque de mas abajo.
    _auxiliares = descubrir_todo() if usar_detectados else {}
    archivo_invima_vencidos = _ruta_detectada(_auxiliares, "invima_vencidos")
    archivo_invima_otros_estados = _ruta_detectada(_auxiliares, "invima_otros_estados")
    archivo_invima_renovacion = _ruta_detectada(_auxiliares, "invima_renovacion")

    if st.session_state.get("auditoria_coherencia") is None:
        # st.status y no st.spinner: el spinner es un texto chico que puede
        # quedar fuera de la parte visible de la pantalla, lejos del boton
        # que se acaba de pulsar. Quien no ve respuesta vuelve a pulsar, y
        # en una aplicacion que rehace la pantalla entera en cada
        # interaccion eso reinicia el trabajo en curso. `st.status` se
        # dibuja AQUI, justo bajo el boton, y se queda visible al terminar.
        _status_auditoria = st.status(
            "Auditando el catálogo completo contra INVIMA — puede tardar varios minutos.",
            expanded=True,
        )
        with _status_auditoria:
            st.write("Leyendo los listados de INVIMA y los medicamentos de Gemma Net…")
            df_invima_vencidos = None
            df_invima_otros_estados = None
            df_invima_renovacion = None
            # Se acumulan en vez de pintarse aqui mismo: asi las
            # degradaciones de carga salen en la MISMA rejilla de tarjetas
            # que el resto de alertas de la auditoria, y no como banners
            # sueltos encima del resultado.
            alertas_carga: list[tuple[str, str, str]] = []
            if usar_api_invima:
                for etiqueta, dataset, destino in [
                    ("Vencidos", DATASET_CUM_VENCIDOS, "vencidos"),
                    ("Otros Estados", DATASET_CUM_OTROS_ESTADOS, "otros_estados"),
                    ("Trámite de Renovación", DATASET_CUM_RENOVACION, "renovacion"),
                ]:
                    try:
                        valor = _cargar_invima_desde_api(dataset)
                    except socrata.ErrorSocrata as exc:
                        alertas_carga.append(
                            (
                                "warning",
                                f"Sin el dataset de {etiqueta}",
                                (
                                    "La auditoría sigue, pero sin poder distinguir "
                                    f"\"{etiqueta.lower()}\" de \"sin correspondencia\" en esta "
                                    f"corrida.\n\nDetalle tecnico: {exc}"
                                ),
                            )
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
                        alertas_carga.append(
                            (
                                "warning",
                                "No se pudo leer el archivo de Vencidos",
                                (
                                    "La auditoría sigue, pero sin poder distinguir \"vencido\" "
                                    "de \"sin correspondencia\" en esta corrida.\n\n"
                                    f"Detalle tecnico: {type(exc).__name__}: {exc}"
                                ),
                            )
                        )
                if archivo_invima_otros_estados is not None:
                    try:
                        df_invima_otros_estados = _cargar_invima_otros_estados_desde_archivo(
                            archivo_invima_otros_estados
                        )
                    except (*_ERRORES_ARCHIVO_CORRUPTO, ValueError) as exc:
                        alertas_carga.append(
                            (
                                "warning",
                                "No se pudo leer el archivo de Otros Estados",
                                (
                                    "La auditoría sigue, pero sin poder distinguir ese caso de "
                                    "\"sin correspondencia\" en esta corrida.\n\n"
                                    f"Detalle tecnico: {type(exc).__name__}: {exc}"
                                ),
                            )
                        )
                if archivo_invima_renovacion is not None:
                    try:
                        df_invima_renovacion = _cargar_invima_renovacion_desde_archivo(
                            archivo_invima_renovacion
                        )
                    except (*_ERRORES_ARCHIVO_CORRUPTO, ValueError) as exc:
                        alertas_carga.append(
                            (
                                "warning",
                                "No se pudo leer el archivo de Trámite de Renovación",
                                (
                                    "La auditoría sigue, pero sin poder distinguir ese caso de "
                                    "\"sin correspondencia\" en esta corrida.\n\n"
                                    f"Detalle tecnico: {type(exc).__name__}: {exc}"
                                ),
                            )
                        )
            auditoria = _auditar_coherencia(
                df_invima,
                archivo_gemma_net,
                df_invima_vencidos,
                df_invima_otros_estados=df_invima_otros_estados,
                df_invima_renovacion=df_invima_renovacion,
                usar_bd=usar_bd_catalogos,
            )
        _status_auditoria.update(
            label=f"Auditoría completa — {len(auditoria):,} medicamentos revisados contra INVIMA.",
            state="complete",
            expanded=False,
        )
        st.session_state["auditoria_coherencia"] = auditoria
        # Junto con la auditoria, no como variable local: Streamlit
        # reejecuta el script entero en cada interaccion (cambiar de
        # pestana, mover un filtro) y en esa pasada el boton NO esta
        # pulsado, asi que este bloque no corre. Leerlas mas abajo como
        # variable local reventaba con UnboundLocalError apenas el usuario
        # tocaba cualquier cosa despues de auditar. Van pegadas a la
        # auditoria porque describen ESA corrida y no la sesion.
        st.session_state["auditoria_alertas_carga"] = alertas_carga
        # Aqui el catalogo ya esta en memoria: calcular su corte no cuesta
        # nada. Saber contra que fecha se audito es parte del resultado.
        _avisar_desactualizacion_invima(df_invima)

    auditoria = st.session_state.get("auditoria_coherencia")

    # NAVEGACION LATERAL, no st.tabs -- y la razon es de rendimiento, no de
    # estetica. Streamlit ejecuta el cuerpo de TODAS las pestañas en cada
    # interaccion: las pestañas solo ocultan del lado del navegador. Con las
    # seis secciones eso eran 1.270 lineas por cada clic, incluido volver a
    # cruzar el catalogo y releer la plantilla de 26 MB, para mostrar una tabla
    # filtrada. Medido el 2026-08-25, cambiar un filtro en auditoria repetia el
    # trabajo de las cinco secciones que nadie estaba mirando.
    #
    # Con `if seccion == ...` solo corre lo que se esta viendo. Ademas libera
    # el ancho completo de la pantalla, que en auditoria hacia falta.
    SECCIONES = list(SUBVISTAS_POR_SECCION)
    SECCIONES_CARGADOS = [
        seccion
        for seccion, configuracion in SUBVISTAS_POR_SECCION.items()
        if configuracion["grupo"] == "cargados"
    ]
    # El estado de la seccion sigue en esta misma clave: el resto del cuerpo
    # usa `seccion` para decidir que vista renderizar y asi no se ejecutan las
    # otras cinco secciones en cada interaccion.
    seccion_activa = st.session_state.get("seccion_activa", SECCIONES[0])
    if seccion_activa not in SECCIONES:
        seccion_activa = SECCIONES[0]
    st.session_state["seccion_activa"] = seccion_activa

    # Inicializar solo las claves de las sub-vistas y conservar su selección
    # mientras siga siendo válida. Así el cuerpo continúa leyendo exactamente
    # las mismas variables de sesión que antes usaban los radios.
    for configuracion in SUBVISTAS_POR_SECCION.values():
        clave_subvista = configuracion["clave"]
        opciones_subvista = configuracion["opciones"]
        if clave_subvista is not None and st.session_state.get(clave_subvista) not in opciones_subvista:
            st.session_state[clave_subvista] = opciones_subvista[0]

    # Navegacion + despacho de secciones, en UN solo fragmento -- pedido
    # explicito del usuario (2026-08-26) tras confirmar que hasta una seccion
    # LIVIANA como "Consultar INVIMA" se sentia lenta al volver a ella: el
    # costo no era de computo (medido ~0.1-0.3s por rerun completo, ver
    # commit anterior) sino de Streamlit reenviando/redibujando TODA la
    # pagina en cada clic del sidebar, porque los botones de navegacion
    # vivian FUERA de cualquier fragmento. Envolviendo el sidebar Y el
    # despacho de secciones juntos, un clic de navegacion (el widget que
    # dispara el cambio) queda DENTRO del fragmento: solo se reejecuta y
    # reenvia esta funcion, no el resto de main() (que de todos modos ya
    # termino de correr antes de este punto).
    @st.fragment
    def _navegacion_y_contenido() -> None:
        with st.sidebar:
            st.markdown("### Navegación")
            # Las 6 secciones se dibujan SIEMPRE en el mismo orden y con el mismo
            # alto -- pedido explicito del usuario: la version anterior insertaba
            # los botones de sub-vista ENTRE los de seccion, y la lista entera se
            # reacomodaba (se "desordenaba") cada vez que cambiaba la seccion
            # activa, porque las secciones de abajo se corrian segun cuantas
            # sub-vistas tuviera la de arriba. Ahora la lista de secciones nunca
            # cambia de alto; solo el bloque de sub-vistas, aparte y siempre
            # despues, cambia de contenido.
            for posicion, seccion_menu in enumerate(SECCIONES):
                if seccion_menu == SECCIONES_CARGADOS[0]:
                    st.caption("MEDICAMENTOS YA CARGADOS")

                st.button(
                    seccion_menu,
                    key=f"menu_seccion_{posicion}",
                    type="primary" if seccion_menu == seccion_activa else "secondary",
                    use_container_width=True,
                    on_click=_activar_seccion,
                    args=(seccion_menu,),
                )

            configuracion_subvista = SUBVISTAS_POR_SECCION[seccion_activa]
            clave_subvista = configuracion_subvista["clave"]
            opciones_subvista = configuracion_subvista["opciones"]
            if clave_subvista is not None and len(opciones_subvista) > 1:
                st.divider()
                st.caption(configuracion_subvista["etiqueta"])
                for indice_subvista, opcion_subvista in enumerate(opciones_subvista):
                    st.button(
                        opcion_subvista,
                        key=f"menu_subvista_{indice_subvista}",
                        type=(
                            "primary"
                            if st.session_state[clave_subvista] == opcion_subvista
                            else "secondary"
                        ),
                        use_container_width=True,
                        on_click=_activar_subvista,
                        args=(clave_subvista, opcion_subvista),
                    )

        seccion = st.session_state["seccion_activa"]
        vista_resumen = st.session_state["resumen_vista"]
        vista_cargue = st.session_state["cargue_vista"]
        origen = st.session_state["diagnostico_origen"]
        vista_auditoria = st.session_state["vista_auditoria"]

        if seccion == "Resumen de resolución":
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
                    _mensaje_breve(
                        "0 filas vigentes: parece que se subió el archivo equivocado de INVIMA.",
                        "El archivo/API usado no trae **ningún** registro con ESTADO "
                        f"REGISTRO=\"Vigente\" (el valor más común encontrado fue "
                        f"\"{valor_mas_comun}\"). Revisa que en el campo de Vigentes de \"Archivos de "
                        "entrada\" no esté, por error, el listado de Vencidos, Trámite de Renovación u "
                        "Otros Estados: los 4 archivos de INVIMA tienen nombres muy parecidos.",
                        tipo="error",
                        etiqueta="Qué revisar",
                    )
                else:
                    _mensaje_breve(
                        "0 filas vigentes en el catálogo INVIMA: no hay nada que procesar.",
                        "El filtro es ESTADO REGISTRO=Vigente + ESTADO CUM=Activo, y no quedó nada. "
                        "Esto no es un resultado normal. Si veniste de la API, confirma que la "
                        "sincronización realmente trajo filas (no debería llegar hasta acá si falló); "
                        "si veniste del Excel de respaldo, confirma que es el listado correcto y no "
                        "está vacío o con la hoja equivocada.",
                        tipo="error",
                        etiqueta="Qué revisar",
                    )
                st.stop()

            candidatos = int((resultado["accion"] == "candidato").sum())
            ya_existe = int((resultado["accion"] == "ya_existe").sum())
            cuarentena = int((resultado["accion"] == "cuarentena").sum())

            if vista_resumen == "Resumen":
                _seccion_resumen_metricas(resultado, total, candidatos, ya_existe, cuarentena)
            elif vista_resumen == "Cómo se resolvió":
                _seccion_resumen_metodos(resultado, total)
            else:
                _seccion_resumen_detalle_registro(df_invima)

        if seccion == "Casos que requieren decisión":
            df_cuarentena = resultado[resultado["accion"] == "cuarentena"]
            st.metric(
                "Casos pendientes de decisión",
                f"{len(df_cuarentena):,}",
                help="Son los medicamentos que el proceso apartó porque necesitan una decisión "
                "humana antes de crear o descartar un registro.",
            )
            # Unica sub-vista desde 2026-08-26: "Explicar con IA" se quito a
            # pedido del usuario ("de momento no se requiere"). Su logica
            # (_cliente_ia_disponible, _explicar_motivo_cacheado, ClienteExplicacionIA.explicar_fila)
            # sigue en el archivo sin usarse desde aqui, por si se reactiva.
            _mensaje_breve(
                "Compara **_texto_invima** (dato oficial) contra **_sugerencia** (coincidencia "
                "aproximada, nunca confirmada).",
                "**_texto_invima** es el dato crudo tal como lo reporta el listado oficial de "
                "INVIMA para ese medicamento. **_sugerencia** es una coincidencia aproximada de "
                "nuestro catálogo interno — sirve para decidir más rápido si el medicamento ya "
                "existe en Gemma Net con otro nombre, pero no está confirmada.",
                etiqueta="Qué significa cada columna",
            )
            _tabla_filtrable(
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
                columna_categoria="motivo",
            )
            _descarga_diferida(
                "Preparar reporte de revisión (.xlsx, una hoja por acción)",
                lambda: _bytes_reporte_cruce(resultado),
                "reporte_cruce_invima.xlsx",
                "descarga_cruce",
            )

        if seccion == "Cargue a Gemma Net":
            candidatos = int((resultado["accion"] == "candidato").sum())
            st.metric(
                "Candidatos recibidos para cargue",
                f"{candidatos:,}",
                help="Son los medicamentos nuevos que pasaron el cruce inicial y ahora se revisan "
                "contra la estructura de cargue antes de preparar el Excel final.",
            )
            _mensaje_breve(
                "Estructura de 37 campos, confirmada dos veces.",
                # `tb_medicamento`, singular. Confirmado el 2026-08-20 consultando el
                # catalogo de la base real (129 MB, esquema administrativo). Se llego a
                # cambiar a plural por un dato de memoria y estaba mal: el nombre
                # original, deducido de la hoja NO POS del workbook, era correcto.
                "Verificada contra el archivo real que exporta Gemma Net y contra el encabezado de "
                "carga que confirmaste. Tabla destino: `administrativo.tb_medicamento`.",
                etiqueta="De dónde sale la estructura",
            )

            if archivo_malla_referencia is None:
                _mensaje_breve(
                    "Falta la **Estructura Cargue Medicamentos (.xlsx)** — sin ella no se genera el "
                    "Excel de cargue.",
                    "Súbela en \"Archivos de entrada\". Es lo que permite clasificar POS y Modelo de "
                    "Servicio por expediente y completar los demás campos de regla de negocio.",
                    tipo="warning",
                    etiqueta="Para qué se usa",
                )
            else:
                try:
                    malla_referencia = _derivado(
                        "derivado_malla_referencia",
                        lambda: _leer_malla_referencia_cacheada(archivo_malla_referencia),
                    )
                except _ERRORES_ARCHIVO_CORRUPTO as exc:
                    _alerta_fallo_lectura(
                        "La Estructura Cargue Medicamentos llegó dañada",
                        "El archivo llegó incompleto o dañado. Vuelve a intentar la subida.",
                        exc,
                    )
                    st.stop()
                reglas = _derivado(
                    "derivado_reglas", lambda: _derivar_reglas_negocio_cacheada(malla_referencia)
                )

                if reglas.advertencias:
                    with st.expander(
                        f"⚠ {len(reglas.advertencias)} campo(s) con inconsistencias en la malla de referencia",
                        expanded=True,
                    ):
                        for campo, advertencia in reglas.advertencias.items():
                            st.write(f"**{campo}**: {advertencia}")

                evaluados = _derivado(
                    "derivado_evaluados", lambda: _evaluar_candidatos_cargue_cacheado(resultado, reglas)
                )
                listos = evaluados[evaluados["listo_para_cargue"]]
                pendientes = evaluados[~evaluados["listo_para_cargue"]]

                if vista_cargue == "Auditoría de estructura":
                    st.write("**Archivo de auditoría — Estructura de Cargue**")
                    _mensaje_breve(
                        "Reemplaza la copia manual de \"plantilla\" a \"plantilla (2)\" del SOP original.",
                        "Trae TODOS los candidatos (listos y pendientes) con CÓDIGO_INTERNO y "
                        "DESCRIPCIÓN ya concatenados, su ESTADO, y en CÓMO VERIFICAR los pasos "
                        "exactos para confirmar cada pendiente contra los archivos oficiales de "
                        "Pijao Salud a mano.",
                        etiqueta="Qué trae el archivo",
                    )
                    df_estructura = _derivado(
                        "derivado_df_estructura",
                        lambda: _armar_estructura_cargue_cacheada(resultado, reglas),
                    )
                    _descarga_diferida(
                        "Preparar Estructura de Cargue (auditoría)",
                        lambda: _bytes_estructura_cargue(df_estructura),
                        f"{nombre_periodo()}.xlsx",
                        "descarga_estructura",
                    )

                    if len(pendientes) > 0:
                        with st.expander(
                            f"🔎 {len(pendientes):,} candidato(s) pendientes de clasificación manual — por qué no están en el Excel",
                            expanded=(len(listos) == 0),
                        ):
                            # Sin _mensaje_breve: ya estamos DENTRO de un expander y
                            # streamlit no permite anidarlos. Aqui el texto se acorta en
                            # sitio; el usuario ya hizo un clic para llegar hasta aca.
                            st.write(
                                "**Lista de tareas pendientes para Autorizaciones.** Cada fila es un "
                                "medicamento que no se pudo crear solo porque falta confirmar marca, "
                                "unidad de medida, POS o modelo de servicio. Nunca se adivina."
                            )
                            st.caption(
                                "**CAMPOS_CON_ERROR**: cuáles de esos 4 faltan. **% COMPLETITUD**: "
                                "cuántos ya están confirmados. **DETALLE**: el motivo y una "
                                "sugerencia aproximada, que siempre hay que verificar en Gemma Net."
                            )
                            pendientes_mostrar = pendientes[
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
                            )
                            _tabla_filtrable(
                                pendientes_mostrar,
                                columnas_filtro=["DETALLE"],
                                key_prefix="pendientes",
                                columnas_mostrar=list(pendientes_mostrar.columns),
                                columna_categoria="DETALLE",
                                columna_campo="CAMPOS_CON_ERROR",
                                opciones_campo=CAMPOS_VERIFICABLES_CARGUE,
                                campos_iniciales=CAMPOS_VERIFICABLES_CARGUE,
                                clave_campo="pendientes_campo_error",
                            )
                else:
                    st.write("**Excel de cargue final — solo lo listo para subir**")
                    _mensaje_breve(
                        f"**{len(listos):,} de {candidatos:,} candidatos listos para cargue.**",
                        "Listo significa: marca y unidad resueltas contra catálogo, POS y Modelo de "
                        "Servicio confirmados por expediente. Ningún campo adivinado.",
                        tipo="write",
                        etiqueta="Qué quiere decir \"listo\"",
                    )

                    if len(listos) == 0:
                        _mensaje_breve(
                            "0 filas en el Excel de cargue. No es un error.",
                            "Ningún candidato de este lote tiene POS y Modelo de Servicio confirmados "
                            "con certeza todavía — revisa la sub-vista «Auditoría de estructura».",
                            tipo="info",
                            etiqueta="Por qué quedó vacío",
                        )
                    else:
                        df_cargue = _derivado(
                            "derivado_df_cargue",
                            lambda: _preparar_filas_cargue_cacheada(resultado, reglas),
                        )
                        _tabla_filtrable(
                            df_cargue,
                            columnas_filtro=["POS", "FORMA_FARMACEUTICA", "CLASIFICADO", "CODIGO_NIVEL_SERVICIO"],
                            key_prefix="cargue_final",
                            columna_categoria="POS",
                        )

                        buffer_excel = _bytes_cargue_final(df_cargue)
                        st.download_button(
                            "Descargar Excel de cargue",
                            data=buffer_excel,
                            file_name="cargue_gemma_net.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )

        if seccion == "Por qué no se cargó":
            # Vista por CAMPO, no por flujo -- pedido explicito del usuario
            # (2026-08-20): "una vista en la que podamos enfocarnos en los
            # medicamentos que no se cargaron y por que [...] los que tienen
            # diferencias de descripcion, que no tienen marca, que no tienen
            # unidad y asi con cada uno". Las otras pestañas responden "en que
            # estado quedo la corrida"; esta responde "quien falla en ESTE campo",
            # que es la pregunta con la que se reparte el trabajo manual.
            _mensaje_breve(
                "Elige un campo y ve exactamente qué medicamentos fallan en él.",
                "Dos orígenes distintos: los **candidatos nuevos** que no se pudieron cargar por "
                "un campo sin confirmar, y los **ya cargados** cuyo dato no coincide con INVIMA. "
                "Son problemas diferentes y se resuelven en sitios diferentes, por eso no se "
                "mezclan en una sola tabla.",
                etiqueta="Qué muestra esta vista",
            )

            if origen.startswith("Candidatos"):
                if archivo_malla_referencia is None:
                    _mensaje_breve(
                        "Falta la **Estructura Cargue Medicamentos (.xlsx)** para saber por qué "
                        "quedó pendiente cada candidato.",
                        "Súbela en \"Archivos de entrada\". Sin ella se sabe que un candidato no "
                        "está listo, pero no qué campo puntual se lo impide.",
                        tipo="warning",
                        etiqueta="Por qué hace falta",
                    )
                else:
                    try:
                        # Mismas claves derivadas que usa "Cargue a Gemma Net": si
                        # esa seccion ya corrio en esta corrida, esto no vuelve a
                        # leer los 26 MB del archivo ni a derivar las reglas de
                        # nuevo -- es el mismo `archivo_malla_referencia`.
                        malla_referencia_diag = _derivado(
                            "derivado_malla_referencia",
                            lambda: _leer_malla_referencia_cacheada(archivo_malla_referencia),
                        )
                        reglas_diag = _derivado(
                            "derivado_reglas",
                            lambda: _derivar_reglas_negocio_cacheada(malla_referencia_diag),
                        )
                    except _ERRORES_ARCHIVO_CORRUPTO as exc:
                        _alerta_fallo_lectura(
                            "La Estructura Cargue Medicamentos llegó dañada",
                            "Sin ella no se puede saber qué campo deja pendiente a cada candidato.",
                            exc,
                        )
                        st.stop()
                    evaluados_diag = _derivado(
                        "derivado_evaluados",
                        lambda: _evaluar_candidatos_cargue_cacheado(resultado, reglas_diag),
                    )
                    pendientes_diag = evaluados_diag[~evaluados_diag["listo_para_cargue"]]
                    _diagnostico_por_campo(
                        pendientes_diag,
                        columna="campos_con_error",
                        campos=CAMPOS_VERIFICABLES_CARGUE,
                        key_prefix="diag_cargue",
                        columnas_extra=["motivo_pendiente", "porcentaje_completitud"],
                        nombre_archivo="pendientes_por_campo.xlsx",
                        total=len(evaluados_diag),
                        leyenda="candidatos evaluados",
                    )
            elif origen.startswith("Novedades"):
                auditoria_vig = st.session_state.get("auditoria_coherencia")
                if auditoria_vig is None or "NOVEDAD_VIGENCIA_INVIMA" not in auditoria_vig.columns:
                    _mensaje_breve(
                        "Todavía no has corrido la auditoría de coherencia.",
                        "Ve a la pestaña \"Auditoría de coherencia\" y ejecútala; las novedades de "
                        "vigencia aparecen aquí al terminar.",
                        tipo="info",
                        etiqueta="Cómo obtenerlas",
                    )
                else:
                    # "coherente" y "no_verificable" no piden nada de nadie: esta
                    # vista es para repartir trabajo, no para listar el universo.
                    accionables = [
                        "riesgo_activo_sin_vigencia",
                        "registro_vencido_en_invima",
                        "revisar_reactivacion",
                        "actualizar_fecha_fin",
                    ]
                    con_novedad = auditoria_vig[
                        auditoria_vig["NOVEDAD_VIGENCIA_INVIMA"].isin(accionables)
                    ]
                    _diagnostico_por_campo(
                        con_novedad,
                        columna="NOVEDAD_VIGENCIA_INVIMA",
                        campos=accionables,
                        key_prefix="diag_vigencia",
                        columnas_extra=["DETALLE_VIGENCIA_INVIMA", "ESTADO_COHERENCIA"],
                        nombre_archivo="novedades_vigencia_invima.xlsx",
                        total=len(auditoria_vig),
                        leyenda="medicamentos auditados",
                    )
            else:
                auditoria_diag = st.session_state.get("auditoria_coherencia")
                if auditoria_diag is None:
                    _mensaje_breve(
                        "Todavía no has corrido la auditoría de coherencia.",
                        "Ve a la pestaña \"Auditoría de coherencia\" y ejecútala; al terminar, "
                        "sus resultados aparecen aquí desglosados por campo.",
                        tipo="info",
                        etiqueta="Cómo obtenerlos",
                    )
                else:
                    con_dif = auditoria_diag[
                        auditoria_diag["CAMPOS_CON_DIFERENCIA"].fillna("").astype(str).str.strip() != ""
                    ]
                    _diagnostico_por_campo(
                        con_dif,
                        columna="CAMPOS_CON_DIFERENCIA",
                        campos=CAMPOS_COMPARADOS_COHERENCIA,
                        key_prefix="diag_coherencia",
                        columnas_extra=["ESTADO_COHERENCIA", "PORCENTAJE_CALIDAD"],
                        nombre_archivo="diferencias_por_campo.xlsx",
                        total=len(auditoria_diag),
                        leyenda="medicamentos auditados",
                    )

        if seccion == "Consultar INVIMA":
            _mensaje_breve(
                "Consulta puntual contra INVIMA, para verificar un caso a mano.",
                "Nunca se usa en el proceso masivo. El resultado no se guarda en ningún registro de "
                "medicamento: solo se muestra en pantalla.",
                etiqueta="Alcance de esta consulta",
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
                                    "Este código no se pudo confirmar contra el servicio en línea de "
                                    "INVIMA porque ahora mismo no está entregando información. No "
                                    "quiere decir que el medicamento no exista."
                                ),
                                fecha_consulta=dt.datetime.now(),
                            )
                        else:
                            resultado_cum = consultar_cum(codigo_consulta)
                    tipo_mensaje, texto_estado = _MENSAJE_ESTADO_CUM[resultado_cum.estado]
                    getattr(st, tipo_mensaje)(f"**{texto_estado}** — {resultado_cum.mensaje}")
                    st.caption(f"Consultado: {resultado_cum.fecha_consulta.strftime('%Y-%m-%d %H:%M:%S')}")
                    # Sin API pero CON respaldo cargado, el archivo si puede responder:
                    # quedarse en "servicio no disponible" teniendo el dato a mano es
                    # dejar al usuario sin salida (ver _consultar_cum_en_respaldo).
                    if (
                        resultado_cum.estado
                        in (
                            EstadoValidacionCUM.SERVICIO_NO_DISPONIBLE,
                            EstadoValidacionCUM.API_NO_CONFIGURADA,
                        )
                        and archivo_invima is not None
                    ):
                        _consultar_cum_en_respaldo(archivo_invima, codigo_consulta)
                    # Siempre, no solo cuando la API falla: "¿es valido en INVIMA?" y
                    # "¿ya esta cargado en Gemma Net?" son preguntas distintas y el
                    # usuario suele necesitar las dos a la vez para decidir.
                    if archivo_gemma_net is not None:
                        _consultar_cum_en_gemanet(archivo_gemma_net, codigo_consulta)
                    if resultado_cum.datos_oficiales:
                        st.json(resultado_cum.datos_oficiales)

        if seccion == "Auditoría de coherencia":
            _mensaje_breve(
                "Revisa **todo** lo que ya está cargado en Gemma Net: compara campo a campo lo que "
                "tiene contraparte en INVIMA, y localiza el resto en los cuatro listados oficiales.",
                "**Son dos operaciones distintas y conviene no confundirlas.** Un medicamento solo "
                "se puede *comparar* si INVIMA lo tiene en su listado vigente: ahí se contrastan "
                "sus siete campos uno por uno. El resto no se compara con nada — de esos solo se "
                "averigua **en cuál de los cuatro listados aparece** (vigentes, vencidos, otros "
                "estados, en renovación), que es una pregunta distinta y con otra respuesta.\n\n"
                "Por eso hay dos familias de resultados: «coinciden» y «con diferencias» hablan del "
                "contenido del dato; «vencido», «otro estado», «en renovación» y «sin "
                "correspondencia» hablan de dónde está el registro, sin haber mirado un solo campo.\n\n"
                "Distinto de la bandeja de casos pendientes: esa es para medicamentos NUEVOS que "
                "aún no existen. Aquí «con diferencias» significa que el medicamento SÍ existe y SÍ "
                "se pudo emparejar — solo que algún campo quedó desactualizado y conviene "
                "corregirlo. Corre sobre el lote completo, no por código individual.",
                etiqueta="Qué compara exactamente, y qué no",
            )
            # Antes esto era un warning fijo, visible incluso antes de correr la
            # auditoria. Un aviso de riesgo sobre cero medicamentos no es un
            # hallazgo, es una explicacion -- y pintarlo en amarillo desde el
            # arranque entrena a ignorar el color justo donde hace falta. Ahora la
            # explicacion se muestra siempre en tono neutro y el color aparece
            # solo cuando la corrida encontro casos que clasificar.
            _auditoria_previa = st.session_state.get("auditoria_coherencia")
            _sin_corresp_previos = (
                int(
                    (
                        _auditoria_previa["ESTADO_COHERENCIA"]
                        == EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value
                    ).sum()
                )
                if _auditoria_previa is not None
                else 0
            )
            _mensaje_breve(
                (
                    f"**{_sin_corresp_previos:,} sin correspondencia en INVIMA.** Detrás de ese número "
                    "hay cuatro situaciones distintas, y no se atienden igual."
                    if _sin_corresp_previos
                    else "\"Sin correspondencia\" no es un solo caso, son cuatro."
                ),
                "Un código que no aparece en el listado Vigente de INVIMA puede significar que el "
                "registro sanitario **venció**, que está en **otro estado** "
                "(Cancelado/Suspendido/Inactivo/etc.), que está en **trámite de renovación**, o que es "
                "un **código legado** sin expediente INVIMA asociado. No se pueden tratar igual: no "
                "nos podemos exponer a autorizar un medicamento que ya no está vigente.",
                tipo="warning" if _sin_corresp_previos else "caption",
                etiqueta="Los cuatro casos",
            )
            # Los 3 auxiliares tambien salen de data/ si estan ahi: son justo los
            # que nadie recuerda subir, y sin ellos "vencido" y "otro estado" se
            # confunden con "codigo legado".
            auxiliares_detectados = descubrir_todo() if usar_detectados else {}
            archivo_invima_vencidos = _ruta_detectada(auxiliares_detectados, "invima_vencidos")
            archivo_invima_otros_estados = _ruta_detectada(auxiliares_detectados, "invima_otros_estados")
            archivo_invima_renovacion = _ruta_detectada(auxiliares_detectados, "invima_renovacion")
            if archivo_invima_vencidos or archivo_invima_otros_estados or archivo_invima_renovacion:
                hallados = [
                    _ETIQUETA_ARCHIVO[k]
                    for k in ("invima_vencidos", "invima_otros_estados", "invima_renovacion")
                    if k in auxiliares_detectados
                ]
                st.caption("Detectados en `data/`: " + " · ".join(hallados))
            elif not usar_api_invima:
                _mensaje_breve(
                    "Modo Excel de respaldo: sin los 3 archivos opcionales, todo lo no encontrado "
                    "cae en \"sin correspondencia\".",
                    "Las distinciones \"vencido\" / \"otro estado\" / \"trámite de renovación\" no "
                    "están disponibles automáticamente en este modo. Para tenerlas, sube abajo los "
                    "archivos oficiales correspondientes de INVIMA a mano (todos opcionales e "
                    "independientes entre sí), o cambia a la fuente API de Socrata en \"Archivos de "
                    "entrada\".",
                    tipo="info",
                    etiqueta="Cómo recuperar esas distinciones",
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

                n_vigente_sin_comerc = int(
                    conteos.get(EstadoCoherencia.VIGENTE_NO_COMERCIALIZADO_INVIMA.value, 0)
                )
                n_comparables = int(auditoria["PORCENTAJE_CALIDAD"].notna().sum())
                n_auditado = len(auditoria)

                # Los dos bloques van en contenedores separados, cada uno con su
                # titulo diciendo EXACTAMENTE que dos fuentes compara -- pedido
                # explicito del usuario: "no se sabe que fuentes son las que se
                # comparan ni tampoco se sabe cuales son los campos que se
                # comparan". Antes eran dos `st.markdown` sueltos en el mismo
                # scroll, sin borde que separe donde termina uno y empieza el
                # otro.
                with st.container(border=True):
                    st.markdown("**Comparados campo a campo — Gemma Net vs INVIMA (listado Vigentes)**")
                    st.caption(
                        f"{n_comparables:,} medicamentos ({n_comparables / n_auditado:.1%} del "
                        f"catálogo): son los que INVIMA tiene en su listado vigente. Los campos "
                        "comparados son DESCRIPCION, MARCA_MEDICAMENTO y UNIDAD_MEDIDA."
                    )
                    d1, d2, d3 = st.columns(3)
                    d1.metric(
                        "Sus datos coinciden",
                        f"{n_correcto:,}",
                        help="Sus campos coinciden con el dato oficial de INVIMA. No significa que el "
                        "medicamento esté activo ni que se pueda autorizar: un medicamento dado de baja "
                        "hace años cuenta aquí si su registro está bien copiado.",
                    )
                    d2.metric(
                        "Algún campo difiere",
                        f"{n_diferencias:,}",
                        help="Existe en INVIMA (mismo listado Vigentes) y alguno de DESCRIPCION, "
                        "MARCA_MEDICAMENTO o UNIDAD_MEDIDA no coincide entre las dos fuentes. Cuál "
                        "campo y qué dice cada lado se ve en la tabla de calidades, más abajo.",
                    )
                    calidad_promedio = auditoria["PORCENTAJE_CALIDAD"].mean()
                    d3.metric(
                        "Calidad de sus campos",
                        f"{calidad_promedio:.1f}%" if pd.notna(calidad_promedio) else "—",
                        help=f"Promedio calculado SOLO sobre los {n_comparables:,} que se pudieron "
                        f"comparar, no sobre los {n_auditado:,} del catálogo: de los campos que se "
                        "pudieron contrastar, cuántos coinciden. Un medicamento con una diferencia "
                        "puede seguir teniendo un porcentaje alto si el resto de sus campos está bien. "
                        "Los campos sin dato salen de la cuenta: a un campo vacío no se le puede "
                        "exigir que coincida con INVIMA.",
                    )
                    st.caption(
                        f"El {calidad_promedio:.1f}% habla de estos {n_comparables:,}, no del catálogo "
                        f"completo. Del resto no se afirma nada: no hay contra qué compararlo."
                        if pd.notna(calidad_promedio)
                        else ""
                    )

                with st.container(border=True):
                    st.markdown(
                        "**Sin contraparte en Vigentes — buscados en INVIMA Vencidos, "
                        "Otros Estados y Trámite de Renovación**"
                    )
                    st.caption(
                        f"{n_auditado - n_comparables:,} medicamentos: aquí NO se compara ningún "
                        "campo (DESCRIPCION/MARCA/UNIDAD), solo se averigua en cuál de los otros "
                        "tres listados de INVIMA aparece cada código."
                    )
                    e1, e2, e3, e4 = st.columns(4)
                    e1.metric(
                        "⚠ Registro vencido",
                        f"{n_vencido:,}",
                        delta_color="inverse",
                        help="INVIMA lo tiene en su listado de Vencidos. Solo es un riesgo si además "
                        "sigue ACTIVO aquí — esa cifra está en la tabla de calidades.",
                    )
                    e2.metric(
                        "⚠ Registro sin vigencia",
                        f"{n_otro_estado:,}",
                        delta_color="inverse",
                        help="INVIMA lo tiene en su listado de Otros Estados: Cancelado, Suspendido, "
                        "Negado, Desistido o con pérdida de fuerza ejecutoria. El valor exacto está "
                        "en ESTADO_INVIMA_DETALLE.",
                    )
                    e3.metric(
                        "En trámite de renovación",
                        f"{n_renovacion:,}",
                        help="INVIMA lo tiene en su listado de Trámite de Renovación. El registro "
                        "sigue siendo válido mientras INVIMA resuelve. Se espera, no se corrige.",
                    )
                    e4.metric(
                        "No se puede verificar",
                        f"{n_sin_corresp:,}",
                        help="No aparece en ninguno de los cuatro listados de INVIMA. En su mayoría "
                        "son códigos anteriores a la convención de INVIMA: no están mal cargados, "
                        "simplemente no hay con qué buscarlos allá.",
                    )
                    if n_vigente_sin_comerc:
                        st.metric(
                            "Vigente, temporalmente sin comercializar",
                            f"{n_vigente_sin_comerc:,}",
                            help="Aparece en el listado Otros Estados de INVIMA, pero el propio texto "
                            "oficial dice que el registro está VIGENTE: lo único que pasa es que el "
                            "producto no se está comercializando ahora. No es un riesgo de vigencia, "
                            "y por eso no se cuenta con los anteriores.",
                        )

                st.caption(
                    "🔎 Cambiar un filtro más abajo no vuelve a calcular esta auditoría ni relee "
                    "archivos — solo se filtra lo que ya está en pantalla."
                )

                # Tarjetas de hallazgo agrupadas por dimension, colapsadas por
                # defecto -- pedido explicito: "son tantas cifras a la vista uno
                # asi tenga la infor al lado se desconcierta". Antes eran 9+
                # tarjetas sueltas en una sola grilla, siempre visibles, sin
                # importar que sub-vista (Priorizar/Entender/Explorar) se
                # hubiera elegido. Cada grupo se abre solo si el usuario quiere
                # ese nivel de detalle.
                alertas_carga = list(st.session_state.get("auditoria_alertas_carga", []))
                alertas_vigencia: list[tuple[str, str, str, pd.DataFrame]] = []
                alertas_calidad: list[
                    tuple[str, str, str] | tuple[str, str, str, pd.DataFrame, list[str]]
                ] = []

                if n_vencido > 0:
                    mascara_vencido = auditoria["ESTADO_COHERENCIA"] == EstadoCoherencia.VENCIDO_EN_INVIMA.value
                    alertas_vigencia.append(
                        (
                            "error",
                            f"⚠ {n_vencido:,} vencido(s) en INVIMA",
                            "Gemma Net (CODIGO_INTERNO) vs INVIMA (listado de Vencidos). INVIMA "
                            "tiene este registro sanitario en su listado de Vencidos. Es un riesgo "
                            "de autorización SOLO si además sigue ACTIVO=SI en Gemma Net — el "
                            "cruce de ambas condiciones ya está en la tarjeta \"activo(s) aquí sin "
                            "vigencia en INVIMA\", más abajo. Filtra por ESTADO_COHERENCIA en la "
                            "tabla para ver estos exactos.",
                            auditoria[mascara_vencido],
                        )
                    )
                if n_otro_estado > 0:
                    mascara_otro_estado = (
                        auditoria["ESTADO_COHERENCIA"]
                        == EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value
                    )
                    alertas_vigencia.append(
                        (
                            "error",
                            f"⚠ {n_otro_estado:,} en otro estado INVIMA",
                            "Gemma Net (CODIGO_INTERNO) vs INVIMA (listado Otros Estados). INVIMA "
                            "tiene este registro como Cancelado, Suspendido, Negado, Desistido o "
                            "con pérdida de fuerza ejecutoria — el valor EXACTO que reportó INVIMA "
                            "para cada uno está en la columna ESTADO_INVIMA_DETALLE de la tabla, no "
                            "es el mismo estado para todos.",
                            auditoria[mascara_otro_estado],
                        )
                    )
                if "INCONSISTENCIA_FECHAS_ACTIVO" in auditoria.columns:
                    mascara_fechas = auditoria["INCONSISTENCIA_FECHAS_ACTIVO"] != ""
                    n_inconsistencia_fechas = int(mascara_fechas.sum())
                    if n_inconsistencia_fechas > 0:
                        alertas_vigencia.append(
                            (
                                "warning",
                                f"{n_inconsistencia_fechas:,} con fechas/vigencia inconsistentes",
                                "Coherencia INTERNA de Gemma Net (no depende de INVIMA): la columna "
                                "ACTIVO no cuadra con FECHA_INICIO/FECHA_FIN de ese mismo registro "
                                "(ej. ACTIVO=SI sin FECHA_INICIO, o ACTIVO=NO con FECHA_FIN vacía). "
                                "El detalle exacto de cada caso está en INCONSISTENCIA_FECHAS_ACTIVO "
                                "en la tabla.",
                                auditoria[mascara_fechas],
                            )
                        )
                # Dimension 10: las novedades de vigencia contra INVIMA. Solo se
                # muestran las accionables -- "coherente" y "no_verificable" son
                # mayoria y no piden nada de nadie.
                if "NOVEDAD_VIGENCIA_INVIMA" in auditoria.columns:
                    for clave, severidad, titulo, detalle in [
                        (
                            "riesgo_activo_sin_vigencia",
                            "error",
                            "activo(s) aquí sin vigencia en INVIMA",
                            "Gemma Net (columna ACTIVO) vs INVIMA (ESTADO_CUM_INVIMA). Los únicos "
                            "sobre los que se puede actuar hoy: están ACTIVOS en Gemma Net y su "
                            "registro no está vigente en INVIMA, así que se pueden llegar a "
                            "autorizar. Es la cifra del riesgo real — no el total de vencidos, que "
                            "en su mayoría ya están inactivos aquí y nadie va a dispensar.",
                        ),
                        (
                            "registro_vencido_en_invima",
                            "error",
                            "con registro sanitario vencido en INVIMA",
                            "Gemma Net (FECHA_FIN) vs INVIMA (FECHA_VENCIMIENTO_INVIMA). Verificado "
                            "dentro de la fecha de corte del catálogo usado.",
                        ),
                        (
                            "revisar_reactivacion",
                            "warning",
                            "inactivo(s) aquí pero con registro vivo en INVIMA",
                            "Gemma Net (columna ACTIVO) vs INVIMA (ESTADO_CUM_INVIMA). Están "
                            "inactivos en Gemma Net y su registro sigue vigente o en renovación en "
                            "INVIMA: se podrían reactivar. Revisar caso por caso — puede ser una "
                            "decisión de negocio ya tomada, no un error.",
                        ),
                        (
                            "actualizar_fecha_fin",
                            "warning",
                            "sin fecha de fin que INVIMA sí tiene",
                            "Gemma Net (FECHA_FIN vacía) vs INVIMA (FECHA_VENCIMIENTO_INVIMA con "
                            "dato). Novedad concreta: la fecha existe en INVIMA y se puede "
                            "actualizar.",
                        ),
                    ]:
                        mascara_novedad = auditoria["NOVEDAD_VIGENCIA_INVIMA"] == clave
                        n = int(mascara_novedad.sum())
                        if n > 0:
                            alertas_vigencia.append(
                                (
                                    severidad,
                                    f"{n:,} {titulo}",
                                    detalle,
                                    auditoria[mascara_novedad],
                                )
                            )

                # Una tarjeta -- con su propia tabla de medicamentos, no la tabla
                # general con todos los filtros -- por cada campo que
                # `campos_calidad_mascaras` (auditar_coherencia()) detecto como
                # sistemicamente vacio, mas la capa legada ATC si aplica. Pedido
                # explicito (2026-08-26): "una tabla por cada cifra distinta...
                # una lista solo para vigentes, una lista solo para diferidos".
                campos_calidad_cubiertos: set[str] = set()
                for campo, mascara_campo in auditoria.attrs.get("campos_calidad_mascaras", {}).items():
                    campos_calidad_cubiertos.add(campo)
                    n = int(mascara_campo.sum())
                    porcentaje = mascara_campo.mean() * 100 if len(mascara_campo) else 0.0
                    alertas_calidad.append(
                        (
                            "warning",
                            f"{n:,} sin dato real en {campo} ({porcentaje:.1f}%)",
                            f"El campo {campo} no trae dato real (vacío, \"-999\" o, si es un "
                            "código de catálogo, el código 1 \"SIN INFORMACIÓN\") en la mayoría "
                            "de las filas del reporte de Gemma Net -- parece no estarse "
                            "diligenciando en el proceso de origen, no un dato puntual faltante "
                            "por medicamento.",
                            auditoria[mascara_campo],
                            [campo],
                        )
                    )

                mascara_capa_legada = auditoria.attrs.get("capa_legada_atc_mascara")
                if mascara_capa_legada is not None and mascara_capa_legada.any():
                    n = int(mascara_capa_legada.sum())
                    alertas_calidad.append(
                        (
                            "warning",
                            f"{n:,} con capa legada ATC+expediente+consecutivo",
                            "TIPO_CODIGO_INTERNO clasifica el CODIGO_INTERNO como una capa "
                            "legada de INVIMA (código ATC + expediente + consecutivo) -- en la "
                            "mayoría de los casos ya existe como fila CUM independiente en este "
                            "mismo reporte. Es informativo: no se fusiona ni se deduplica "
                            "automáticamente.",
                            auditoria[mascara_capa_legada],
                            ["TIPO_CODIGO_INTERNO"],
                        )
                    )

                # El resto de advertencias (lectura del archivo, sin mascara
                # limpia por fila) siguen como tarjeta simple -- se excluyen las
                # que ya se representaron arriba con su tabla, que vienen del
                # mismo texto generado por coherencia_invima.py y se repetirian.
                for advertencia in auditoria.attrs.get("advertencias", []):
                    if any(f"El campo {campo} " in advertencia for campo in campos_calidad_cubiertos):
                        continue
                    if mascara_capa_legada is not None and "capa legada de INVIMA" in advertencia:
                        continue
                    alertas_calidad.append(_alerta_desde_advertencia(advertencia))

                # Encabezado + tarjetas directo, SIN expander alrededor del
                # grupo -- pedido explicito y enfatico del usuario: los grupos
                # colapsados "solo desperdician espacio". Cada tarjeta ya es
                # compacta (icono + titulo de una linea + boton "❓" con tooltip
                # nativo para el detalle), asi que ya no hace falta esconderlas
                # detras de un clic extra.
                if alertas_carga:
                    st.markdown("**Avisos de esta corrida**")
                    _mostrar_tarjetas_alerta(alertas_carga, grupo="carga")
                if alertas_vigencia:
                    st.markdown(f"**Vigencia frente a INVIMA** ({len(alertas_vigencia)} hallazgo(s))")
                    _mostrar_tarjetas_alerta(alertas_vigencia, grupo="vigencia")
                if alertas_calidad:
                    st.markdown(
                        f"**Calidad de los campos del reporte** ({len(alertas_calidad)} hallazgo(s))"
                    )
                    _mostrar_tarjetas_alerta(alertas_calidad, grupo="calidad")

                if vista_auditoria == "Priorizar lo que requiere accion":
                    _panel_prioridades_auditoria(auditoria)
                    return
                if vista_auditoria == "Entender la calidad del catalogo":
                    _panel_entender_auditoria(auditoria)
                    return

                # Por CLASE de problema, no por campo. Es la vista que contesta
                # "¿y ahora qué hago con esto?": lo que hay que esperar, lo que no
                # se corrige fila por fila y lo que sí pide trabajo manual salían
                # antes revueltos en la misma lista.
                if "NATURALEZA_HALLAZGO" in auditoria.columns:
                    conteo_naturaleza = auditoria["NATURALEZA_HALLAZGO"].value_counts()
                    naturalezas = [
                        (etiqueta, int(conteo_naturaleza.get(etiqueta, 0)))
                        for etiqueta in ACCION_POR_NATURALEZA
                    ]
                    naturalezas = [(etiqueta, n) for etiqueta, n in naturalezas if n]
                    if naturalezas:
                        # Como TABLA y no como tarjetas sueltas, y plegado por
                        # defecto. Tres de estas cinco cifras son exactamente las
                        # mismas que ya estan arriba, solo renombradas: "vigencia en
                        # riesgo" es vencido + sin vigencia, "en tramite de
                        # renovacion" y "dato desactualizado" son identicas a sus
                        # tarjetas. Repetirlas como metricas grandes hacia que el
                        # mismo medicamento se contara tres veces al sumar a ojo.
                        # Aqui aportan lo unico que las otras no dicen: QUE HACER.
                        with st.expander(
                            "Qué hacer con cada hallazgo — acción sugerida por clase", expanded=False
                        ):
                            st.caption(
                                "Cada medicamento lleva **una sola** etiqueta: la de lo más urgente "
                                "que pide. Varias de estas cifras son los mismos medicamentos que "
                                "las tarjetas de arriba, agrupados por la acción que piden en vez "
                                "de por su estado — **no se suman entre sí ni con aquellas**."
                            )
                            _mostrar_tabla_estandar(
                                pd.DataFrame(
                                    [
                                        {
                                            "Clase de hallazgo": etiqueta,
                                            "Medicamentos": n,
                                            "Qué hacer": ACCION_POR_NATURALEZA[etiqueta],
                                        }
                                        for etiqueta, n in naturalezas
                                    ]
                                ),
                                variante="resumen",
                            )

                if "PORCENTAJE_COMPLETITUD_REPORTE" in auditoria.columns:
                    with st.expander("10 dimensiones de calidad de dato (completitud, unicidad, dominio, razonabilidad, formato, integridad referencial, vigencia)"):
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
                            "Consistencia (arriba), son las 10 dimensiones de calidad de dato de esta auditoría."
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

                st.divider()
                st.subheader("Tabla de calidades")
                _mensaje_breve(
                    "Cada calidad se puede **abrir** hasta los medicamentos que la componen.",
                    "Las tarjetas de arriba dicen cuántos; esta tabla dice cuáles. Es el mismo "
                    "cálculo, pero navegable: se elige una calidad, se ve la lista con el dato "
                    "de Gemma Net y el de INVIMA al lado, y se puede buscar, filtrar y descargar.",
                    etiqueta="Para qué sirve",
                )
                _mostrar_tabla_de_calidades(auditoria)

                st.divider()
                st.subheader("Explorar por estado y por campo")
                estados_disponibles = sorted(auditoria["ESTADO_COHERENCIA"].unique())
                estados_iniciales = [
                    estado
                    for estado in [
                        EstadoCoherencia.VENCIDO_EN_INVIMA.value,
                        EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value,
                        EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value,
                        EstadoCoherencia.CON_DIFERENCIAS.value,
                    ]
                    if estado in estados_disponibles
                ] or estados_disponibles
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
                _tabla_auditoria_esencial(
                    auditoria,
                    columnas_mostrar,
                    clave="explorar_auditoria",
                    vacio="No hay medicamentos con esos criterios en la corrida actual.",
                    columna_categoria="ESTADO_COHERENCIA",
                    columna_campo="CAMPOS_CON_DIFERENCIA",
                    opciones_campo=CAMPOS_COMPARADOS_COHERENCIA,
                    categorias_iniciales=estados_iniciales,
                    clave_campo="coherencia_campo_diferencia",
                )

                _descarga_diferida(
                    "Preparar auditoría de coherencia (.xlsx, una hoja por estado)",
                    lambda: _bytes_auditoria_coherencia(auditoria),
                    "auditoria_coherencia_invima.xlsx",
                    "descarga_auditoria",
                )

    _navegacion_y_contenido()


def _exportar_a_bytes(escribir) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "salida"
        escribir(ruta)
        return ruta.read_bytes()


if __name__ == "__main__":
    main()
