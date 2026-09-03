"""La unidad de trabajo del refresco periodico: lee INVIMA (API de Socrata,
los 4 datasets) y Gemma Net (base en vivo), corre el mismo pipeline que ya
usa la UI (`procesar_desde_catalogo_invima` / `auditar_coherencia_gemanet`
de `gemma_cum_loader.pipeline` -- no se reimplementa nada de negocio aca),
y deja el resultado en un snapshot que Streamlit/backend puedan leer sin
volver a golpear Gemma Net ni Socrata.

Cada dependencia externa (lector de Gemma Net, lector de INVIMA, fuente de
catalogos) es inyectable -- mismo patron que ya usa el resto del proyecto
(`ClienteExplicacionIA(client=...)`, `gemanet_db.consultar(conexion=...)`)
para que las pruebas nunca toquen Postgres ni Socrata reales.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from gemma_cum_loader.armado.malla import universo_invima_clasificado
from gemma_cum_loader.armado.reglas_negocio import (
    ReglasNegocio,
    derivar_reglas_negocio,
    leer_malla_referencia,
)
from gemma_cum_loader.catalogos.fuentes import (
    FuenteCatalogos,
    FuenteCatalogosConRespaldo,
)
from gemma_cum_loader.exportacion.cargue import (
    evaluar_candidatos_cargue,
    preparar_filas_cargue,
)
from gemma_cum_loader.exportacion.estructura_cargue import armar_estructura_cargue
from gemma_cum_loader.ingesta.almacen_local import descubrir_todo
from gemma_cum_loader.ingesta.gemanet_sql import leer_reporte_gemanet_db
from gemma_cum_loader.ingesta.invima_con_respaldo import LectorInvimaConRespaldo
from gemma_cum_loader.ingesta.invima_socrata import (
    DATASET_CUM_OTROS_ESTADOS,
    DATASET_CUM_RENOVACION,
    DATASET_CUM_VENCIDOS,
)
from gemma_cum_loader.pipeline import (
    auditar_coherencia_gemanet,
    procesar_desde_catalogo_invima,
)
from worker.almacen_snapshots import escribir_snapshot
from worker.estado import (
    ESTADO_ERROR,
    ESTADO_OK,
    ESTADO_PASO_EN_CURSO,
    ESTADO_PASO_ERROR,
    ESTADO_PASO_HECHO,
    EstadoRefresco,
    actualizar_paso,
    iniciar_progreso,
    registrar_refresco,
)

# Los pasos visibles del refresco -- "una lista mostrando uno a uno los
# procesos que se van haciendo" (pedido del usuario, 2026-08-27). Nombres
# de negocio, no de funcion: son los que ve la persona que hizo clic en
# "Actualizar ahora", no un desarrollador leyendo el codigo.
NOMBRES_PASOS_REFRESCO = (
    "Leyendo reporte de Gemma Net",
    "Leyendo INVIMA -- Vigentes",
    "Leyendo INVIMA -- Vencidos",
    "Leyendo INVIMA -- Otros Estados",
    "Leyendo INVIMA -- Renovacion",
    "Cruzando candidatos contra Gemma Net",
    "Auditando coherencia contra INVIMA",
    "Clasificando universo INVIMA",
    "Derivando reglas de cargue",
    "Guardando snapshot",
)


def _localizar_malla_referencia_defecto() -> str | None:
    """Ruta de la "Estructura Cargue Medicamentos" si `descubrir_todo()` la
    encuentra en `data/` -- mismo autodescubrimiento que ya usa la UI, asi
    que no hace falta configurar una ruta aparte para el worker."""
    hallado = descubrir_todo().get("estructura_cargue")
    return str(hallado.ruta) if hallado is not None else None


def _tablas_cargue(
    candidatos: pd.DataFrame,
    localizador_malla: Callable[[], str | None],
    lector_malla: Callable[[str], pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Las 4 tablas de la seccion "Cargue a Gemma Net" (Auditoria de
    estructura + Excel de cargue final), o un dict vacio si no hay
    Estructura Cargue Medicamentos disponible -- degradacion explicita:
    sin esa malla de referencia no hay con que derivar POS/Modelo de
    Servicio/edad/copagos, y no se inventa un valor por defecto (ver
    armado/reglas_negocio.py). El resto del snapshot (candidatos, auditoria,
    universo) se guarda igual aunque esto falte.
    """
    ruta_malla = localizador_malla()
    if ruta_malla is None:
        return {}

    malla_referencia = lector_malla(ruta_malla)
    reglas: ReglasNegocio = derivar_reglas_negocio(malla_referencia)
    evaluados = evaluar_candidatos_cargue(candidatos, reglas)
    estructura = armar_estructura_cargue(candidatos, reglas)
    # preparar_filas_cargue ya se encarga de filtrar a "listos" y arma las
    # columnas correctas incluso con 0 filas -- no reemplazarlo con un
    # DataFrame vacio de OTRO esquema (bug real: `estructura` trae 4
    # columnas de auditoria -- ESTADO, CAMPOS_CON_ERROR... -- que no
    # pertenecen al Excel de cargue final).
    cargue_final = preparar_filas_cargue(candidatos, reglas)

    return {
        "cargue_evaluados": evaluados,
        "cargue_estructura": estructura,
        "cargue_final": cargue_final,
        # dict[str, str] no es una tabla de negocio, pero se persiste igual
        # como DataFrame chico -- mismo mecanismo que todo lo demas del
        # snapshot, sin inventar un segundo formato de archivo para esto.
        "cargue_reglas_advertencias": pd.DataFrame(
            list(reglas.advertencias.items()), columns=["campo", "advertencia"]
        ),
    }


