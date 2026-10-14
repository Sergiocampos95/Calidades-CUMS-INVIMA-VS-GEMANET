"""Descubrimiento de archivos en `data/`.

Los casos aqui salieron de la carpeta real del usuario el 2026-08-20: los
cuatro listados de INVIMA se llaman casi igual, Excel deja archivos de
bloqueo, y habia dos Estructura de Cargue donde la mas nueva no servia.
Cada prueba fija uno de esos tropiezos.
"""

from datetime import date

from gemma_cum_loader.ingesta.almacen_local import descubrir, descubrir_todo


def _crear(carpeta, nombre, contenido=b"x"):
    ruta = carpeta / nombre
    ruta.write_bytes(contenido)
    return ruta


def test_distingue_vigentes_de_los_otros_tres_listados(tmp_path):
    """Caso real: "ListadoCodigounicoOtrosEstado2022.xlsx" calzaba con un
    patron generico de Vigentes y, por ser mas reciente, ganaba. Usarlo como
    Vigentes produce "0 filas vigentes" mucho despues, sin causa evidente."""
    _crear(tmp_path, "ListadoCodigoUnicoVigentes2022.xlsx")
    _crear(tmp_path, "ListadoCodigounicoOtrosEstado2022.xlsx")
    _crear(tmp_path, "ListadoCodigoUnicoVencidos2022.xlsx")
    _crear(tmp_path, "ListadoCodigoUnicoRenovacion2022.xlsx")

    hallado = descubrir_todo(tmp_path)
    assert hallado["invima_vigentes"].nombre == "ListadoCodigoUnicoVigentes2022.xlsx"
    assert hallado["invima_vencidos"].nombre == "ListadoCodigoUnicoVencidos2022.xlsx"
    assert hallado["invima_otros_estados"].nombre == "ListadoCodigounicoOtrosEstado2022.xlsx"
    assert hallado["invima_renovacion"].nombre == "ListadoCodigoUnicoRenovacion2022.xlsx"


def test_ignora_los_archivos_de_bloqueo_de_excel(tmp_path):
    """"~$nombre.xlsx" calza con cualquier patron y es siempre el mas
    reciente: sin filtrarlo se elegiria un archivo de 1 KB."""
    real = _crear(tmp_path, "ListadoCodigoUnicoVigentes2022.xlsx", b"contenido real")
    _crear(tmp_path, "~$ListadoCodigoUnicoVigentes2022.xlsx")

    assert descubrir("invima_vigentes", tmp_path).ruta == real


def test_ignora_las_salidas_de_la_propia_aplicacion(tmp_path):
    """`reporte_cruce_invima.xlsx` es el resultado de una corrida anterior:
    tomarlo por un catalogo de entrada seria un desastre silencioso."""
    _crear(tmp_path, "reporte_cruce_invima.xlsx")
    _crear(tmp_path, "auditoria_coherencia_invima.xlsx")

    assert descubrir("reporte_gemanet", tmp_path) is None


def test_entre_dos_candidatos_gana_el_mas_reciente(tmp_path):
    import os
    import time

    viejo = _crear(tmp_path, "ListadoCodigoUnicoVigentes2022.xlsx")
    nuevo = _crear(tmp_path, "ListadoCodigoUnicoVigentes2026.xlsx")
    os.utime(viejo, (time.time() - 86400, time.time() - 86400))

    assert descubrir("invima_vigentes", tmp_path).ruta == nuevo


