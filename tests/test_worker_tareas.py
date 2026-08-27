"""Pruebas de orquestacion de worker/tareas.py -- nunca tocan Postgres ni
Socrata reales (todos los lectores/procesadores son dobles inyectados), y
no vuelven a probar la logica de negocio de pipeline.py (eso ya lo cubre
tests/test_pipeline.py)."""

import pandas as pd

from worker.almacen_snapshots import leer_tabla
from worker.estado import ESTADO_ERROR, ESTADO_OK, ultimo_refresco
from worker.tareas import ejecutar_refresco

_DF_INVIMA = pd.DataFrame({"CODIGO_INTERNO": ["1-1"]})
_DF_VACIO = pd.DataFrame({"CODIGO_INTERNO": []})


def _lector_invima_api_fake(dataset=None):
    return _DF_INVIMA if dataset is None else _DF_VACIO


def _procesador_fake(df_invima, reporte_gemanet, fuente_catalogos=None):
    return pd.DataFrame({"CODIGO_INTERNO": ["1-1"], "accion": ["candidato"]})


def _auditor_fake(df_invima, reporte_gemanet, df_invima_vencidos, **kwargs):
    return pd.DataFrame({"CODIGO_INTERNO": ["1-1"], "PORCENTAJE_CALIDAD": [100.0]})


def _kwargs_comunes(tmp_path):
    return {
        "lector_gemanet": lambda: object(),
        "lector_invima_api": _lector_invima_api_fake,
        "procesador": _procesador_fake,
        "auditor": _auditor_fake,
        "carpeta_snapshots": tmp_path / "snapshots",
        "ruta_estado": tmp_path / "estado.sqlite3",
    }


def test_refresco_exitoso_escribe_snapshot_y_registra_ok(tmp_path):
    evento = ejecutar_refresco(**_kwargs_comunes(tmp_path))

    assert evento.estado == ESTADO_OK
    assert evento.detalle_error == ""

    auditoria = leer_tabla("auditoria", tmp_path / "snapshots")
    candidatos = leer_tabla("candidatos", tmp_path / "snapshots")
    assert auditoria["PORCENTAJE_CALIDAD"].tolist() == [100.0]
    assert candidatos["accion"].tolist() == ["candidato"]


def test_refresco_exitoso_queda_registrado_en_el_estado(tmp_path):
    ejecutar_refresco(**_kwargs_comunes(tmp_path))
    ultimo = ultimo_refresco(tmp_path / "estado.sqlite3")
    assert ultimo.estado == ESTADO_OK


def test_fallo_del_lector_de_gemanet_no_rompe_el_proceso_y_queda_registrado(tmp_path):
    """Degradacion explicita: un fallo real (ej. la base no responde) se
    captura, se registra como ESTADO_ERROR con el detalle, y la funcion
    devuelve en vez de dejar la excepcion sin manejar -- asi el scheduler
    (refresco.py) puede loguear y seguir para el proximo ciclo."""
    kwargs = _kwargs_comunes(tmp_path)

    def _lector_que_falla():
        raise RuntimeError("no se pudo conectar a Gemma Net")

    kwargs["lector_gemanet"] = _lector_que_falla
    evento = ejecutar_refresco(**kwargs)

    assert evento.estado == ESTADO_ERROR
    assert "no se pudo conectar a Gemma Net" in evento.detalle_error
    # y NO debe haber quedado un snapshot a medio escribir
    assert leer_tabla("auditoria", tmp_path / "snapshots") is None


def test_fallo_deja_registrado_el_estado_error_consultable(tmp_path):
    kwargs = _kwargs_comunes(tmp_path)
    kwargs["auditor"] = lambda *a, **k: (_ for _ in ()).throw(ValueError("dato invalido"))

    ejecutar_refresco(**kwargs)

    ultimo = ultimo_refresco(tmp_path / "estado.sqlite3")
    assert ultimo.estado == ESTADO_ERROR
    assert "dato invalido" in ultimo.detalle_error


def test_snapshot_anterior_se_conserva_si_el_siguiente_refresco_falla(tmp_path):
    """Si un refresco exitoso ya dejo un snapshot bueno, y el SIGUIENTE
    refresco falla, el snapshot viejo tiene que seguir siendo el vigente --
    nunca se debe servir un snapshot a medio escribir ni perder el ultimo
    bueno por un fallo posterior."""
    kwargs_ok = _kwargs_comunes(tmp_path)
    ejecutar_refresco(**kwargs_ok)

    kwargs_falla = _kwargs_comunes(tmp_path)
    kwargs_falla["lector_gemanet"] = lambda: (_ for _ in ()).throw(RuntimeError("caida"))
    ejecutar_refresco(**kwargs_falla)

    auditoria = leer_tabla("auditoria", tmp_path / "snapshots")
    assert auditoria is not None
    assert auditoria["PORCENTAJE_CALIDAD"].tolist() == [100.0]
