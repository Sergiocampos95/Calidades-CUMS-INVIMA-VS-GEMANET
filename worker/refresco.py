"""Entrypoint del worker: agenda `tareas.ejecutar_refresco()` cada
~50 minutos, independiente de que alguien tenga el navegador abierto.

Uso:

    python -m worker.refresco

`apscheduler` en vez de un `while True: sleep(...)` a mano porque ya
resuelve, sin reinventarlo, lo que un refresco de datos de produccion
necesita:

- `max_instances=1`: si un refresco tarda mas de 50 minutos (poco probable,
  pero la auditoria completa toma varios minutos), la siguiente ejecucion
  programada NO arranca encima -- se salta, no se solapa. Solapar dos
  corridas escribiendo snapshots a la vez seria exactamente el tipo de
  condicion de carrera que el patron de puntero atomico de
  `almacen_snapshots.py` ya evita para UNA escritura, pero no para dos
  simultaneas.
- `coalesce=True`: si el proceso estuvo dormido/pausado y se "debieron"
  varias ejecuciones, corre una sola al despertar, no todas las perdidas de
  una.

Sin Celery/Redis: es una sola tarea periodica en un solo proceso, sin
necesidad de un broker externo -- infraestructura que este proyecto no
tiene hoy (no hay Docker/K8s). Si el proceso muere, se relanza con el
supervisor del sistema operativo (Task Scheduler en Windows, o el
equivalente), no con logica propia -- no reinventar supervision de
procesos aca.
"""

from __future__ import annotations

import logging
import sys

from apscheduler.schedulers.blocking import BlockingScheduler

from worker.estado import ESTADO_ERROR
from worker.tareas import ejecutar_refresco

INTERVALO_MINUTOS = 50

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
_log = logging.getLogger("worker.refresco")


def _ciclo() -> None:
    _log.info("Arrancando refresco...")
    evento = ejecutar_refresco()
    if evento.estado == ESTADO_ERROR:
        _log.error(
            "Refresco fallido en %.1fs: %s", evento.duracion_segundos, evento.detalle_error
        )
    else:
        _log.info("Refresco terminado en %.1fs", evento.duracion_segundos)


def main() -> None:
    scheduler = BlockingScheduler()
    # Sin `start_date`: el trigger de intervalo de apscheduler dispara la
    # PRIMERA corrida de inmediato (start_date por defecto es "ahora") y
    # despues cada INTERVALO_MINUTOS -- exactamente lo que hace falta: un
    # proceso reiniciado (deploy, crash) no se queda hasta 50 min sin
    # snapshot nuevo aunque los datos de origen ya hayan cambiado.
    scheduler.add_job(
        _ciclo,
        "interval",
        minutes=INTERVALO_MINUTOS,
        max_instances=1,
        coalesce=True,
    )
    _log.info("Worker arrancado -- refresco cada %s minutos.", INTERVALO_MINUTOS)
    scheduler.start()


if __name__ == "__main__":
    main()
