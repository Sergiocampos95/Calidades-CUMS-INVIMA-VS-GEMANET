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
from gemma_cum_loader.ingesta.invima_socrata import (
    DATASET_CUM_OTROS_ESTADOS,
    DATASET_CUM_RENOVACION,
    DATASET_CUM_VENCIDOS,
    leer_catalogo_invima_api,
)
from gemma_cum_loader.pipeline import (
    auditar_coherencia_gemanet,
    procesar_desde_catalogo_invima,
)
from worker.almacen_snapshots import escribir_snapshot
from worker.estado import ESTADO_ERROR, ESTADO_OK, EstadoRefresco, registrar_refresco


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


def ejecutar_refresco(
    *,
    lector_gemanet: Callable[[], object] = leer_reporte_gemanet_db,
    lector_invima_api: Callable[..., pd.DataFrame] = leer_catalogo_invima_api,
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

    `procesador`/`auditor`/`clasificador`/`localizador_malla`/`lector_malla`
    inyectables (ademas de los lectores de fuentes externas): las pruebas de
    ESTE modulo verifican la orquestacion -- orden de llamadas, manejo de
    errores, que el snapshot se escriba -- no vuelven a probar la logica de
    negocio de `pipeline.py`/`reglas_negocio.py`, que ya tienen su propia
    suite.
    """
    inicio = datetime.now(UTC)
    fuente = fuente_catalogos if fuente_catalogos is not None else FuenteCatalogosConRespaldo()

    try:
        reporte_gemanet = lector_gemanet()
        df_invima = lector_invima_api()
        df_invima_vencidos = lector_invima_api(dataset=DATASET_CUM_VENCIDOS)
        df_invima_otros_estados = lector_invima_api(dataset=DATASET_CUM_OTROS_ESTADOS)
        df_invima_renovacion = lector_invima_api(dataset=DATASET_CUM_RENOVACION)

        candidatos = procesador(df_invima, reporte_gemanet, fuente_catalogos=fuente)
        auditoria = auditor(
            df_invima,
            reporte_gemanet,
            df_invima_vencidos,
            df_invima_otros_estados=df_invima_otros_estados,
            df_invima_renovacion=df_invima_renovacion,
            fuente_catalogos=fuente,
        )
        # Universo COMPLETO de INVIMA clasificado (los 101.183 registros del
        # corte, no solo los "candidato") -- alimenta la sub-vista "Detalle
        # por registro". candidatos_creacion() ya lo calcula internamente
        # pero descarta las filas que no son candidato; se recalcula aca
        # sobre el mismo df_invima ya en memoria, sin releer nada.
        universo = clasificador(df_invima)
        tablas_cargue = _tablas_cargue(candidatos, localizador_malla, lector_malla)

        escribir_snapshot(
            {"candidatos": candidatos, "auditoria": auditoria, "universo": universo, **tablas_cargue},
            carpeta=carpeta_snapshots,
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
