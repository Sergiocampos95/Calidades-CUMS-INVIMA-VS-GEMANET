"""Pruebas de orquestacion de worker/tareas.py -- nunca tocan Postgres ni
Socrata reales (todos los lectores/procesadores son dobles inyectados), y
no vuelven a probar la logica de negocio de pipeline.py (eso ya lo cubre
tests/test_pipeline.py)."""

import pandas as pd

from worker import tareas
from worker.almacen_snapshots import leer_tabla
from worker.estado import (
    ESTADO_ERROR,
    ESTADO_OK,
    ESTADO_PASO_ERROR,
    ESTADO_PASO_HECHO,
    iniciar_progreso,
    progreso_actual,
    ultimo_refresco,
)
from worker.tareas import (
    NOMBRES_PASOS_REFRESCO,
    _listados_invima_unificados,
    ejecutar_refresco,
)

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


class _LectorConRespaldoFalso:
    """Doble de LectorInvimaConRespaldo -- simula caer al respaldo local
    solo en la llamada de Vigentes (dataset=None), responder normal en las
    otras 3. `.advertencias` es el mismo atributo que expone el real."""

    def __init__(self):
        self.advertencias: list[str] = []

    def leer(self, dataset=None):
        if dataset is None:
            self.advertencias.append(
                "Socrata no respondio para invima_vigentes -- se uso el archivo local mas reciente"
            )
            return _DF_INVIMA
        return _DF_VACIO


def test_lector_invima_por_defecto_usa_respaldo_y_anota_el_paso_sin_marcarlo_error(tmp_path, monkeypatch):
    """Sin lector_invima_api inyectado, ejecutar_refresco construye
    LectorInvimaConRespaldo() -- si esta cae al archivo local, el paso
    correspondiente queda en HECHO (el dato SI llego, solo con otro origen)
    con la advertencia como detalle informativo, nunca como error."""
    import worker.tareas as modulo

    monkeypatch.setattr(modulo, "LectorInvimaConRespaldo", _LectorConRespaldoFalso)

    kwargs = _kwargs_comunes(tmp_path)
    del kwargs["lector_invima_api"]  # usa el default -> LectorInvimaConRespaldo (parcheado)

    evento = ejecutar_refresco(**kwargs)

    assert evento.estado == ESTADO_OK
    pasos = {p.nombre: p for p in progreso_actual(kwargs["ruta_estado"])}
    assert pasos["Leyendo INVIMA -- Vigentes"].estado == ESTADO_PASO_HECHO
    assert "archivo local" in pasos["Leyendo INVIMA -- Vigentes"].detalle
    # Los otros 3 datasets no cayeron al respaldo en este doble -- sin nota.
    assert pasos["Leyendo INVIMA -- Vencidos"].detalle == ""


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


def test_el_snapshot_incluye_los_4_listados_de_invima_con_su_rotulo(tmp_path):
    """Hasta ahora el snapshot solo guardaba "universo" = Vigentes ya
    clasificado; los otros 3 datasets se leian, se usaban para marcar estado y
    se descartaban. Consecuencia real (caso 20102710-2): la consulta puntual
    no tenia ninguna fila de INVIMA que mostrar para un CUM vencido. Ahora se
    persisten los 4 con una columna LISTADO que dice de cual salio cada uno."""

    def _lector_por_dataset(dataset=None):
        # Un codigo distinto por listado, para poder distinguirlos en el
        # resultado; `dataset=None` es Vigentes (ver ejecutar_refresco).
        codigos = {
            None: "1-1",
            "vwwf-4ftk": "2-2",       # Vencidos
            "spzp-dfuc": "3-3",       # Otros Estados
            "vgr4-gemg": "4-4",       # Renovacion
        }
        return pd.DataFrame({"CODIGO_INTERNO": [codigos[dataset]]})

    kwargs = _kwargs_comunes(tmp_path)
    kwargs["lector_invima_api"] = _lector_por_dataset
    ejecutar_refresco(**kwargs)

    listados = leer_tabla("invima_listados", tmp_path / "snapshots")
    assert dict(zip(listados["CODIGO_INTERNO"], listados["LISTADO"])) == {
        "1-1": "vigente",
        "2-2": "vencido",
        "3-3": "otros_estados",
        "4-4": "renovacion",
    }


