import pandas as pd

from gemma_cum_loader.auditoria.cadena_calidad import (
    CADENA_CALIDAD_DEFAULT,
    ESTADO_CADENA_NO_PASA,
    ESTADO_CADENA_PASA,
    construir_cadena_calidad,
)
from gemma_cum_loader.auditoria.coherencia_invima import auditar_coherencia
from gemma_cum_loader.catalogos.resolver import cargar_catalogo
from gemma_cum_loader.normaliza.texto import normalizar_entidad

_CATALOGO_UNIDAD = cargar_catalogo([(10, "MG - MILIGRAMO")])
_CATALOGO_MARCA = cargar_catalogo(
    [(200, "ACME SAS")], normalizador=normalizar_entidad, dividir_sigla_descripcion=False
)


def _fila_gemanet(codigo_interno, **overrides):
    # Mismo patron de fixture que tests/test_coherencia_invima.py: si algun
    # dia diverge, es porque un campo de esta lista dejo de ser comparable.
    base = {
        "CODIGO_INTERNO": codigo_interno,
        "DESCRIPCION": "ACETAMINOFEN 500MG TABLETA",
        "CONCENTRACION": "CAJA POR 100 TABLETAS EN BLISTER PVC/ALUMINIO",
        "FORMA_FARMACEUTICA": "TABLETA",
        "PRINCIPIO_ACTIVO": "ACETAMINOFEN",
        "CODIGO_ATC": "N02BE01",
        "MARCA_MEDICAMENTO": 200,
        "UNIDAD_MEDIDA": 10,
    }
    base.update(overrides)
    return base


def _fila_invima(codigo_interno, **overrides):
    base = {
        "CODIGO_INTERNO": codigo_interno,
        "TITULAR": "ACME SAS",
        "UNIDAD_MEDIDA": "mg",
        "CANTIDAD": 500,
        "PRINCIPIO_ACTIVO": "ACETAMINOFEN",
        "UNIDAD_REFERENCIA": "CADA TABLETA CONTIENE",
        "CONCENTRACION": "500 MG",
        "DESCRIPCION_COMERCIAL": "CAJA POR 100 TABLETAS EN BLISTER PVC/ALUMINIO",
        "FORMA_FARMACEUTICA": "TABLETA",
        "ATC": "N02BE01",
    }
    base.update(overrides)
    return base


def _auditar(gemanet_filas, invima_filas):
    return auditar_coherencia(
        pd.DataFrame(gemanet_filas),
        pd.DataFrame(invima_filas),
        _CATALOGO_UNIDAD,
        _CATALOGO_MARCA,
    )


def test_h1_es_todo_el_universo_menos_sin_correspondencia():
    """"500-2" no tiene fila de INVIMA -- falla H1, no debe pasar a H2."""
    auditoria = _auditar(
        [_fila_gemanet("500-1"), _fila_gemanet("500-2")],
        [_fila_invima("500-1")],
    )
    cadena = construir_cadena_calidad(auditoria)
    h1 = cadena[0]
    assert h1.universo == 2
    estado_por_codigo = h1.df_tabla.set_index("CODIGO_INTERNO")[h1.columna_estado]
    assert estado_por_codigo["500-1"] == ESTADO_CADENA_PASA
    assert estado_por_codigo["500-2"] == ESTADO_CADENA_NO_PASA


def test_h2_es_subconjunto_estricto_de_h1():
    """Una fila con DESCRIPCION distinta pasa H1 (tiene correspondencia) pero
    no H2 (el campo difiere) -- la propiedad central de la cadena: H2 nunca
    tiene una fila que H1 no tuviera."""
    auditoria = _auditar(
        [
            _fila_gemanet("500-1"),
            _fila_gemanet("500-2", DESCRIPCION="IBUPROFENO 400MG TABLETA"),
        ],
        [_fila_invima("500-1"), _fila_invima("500-2")],
    )
    cadena = construir_cadena_calidad(auditoria)
    h1, h2 = cadena[0], cadena[1]

    pasa_h1 = h1.df_tabla[h1.columna_estado] == ESTADO_CADENA_PASA
    pasa_h2 = h2.df_tabla[h2.columna_estado] == ESTADO_CADENA_PASA

    assert (pasa_h2 & ~pasa_h1).sum() == 0
    assert pasa_h1.sum() == 2
    assert pasa_h2.sum() == 1


