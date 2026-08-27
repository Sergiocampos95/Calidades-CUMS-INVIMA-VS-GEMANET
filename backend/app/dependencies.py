"""Regla de arquitectura de esta capa -- NO NEGOCIABLE (ver el plan de
migracion en `.claude/plans`):

El backend NUNCA importa `gemma_cum_loader.integraciones.gemanet_db` ni
`gemma_cum_loader.catalogos.fuentes` directo, y NUNCA ejecuta
`gemma_cum_loader.pipeline.procesar_desde_catalogo_invima` /
`auditar_coherencia_gemanet` dentro de un request HTTP. Ese trabajo (leer
INVIMA/Gemma Net, correr el pipeline completo -- minutos, no milisegundos)
es exclusivo de `worker/tareas.py`, que corre una vez cada ~50 min fuera
del ciclo de request/response.

Por que importa: si un endpoint alguna vez "para no esperar al worker"
termina llamando a `gemanet_db.consultar()` directo, dos problemas
aparecen a la vez -- (1) un request HTTP queda bloqueado varios minutos, y
(2) cada request concurrente abre su propia conexion a Postgres sin pool
(ver `gemanet_db.py`, pensado para UNA llamada secuencial por corrida, no
para trafico concurrente). El backend es un LECTOR delgado sobre
`worker/almacen_snapshots.py` -- nada mas.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from worker.almacen_snapshots import CARPETA_SNAPSHOTS_DEFECTO
from worker.estado import RUTA_ESTADO_DEFECTO


@lru_cache(maxsize=1)
def carpeta_snapshots() -> Path:
    return CARPETA_SNAPSHOTS_DEFECTO


@lru_cache(maxsize=1)
def ruta_estado() -> Path:
    return RUTA_ESTADO_DEFECTO
