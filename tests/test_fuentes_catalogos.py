"""La suite NUNCA golpea la base real: toda conexion se inyecta.

La base es produccion de Pijao Salud; un test que se conecte de verdad seria
carga sobre un servidor del que dependen autorizaciones de pacientes. Mismo
criterio que ya se aplica a Socrata y al cliente de IA.
"""

import pytest

from gemma_cum_loader.catalogos.fuentes import (
    FuenteCatalogosConRespaldo,
    FuenteCatalogosCSV,
    FuenteCatalogosGemaNet,
)
from gemma_cum_loader.integraciones import gemanet_db


class _CursorFalso:
    def __init__(self, filas, registro):
        self._filas = filas
        self._registro = registro

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql):
        self._registro.append(sql)

    def fetchmany(self, n):
        return self._filas[:n]


class _ConexionFalsa:
    """Doble de una conexion psycopg: guarda el SQL que recibio."""

    def __init__(self, filas):
        self._filas = filas
        self.sql_ejecutado: list[str] = []

    def cursor(self):
        return _CursorFalso(self._filas, self.sql_ejecutado)


class _ConexionQueFalla:
    def cursor(self):
        raise RuntimeError("servidor caido")


def test_marca_desde_la_base_se_convierte_en_catalogo_resoluble():
    conexion = _ConexionFalsa([(200, "ACME SAS"), (201, "LABORATORIOS ECAR S.A.")])
    catalogo = FuenteCatalogosGemaNet(conexion=conexion).marca()
    assert [e.codigo for e in catalogo] == [200, 201]
    # normalizar_entidad quita el sufijo societario -- es lo que permite que
    # "LABORATORIOS ECAR S.A" y "LABORATORIOS ECAR S.A." resuelvan igual.
    assert catalogo[1].sigla == "LABORATORIOS ECAR"


def test_toda_consulta_fija_un_statement_timeout():
    """Sin tope, una consulta desbocada queda tomando recursos de produccion."""
    conexion = _ConexionFalsa([(1, "X")])
    FuenteCatalogosGemaNet(conexion=conexion).unidad()
    assert any("statement_timeout" in s for s in conexion.sql_ejecutado)


def test_se_consultan_las_tablas_reales_del_esquema_administrativo():
    conexion = _ConexionFalsa([(1, "X")])
    fuente = FuenteCatalogosGemaNet(conexion=conexion)
    fuente.marca()
    fuente.unidad()
    fuente.modelo_servicio()
    sql = " ".join(conexion.sql_ejecutado)
    assert "administrativo.tb_marca_medicamento" in sql
    assert "administrativo.tb_unidad_medida" in sql
    assert "administrativo.tb_concepto_nota_tecnica" in sql


def test_sin_credenciales_falla_explicito_y_no_en_silencio(monkeypatch):
    monkeypatch.delenv(gemanet_db.NOMBRE_VARIABLE_ENTORNO, raising=False)
    with pytest.raises(gemanet_db.ErrorGemaNetDB):
        FuenteCatalogosGemaNet().marca()


def test_la_fuente_de_base_no_cae_al_csv_por_su_cuenta():
    """Degradar en silencio es justo lo que el proyecto prohibe: quien pidio
    la base tiene que enterarse de que no la obtuvo."""
    with pytest.raises(gemanet_db.ErrorGemaNetDB):
        FuenteCatalogosGemaNet(conexion=_ConexionQueFalla()).marca()


def test_con_respaldo_cae_al_csv_y_deja_constancia():
    fuente = FuenteCatalogosConRespaldo(
        principal=FuenteCatalogosGemaNet(conexion=_ConexionQueFalla()),
        respaldo=FuenteCatalogosCSV(),
    )
    catalogo = fuente.marca()
    assert catalogo, "el respaldo debe entregar el catalogo del CSV"
    assert len(fuente.advertencias) == 1
    assert "CSV local" in fuente.advertencias[0]


def test_con_respaldo_no_advierte_cuando_la_base_responde():
    fuente = FuenteCatalogosConRespaldo(
        principal=FuenteCatalogosGemaNet(conexion=_ConexionFalsa([(200, "ACME SAS")])),
        respaldo=FuenteCatalogosCSV(),
    )
    assert len(fuente.marca()) == 1
    assert fuente.advertencias == []


def test_el_resumen_de_conexion_nunca_incluye_la_contrasena(monkeypatch):
    monkeypatch.setenv(
        gemanet_db.NOMBRE_VARIABLE_ENTORNO,
        "host=servidor port=5432 dbname=basex user=usuariox password=SECRETO123",
    )
    estado = gemanet_db.estado_conexion()
    assert estado.configurado
    assert "SECRETO123" not in estado.resumen
    assert "usuariox" in estado.resumen and "servidor" in estado.resumen


def test_el_resumen_tampoco_filtra_la_contrasena_en_formato_url(monkeypatch):
    monkeypatch.setenv(
        gemanet_db.NOMBRE_VARIABLE_ENTORNO,
        "postgresql://usuariox:SECRETO123@servidor:5432/basex",
    )
    assert "SECRETO123" not in gemanet_db.estado_conexion().resumen


def test_el_csv_sigue_siendo_la_fuente_por_defecto_y_carga_los_tres():
    fuente = FuenteCatalogosCSV()
    assert fuente.marca() and fuente.unidad() and fuente.modelo_servicio()


# ---- Lectura del reporte de medicamentos desde la base ----


def test_el_reporte_desde_la_base_usa_los_nombres_del_export():
    """Aguas abajo (auditoria, cruce, exportacion) nada debe notar de donde
    vino el dato: los alias del SQL son los nombres del archivo exportado."""
    from gemma_cum_loader.ingesta.gemanet_sql import SQL_REPORTE_GEMANET

    for columna in ("CODIGO_INTERNO", "DESCRIPCION", "POS", "ACTIVO", "FECHA_FIN"):
        assert f'AS "{columna}"' in SQL_REPORTE_GEMANET


def test_las_banderas_de_la_base_se_traducen_a_si_no():
    """La base guarda sw_* como 0/1 y el export trae "Si"/"No"."""
    from gemma_cum_loader.ingesta.gemanet_sql import SQL_REPORTE_GEMANET

    assert "sw_activo = 1 THEN 'Si'" in SQL_REPORTE_GEMANET
    assert "sw_pos = 1 THEN 'Si'" in SQL_REPORTE_GEMANET


def test_el_nivel_de_servicio_se_traduce_al_texto_del_dominio():
    """La base guarda 1/2/3/4 y el dominio valido dice "Nivel 1"... Sin
    traducir, 4.031 filas salian como "fuera de dominio"."""
    from gemma_cum_loader.ingesta.gemanet_sql import SQL_REPORTE_GEMANET

    assert "'Nivel ' || m.consecutivo_nivel_servicio" in SQL_REPORTE_GEMANET


def test_el_modelo_de_servicio_se_resuelve_con_distinct_on_no_con_lateral():
    """Un LATERAL con LIMIT 1 se ejecutaba una vez por cada uno de los
    199.608 medicamentos y la consulta moria por statement_timeout."""
    from gemma_cum_loader.ingesta.gemanet_sql import SQL_REPORTE_GEMANET

    assert "DISTINCT ON (mnt.consecutivo_medicamento)" in SQL_REPORTE_GEMANET
    assert "LEFT JOIN LATERAL" not in SQL_REPORTE_GEMANET
