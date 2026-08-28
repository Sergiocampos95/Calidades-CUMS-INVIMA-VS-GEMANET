"""Pruebas de orquestacion de worker/tareas.py -- nunca tocan Postgres ni
Socrata reales (todos los lectores/procesadores son dobles inyectados), y
no vuelven a probar la logica de negocio de pipeline.py (eso ya lo cubre
tests/test_pipeline.py)."""

import pandas as pd

from worker.almacen_snapshots import leer_tabla
from worker.estado import (
    ESTADO_ERROR,
    ESTADO_OK,
    ESTADO_PASO_ERROR,
    ESTADO_PASO_HECHO,
    progreso_actual,
    ultimo_refresco,
)
from worker.tareas import NOMBRES_PASOS_REFRESCO, ejecutar_refresco

_DF_INVIMA = pd.DataFrame({"CODIGO_INTERNO": ["1-1"]})
_DF_VACIO = pd.DataFrame({"CODIGO_INTERNO": []})


def _lector_invima_api_fake(dataset=None):
    return _DF_INVIMA if dataset is None else _DF_VACIO


def _procesador_fake(df_invima, reporte_gemanet, fuente_catalogos=None):
    return pd.DataFrame({"CODIGO_INTERNO": ["1-1"], "accion": ["candidato"]})


def _auditor_fake(df_invima, reporte_gemanet, df_invima_vencidos, **kwargs):
    return pd.DataFrame({"CODIGO_INTERNO": ["1-1"], "PORCENTAJE_CALIDAD": [100.0]})


def _clasificador_fake(df_invima):
    return pd.DataFrame({"CODIGO_INTERNO": ["1-1"], "CLASIFICACION_CREACION": ["candidato"]})


def _kwargs_comunes(tmp_path):
    return {
        "lector_gemanet": lambda: object(),
        "lector_invima_api": _lector_invima_api_fake,
        "procesador": _procesador_fake,
        "auditor": _auditor_fake,
        "clasificador": _clasificador_fake,
        # Sin esto, el default real (_localizar_malla_referencia_defecto)
        # escanearia data/ de verdad -- en esta maquina de desarrollo SI
        # existe una Estructura Cargue Medicamentos real ahi, y las pruebas
        # nunca deben depender de lo que haya o no en el filesystem local.
        "localizador_malla": lambda: None,
        "carpeta_snapshots": tmp_path / "snapshots",
        "ruta_estado": tmp_path / "estado.sqlite3",
    }


def test_refresco_exitoso_escribe_snapshot_y_registra_ok(tmp_path):
    evento = ejecutar_refresco(**_kwargs_comunes(tmp_path))

    assert evento.estado == ESTADO_OK
    assert evento.detalle_error == ""

    auditoria = leer_tabla("auditoria", tmp_path / "snapshots")
    candidatos = leer_tabla("candidatos", tmp_path / "snapshots")
    universo = leer_tabla("universo", tmp_path / "snapshots")
    assert auditoria["PORCENTAJE_CALIDAD"].tolist() == [100.0]
    assert candidatos["accion"].tolist() == ["candidato"]
    assert universo["CLASIFICACION_CREACION"].tolist() == ["candidato"]


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


def test_sin_malla_de_referencia_no_hay_tablas_de_cargue(tmp_path):
    """Degradacion explicita: sin Estructura Cargue Medicamentos no hay con
    que derivar POS/Modelo de Servicio/edad/copagos -- no se inventa nada,
    esas 4 tablas simplemente no se escriben (el resto del snapshot si)."""
    ejecutar_refresco(**_kwargs_comunes(tmp_path))
    for tabla in ("cargue_evaluados", "cargue_estructura", "cargue_final", "cargue_reglas_advertencias"):
        assert leer_tabla(tabla, tmp_path / "snapshots") is None


def _procesador_fake_con_cargue(df_invima, reporte_gemanet, fuente_catalogos=None):
    return pd.DataFrame(
        {
            "CODIGO_INTERNO": ["100-1"],
            "accion": ["candidato"],
            "DESCRIPCION": ["ACETAMINOFEN 500MG TABLETA"],
            "CONCENTRACION": ["500 MG"],
            "marca_codigo": [200],
            "EXPEDIENTE": [100],
            "CONSECUTIVO": [1],
            "unidad_codigo": [10],
            "FORMA_FARMACEUTICA": ["TABLETA"],
            "PRINCIPIO_ACTIVO": ["ACETAMINOFEN"],
            "ATC": ["N02BE01"],
            "unidad_metodo": ["exacto_sigla"],
            "marca_metodo": ["exacto_sigla"],
        }
    )