# Rotulo de negocio de cada dataset de INVIMA -- el MISMO vocabulario cerrado
# que usa ESTADO_LISTADO_INVIMA en auditoria/coherencia_invima.py
# (_MAPA_ESTADO_LISTADO_INVIMA), para que la consulta puntual y la auditoria
# no digan el estado de dos formas distintas.
LISTADO_VIGENTE = "vigente"
LISTADO_VENCIDO = "vencido"
LISTADO_RENOVACION = "renovacion"
LISTADO_OTROS_ESTADOS = "otros_estados"


def _listados_invima_unificados(
    df_invima: pd.DataFrame,
    df_invima_vencidos: pd.DataFrame | None,
    df_invima_otros_estados: pd.DataFrame | None,
    df_invima_renovacion: pd.DataFrame | None,
) -> pd.DataFrame:
    """Los 4 datasets de INVIMA en una sola tabla, con una columna `LISTADO`
    que dice de cual salio cada fila.

    Por que existe: hasta ahora el snapshot solo persistia `universo`, que es
    `universo_invima_clasificado(df_invima)` -- **solo Vigentes**. Los otros
    tres se leian, se usaban para marcar ESTADO_COHERENCIA y se descartaban.
    Consecuencia real (caso 20102710-2, un CUM que vive solo en Vencidos): la
    consulta puntual mostraba la tabla de Gemma Net y NINGUNA fila de INVIMA,
    aunque el diagnostico de arriba dijera "Vencido y activo" -- la aplicacion
    sabia la respuesta y no podia mostrar la evidencia.

    No lee nada nuevo: los 4 DataFrames ya estan en memoria en
    `ejecutar_refresco`. Los 4 comparten las mismas 29 columnas (todos pasan
    por `leer_catalogo_invima_api`, solo cambia el `dataset` -- verificado
    contra los respaldos reales), asi que el concat no desalinea nada; un
    dataset ausente (los 3 auxiliares son opcionales e independientes)
    simplemente no aporta filas, en vez de romper el refresco completo.

    Comparten los NOMBRES de columna, pero no siempre el TIPO: Socrata
    entrega el mismo campo unas veces entrecomillado y otras no, asi que
    `EXPEDIENTE` llega como texto en unos datasets y como entero en otros
    (medido 2026-09-03: 311.159 str contra 112.969 int en la misma columna).
    El concat los deja convivir en una columna `object` y `to_parquet`
    revienta al inferir el esquema ("Expected bytes, got a 'int' object" /
    "Could not convert '19916871' with type str"). Reventaba en el ULTIMO
    paso del refresco, tirando los 3 minutos de trabajo previos, y de forma
    intermitente: dependia de que a esa corrida le tocara la mezcla, asi que
    la corrida siguiente parecia sana y el defecto quedaba latente.
    Por eso se normalizan a texto antes de escribir -- ver `_a_texto_estable`.
    """
    partes = []
    for etiqueta, df in (
        (LISTADO_VIGENTE, df_invima),
        (LISTADO_VENCIDO, df_invima_vencidos),
        (LISTADO_OTROS_ESTADOS, df_invima_otros_estados),
        (LISTADO_RENOVACION, df_invima_renovacion),
    ):
        if df is None or df.empty:
            continue
        parte = df.copy()
        parte["LISTADO"] = etiqueta
        partes.append(parte)
    if not partes:
        # Degradacion explicita: sin ningun listado no se inventa una tabla
        # vacia con columnas adivinadas -- se devuelve vacia y quien la lea
        # vera que no hay nada, no un esquema falso.
        return pd.DataFrame()
    return _a_texto_estable(pd.concat(partes, ignore_index=True))