def test_reconoce_los_cuatro_listados_con_los_nombres_del_portal_nuevo(tmp_path):
    """Descargas de octubre 2026: nombres en mayusculas, con tildes
    ("TRÁMITE", "RENOVACIÓN") y la fecha al final. Junto a ellos queda un
    "Vencidos_A" viejo y diminuto que NO debe ganar por calzar con *vencid*."""
    import os
    import time

    viejo = _crear(tmp_path, "Código_Único_Medicamentos_Vencidos_A_20261001.xlsx")
    os.utime(viejo, (time.time() - 86400, time.time() - 86400))
    _crear(tmp_path, "CÓDIGO_ÚNICO_DE_MEDICAMENTOS_VIGENTES_20261002.xlsx")
    _crear(tmp_path, "CÓDIGO_ÚNICO_DE_MEDICAMENTOS_VENCIDOS_20261002.xlsx")
    _crear(tmp_path, "CÓDIGO_ÚNICO_DE_MEDICAMENTOS_OTROS_ESTADOS_20261002.xlsx")
    _crear(tmp_path, "CÓDIGO_ÚNICO_DE_MEDICAMENTOS_EN_TRÁMITE_DE_RENOVACIÓN_20261002.xlsx")

    hallado = descubrir_todo(tmp_path)
    assert hallado["invima_vigentes"].nombre.endswith("VIGENTES_20261002.xlsx")
    assert hallado["invima_vencidos"].nombre.endswith("VENCIDOS_20261002.xlsx")
    assert hallado["invima_otros_estados"].nombre.endswith("OTROS_ESTADOS_20261002.xlsx")
    assert "RENOVACIÓN" in hallado["invima_renovacion"].nombre


def _libro_con_hojas(carpeta, nombre, hojas):
    from openpyxl import Workbook

    libro = Workbook()
    libro.active.title = hojas[0]
    for hoja in hojas[1:]:
        libro.create_sheet(hoja)
    libro.save(carpeta / nombre)


def test_la_estructura_con_hoja_plantilla_sin_el_2_se_descubre(tmp_path):
    """Archivo oficial de octubre 2026: hojas `plantilla`, `NO POS` y `TABLAS DE
    REFERENCIA`. El lector de la malla (`_resolver_hoja_malla`) ya lo acepta;
    el validador de descubrimiento exigia `plantilla (2)` y lo dejaba afuera,
    con lo que las vistas de Cargue se apagaban sin ningun aviso."""
    _libro_con_hojas(
        tmp_path, "Estructura Cargue Medicamentos ultimo mixto.xlsx", ["plantilla", "NO POS", "TABLAS DE REFERENCIA"]
    )
    assert descubrir_todo(tmp_path)["estructura_cargue"].nombre == "Estructura Cargue Medicamentos ultimo mixto.xlsx"


def test_la_estructura_con_plantilla_2_sigue_descubriendose(tmp_path):
    _libro_con_hojas(tmp_path, "Estructura Cargue Medicamentos.xlsx", ["plantilla", "plantilla (2)", "NO POS"])
    assert "estructura_cargue" in descubrir_todo(tmp_path)


def test_una_estructura_sin_hoja_de_malla_o_con_hoja_ambigua_no_se_propone(tmp_path):
    """Sin ninguna hoja con "plantilla" -- o con dos y ninguna exacta -- el
    lector no sabria cual usar y fallaria a mitad de corrida: mejor no
    proponer nada (mismo criterio de `_resolver_hoja_malla`)."""
    _libro_con_hojas(tmp_path, "Estructura Cargue A.xlsx", ["Hoja1", "Hoja2"])
    _libro_con_hojas(tmp_path, "Estructura Cargue B.xlsx", ["plantilla vieja", "plantilla nueva"])
    assert "estructura_cargue" not in descubrir_todo(tmp_path)


def test_el_validador_descarta_un_archivo_que_no_sirve(tmp_path):
    """Caso real: habia dos Estructura de Cargue y la MAS NUEVA no traia la
    hoja `plantilla (2)`. Sin validador se habria propuesto esa y la corrida
    fallaria a mitad de camino."""
    _crear(tmp_path, "Estructura Cargue A.xlsx")
    _crear(tmp_path, "Estructura Cargue B.xlsx")

    assert descubrir("estructura_cargue", tmp_path, validador=lambda p: False) is None
    assert descubrir("estructura_cargue", tmp_path, validador=lambda p: "A" in p.name).nombre == (
        "Estructura Cargue A.xlsx"
    )


