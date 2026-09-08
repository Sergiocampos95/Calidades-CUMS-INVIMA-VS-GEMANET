"""Prueba `_ciclo()` (logging de un refresco exitoso/fallido) y
`_vigilar_solicitud_manual()` (adelanta la corrida cuando el backend pidio
un refresco manual) -- `main()` bloquea con `BlockingScheduler.start()` y no
es testeable sin levantar un scheduler real, ni tiene sentido hacerlo: es un
one-liner de configuracion que se verifica leyendo el codigo, no
ejecutandolo."""

from datetime import UTC

import worker.refresco as modulo
from worker.estado import ESTADO_ERROR, ESTADO_OK, EstadoRefresco


def _sin_leer_el_estado_real(monkeypatch, fuente="archivos") -> None:
    """`_ciclo` consulta de que fuente leer INVIMA, y esa consulta va al
    SQLite real de `data_runtime/` si no se intercepta. Igual que el latido:
    pytest no toca archivos de produccion (regla del proyecto)."""
    monkeypatch.setattr(modulo, "fuente_refresco", lambda defecto=None: fuente)


def test_ciclo_registra_info_cuando_el_refresco_sale_bien(monkeypatch, caplog):
    _sin_leer_el_estado_real(monkeypatch)
    exitoso = EstadoRefresco("2026-08-27T10:00:00+00:00", "2026-08-27T10:01:00+00:00", 60.0, ESTADO_OK)
    monkeypatch.setattr(modulo, "ejecutar_refresco", lambda **_: exitoso)

    with caplog.at_level("INFO", logger="worker.refresco"):
        modulo._ciclo()

    assert any("terminado" in r.message for r in caplog.records)
    assert not any(r.levelname == "ERROR" for r in caplog.records)


def test_ciclo_registra_error_cuando_el_refresco_falla(monkeypatch, caplog):
    _sin_leer_el_estado_real(monkeypatch)
    fallido = EstadoRefresco(
        "2026-08-27T10:00:00+00:00", "2026-08-27T10:01:00+00:00", 60.0, ESTADO_ERROR, "boom"
    )
    monkeypatch.setattr(modulo, "ejecutar_refresco", lambda **_: fallido)

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


def _sin_tocar_el_estado_real(monkeypatch) -> list[bool]:
    """`registrar_latido_worker()` se llama SIN ruta, asi que escribe en
    `RUTA_ESTADO_DEFECTO` -- el SQLite real de `data_runtime/`. Sin este
    monkeypatch la suite le mete un latido a produccion y `worker_vivo()`
    empieza a decir que hay un worker corriendo cuando no lo hay, que es
    exactamente lo que el guard de POST /refrescar necesita detectar. Pasó
    (2026-09-07) y por eso queda como helper compartido: la regla del proyecto
    es que pytest nunca toca archivos reales."""
    latidos: list[bool] = []
    monkeypatch.setattr(modulo, "registrar_latido_worker", lambda: latidos.append(True))
    return latidos


def test_vigilar_no_hace_nada_sin_solicitud_pendiente(monkeypatch):
    latidos = _sin_tocar_el_estado_real(monkeypatch)
    monkeypatch.setattr(modulo, "hay_solicitud_pendiente", lambda: False)
    limpiezas = []
    monkeypatch.setattr(modulo, "limpiar_solicitud_pendiente", lambda: limpiezas.append(True))
    scheduler = _SchedulerFalso()

    modulo._vigilar_solicitud_manual(scheduler)

    assert scheduler.llamadas_modify_job == []
    assert limpiezas == []
    # Late IGUAL sin solicitud: el latido dice "sigo vivo", no "estoy haciendo
    # algo". Si solo latiera al haber solicitud, el backend daria el worker
    # por caido justo cuando esta ocioso y esperando.
    assert latidos == [True]


def test_vigilar_adelanta_la_corrida_y_limpia_la_solicitud(monkeypatch):
    latidos = _sin_tocar_el_estado_real(monkeypatch)
    monkeypatch.setattr(modulo, "hay_solicitud_pendiente", lambda: True)
    limpiezas = []
    monkeypatch.setattr(modulo, "limpiar_solicitud_pendiente", lambda: limpiezas.append(True))
    scheduler = _SchedulerFalso()

    modulo._vigilar_solicitud_manual(scheduler)

    assert latidos == [True]
    assert limpiezas == [True]
    assert len(scheduler.llamadas_modify_job) == 1
    job_id, next_run_time = scheduler.llamadas_modify_job[0]
    assert job_id == modulo.ID_JOB_PRINCIPAL
    assert next_run_time is not None


def test_el_ciclo_aplica_la_fuente_elegida_y_no_siempre_la_api(monkeypatch, caplog):
    """El ciclo PERIODICO tambien respeta la fuente anotada, no solo el
    refresco manual: si alguien dejo la auditoria sobre los listados en
    archivo para explicar unas cifras, que la corrida de los 50 minutos se las
    cambie por las de la API sin avisar volveria imposible esa explicacion."""
    _sin_leer_el_estado_real(monkeypatch, fuente="archivos")
    recibidos = {}
    monkeypatch.setattr(
        modulo,
        "ejecutar_refresco",
        lambda **kwargs: recibidos.update(kwargs)
        or EstadoRefresco("a", "b", 1.0, ESTADO_OK),
    )

    with caplog.at_level("INFO", logger="worker.refresco"):
        modulo._ciclo()

    # "archivos" -> un lector concreto; la API es None (que ejecutar_refresco
    # interpreta como "construi el LectorInvimaConRespaldo por defecto").
    assert callable(recibidos["lector_invima_api"])
    assert any("archivos" in r.message for r in caplog.records)


class _SchedulerCapturador:
    """Captura los add_job de `main()` sin levantar un scheduler real."""

    def __init__(self):
        self.jobs = []
        self.iniciado = False

    def add_job(self, funcion, disparador, **kwargs):
        self.jobs.append((funcion, disparador, kwargs))

    def start(self):
        self.iniciado = True


def test_la_primera_corrida_es_inmediata_no_dentro_de_50_minutos(monkeypatch):
    """Defecto real encontrado el 2026-09-07: el `IntervalTrigger` de
    apscheduler SIN `start_date` no arranca "ahora" sino en `ahora +
    intervalo`, asi que un worker recien levantado se quedaba 50 minutos sin
    refrescar -- justo lo contrario de lo que el comentario del codigo decia.

    No se notaba porque en la practica se pulsaba "Actualizar ahora" enseguida
    y eso adelanta el job, tapando el sintoma. Por eso se fija aca: el unico
    momento en que se ve es un worker que nadie toca."""
    capturador = _SchedulerCapturador()
    monkeypatch.setattr(modulo, "BlockingScheduler", lambda: capturador)

    modulo.main()

    principal = [j for j in capturador.jobs if j[2].get("id") == modulo.ID_JOB_PRINCIPAL]
    assert len(principal) == 1
    assert principal[0][2].get("next_run_time") is not None, (
        "sin next_run_time la primera corrida se va a 50 minutos"
    )
