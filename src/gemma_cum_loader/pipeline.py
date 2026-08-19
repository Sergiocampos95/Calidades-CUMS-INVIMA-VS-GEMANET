"""Orquesta el flujo end-to-end: arma las filas candidatas a partir del
catalogo INVIMA vigente (fases 2, 4 y 5 -- ver armado/malla.py), resuelve
catalogos (unidad, marca) contra el config interno, descarta lo que ya esta
cargado en Gemma Net (fase 6 -- ver armado/cruce_gemanet.py), y clasifica
cada fila con el motor de validacion.

Ya no recibe una "malla" externa: ese archivo se preparaba a mano en Excel
(depuracion, CODIGO_INTERNO, DESCRIPCION ya construidos) y por pedido
explicito del usuario dejo de ser una entrada -- lo que antes traia hecho
esa hoja ahora lo arma este pipeline directamente desde el catalogo INVIMA.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from gemma_cum_loader.armado.cruce_gemanet import leer_codigos_gemanet, leer_reporte_gemanet
from gemma_cum_loader.armado.malla import candidatos_creacion
from gemma_cum_loader.auditoria.coherencia_invima import auditar_coherencia
from gemma_cum_loader.catalogos.resolver import (
    ResolverCatalogo,
    SugerenciaCatalogo,
    cargar_catalogo,
    cargar_catalogo_csv,
)
from gemma_cum_loader.ingesta.invima_reader import leer_catalogo_invima
from gemma_cum_loader.ingesta.invima_socrata import leer_catalogo_invima_api
from gemma_cum_loader.integraciones.socrata import SesionHTTP
from gemma_cum_loader.normaliza.texto import normalizar_entidad
from gemma_cum_loader.validacion.reglas import (
    filtro_codigo_interno_valido,
    filtro_integridad_estructural,
)

RAIZ = Path(__file__).resolve().parent.parent.parent
RUTA_CATALOGO_UNIDAD = RAIZ / "config" / "catalogos" / "unidad_medida.csv"
RUTA_CATALOGO_MARCA = RAIZ / "config" / "catalogos" / "marca_medicamento.csv"

# Campos que candidatos_creacion() ya deja listos en cada fila y que pasan
# directo al resultado, sin transformacion -- ver exportacion/cargue.py para
# el resto de campos que exige el cargue final (ahi si hace falta mapear
# nombres y dejar en blanco lo que no es derivable del catalogo INVIMA).
COLUMNAS_PASO_DIRECTO = [
    "CODIGO_INTERNO",
    "DESCRIPCION",
    "CONCENTRACION",
    "EXPEDIENTE",
    "CONSECUTIVO",
    "FORMA_FARMACEUTICA",
    "PRINCIPIO_ACTIVO",
    "ATC",
]


def _formatear_sugerencias(sugerencias: list[SugerenciaCatalogo]) -> str:
    """Texto listo para mostrar en pantalla -- ver ResolverCatalogo.sugerencias:
    nunca es una respuesta confirmada, solo una guia de por donde buscar."""
    if not sugerencias:
        return ""
    return " | ".join(f"{s.texto} ({s.score:.0f}%, codigo {s.codigo})" for s in sugerencias)


def _resolver_unidad(ruta_catalogo: str | Path = RUTA_CATALOGO_UNIDAD) -> ResolverCatalogo:
    catalogo = cargar_catalogo(cargar_catalogo_csv(ruta_catalogo))
    return ResolverCatalogo(catalogo)


def _resolver_marca(ruta_catalogo: str | Path = RUTA_CATALOGO_MARCA) -> ResolverCatalogo:
    catalogo = cargar_catalogo(
        cargar_catalogo_csv(ruta_catalogo),
        normalizador=normalizar_entidad,
        dividir_sigla_descripcion=False,
    )
    return ResolverCatalogo(catalogo, normalizador=normalizar_entidad)


def procesar_invima_vigentes(
    archivo_invima: Any,
    archivo_gemma_net: Any,
    ruta_catalogo_unidad: str | Path = RUTA_CATALOGO_UNIDAD,
    ruta_catalogo_marca: str | Path = RUTA_CATALOGO_MARCA,
) -> pd.DataFrame:
    """archivo_invima: Listado Codigo Unico de Medicamentos Vigentes (.xlsx),
    subido a mano -- via de respaldo si la API de Socrata no esta disponible.
    Ver `procesar_invima_vigentes_desde_api` para la via preferida (sin
    descarga manual). archivo_gemma_net: archivo exportado por la
    plataforma (.xlsx o .txt), usado para el cruce de la fase 6 (que ya esta
    cargado).

    Ambos aceptan ruta o un objeto tipo-archivo (ej. UploadedFile de
    Streamlit) -- pandas/openpyxl leen los dos igual. ruta_catalogo_unidad y
    ruta_catalogo_marca son inyectables (por defecto el config bundled) para
    poder testear con catalogos chicos sin depender del contenido real.
    """
    df_invima = leer_catalogo_invima(archivo_invima)
    return procesar_desde_catalogo_invima(
        df_invima, archivo_gemma_net, ruta_catalogo_unidad, ruta_catalogo_marca
    )


def procesar_invima_vigentes_desde_api(
    archivo_gemma_net: Any,
    token: str | None = None,
    sesion: SesionHTTP | None = None,
    ruta_catalogo_unidad: str | Path = RUTA_CATALOGO_UNIDAD,
    ruta_catalogo_marca: str | Path = RUTA_CATALOGO_MARCA,
) -> pd.DataFrame:
    """Igual que `procesar_invima_vigentes`, pero trae el catalogo INVIMA
    vigente en vivo desde la API de Socrata (Datos Abiertos Colombia,
    dataset i7cb-raxc de INVIMA) en vez de un Excel subido a mano -- ver
    ingesta/invima_socrata.py. `token`/`sesion` son inyectables para poder
    testear sin red real; por defecto usa la variable de entorno
    INVIMA_SOCRATA_APP_TOKEN.
    """
    df_invima = leer_catalogo_invima_api(token=token, sesion=sesion)
    return procesar_desde_catalogo_invima(
        df_invima, archivo_gemma_net, ruta_catalogo_unidad, ruta_catalogo_marca
    )


def procesar_desde_catalogo_invima(
    df_invima: pd.DataFrame,
    archivo_gemma_net: Any,
    ruta_catalogo_unidad: str | Path = RUTA_CATALOGO_UNIDAD,
    ruta_catalogo_marca: str | Path = RUTA_CATALOGO_MARCA,
) -> pd.DataFrame:
    """Publica (no solo nucleo interno) para que quien ya cargo `df_invima`
    una vez (ej. la UI, para tambien pasarselo a `auditar_coherencia_gemanet`
    sin sincronizar el dataset completo dos veces) pueda reusarlo aqui sin
    pasar por `procesar_invima_vigentes`/`_desde_api`.

    Nucleo compartido entre la via archivo y la via API -- ambas terminan
    en el mismo DataFrame normalizado (ver invima_reader.py /
    invima_socrata.py), asi que todo lo que sigue (armado de candidatos,
    resolucion de catalogo, cruce contra Gemma Net) es identico sin importar
    de donde vino el catalogo INVIMA.
    """
    malla = candidatos_creacion(df_invima)
    columnas_esperadas = list(malla.columns)

    resolver_unidad = _resolver_unidad(ruta_catalogo_unidad)
    resolver_marca = _resolver_marca(ruta_catalogo_marca)
    cruce_gemanet = leer_codigos_gemanet(archivo_gemma_net)
    ya_existentes = cruce_gemanet.codigos
    no_verificables = cruce_gemanet.codigos_no_verificables

    resultado_unidad = malla["UNIDAD_DE_MEDIDA"].apply(resolver_unidad.resolver)
    resultado_marca = malla["MARCA_MEDICAMENTO"].apply(resolver_marca.resolver)

    acciones: list[str] = []
    motivos: list[str] = []
    # strict=True: las 3 secuencias salen de `malla`, tienen que medir igual.
    # Si algun dia dejan de medir igual es un bug -- mejor que reviente aqui
    # que truncar en silencio y perder filas del reporte sin que nadie lo note.
    for fila, r_unidad, r_marca in zip(
        malla.to_dict("records"), resultado_unidad, resultado_marca, strict=True
    ):
        identidad = filtro_codigo_interno_valido(fila.get("CODIGO_INTERNO"))
        if identidad is not None:
            acciones.append(identidad.accion.value)
            motivos.append(identidad.motivo)
            continue

        estructural = filtro_integridad_estructural(fila, columnas_esperadas)
        if estructural is not None:
            acciones.append(estructural.accion.value)
            motivos.append(estructural.motivo)
            continue

        codigo = str(fila["CODIGO_INTERNO"])
        if codigo in ya_existentes:
            acciones.append("ya_existe")
            motivos.append(
                "ya esta cargado en Gemma Net (cruce por CODIGO_INTERNO contra "
                "el archivo exportado de la plataforma)"
            )
            continue

        if codigo in no_verificables:
            # el motivo debe ser exhaustivo, no solo el primero que aplica --
            # caso real: un CODIGO_INTERNO que coincide con una linea rota de
            # Gemma Net Y ademas tiene la marca sin resolver son DOS
            # problemas independientes; mostrar solo el primero le hace creer
            # a quien revisa que basta con verificar Gemma Net a mano, cuando
            # en realidad tambien falta resolver la marca/unidad despues.
            motivos_fila = [
                "no se pudo confirmar si ya esta cargado en Gemma Net: este "
                "CODIGO_INTERNO coincide con una linea del archivo exportado que "
                "no se pudo leer completa (formato irregular) -- verificar "
                "manualmente antes de crear, para no duplicarlo"
            ]
            if r_unidad.metodo == "sin_resolver":
                motivos_fila.append(
                    "ademas, UNIDAD DE MEDIDA no se encontro en el catalogo interno "
                    "-- tambien haria falta resolverla antes de poder crear este medicamento"
                )
            if r_marca.metodo == "sin_resolver":
                motivos_fila.append(
                    "ademas, MARCA MEDICAMENTO no se encontro en el catalogo interno "
                    "-- tambien haria falta resolverla antes de poder crear este medicamento"
                )
            acciones.append("cuarentena")
            motivos.append(" | ".join(motivos_fila))
            continue

        acciones.append("candidato")
        motivos.append(
            "vigente y activo en el corte INVIMA, no esta aun en Gemma Net -- "
            "listo para crear si ademas resuelve unidad y marca"
        )

    # sugerencias aproximadas solo para candidatos sin_resolver -- son la
    # mayoria de las filas normalmente resueltas, calcularlas para todas
    # seria trabajo desperdiciado (y mas lento) sin ningun uso
    sugerencia_unidad: list[str] = []
    sugerencia_marca: list[str] = []
    for accion, r_unidad, r_marca, valor_unidad, valor_marca in zip(
        acciones, resultado_unidad, resultado_marca,
        malla["UNIDAD_DE_MEDIDA"], malla["MARCA_MEDICAMENTO"], strict=True,
    ):
        necesita_sugerencia = accion == "candidato"
        sugerencia_unidad.append(
            _formatear_sugerencias(resolver_unidad.sugerencias(valor_unidad))
            if necesita_sugerencia and r_unidad.metodo == "sin_resolver"
            else ""
        )
        sugerencia_marca.append(
            _formatear_sugerencias(resolver_marca.sugerencias(valor_marca))
            if necesita_sugerencia and r_marca.metodo == "sin_resolver"
            else ""
        )

    datos: dict[str, object] = {columna: malla[columna] for columna in COLUMNAS_PASO_DIRECTO}
    datos.update(
        {
            "unidad_metodo": [r.metodo for r in resultado_unidad],
            "unidad_codigo": [r.codigo for r in resultado_unidad],
            "unidad_sugerencia": sugerencia_unidad,
            # texto CRUDO de INVIMA (antes de resolver contra el catalogo interno) --
            # se conserva para que, cuando no resuelve, se pueda mostrar lo que
            # INVIMA realmente reporta (no solo una sugerencia aproximada del
            # catalogo bundled) y comparar contra el listado oficial a mano
            "unidad_texto_invima": malla["UNIDAD_DE_MEDIDA"],
            "marca_metodo": [r.metodo for r in resultado_marca],
            "marca_codigo": [r.codigo for r in resultado_marca],
            "marca_sugerencia": sugerencia_marca,
            "marca_texto_invima": malla["MARCA_MEDICAMENTO"],
            "accion": acciones,
            "motivo": motivos,
        }
    )
    resultado = pd.DataFrame(datos)
    resultado = _reclasificar_duplicados(resultado)
    # .attrs sobrevive al retorno (no es una columna) -- la UI lo muestra como
    # advertencia si viene poblado. Ver CodigosGemaNet.
    resultado.attrs["advertencias"] = cruce_gemanet.advertencias
    resultado.attrs["lineas_omitidas_gemanet"] = cruce_gemanet.lineas_omitidas
    resultado.attrs["codigos_no_verificables_gemanet"] = cruce_gemanet.codigos_no_verificables_por_linea
    return resultado


def _reclasificar_duplicados(resultado: pd.DataFrame) -> pd.DataFrame:
    """Dos candidatos con el mismo CODIGO_INTERNO (medicamento combinado: un
    principio activo por fila, mismo codigo -- ver invima_reader.py) no deben
    entrar los dos al cargue final con la misma llave. Fusionarlos a ciegas
    perderia un principio activo, asi que se manda a cuarentena para que
    negocio decida, en vez de adivinar.
    """
    es_candidato_duplicado = (resultado["accion"] == "candidato") & resultado[
        "CODIGO_INTERNO"
    ].duplicated(keep=False)
    resultado.loc[es_candidato_duplicado, "motivo"] = (
        "CODIGO_INTERNO duplicado entre candidatos nuevos (posible medicamento "
        "combinado con varios principios activos) -- requiere decision de "
        "negocio antes de cargar, no se fusiona ni se descarta en automatico"
    )
    resultado.loc[es_candidato_duplicado, "accion"] = "cuarentena"
    return resultado


def auditar_coherencia_gemanet(
    df_invima: pd.DataFrame,
    archivo_gemma_net: Any,
    df_invima_vencidos: pd.DataFrame | None = None,
    df_invima_otros_estados: pd.DataFrame | None = None,
    df_invima_renovacion: pd.DataFrame | None = None,
    ruta_catalogo_unidad: str | Path = RUTA_CATALOGO_UNIDAD,
    ruta_catalogo_marca: str | Path = RUTA_CATALOGO_MARCA,
) -> pd.DataFrame:
    """Audita los medicamentos que YA existen en el Reporte de Gemma Net
    contra el catalogo INVIMA vigente, campo por campo (ver
    auditoria/coherencia_invima.py) -- distinto de `procesar_desde_catalogo_
    invima`, que arma candidatos NUEVOS. `df_invima` es el mismo catalogo
    crudo que esa funcion (API o archivo) -- se pasa ya cargado para no
    sincronizar el dataset completo de INVIMA dos veces en la misma corrida.

    `df_invima_vencidos` / `df_invima_otros_estados` / `df_invima_renovacion`
    (todos opcionales e independientes): catalogos de los datasets de
    VENCIDOS, OTROS ESTADOS y TRAMITE DE RENOVACION de INVIMA (mismo tipo
    que `df_invima`, ver `ingesta/invima_socrata.py::DATASET_CUM_VENCIDOS`/
    `DATASET_CUM_OTROS_ESTADOS`/`DATASET_CUM_RENOVACION`). Con estos, un
    codigo que no aparece en Vigentes se distingue entre "vencido" (riesgo
    alto), "otro estado" (riesgo alto, agrupa Cancelado/Suspendido/etc.),
    "en tramite de renovacion" (riesgo medio) y "sin correspondencia"
    (codigo legado) -- sin alguno, esa distincion puntual no esta disponible
    y cae en el siguiente estado de la cascada como antes.
    """
    reporte = leer_reporte_gemanet(archivo_gemma_net)
    catalogo_unidad = cargar_catalogo(cargar_catalogo_csv(ruta_catalogo_unidad))
    catalogo_marca = cargar_catalogo(
        cargar_catalogo_csv(ruta_catalogo_marca),
        normalizador=normalizar_entidad,
        dividir_sigla_descripcion=False,
    )
    resultado = auditar_coherencia(
        reporte.df,
        df_invima,
        catalogo_unidad,
        catalogo_marca,
        df_invima_vencidos=df_invima_vencidos,
        df_invima_otros_estados=df_invima_otros_estados,
        df_invima_renovacion=df_invima_renovacion,
    )
    # list(...) + [...] , no .extend(): resultado.attrs ya trae "advertencias_
    # calidad" (ver auditoria/coherencia_invima.py::_detectar_campos_
    # sistemicamente_no_diligenciados) -- se combinan en la misma lista que
    # ya lee la UI, en vez de agregar una clave nueva que habria que revisar
    # aparte.
    resultado.attrs["advertencias"] = list(reporte.advertencias) + resultado.attrs.get(
        "advertencias_calidad", []
    )
    return resultado


def guardar_reporte(df: pd.DataFrame, ruta: str | Path, columna_hoja: str = "accion") -> None:
    """Escribe el resultado de procesar_invima_vigentes() (o de
    auditar_coherencia_gemanet(), pasando columna_hoja="ESTADO_COHERENCIA")
    a un .xlsx con una hoja por valor distinto de `columna_hoja`, para que
    negocio pueda revisar sin tocar codigo. Antes de esto procesar_*() solo
    devolvia un DataFrame en memoria -- nadie fuera de una sesion de Python
    podia ver el resultado.
    """
    with pd.ExcelWriter(ruta, engine="openpyxl") as writer:
        for valor, grupo in df.groupby(columna_hoja):
            grupo.to_excel(writer, sheet_name=str(valor), index=False)