def _a_texto_estable(df: pd.DataFrame) -> pd.DataFrame:
    """Pasa a texto las columnas que quedaron con tipos de Python MEZCLADOS
    (int y str a la vez), que es lo que hace fallar a `to_parquet`.

    Solo toca esas: una columna homogenea -- aunque sea `object` con puros
    str -- se deja igual, porque convertir de mas cambiaria el tipo de datos
    que hoy se guardan bien y no hay razon para tocarlos.

    `infer_dtype` responde "mixed" / "mixed-integer" sin recorrer el
    DataFrame en Python (va en C), que importa con 424.128 filas por 29
    columnas. El valor se normaliza con `str`, no con `astype(str)`, para no
    convertir los nulos en la cadena "nan"."""
    for columna in df.columns:
        if df[columna].dtype != object:
            continue
        if not pd.api.types.infer_dtype(df[columna], skipna=True).startswith("mixed"):
            continue
        df[columna] = df[columna].map(lambda v: v if pd.isna(v) else str(v))
    return df


def _paso(nombre, funcion, /, *args, ruta_estado=None, **kwargs):
    """Envuelve un paso del refresco: lo marca en_curso antes de llamarlo,
    hecho despues, error (con el detalle) si revienta -- y lo vuelve a
    lanzar, para que el try/except de `ejecutar_refresco` siga registrando
    el resultado final como ya hacia. Un solo lugar que arma esto para que
    los 10 pasos no repitan el mismo par de llamadas a `actualizar_paso`."""
    actualizar_paso(nombre, ESTADO_PASO_EN_CURSO, ruta=ruta_estado)
    try:
        resultado = funcion(*args, **kwargs)
    except Exception as exc:
        actualizar_paso(
            nombre, ESTADO_PASO_ERROR, detalle=f"{type(exc).__name__}: {exc}", ruta=ruta_estado
        )
        raise
    actualizar_paso(nombre, ESTADO_PASO_HECHO, ruta=ruta_estado)
    return resultado


def _leer_invima(nombre, lector_invima_api, lector_con_respaldo, *, dataset=None, ruta_estado=None):
    """`_paso()` para un dataset de INVIMA + nota informativa si
    `lector_con_respaldo` (LectorInvimaConRespaldo) tuvo que caer al
    archivo local -- el paso sigue en `hecho` (el dato SI llego, solo con
    otro origen), no en error."""
    n_advertencias_antes = len(lector_con_respaldo.advertencias) if lector_con_respaldo is not None else 0
    kwargs = {} if dataset is None else {"dataset": dataset}
    resultado = _paso(nombre, lector_invima_api, ruta_estado=ruta_estado, **kwargs)
    if lector_con_respaldo is not None:
        nuevas = lector_con_respaldo.advertencias[n_advertencias_antes:]
        if nuevas:
            actualizar_paso(nombre, ESTADO_PASO_HECHO, detalle=nuevas[-1], ruta=ruta_estado)
    return resultado


