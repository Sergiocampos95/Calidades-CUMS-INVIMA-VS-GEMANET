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
from gemma_cum_loader.catalogos.fuentes import (
    FuenteCatalogos,
    FuenteCatalogosConRespaldo,
)
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


def ejecutar_refresco(
    *,
    lector_gemanet: Callable[[], object] = leer_reporte_gemanet_db,
    lector_invima_api: Callable[..., pd.DataFrame] = leer_catalogo_invima_api,
    procesador: Callable[..., pd.DataFrame] = procesar_desde_catalogo_invima,
    auditor: Callable[..., pd.DataFrame] = auditar_coherencia_gemanet,
    clasificador: Callable[[pd.DataFrame], pd.DataFrame] = universo_invima_clasificado,
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

    `procesador`/`auditor` inyectables (ademas de los lectores): las
    pruebas de ESTE modulo verifican la orquestacion -- orden de llamadas,
    manejo de errores, que el snapshot se escriba -- no vuelven a probar la
    logica de negocio de `pipeline.py`, que ya tiene su propia suite.
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
        escribir_snapshot(
            {"candidatos": candidatos, "auditoria": auditoria, "universo": universo},
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
