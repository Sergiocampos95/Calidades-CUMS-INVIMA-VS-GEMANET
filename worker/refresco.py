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

from gemma_cum_loader.ingesta.fuente_invima import FUENTE_DEFECTO, lector_para_fuente
from worker.estado import (
    ESTADO_ERROR,
    fuente_refresco,
    hay_solicitud_pendiente,
    limpiar_solicitud_pendiente,
    registrar_latido_worker,
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
    # La fuente la elige quien pide el refresco desde la UI (POST /refrescar
    # ?fuente=...) y queda anotada en `control`. El ciclo PERIODICO la lee
    # igual, a proposito: si alguien puso la auditoria sobre los listados de
    # archivo para explicar unas cifras, que el refresco automatico de 50
    # minutos se las cambie por las de la API sin avisar seria justo el
    # cambio silencioso que hace imposible sostener una explicacion.
    fuente = fuente_refresco(defecto=FUENTE_DEFECTO)
    _log.info("Arrancando refresco (fuente de INVIMA: %s)...", fuente)
    evento = ejecutar_refresco(lector_invima_api=lector_para_fuente(fuente))
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
    # Late SIEMPRE, haya solicitud o no: es lo que le permite al backend
    # distinguir "worker trabajando" de "worker caido" y no aceptar un boton
    # que nadie va a atender (ver `registrar_latido_worker`).
    registrar_latido_worker()
    if hay_solicitud_pendiente():
        limpiar_solicitud_pendiente()
        _log.info("Solicitud de refresco manual detectada -- adelantando la corrida.")
        # tz del propio scheduler, no UTC fijo -- next_run_time tiene que
        # calzar con la zona horaria que ya usa internamente para comparar
        # contra la proxima corrida programada.
        scheduler.modify_job(ID_JOB_PRINCIPAL, next_run_time=datetime.now(scheduler.timezone))


def main() -> None:
    scheduler = BlockingScheduler()
    # `next_run_time=ahora` es OBLIGATORIO para que la primera corrida sea
    # inmediata. El comentario que habia aca afirmaba que apscheduler ya lo
    # hacia solo ("start_date por defecto es ahora"), y es FALSO: el
    # IntervalTrigger sin `start_date` arranca en `ahora + intervalo`, o sea
    # que un worker recien levantado se quedaba 50 MINUTOS sin refrescar.
    #
    # Verificado el 2026-09-07: worker arrancado, el job de vigilancia (5 s)
    # corriendo una y otra vez en el log, y `_ciclo` sin ejecutarse ni una
    # vez. No se habia notado porque en la practica siempre se pulsaba
    # "Actualizar ahora" enseguida, y ESO si adelanta el job
    # (`_vigilar_solicitud_manual` -> modify_job), tapando el sintoma.
    #
    # Importa justo cuando mas duele: un proceso reiniciado (deploy, crash,
    # corte) no debe quedarse casi una hora sirviendo el snapshot viejo, que
    # es exactamente lo que el intervalo venia a evitar.
    scheduler.add_job(
        _ciclo,
        "interval",
        minutes=INTERVALO_MINUTOS,
        max_instances=1,
        coalesce=True,
        id=ID_JOB_PRINCIPAL,
        next_run_time=datetime.now(),
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
