"""Prueba `_ciclo()` (logging de un refresco exitoso/fallido) y
`_vigilar_solicitud_manual()` (adelanta la corrida cuando el backend pidio
un refresco manual) -- `main()` bloquea con `BlockingScheduler.start()` y no
es testeable sin levantar un scheduler real, ni tiene sentido hacerlo: es un
one-liner de configuracion que se verifica leyendo el codigo, no
ejecutandolo."""

from datetime import UTC

import worker.refresco as modulo
from worker.estado import ESTADO_ERROR, ESTADO_OK, EstadoRefresco


def test_ciclo_registra_info_cuando_el_refresco_sale_bien(monkeypatch, caplog):
    exitoso = EstadoRefresco("2026-08-27T10:00:00+00:00", "2026-08-27T10:01:00+00:00", 60.0, ESTADO_OK)
    monkeypatch.setattr(modulo, "ejecutar_refresco", lambda: exitoso)

    with caplog.at_level("INFO", logger="worker.refresco"):
        modulo._ciclo()

    assert any("terminado" in r.message for r in caplog.records)
    assert not any(r.levelname == "ERROR" for r in caplog.records)


def test_ciclo_registra_error_cuando_el_refresco_falla(monkeypatch, caplog):
    fallido = EstadoRefresco(
        "2026-08-27T10:00:00+00:00", "2026-08-27T10:01:00+00:00", 60.0, ESTADO_ERROR, "boom"
    )
    monkeypatch.setattr(modulo, "ejecutar_refresco", lambda: fallido)

    with caplog.at_level("INFO", logger="worker.refresco"):
        modulo._ciclo()

    mensajes_error = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert any("boom" in m for m in mensajes_error)


class _SchedulerFalso:
    """Doble minimo -- solo lo que `_vigilar_solicitud_manual` usa. No se
    levanta un BlockingScheduler real (bloquearia la prueba)."""

    def __init__(self):
        self.timezone = UTC
        self.llamadas_modify_job = []

    def modify_job(self, job_id, next_run_time=None):
        self.llamadas_modify_job.append((job_id, next_run_time))


def test_vigilar_no_hace_nada_sin_solicitud_pendiente(monkeypatch):
    monkeypatch.setattr(modulo, "hay_solicitud_pendiente", lambda: False)
    limpiezas = []
    monkeypatch.setattr(modulo, "limpiar_solicitud_pendiente", lambda: limpiezas.append(True))
    scheduler = _SchedulerFalso()

    modulo._vigilar_solicitud_manual(scheduler)

    assert scheduler.llamadas_modify_job == []
    assert limpiezas == []


def test_vigilar_adelanta_la_corrida_y_limpia_la_solicitud(monkeypatch):
    monkeypatch.setattr(modulo, "hay_solicitud_pendiente", lambda: True)
    limpiezas = []
    monkeypatch.setattr(modulo, "limpiar_solicitud_pendiente", lambda: limpiezas.append(True))
    scheduler = _SchedulerFalso()

    modulo._vigilar_solicitud_manual(scheduler)

    assert limpiezas == [True]
    assert len(scheduler.llamadas_modify_job) == 1
    job_id, next_run_time = scheduler.llamadas_modify_job[0]
    assert job_id == modulo.ID_JOB_PRINCIPAL
    assert next_run_time is not None