def test_cada_eslabon_es_subconjunto_del_anterior_para_toda_la_cadena():
    """Fila que coincide en todo hasta PRINCIPIO_ACTIVO (H3) pero difiere en
    CONCENTRACION (H4): debe seguir pasando H1-H3 y caer justo en H4."""
    auditoria = _auditar(
        [_fila_gemanet("500-1", CONCENTRACION="OTRA PRESENTACION DISTINTA")],
        [_fila_invima("500-1")],
    )
    cadena = construir_cadena_calidad(auditoria)
    pasa_por_eslabon = {
        eslabon.nombre: bool((eslabon.df_tabla[eslabon.columna_estado] == ESTADO_CADENA_PASA).iloc[0])
        for eslabon in cadena
    }
    nombres = [nombre for nombre, _ in CADENA_CALIDAD_DEFAULT]
    indice_h4 = nombres.index("H4")
    for nombre in nombres[:indice_h4]:
        assert pasa_por_eslabon[nombre] is True, nombre
    for nombre in nombres[indice_h4:]:
        assert pasa_por_eslabon[nombre] is False, nombre


def test_porcentaje_total_es_nan_si_universo_del_eslabon_es_cero():
    """Si ninguna fila tiene correspondencia con INVIMA, H1 ya deja el
    universo de H2 en cero -- el porcentaje de H2 debe quedar vacio, nunca
    en 0 %, mismo criterio no negociable que PORCENTAJE_CALIDAD."""
    auditoria = _auditar([_fila_gemanet("500-1")], [_fila_invima("999-9")])
    cadena = construir_cadena_calidad(auditoria)
    h1, h2 = cadena[0], cadena[1]
    assert h1.universo == 1
    assert h1.porcentaje_total == 0.0  # 0 de 1 SI tienen correspondencia: valido, no vacio
    assert h2.universo == 0
    assert h2.porcentaje_total is None


def test_porcentaje_total_no_es_cero_cuando_todo_pasa():
    auditoria = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    cadena = construir_cadena_calidad(auditoria)
    for eslabon in cadena:
        assert eslabon.porcentaje_total == 100.0


def test_campo_sin_dato_en_gemanet_no_pasa_el_eslabon():
    """MARCA_MEDICAMENTO=1 ("SIN INFORMACION") no es un error de INVIMA --
    pero tampoco es evidencia de que el dato este correcto, asi que no debe
    contar como "pasa" un eslabon que dependa de ese campo."""
    cadena_con_marca = (("H1", None), ("H_marca", "MARCA_MEDICAMENTO"))
    auditoria = _auditar(
        [_fila_gemanet("500-1", MARCA_MEDICAMENTO=1)], [_fila_invima("500-1")]
    )
    cadena = construir_cadena_calidad(auditoria, cadena=cadena_con_marca)
    h_marca = cadena[1]
    assert (h_marca.df_tabla[h_marca.columna_estado] == ESTADO_CADENA_NO_PASA).all()


def test_columnas_acumuladas_de_h3_incluyen_las_de_h1_y_h2():
    auditoria = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    cadena = construir_cadena_calidad(auditoria)
    h1, h2, h3 = cadena[0], cadena[1], cadena[2]
    assert set(h1.columnas_trio).issubset(h3.columnas_trio)
    assert set(h2.columnas_trio).issubset(h3.columnas_trio)
    assert "DESCRIPCION_VALIDACION" in h3.columnas_trio
    assert "PRINCIPIO_ACTIVO_VALIDACION" in h3.columnas_trio


def test_construir_cadena_calidad_solo_recibe_el_dataframe_ya_auditado():
    """Contrato de rendimiento: la funcion no debe necesitar df_invima ni
    catalogos crudos -- todo lo que usa ya esta materializado en `auditoria`
    por auditar_coherencia(), sin volver a tocar ninguna fuente cruda."""
    auditoria = _auditar([_fila_gemanet("500-1")], [_fila_invima("500-1")])
    cadena = construir_cadena_calidad(auditoria)
    assert len(cadena) == len(CADENA_CALIDAD_DEFAULT)
