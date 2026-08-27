"""Solo prueba `_ciclo()` (el logging de un refresco exitoso/fallido) --
`main()` bloquea con `BlockingScheduler.start()` y no es testeable sin
levantar un scheduler real, ni tiene sentido hacerlo: es un one-liner de
configuracion que se verifica leyendo el codigo, no ejecutandolo."""

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
