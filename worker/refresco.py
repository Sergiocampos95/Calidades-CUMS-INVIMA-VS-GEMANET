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
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from worker.estado import (
    ESTADO_ERROR,
    hay_solicitud_pendiente,
    limpiar_solicitud_pendiente,
)
from worker.tareas import ejecutar_refresco

INTERVALO_MINUTOS = 50
ID_JOB_PRINCIPAL = "refresco_periodico"
# Cada cuanto se revisa si alguien pidio un refresco manual (POST
# /refrescar del backend) -- pedido del usuario (2026-08-27): "ya no hace
# falta un boton... esto si no tendra problema en demora porque ya depende
# del usuario si quiere hacer la espera". Unos pocos segundos de reaccion
# son aceptables frente a los ~87s que ya tarda la corrida completa.
INTERVALO_VIGILANCIA_SEGUNDOS = 5

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


def _vigilar_solicitud_manual(scheduler: BlockingScheduler) -> None:
    """Corre cada `INTERVALO_VIGILANCIA_SEGUNDOS`: si el backend escribio una
    solicitud de refresco manual (unica via de comunicacion entre los dos
    procesos -- un flag en `estado_worker.sqlite3`, mismo patron de
    archivo/SQLite que ya usa el resto del proyecto, sin agregar un broker
    ni un segundo servidor HTTP), adelanta la corrida periodica a AHORA en
    vez de esperar hasta 50 minutos. `max_instances=1` en el job principal
    sigue protegiendo contra que esto se solape con una corrida ya en
    curso -- es el MISMO job, apscheduler simplemente no dispara una
    segunda instancia por encima."""
    if hay_solicitud_pendiente():
        limpiar_solicitud_pendiente()
        _log.info("Solicitud de refresco manual detectada -- adelantando la corrida.")
        # tz del propio scheduler, no UTC fijo -- next_run_time tiene que
        # calzar con la zona horaria que ya usa internamente para comparar
        # contra la proxima corrida programada.
        scheduler.modify_job(ID_JOB_PRINCIPAL, next_run_time=datetime.now(scheduler.timezone))


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
        id=ID_JOB_PRINCIPAL,
    )
    scheduler.add_job(
        _vigilar_solicitud_manual,
        "interval",
        seconds=INTERVALO_VIGILANCIA_SEGUNDOS,
        args=[scheduler],
        max_instances=1,
    )
    _log.info(
        "Worker arrancado -- refresco cada %s minutos (o antes, si se pide manual).",
        INTERVALO_MINUTOS,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
