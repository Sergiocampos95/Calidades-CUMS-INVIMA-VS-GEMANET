from worker.estado import (
    ESTADO_ERROR,
    ESTADO_OK,
    EstadoRefresco,
    registrar_refresco,
    ultimo_refresco,
)


def test_sin_refresco_previo_devuelve_none(tmp_path):
    ruta = tmp_path / "estado.sqlite3"
    assert ultimo_refresco(ruta) is None


def test_registrar_y_leer_el_ultimo_refresco(tmp_path):
    ruta = tmp_path / "estado.sqlite3"
    evento = EstadoRefresco(
        inicio_utc="2026-08-27T10:00:00+00:00",
        fin_utc="2026-08-27T10:03:00+00:00",
        duracion_segundos=180.0,
        estado=ESTADO_OK,
    )
    registrar_refresco(evento, ruta)

    leido = ultimo_refresco(ruta)
    assert leido == evento


def test_ultimo_refresco_devuelve_el_mas_reciente_no_el_primero(tmp_path):
    ruta = tmp_path / "estado.sqlite3"
    viejo = EstadoRefresco("2026-08-27T09:00:00+00:00", "2026-08-27T09:01:00+00:00", 60.0, ESTADO_OK)
    nuevo = EstadoRefresco(
        "2026-08-27T10:00:00+00:00",
        "2026-08-27T10:01:00+00:00",
        60.0,
        ESTADO_ERROR,
        "ErrorGemaNetDB: no responde",
    )
    registrar_refresco(viejo, ruta)
    registrar_refresco(nuevo, ruta)

    assert ultimo_refresco(ruta) == nuevo


def test_historial_de_fallos_se_conserva_no_se_sobrescribe(tmp_path):
    """El historial completo importa para diagnosticar -- ver cuantos
    refrescos seguidos vienen fallando -- no solo el ultimo."""
    import sqlite3

    ruta = tmp_path / "estado.sqlite3"
    for i in range(3):
        registrar_refresco(
            EstadoRefresco(f"2026-08-27T1{i}:00:00+00:00", f"2026-08-27T1{i}:01:00+00:00", 60.0, ESTADO_ERROR),
            ruta,
        )
    con = sqlite3.connect(ruta)
    try:
        total = con.execute("SELECT count(*) FROM refrescos").fetchone()[0]
    finally:
        con.close()
    assert total == 3