def ejecutar_refresco(
    *,
    lector_gemanet: Callable[[], object] = leer_reporte_gemanet_db,
    lector_invima_api: Callable[..., pd.DataFrame] | None = None,
    procesador: Callable[..., pd.DataFrame] = procesar_desde_catalogo_invima,
    auditor: Callable[..., pd.DataFrame] = auditar_coherencia_gemanet,
    clasificador: Callable[[pd.DataFrame], pd.DataFrame] = universo_invima_clasificado,
    localizador_malla: Callable[[], str | None] = _localizar_malla_referencia_defecto,
    lector_malla: Callable[[str], pd.DataFrame] = leer_malla_referencia,
    fuente_catalogos: FuenteCatalogos | None = None,
    carpeta_snapshots: Path | None = None,
    ruta_estado: Path | None = None,
) -> EstadoRefresco:
    """Corre una vez el ciclo completo: leer -> procesar -> auditar ->
    guardar snapshot -> registrar salud. Nunca deja una excepcion sin
    registrar: si algo falla, se guarda como `ESTADO_ERROR` con el detalle,
    en vez de que el proceso muera en silencio y el proximo refresco
    programado sea la unica pista de que algo anduvo mal.

    `fuente_catalogos=None` construye `FuenteCatalogosConRespaldo()` (base
    de Gemma Net, con respaldo automatico a CSV si falla) -- la misma
    politica que ya usa la UI cuando el usuario elige "en vivo".

    `lector_invima_api=None` construye `LectorInvimaConRespaldo()`: intenta
    Socrata y, si falla (`ErrorSocrata`), cae al archivo local mas reciente
    en `data/` -- caso real 2026-08-28, outage de Socrata en el dataset de
    Vigentes ('i7cb-raxc' devolviendo 0 filas) tumbaba el refresco completo
    aunque hubiera un Excel/parquet local perfectamente utilizable. Las
    pruebas inyectan un callable simple (sin respaldo) para no depender de
    `data/` real.

    `procesador`/`auditor`/`clasificador`/`localizador_malla`/`lector_malla`
    inyectables (ademas de los lectores de fuentes externas): las pruebas de
    ESTE modulo verifican la orquestacion -- orden de llamadas, manejo de
    errores, que el snapshot se escriba -- no vuelven a probar la logica de
    negocio de `pipeline.py`/`reglas_negocio.py`, que ya tienen su propia
    suite.

    Cada paso se reporta a `worker/estado.py` (`iniciar_progreso`/
    `actualizar_paso`) para que GET /refrescar/progreso pueda mostrar "una
    lista uno a uno de los procesos que se van haciendo" (pedido del
    usuario, 2026-08-27) -- ver NOMBRES_PASOS_REFRESCO arriba.
    """
    inicio = datetime.now(UTC)
    fuente = fuente_catalogos if fuente_catalogos is not None else FuenteCatalogosConRespaldo()
    iniciar_progreso(list(NOMBRES_PASOS_REFRESCO), ruta=ruta_estado)

    # Solo si NO fue inyectado: guardamos la referencia para poder leer
    # `.advertencias` despues de cada llamada y anotar en el paso cuando
    # cayo al respaldo local -- un callable simple inyectado (pruebas) no
    # tiene ese atributo, por eso lector_con_respaldo queda None en ese caso.
    lector_con_respaldo: LectorInvimaConRespaldo | None = None
    if lector_invima_api is None:
        lector_con_respaldo = LectorInvimaConRespaldo()
        lector_invima_api = lector_con_respaldo.leer

    try:
        reporte_gemanet = _paso(
            "Leyendo reporte de Gemma Net", lector_gemanet, ruta_estado=ruta_estado
        )
        df_invima = _leer_invima(
            "Leyendo INVIMA -- Vigentes", lector_invima_api, lector_con_respaldo, ruta_estado=ruta_estado
        )
        df_invima_vencidos = _leer_invima(
            "Leyendo INVIMA -- Vencidos",
            lector_invima_api,
            lector_con_respaldo,
            dataset=DATASET_CUM_VENCIDOS,
            ruta_estado=ruta_estado,
        )
        df_invima_otros_estados = _leer_invima(
            "Leyendo INVIMA -- Otros Estados",
            lector_invima_api,
            lector_con_respaldo,
            dataset=DATASET_CUM_OTROS_ESTADOS,
            ruta_estado=ruta_estado,
        )
        df_invima_renovacion = _leer_invima(
            "Leyendo INVIMA -- Renovacion",
            lector_invima_api,
            lector_con_respaldo,
            dataset=DATASET_CUM_RENOVACION,
            ruta_estado=ruta_estado,
        )

        candidatos = _paso(
            "Cruzando candidatos contra Gemma Net",
            procesador,
            df_invima,
            reporte_gemanet,
            fuente_catalogos=fuente,
            ruta_estado=ruta_estado,
        )
        auditoria = _paso(
            "Auditando coherencia contra INVIMA",
            auditor,
            df_invima,
            reporte_gemanet,
            df_invima_vencidos,
            df_invima_otros_estados=df_invima_otros_estados,
            df_invima_renovacion=df_invima_renovacion,
            fuente_catalogos=fuente,
            ruta_estado=ruta_estado,
        )
        # Universo COMPLETO de INVIMA clasificado (los 101.183 registros del
        # corte, no solo los "candidato") -- alimenta la sub-vista "Detalle
        # por registro". candidatos_creacion() ya lo calcula internamente
        # pero descarta las filas que no son candidato; se recalcula aca
        # sobre el mismo df_invima ya en memoria, sin releer nada.
        universo = _paso(
            "Clasificando universo INVIMA", clasificador, df_invima, ruta_estado=ruta_estado
        )
        tablas_cargue = _paso(
            "Derivando reglas de cargue",
            _tablas_cargue,
            candidatos,
            localizador_malla,
            lector_malla,
            ruta_estado=ruta_estado,
        )

        # Los 4 listados de INVIMA tal cual, para que la consulta puntual
        # pueda encontrar un CUM en cualquiera de ellos y no solo en Vigentes
        # (ver _listados_invima_unificados). `universo` se conserva aparte:
        # es Vigentes YA CLASIFICADO, que es otra cosa y alimenta otra vista.
        invima_listados = _listados_invima_unificados(
            df_invima, df_invima_vencidos, df_invima_otros_estados, df_invima_renovacion
        )
        _paso(
            "Guardando snapshot",
            escribir_snapshot,
            {
                "candidatos": candidatos,
                "auditoria": auditoria,
                "universo": universo,
                "invima_listados": invima_listados,
                **tablas_cargue,
            },
            carpeta=carpeta_snapshots,
            ruta_estado=ruta_estado,
        )
        fin = datetime.now(UTC)
        evento = EstadoRefresco(
            inicio_utc=inicio.isoformat(),
            fin_utc=fin.isoformat(),
            duracion_segundos=(fin - inicio).total_seconds(),
            estado=ESTADO_OK,
        )
    except Exception as exc:
        fin = datetime.now(UTC)
        evento = EstadoRefresco(
            inicio_utc=inicio.isoformat(),
            fin_utc=fin.isoformat(),
            duracion_segundos=(fin - inicio).total_seconds(),
            estado=ESTADO_ERROR,
            detalle_error=f"{type(exc).__name__}: {exc}",
        )

    registrar_refresco(evento, ruta=ruta_estado)
    return evento