def test_un_listado_auxiliar_vacio_no_rompe_el_refresco(tmp_path):
    """Los 3 auxiliares son opcionales e independientes: si uno viene vacio
    simplemente no aporta filas, no tumba el refresco completo."""
    evento = ejecutar_refresco(**_kwargs_comunes(tmp_path))

    assert evento.estado == ESTADO_OK
    listados = leer_tabla("invima_listados", tmp_path / "snapshots")
    # `_lector_invima_api_fake` devuelve filas solo para Vigentes.
    assert listados["LISTADO"].tolist() == ["vigente"]


def test_expediente_con_tipos_mezclados_no_tumba_la_escritura_del_snapshot():
    """Socrata entrega el mismo campo unas veces entrecomillado y otras no,
    asi que EXPEDIENTE llega como texto en un dataset y como entero en otro.
    Antes el concat los dejaba convivir en una columna `object` y
    `to_parquet` reventaba en el ULTIMO paso del refresco -- de forma
    intermitente, segun le tocara la mezcla a esa corrida."""
    unificado = _listados_invima_unificados(
        pd.DataFrame({"EXPEDIENTE": ["20048021"], "CODIGO_INTERNO": ["1-1"]}),
        pd.DataFrame({"EXPEDIENTE": [10858], "CODIGO_INTERNO": ["2-1"]}),
        None,
        None,
    )

    assert unificado["EXPEDIENTE"].tolist() == ["20048021", "10858"]
    assert pd.api.types.infer_dtype(unificado["EXPEDIENTE"], skipna=True) == "string"


def test_una_columna_de_un_solo_tipo_se_deja_intacta():
    """Solo se normaliza lo que esta MEZCLADO: convertir de mas cambiaria el
    tipo de columnas que hoy se guardan bien."""
    unificado = _listados_invima_unificados(
        pd.DataFrame({"CONSECUTIVO": [1], "CODIGO_INTERNO": ["1-1"]}),
        pd.DataFrame({"CONSECUTIVO": [2], "CODIGO_INTERNO": ["2-1"]}),
        None,
        None,
    )

    assert unificado["CONSECUTIVO"].tolist() == [1, 2]


def test_los_nulos_no_se_vuelven_la_cadena_nan_al_normalizar():
    """`astype(str)` convertiria un vacio en el texto "nan", que despues se
    leeria como un dato. Se preserva el nulo."""
    unificado = _listados_invima_unificados(
        pd.DataFrame({"EXPEDIENTE": ["20048021"], "CODIGO_INTERNO": ["1-1"]}),
        pd.DataFrame({"EXPEDIENTE": [10858], "CODIGO_INTERNO": ["2-1"]}),
        pd.DataFrame({"EXPEDIENTE": [None], "CODIGO_INTERNO": ["3-1"]}),
        None,
    )

    assert unificado["EXPEDIENTE"].isna().sum() == 1
    assert "nan" not in unificado["EXPEDIENTE"].dropna().tolist()


def test_el_progreso_dice_de_que_archivo_salio_el_catalogo(tmp_path):
    """Con la fuente "archivos", el paso de INVIMA debe decir de QUE Excel
    salio el dato. Las dos fuentes (API y archivos) producen snapshots que se
    ven igual de sanos pero con cifras muy distintas, asi que un progreso mudo
    sobre el origen deja imposible saber cual se cargo -- que es lo unico que
    esta funcionalidad viene a resolver."""
    from gemma_cum_loader.ingesta.fuente_invima import LectorInvimaDeArchivos
    from gemma_cum_loader.ingesta.invima_socrata import DATASET_CUM_VIGENTES
    pd.DataFrame({"EXPEDIENTE": ["1"]}).to_excel(
        tmp_path / "ListadoCodigoUnicoVigentesJulio2026.xlsx", index=False
    )
    falso = {DATASET_CUM_VIGENTES: ("invima_vigentes", lambda r: pd.DataFrame())}
    lector = LectorInvimaDeArchivos(tmp_path, por_dataset=falso)

    ruta_estado = tmp_path / "estado.sqlite3"
    iniciar_progreso(["Leyendo INVIMA -- Vigentes"], ruta=ruta_estado)
    tareas._leer_invima(
        "Leyendo INVIMA -- Vigentes", lector.leer, lector, ruta_estado=ruta_estado
    )

    paso = progreso_actual(ruta=ruta_estado)[0]
    assert paso.estado == ESTADO_PASO_HECHO
    assert "ListadoCodigoUnicoVigentesJulio2026.xlsx" in paso.detalle
