import json

import pandas as pd

from worker.almacen_snapshots import escribir_snapshot, leer_tabla, snapshot_actual


def test_sin_snapshot_previo_devuelve_none(tmp_path):
    """Degradacion explicita: antes del primer refresco no hay nada que
    leer, y eso se representa con None, no con un DataFrame vacio que
    parezca un resultado valido."""
    assert snapshot_actual(tmp_path) is None
    assert leer_tabla("auditoria", tmp_path) is None


def test_escribir_snapshot_se_puede_releer_igual(tmp_path):
    auditoria = pd.DataFrame({"CODIGO_INTERNO": ["1-1", "2-2"], "PORCENTAJE_CALIDAD": [100.0, 80.0]})
    candidatos = pd.DataFrame({"CODIGO_INTERNO": ["3-3"], "accion": ["candidato"]})

    escribir_snapshot({"auditoria": auditoria, "candidatos": candidatos}, carpeta=tmp_path)

    releida_auditoria = leer_tabla("auditoria", tmp_path)
    releida_candidatos = leer_tabla("candidatos", tmp_path)
    pd.testing.assert_frame_equal(releida_auditoria, auditoria)
    pd.testing.assert_frame_equal(releida_candidatos, candidatos)


def test_tabla_que_no_esta_en_el_snapshot_da_none(tmp_path):
    escribir_snapshot({"auditoria": pd.DataFrame({"a": [1]})}, carpeta=tmp_path)
    assert leer_tabla("candidatos", tmp_path) is None


def test_segundo_snapshot_reemplaza_el_puntero_sin_perder_datos(tmp_path):
    escribir_snapshot({"auditoria": pd.DataFrame({"a": [1]})}, carpeta=tmp_path)
    escribir_snapshot({"auditoria": pd.DataFrame({"a": [2]})}, carpeta=tmp_path)

    releida = leer_tabla("auditoria", tmp_path)
    assert releida["a"].tolist() == [2]


def test_puntero_es_json_valido_con_los_campos_esperados(tmp_path):
    escribir_snapshot({"auditoria": pd.DataFrame({"a": [1]})}, carpeta=tmp_path)
    datos = json.loads((tmp_path / "actual.json").read_text(encoding="utf-8"))
    assert set(datos.keys()) == {"nombre", "generado_utc", "tablas"}
    assert "auditoria" in datos["tablas"]


def test_escribir_snapshot_con_attrs_no_serializable_no_revienta(tmp_path):
    """Reproduce el fallo real: pipeline.py deja `resultado.attrs["advertencias"]`
    poblado, y si alguien mete ahi un objeto no serializable a JSON (un
    pd.Series, por ejemplo), `to_parquet` reventaba con TypeError. Los
    attrs no son parte del snapshot -- se excluyen de la escritura sin
    perderlos para quien siga usando el DataFrame despues."""
    auditoria = pd.DataFrame({"a": [1, 2]})
    auditoria.attrs["advertencias"] = pd.Series(["no serializable"])

    escribir_snapshot({"auditoria": auditoria}, carpeta=tmp_path)

    releida = leer_tabla("auditoria", tmp_path)
    assert releida["a"].tolist() == [1, 2]
    # y el DataFrame original conserva sus attrs -- no se pierden por escribir
    assert "advertencias" in auditoria.attrs


def test_poda_conserva_solo_los_ultimos_n_snapshots(tmp_path, monkeypatch):
    import worker.almacen_snapshots as modulo

    monkeypatch.setattr(modulo, "SNAPSHOTS_A_CONSERVAR", 2)
    for i in range(4):
        escribir_snapshot({"auditoria": pd.DataFrame({"a": [i]})}, carpeta=tmp_path)

    archivos_parquet = list(tmp_path.glob("*.parquet"))
    assert len(archivos_parquet) == 2
    # y el que queda vigente es el ULTIMO escrito, no uno viejo podado
    releida = leer_tabla("auditoria", tmp_path)
    assert releida["a"].tolist() == [3]


# --- Colisiones con versiones pasadas (regla del usuario, 2026-09-02) ---


def test_snapshot_de_version_anterior_se_reporta_como_desfase(tmp_path):
    """El problema real, repetido: se agrega una columna a la auditoria pero
    el snapshot en disco lo escribio la version ANTERIOR. Los consumidores
    degradan a 0 en silencio y eso se lee como "no hay hallazgos" cuando en
    realidad es "este snapshot es viejo". Un dato ausente no es un cero."""
    import pandas as pd

    from worker.almacen_snapshots import desfases_de_esquema, escribir_snapshot

    carpeta = tmp_path / "snapshots"
    escribir_snapshot(
        {"auditoria": pd.DataFrame({"CODIGO_INTERNO": ["1-1"], "ESTADO_COHERENCIA": ["correcto"]})},
        carpeta=carpeta,
    )
    desfases = desfases_de_esquema(carpeta)
    assert "auditoria" in desfases
    assert "VIGENCIA_NO_CONFIRMABLE" in desfases["auditoria"]


def test_snapshot_al_dia_no_reporta_desfase(tmp_path):
    import pandas as pd

    from worker.almacen_snapshots import (
        COLUMNAS_ESPERADAS,
        desfases_de_esquema,
        escribir_snapshot,
    )

    carpeta = tmp_path / "snapshots"
    escribir_snapshot(
        {tabla: pd.DataFrame({c: [""] for c in columnas}) for tabla, columnas in COLUMNAS_ESPERADAS.items()},
        carpeta=carpeta,
    )
    assert desfases_de_esquema(carpeta) == {}
