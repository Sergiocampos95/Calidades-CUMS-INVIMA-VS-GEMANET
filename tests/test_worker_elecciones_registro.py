from worker.elecciones_registro import (
    elecciones_vigentes,
    firmas_elegidas,
    guardar_eleccion,
    quitar_eleccion,
)


def test_sin_archivo_no_hay_elecciones_y_leer_no_crea_nada(tmp_path):
    ruta = tmp_path / "elecciones.sqlite3"

    assert elecciones_vigentes(ruta) == {}
    assert not ruta.exists()


def test_guardar_reemplaza_la_eleccion_del_cum_y_la_anota_en_el_historial(tmp_path):
    ruta = tmp_path / "elecciones.sqlite3"
    guardar_eleccion("500-1", "vigente", "firma-a", 2, "PIPERACILINA", "ana", ruta)
    guardar_eleccion("500-1", "vigente", "firma-b", 3, "TAZOBACTAM", "luis", ruta)

    vigente = elecciones_vigentes(ruta)["500-1"]
    assert (vigente.firma, vigente.registro_al_elegir, vigente.usuario) == ("firma-b", 3, "luis")
    assert firmas_elegidas(ruta) == {"500-1": "firma-b"}

    import sqlite3

    con = sqlite3.connect(ruta)
    historial = con.execute("SELECT accion, usuario FROM historial ORDER BY rowid").fetchall()
    con.close()
    assert historial == [("elegir", "ana"), ("elegir", "luis")]


def test_quitar_vuelve_al_cruce_de_siempre_y_queda_en_el_historial(tmp_path):
    ruta = tmp_path / "elecciones.sqlite3"
    guardar_eleccion("500-1", "vigente", "firma-a", 2, "", "ana", ruta)

    assert quitar_eleccion("500-1", "luis", ruta) is True
    assert quitar_eleccion("500-1", "luis", ruta) is False
    assert firmas_elegidas(ruta) == {}

    import sqlite3

    con = sqlite3.connect(ruta)
    acciones = [f[0] for f in con.execute("SELECT accion FROM historial ORDER BY rowid")]
    con.close()
    assert acciones == ["elegir", "quitar"]