def test_carpeta_inexistente_no_revienta(tmp_path):
    assert descubrir("invima_vigentes", tmp_path / "no_existe") is None
    assert descubrir_todo(tmp_path / "no_existe") == {}


# ---- guardar_subida: "subir una vez y olvidarse" ----


class _ArchivoSubido:
    """Doble de un UploadedFile de Streamlit."""

    def __init__(self, nombre, datos):
        self.name = nombre
        self._datos = datos

    def getvalue(self):
        return self._datos


def test_guardar_subida_deja_el_archivo_para_la_proxima_corrida(tmp_path):
    """El navegador nunca da la ruta real del archivo elegido -- guardar el
    contenido es lo que logra que subir una vez baste."""
    from gemma_cum_loader.ingesta.almacen_local import guardar_subida

    subido = _ArchivoSubido("ListadoCodigoUnicoVigentes2026.xlsx", b"contenido")
    ruta = guardar_subida(subido, subido.name, tmp_path)

    assert ruta is not None and ruta.read_bytes() == b"contenido"
    # y desde ese momento el descubrimiento lo encuentra solo
    assert descubrir("invima_vigentes", tmp_path).nombre == subido.name


def test_guardar_subida_ignora_un_archivo_vacio(tmp_path):
    from gemma_cum_loader.ingesta.almacen_local import guardar_subida

    assert guardar_subida(_ArchivoSubido("vacio.xlsx", b""), "vacio.xlsx", tmp_path) is None


def test_guardar_descarga_publica_el_parquet_solo_al_terminar(monkeypatch, tmp_path):
    import pandas as pd

    from gemma_cum_loader.ingesta.almacen_local import guardar_descarga

    escrito = []

    def _to_parquet(_df, ruta, index):
        escrito.append(ruta)
        assert not (tmp_path / "invima_vigentes_20260825.parquet").exists()
        ruta.write_bytes(b"parquet")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _to_parquet)

    resultado = guardar_descarga(
        pd.DataFrame({"EXPEDIENTE": ["500"]}),
        "invima_vigentes",
        tmp_path,
        fecha=date(2026, 8, 25),
    )

    assert resultado.ok is True
    assert resultado.ruta == tmp_path / "invima_vigentes_20260825.parquet"
    assert resultado.ruta.read_bytes() == b"parquet"
    assert len(escrito) == 1
    assert not list(tmp_path.glob(".*.tmp"))


# --- Carpeta de listados en el servidor (2026-09-14) ---------------------


def test_la_carpeta_de_datos_sale_de_la_variable_de_entorno(monkeypatch, tmp_path):
    """Produccion (2026-09-14): los listados viven en una carpeta del servidor
    elegida por operaciones, no dentro del repo."""
    from gemma_cum_loader.ingesta.almacen_local import carpeta_datos

    monkeypatch.setenv("INVIMA_LISTADOS_DIR", str(tmp_path))
    assert carpeta_datos() == tmp_path


def test_sin_variable_la_carpeta_es_gemanet_invima_en_el_home(monkeypatch):
    from pathlib import Path

    from gemma_cum_loader.ingesta.almacen_local import carpeta_datos

    monkeypatch.delenv("INVIMA_LISTADOS_DIR", raising=False)
    assert carpeta_datos() == Path.home() / "gemanet" / "invima"


def test_descubrir_usa_la_carpeta_del_entorno_cuando_no_le_pasan_una(monkeypatch, tmp_path):
    from gemma_cum_loader.ingesta.almacen_local import descubrir

    monkeypatch.setenv("INVIMA_LISTADOS_DIR", str(tmp_path))
    _crear(tmp_path, "ListadoCodigoUnicoVigentes2026.xlsx")
    assert descubrir("invima_vigentes").nombre == "ListadoCodigoUnicoVigentes2026.xlsx"
