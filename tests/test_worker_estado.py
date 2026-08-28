from worker.estado import (
    ESTADO_ERROR,
    ESTADO_OK,
    ESTADO_PASO_EN_CURSO,
    ESTADO_PASO_HECHO,
    ESTADO_PASO_PENDIENTE,
    EstadoRefresco,
    actualizar_paso,
    hay_solicitud_pendiente,
    iniciar_progreso,
    limpiar_solicitud_pendiente,
    progreso_actual,
    registrar_refresco,
    solicitar_refresco_manual,
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


def test_progreso_vacio_antes_de_la_primera_corrida(tmp_path):
    ruta = tmp_path / "estado.sqlite3"
    assert progreso_actual(ruta) == []


def test_iniciar_progreso_deja_todos_los_pasos_pendientes(tmp_path):
    ruta = tmp_path / "estado.sqlite3"
    iniciar_progreso(["Leer INVIMA", "Auditar", "Guardar"], ruta=ruta)
    pasos = progreso_actual(ruta)
    assert [p.nombre for p in pasos] == ["Leer INVIMA", "Auditar", "Guardar"]
    assert all(p.estado == ESTADO_PASO_PENDIENTE for p in pasos)


def test_actualizar_paso_cambia_solo_ese_paso(tmp_path):
    ruta = tmp_path / "estado.sqlite3"
    iniciar_progreso(["Leer INVIMA", "Auditar"], ruta=ruta)
    actualizar_paso("Leer INVIMA", ESTADO_PASO_HECHO, ruta=ruta)
    actualizar_paso("Auditar", ESTADO_PASO_EN_CURSO, ruta=ruta)
    pasos = {p.nombre: p.estado for p in progreso_actual(ruta)}
    assert pasos == {"Leer INVIMA": ESTADO_PASO_HECHO, "Auditar": ESTADO_PASO_EN_CURSO}


def test_iniciar_progreso_de_nuevo_reemplaza_la_corrida_anterior():
    """No se acumulan pasos de corridas viejas -- solo importa la vigente/
    mas reciente, el historial resumido ya vive en `refrescos`."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directorio:
        ruta = Path(directorio) / "estado.sqlite3"
        iniciar_progreso(["Paso viejo A", "Paso viejo B"], ruta=ruta)
        iniciar_progreso(["Paso nuevo"], ruta=ruta)
        pasos = progreso_actual(ruta)
        assert [p.nombre for p in pasos] == ["Paso nuevo"]


def test_solicitud_de_refresco_manual_se_puede_pedir_ver_y_limpiar(tmp_path):
    ruta = tmp_path / "estado.sqlite3"
    assert hay_solicitud_pendiente(ruta) is False
    solicitar_refresco_manual(ruta)
    assert hay_solicitud_pendiente(ruta) is True
    limpiar_solicitud_pendiente(ruta)
    assert hay_solicitud_pendiente(ruta) is False


def test_solicitar_dos_veces_seguidas_no_revienta():
    """POST /refrescar pudo llegar dos veces (doble clic, reintento de red)
    -- la segunda solicitud no debe reventar con un error de clave
    duplicada."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directorio:
        ruta = Path(directorio) / "estado.sqlite3"
        solicitar_refresco_manual(ruta)
        solicitar_refresco_manual(ruta)
        assert hay_solicitud_pendiente(ruta) is True