def _malla_referencia_fake():
    # Solo EXPEDIENTE + POS + Modelo de Servicio -- los 22 campos
    # "constantes" quedan ausentes a proposito, para probar tambien que
    # faltar una columna termina en advertencia, no en un valor inventado.
    return pd.DataFrame(
        {
            "EXPEDIENTE": [100],
            "POS(SI/NO)": ["SI"],
            "CÓDIGO INTERNO MODELO SERVICIO": [1],
        }
    )


def test_con_malla_de_referencia_disponible_arma_las_4_tablas_de_cargue(tmp_path):
    kwargs = _kwargs_comunes(tmp_path)
    kwargs["procesador"] = _procesador_fake_con_cargue
    kwargs["localizador_malla"] = lambda: "ruta/falsa/estructura_cargue.xlsx"
    kwargs["lector_malla"] = lambda ruta: _malla_referencia_fake()

    evento = ejecutar_refresco(**kwargs)
    assert evento.estado == ESTADO_OK

    carpeta = tmp_path / "snapshots"
    evaluados = leer_tabla("cargue_evaluados", carpeta)
    estructura = leer_tabla("cargue_estructura", carpeta)
    cargue_final = leer_tabla("cargue_final", carpeta)
    advertencias = leer_tabla("cargue_reglas_advertencias", carpeta)

    # EXPEDIENTE 100 tiene POS/modelo consistentes en la malla y unidad/marca
    # ya resueltas -- este candidato queda "listo_para_cargue".
    assert evaluados["listo_para_cargue"].tolist() == [True]
    assert len(estructura) == 1
    assert len(cargue_final) == 1
    assert "ESTADO" not in cargue_final.columns  # esquema del cargue final, no el de auditoria
    # a los 22 campos "constantes" les falta su columna en la malla fake --
    # tienen que quedar como advertencia, no silenciosos.
    assert len(advertencias) >= 20


def test_cargue_final_vacio_conserva_el_esquema_correcto_no_el_de_auditoria(tmp_path):
    """Bug real encontrado corriendo esto contra produccion: con 0 filas
    'listas', el DataFrame vacio tenia las columnas de `cargue_estructura`
    (ESTADO, CAMPOS_CON_ERROR...) en vez de las 37 columnas reales del
    Excel de cargue -- confundiria a quien lo abra pensando que es el
    archivo de auditoria."""
    kwargs = _kwargs_comunes(tmp_path)

    def _procesador_no_listo(df_invima, reporte_gemanet, fuente_catalogos=None):
        fila = _procesador_fake_con_cargue(df_invima, reporte_gemanet, fuente_catalogos)
        fila["unidad_metodo"] = ["sin_resolver"]  # nunca queda listo
        return fila

    kwargs["procesador"] = _procesador_no_listo
    kwargs["localizador_malla"] = lambda: "ruta/falsa/estructura_cargue.xlsx"
    kwargs["lector_malla"] = lambda ruta: _malla_referencia_fake()

    ejecutar_refresco(**kwargs)

    cargue_final = leer_tabla("cargue_final", tmp_path / "snapshots")
    assert len(cargue_final) == 0
    assert "ESTADO" not in cargue_final.columns
    assert "DESCRIPCION" in cargue_final.columns


def test_refresco_exitoso_deja_todos_los_pasos_en_hecho(tmp_path):
    kwargs = _kwargs_comunes(tmp_path)
    ejecutar_refresco(**kwargs)
    pasos = progreso_actual(kwargs["ruta_estado"])
    assert [p.nombre for p in pasos] == list(NOMBRES_PASOS_REFRESCO)
    assert all(p.estado == ESTADO_PASO_HECHO for p in pasos)


def test_refresco_fallido_marca_el_paso_que_reventó_y_no_avanza_los_siguientes(tmp_path):
    """El paso donde fallo queda en error con el detalle -- los que ya
    habian terminado siguen en hecho, y los que nunca llegaron a correr
    quedan en pendiente (no se marcan como si hubieran corrido)."""
    kwargs = _kwargs_comunes(tmp_path)
    kwargs["auditor"] = lambda *a, **k: (_ for _ in ()).throw(ValueError("dato invalido"))

    ejecutar_refresco(**kwargs)

    pasos = {p.nombre: p.estado for p in progreso_actual(kwargs["ruta_estado"])}
    # Los 5 pasos de lectura corren antes que "Auditando...".
    assert pasos["Leyendo reporte de Gemma Net"] == ESTADO_PASO_HECHO
    assert pasos["Cruzando candidatos contra Gemma Net"] == ESTADO_PASO_HECHO
    assert pasos["Auditando coherencia contra INVIMA"] == ESTADO_PASO_ERROR
    assert pasos["Guardando snapshot"] == "pendiente"


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
