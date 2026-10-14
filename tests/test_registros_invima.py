import pandas as pd
import pytest

from gemma_cum_loader.auditoria.coherencia_invima import (
    CAMPOS_COMPARADOS_COHERENCIA,
    SUFIJO_INVIMA,
    SUFIJO_VALIDACION,
    VALIDACION_COINCIDE,
    VALIDACION_DIFIERE,
    VALIDACION_PENDIENTE_GYC,
    auditar_coherencia,
)
from gemma_cum_loader.auditoria.registros_invima import (
    COLUMNA_ELECCION,
    COLUMNA_FILAS_INVIMA,
    COLUMNA_OTRO_COINCIDE_MAS,
    COLUMNA_REGISTRO_CRUZADO,
    COLUMNA_REGISTROS_DISTINTOS,
    COLUMNAS_INVIMA_COMPARADAS,
    COLUMNAS_TABLA_REGISTROS,
    ELECCION_APLICADA,
    ELECCION_NO_ENCONTRADA,
    OTRO_COINCIDE_MAS_NO,
    OTRO_COINCIDE_MAS_SI,
    aplicar_elecciones_registro,
    comparar_contra_cada_registro_invima,
    filas_invima_con_registro,
    registros_distintos_por_clave,
)
from gemma_cum_loader.catalogos.resolver import cargar_catalogo
from gemma_cum_loader.normaliza.texto import normalizar_entidad

_CATALOGO_UNIDAD = cargar_catalogo([(10, "MG - MILIGRAMO")])
_CATALOGO_MARCA = cargar_catalogo(
    [(200, "ACME SAS"), (201, "OTRO LABORATORIO SAS")],
    normalizador=normalizar_entidad,
    dividir_sigla_descripcion=False,
)

_TRIO = [
    f"{campo}{sufijo}" for campo in CAMPOS_COMPARADOS_COHERENCIA for sufijo in (SUFIJO_INVIMA, SUFIJO_VALIDACION)
]


def _fila_gemanet(codigo_interno, **overrides):
    base = {
        "CODIGO_INTERNO": codigo_interno,
        "DESCRIPCION": "ACETAMINOFEN 500MG TABLETA",
        "CONCENTRACION": "500 MG",
        "FORMA_FARMACEUTICA": "TABLETA",
        "PRINCIPIO_ACTIVO": "ACETAMINOFEN",
        "CODIGO_ATC": "N02BE01",
        "MARCA_MEDICAMENTO": 200,
        "UNIDAD_MEDIDA": 10,
        "ACTIVO": "SI",
    }
    base.update(overrides)
    return base


def _fila_invima(codigo_interno, **overrides):
    # Las 29 columnas del archivo real de INVIMA, para que la prueba de
    # "columnas que no se comparan" las recorra todas.
    base = {
        "EXPEDIENTE": codigo_interno.split("-")[0],
        "PRODUCTO": "ACETAMINOFEN 500",
        "TITULAR": "ACME SAS",
        "REGISTRO_SANITARIO": "INVIMA 2020M-0000001",
        "FECHA_EXPEDICION": "2020-01-01",
        "ESTADO_REGISTRO": "Vigente",
        "EXPEDIENTE_CUM": codigo_interno.split("-")[0],
        "CONSECUTIVO": codigo_interno.split("-")[1],
        "CANTIDAD_CUM": "100",
        "DESCRIPCION_COMERCIAL": "CAJA POR 100 TABLETAS",
        "ESTADO_CUM": "Activo",
        "FECHA_ACTIVO": "2020-01-01",
        "MUESTRA_MEDICA": "No",
        "UNIDAD": "U",
        "ATC": "N02BE01",
        "DESCRIPCION_ATC": "PARACETAMOL",
        "VIA_ADMINISTRACION": "ORAL",
        "CONCENTRACION": "500 MG",
        "PRINCIPIO_ACTIVO": "ACETAMINOFEN",
        "UNIDAD_MEDIDA": "mg",
        "CANTIDAD": 500,
        "UNIDAD_REFERENCIA": "CADA TABLETA CONTIENE",
        "FORMA_FARMACEUTICA": "TABLETA",
        "NOMBRE_ROL": "ACME SAS",
        "TIPO_ROL": "FABRICANTE",
        "MODALIDAD": "FABRICAR Y VENDER",
        "FECHA_INACTIVO": "",
        "IUM": "",
        "FECHA_VENCIMIENTO": "2030-01-01",
        "CODIGO_INTERNO": codigo_interno,
    }
    base.update(overrides)
    return base


def _combinado(codigo="20086888-11"):
    return [
        _fila_invima(codigo, PRINCIPIO_ACTIVO="IBUPROFENO", CANTIDAD=400, CONCENTRACION="400 MG"),
        _fila_invima(codigo, PRINCIPIO_ACTIVO="TIOCOLCHICOSIDO", CANTIDAD=4, CONCENTRACION="400 MG"),
    ]


def _comparar(gemanet_filas, invima_filas, vencidos_filas=None):
    reporte = pd.DataFrame(gemanet_filas)
    invima = pd.DataFrame(invima_filas)
    vencidos = pd.DataFrame(vencidos_filas) if vencidos_filas is not None else None
    comparacion = comparar_contra_cada_registro_invima(
        reporte, invima, _CATALOGO_UNIDAD, _CATALOGO_MARCA, df_invima_vencidos=vencidos
    )
    normal = auditar_coherencia(
        reporte, invima, _CATALOGO_UNIDAD, _CATALOGO_MARCA, df_invima_vencidos=vencidos
    )
    return comparacion, normal


def _registro(comparacion, numero, fila=0):
    tabla = comparacion.registros
    return tabla[(tabla["FILA_AUDITORIA"] == fila) & (tabla["REGISTRO"] == numero)].iloc[0]


def test_filas_que_solo_cambian_el_rol_son_un_solo_registro():
    """Caso mayoritario en INVIMA (77.272 CUM): la misma presentacion con un
    fabricante y un importador. Elegir otra fila no cambia ningun veredicto,
    asi que no hay nada que avisar ni que elegir."""
    comparacion, _ = _comparar(
        [_fila_gemanet("20012345-1")],
        [
            _fila_invima("20012345-1", NOMBRE_ROL="ACME SAS", TIPO_ROL="FABRICANTE"),
            _fila_invima("20012345-1", NOMBRE_ROL="DISTRIBUIDORA SAS", TIPO_ROL="IMPORTADOR"),
        ],
    )

    assert comparacion.resumen.loc[0, COLUMNA_REGISTROS_DISTINTOS] == 1
    assert comparacion.resumen.loc[0, COLUMNA_FILAS_INVIMA] == 2
    # Un solo registro: vacio, no "No" -- no hubo otro contra que comparar.
    assert comparacion.resumen.loc[0, COLUMNA_OTRO_COINCIDE_MAS] == ""
    assert comparacion.registros.empty
    assert list(comparacion.registros.columns) == list(COLUMNAS_TABLA_REGISTROS)


def test_el_registro_1_reproduce_el_trio_del_cruce_normal():
    """La garantia de que esto usa la MISMA logica que la auditoria y no una
    copia: el registro 1 es el que el cruce normal ya usa, y su trio tiene
    que salir identico, campo por campo -- tambien el combinado a GyC."""
    gemanet = [
        _fila_gemanet("20086888-11", DESCRIPCION="TIOCOLCHICOSIDO 4MG TABLETA", PRINCIPIO_ACTIVO="TIOCOLCHICOSIDO"),
        _fila_gemanet(
            "20086888-12",
            DESCRIPCION="IBUPROFENO 400MG TABLETA TIOCOLCHICOSIDO 4MG TABLETA",
            PRINCIPIO_ACTIVO="IBUPROFENO TIOCOLCHICOSIDO",
        ),
    ]
    comparacion, normal = _comparar(gemanet, _combinado("20086888-11") + _combinado("20086888-12"))

    for fila in (0, 1):
        registro_1 = _registro(comparacion, 1, fila)
        # Tambien lo que arma el diagnostico de la consulta: si el registro 1
        # no reproduce estado, campos distintos y calidad, elegir un registro
        # cambiaria el caso por algo distinto de "otro registro".
        for columna in [*_TRIO, "CAMPOS_CON_DIFERENCIA", "ESTADO_COHERENCIA", "PORCENTAJE_CALIDAD"]:
            assert registro_1[columna] == normal.loc[fila, columna], columna
    # Y el combinado pegado sigue en GyC contra cualquiera de los registros.
    assert _registro(comparacion, 2, 1)["DESCRIPCION_VALIDACION"] == VALIDACION_PENDIENTE_GYC


def test_gemma_que_calza_con_el_segundo_registro_lo_ordena_primero_y_avisa():
    """El caso que motivo el pedido: el cruce normal dice "difiere" porque
    mira la primera fila, y Gemma Net calza con la segunda del mismo CUM."""
    comparacion, normal = _comparar(
        [_fila_gemanet("20086888-11", DESCRIPCION="TIOCOLCHICOSIDO 4MG TABLETA", PRINCIPIO_ACTIVO="TIOCOLCHICOSIDO", CONCENTRACION="400 MG")],
        _combinado(),
    )

    assert normal.loc[0, "PRINCIPIO_ACTIVO_VALIDACION"] == VALIDACION_DIFIERE
    segundo = _registro(comparacion, 2)
    assert segundo["PRINCIPIO_ACTIVO_VALIDACION"] == VALIDACION_COINCIDE
    assert segundo["DESCRIPCION_VALIDACION"] == VALIDACION_COINCIDE
    assert segundo["ORDEN_COINCIDENCIA"] == 1
    assert _registro(comparacion, 1)["ORDEN_COINCIDENCIA"] == 2
    assert segundo["PORCENTAJE_COINCIDENCIA"] > _registro(comparacion, 1)["PORCENTAJE_COINCIDENCIA"]
    assert comparacion.resumen.loc[0, COLUMNA_REGISTROS_DISTINTOS] == 2
    assert comparacion.resumen.loc[0, COLUMNA_OTRO_COINCIDE_MAS] == OTRO_COINCIDE_MAS_SI


def test_a_igual_coincidencia_el_registro_del_cruce_normal_va_primero():
    """Nunca se sugiere "otro" registro que no mejora nada: con empate, gana
    el que ya usa la auditoria."""
    comparacion, _ = _comparar(
        [_fila_gemanet("20086888-11", DESCRIPCION="IBUPROFENO 400MG TABLETA TIOCOLCHICOSIDO 4MG TABLETA",
                       PRINCIPIO_ACTIVO="IBUPROFENO TIOCOLCHICOSIDO", CONCENTRACION="400 MG")],
        _combinado(),
    )

    assert _registro(comparacion, 1)["ORDEN_COINCIDENCIA"] == 1
    assert comparacion.resumen.loc[0, COLUMNA_OTRO_COINCIDE_MAS] == OTRO_COINCIDE_MAS_NO


def test_varios_titulares_marca_que_calza_con_el_segundo():
    comparacion, normal = _comparar(
        [_fila_gemanet("20012345-1", MARCA_MEDICAMENTO=201)],
        [
            _fila_invima("20012345-1", TITULAR="ACME SAS"),
            _fila_invima("20012345-1", TITULAR="OTRO LABORATORIO SAS"),
        ],
    )

    assert normal.loc[0, "MARCA_MEDICAMENTO_VALIDACION"] == VALIDACION_DIFIERE
    assert _registro(comparacion, 2)["MARCA_MEDICAMENTO_VALIDACION"] == VALIDACION_COINCIDE
    assert comparacion.resumen.loc[0, COLUMNA_OTRO_COINCIDE_MAS] == OTRO_COINCIDE_MAS_SI


def test_cum_que_vive_en_vencidos_no_rellena_el_registro_2_con_el_1():
    """El cruce normal completa los campos vacios desde los listados de menor
    prioridad. El registro 2 de un CUM de Vencidos no debe completarse con
    el registro 1 del MISMO listado: su descripcion "segun la guia" (sin
    UNIDAD_REFERENCIA) quedaria siendo la del registro 1 y podria decir
    "coincide" contra un dato que este registro no tiene."""
    gemanet = [_fila_gemanet("20012345-1", DESCRIPCION="IBUPROFENO CADA TABLETA CONTIENE", PRINCIPIO_ACTIVO="IBUPROFENO")]
    vencidos = [
        _fila_invima("20012345-1", PRINCIPIO_ACTIVO="IBUPROFENO", CANTIDAD=400),
        _fila_invima("20012345-1", PRINCIPIO_ACTIVO="TIOCOLCHICOSIDO", CANTIDAD=4, UNIDAD_REFERENCIA=""),
    ]
    comparacion, normal = _comparar(gemanet, [_fila_invima("99999999-1")], vencidos)

    registro_1 = _registro(comparacion, 1)
    for columna in [*_TRIO, "CAMPOS_CON_DIFERENCIA"]:
        assert registro_1[columna] == normal.loc[0, columna], columna
    # Fuera de Vigentes el estado de la llamada alternativa no es el del cruce
    # normal ("vencido"): se deja vacio y la pantalla conserva el de la auditoria.
    assert registro_1["ESTADO_COHERENCIA"] == ""
    assert pd.isna(registro_1["PORCENTAJE_CALIDAD"])
    segundo = _registro(comparacion, 2)
    assert "IBUPROFENO" not in segundo["DESCRIPCION_INVIMA"]
    assert segundo["DESCRIPCION_VALIDACION"] == VALIDACION_DIFIERE
    assert segundo["LISTADO_INVIMA"] == "vencido"


def test_sin_registro_en_invima_queda_en_cero_y_sin_aviso():
    comparacion, _ = _comparar([_fila_gemanet("20012345-1")], [_fila_invima("99999999-1")])

    assert comparacion.resumen.loc[0, COLUMNA_REGISTROS_DISTINTOS] == 0
    assert comparacion.resumen.loc[0, COLUMNA_FILAS_INVIMA] == 0
    assert comparacion.resumen.loc[0, COLUMNA_OTRO_COINCIDE_MAS] == ""
    # Vacio, no 0: no se cruzo contra ningun registro (regla 6 del proyecto).
    assert pd.isna(comparacion.resumen.loc[0, COLUMNA_REGISTRO_CRUZADO])


def test_el_registro_sale_del_listado_que_usa_el_cruce_normal():
    """Un CUM en Vigentes que tambien tiene filas viejas en Vencidos: el
    registro es el de Vigentes, las de Vencidos no se cuentan."""
    registros = registros_distintos_por_clave(
        pd.DataFrame([_fila_invima("20012345-1")]),
        pd.DataFrame([_fila_invima("20012345-1", TITULAR="VIEJO SAS"), _fila_invima("20012345-1", CANTIDAD=1)]),
    )

    assert len(registros) == 1
    assert registros.loc[0, "LISTADO_INVIMA"] == "vigente"
    assert registros.loc[0, "FILAS_INVIMA"] == 1


@pytest.mark.parametrize(
    "columna",
    [c for c in _fila_invima("20012345-1") if c not in COLUMNAS_INVIMA_COMPARADAS and c != "CODIGO_INTERNO"],
)
def test_una_columna_que_no_se_compara_no_cambia_el_veredicto(columna):
    """Guarda de `COLUMNAS_INVIMA_COMPARADAS`: dos filas que solo difieren
    fuera de esa lista se cuentan como UN registro. Si `auditar_coherencia`
    empieza a comparar otra columna, esta prueba falla en vez de esconder
    registros que si darian otro veredicto."""
    reporte = pd.DataFrame([_fila_gemanet("20012345-1")])
    base = auditar_coherencia(reporte, pd.DataFrame([_fila_invima("20012345-1")]), _CATALOGO_UNIDAD, _CATALOGO_MARCA)
    valor = "2011-11-11" if columna.startswith("FECHA") else "VALOR DISTINTO 123"
    mutada = auditar_coherencia(
        reporte, pd.DataFrame([_fila_invima("20012345-1", **{columna: valor})]), _CATALOGO_UNIDAD, _CATALOGO_MARCA
    )

    for trio in _TRIO:
        assert mutada.loc[0, trio] == base.loc[0, trio], trio


def test_filas_invima_con_registro_lista_todas_las_filas_con_su_registro():
    """Lo que la consulta muestra como "cuales son": TODAS las filas del CUM,
    no solo una por registro. Las que solo cambian el rol comparten numero."""
    filas = filas_invima_con_registro(
        pd.DataFrame(
            [
                _fila_invima("20012345-1", PRINCIPIO_ACTIVO="IBUPROFENO", TIPO_ROL="FABRICANTE"),
                _fila_invima("20012345-1", PRINCIPIO_ACTIVO="TIOCOLCHICOSIDO", TIPO_ROL="FABRICANTE"),
                _fila_invima("20012345-1", PRINCIPIO_ACTIVO="IBUPROFENO", TIPO_ROL="IMPORTADOR"),
            ]
        )
    )

    assert filas["REGISTRO"].tolist() == [1, 2, 1]
    assert filas["TIPO_ROL"].tolist() == ["FABRICANTE", "FABRICANTE", "IMPORTADOR"]
    assert filas["REGISTROS_DISTINTOS"].unique().tolist() == [2]
    assert filas["FILAS_INVIMA"].unique().tolist() == [3]
    assert filas["FILAS_DEL_REGISTRO"].tolist() == [2, 1, 2]


def test_cada_fila_apunta_a_su_posicion_en_el_listado_original():
    """La comparacion se hace contra la fila ORIGINAL del listado (`.iloc`),
    no contra la copia del concat de los cuatro, que puede cambiar tipos. Una
    fila sin codigo descartada no corre la posicion de las demas."""
    vigentes = pd.DataFrame(
        [
            _fila_invima("20012345-1"),
            {**_fila_invima("20012345-1"), "CODIGO_INTERNO": None},
            _fila_invima("20012345-1", TITULAR="OTRO LABORATORIO SAS"),
        ]
    )
    filas = filas_invima_con_registro(vigentes)

    assert filas["_FILA_ORIGEN"].tolist() == [0, 2]
    assert vigentes.iloc[filas["_FILA_ORIGEN"]]["TITULAR"].tolist() == ["ACME SAS", "OTRO LABORATORIO SAS"]


def _firma(invima_filas, clave, registro, vencidos_filas=None):
    filas = filas_invima_con_registro(
        pd.DataFrame(invima_filas), pd.DataFrame(vencidos_filas) if vencidos_filas else None
    )
    return filas[(filas["_CLAVE"] == clave) & (filas["REGISTRO"] == registro)]["_FIRMA"].iloc[0]


def _cruzar_con_eleccion(gemanet_filas, invima_filas, elecciones, vencidos_filas=None):
    """Lo mismo que hace pipeline.auditar_coherencia_gemanet: la auditoria con
    los listados reordenados y la comparacion con los originales."""
    reporte = pd.DataFrame(gemanet_filas)
    invima = pd.DataFrame(invima_filas)
    vencidos = pd.DataFrame(vencidos_filas) if vencidos_filas is not None else None
    aplicadas = aplicar_elecciones_registro(invima, vencidos, None, None, elecciones)
    normal = auditar_coherencia(
        reporte, aplicadas.listados[0], _CATALOGO_UNIDAD, _CATALOGO_MARCA, df_invima_vencidos=aplicadas.listados[1]
    )
    comparacion = comparar_contra_cada_registro_invima(
        reporte, invima, _CATALOGO_UNIDAD, _CATALOGO_MARCA, df_invima_vencidos=vencidos,
        registro_cruzado=aplicadas.registro_por_clave, elecciones_no_encontradas=aplicadas.no_encontradas,
    )
    return aplicadas, normal, comparacion


def test_elegir_el_registro_2_hace_que_la_auditoria_cruce_contra_el():
    """Pedido del usuario (2026-10-14): "debe permitirme cual quiero cruzar",
    guardado. La auditoria cruza contra el elegido -- y da EXACTAMENTE lo que la
    comparacion mostraba para ese registro: es la misma logica, no otra."""
    gemanet = [_fila_gemanet("20086888-11", DESCRIPCION="TIOCOLCHICOSIDO 4MG TABLETA", PRINCIPIO_ACTIVO="TIOCOLCHICOSIDO", CONCENTRACION="400 MG")]
    elecciones = {"20086888-11": _firma(_combinado(), "20086888-11", 2)}
    aplicadas, normal, comparacion = _cruzar_con_eleccion(gemanet, _combinado(), elecciones)

    assert aplicadas.registro_por_clave == {"20086888-11": 2}
    assert normal.loc[0, "PRINCIPIO_ACTIVO_VALIDACION"] == VALIDACION_COINCIDE
    segundo = _registro(comparacion, 2)
    for columna in [*_TRIO, "CAMPOS_CON_DIFERENCIA", "ESTADO_COHERENCIA", "PORCENTAJE_CALIDAD"]:
        assert segundo[columna] == normal.loc[0, columna], columna
    assert comparacion.resumen.loc[0, COLUMNA_REGISTRO_CRUZADO] == 2
    assert comparacion.resumen.loc[0, COLUMNA_ELECCION] == ELECCION_APLICADA
    # El elegido ya es el que mas coincide: no hay "otro" que sugerir.
    assert comparacion.resumen.loc[0, COLUMNA_OTRO_COINCIDE_MAS] == OTRO_COINCIDE_MAS_NO
    # La numeracion sigue siendo la del archivo de INVIMA, no la del reordenado.
    assert _registro(comparacion, 1)["PRINCIPIO_ACTIVO_INVIMA"] == "IBUPROFENO"


def test_una_eleccion_que_ya_no_existe_en_invima_no_se_aplica_ni_se_adivina():
    gemanet = [_fila_gemanet("20086888-11")]
    aplicadas, _normal, comparacion = _cruzar_con_eleccion(gemanet, _combinado(), {"20086888-11": "firma que ya no existe"})

    assert aplicadas.registro_por_clave == {}
    assert aplicadas.no_encontradas == frozenset({"20086888-11"})
    assert aplicadas.listados[0]["PRINCIPIO_ACTIVO"].tolist() == ["IBUPROFENO", "TIOCOLCHICOSIDO"]
    assert comparacion.resumen.loc[0, COLUMNA_REGISTRO_CRUZADO] == 1
    assert comparacion.resumen.loc[0, COLUMNA_ELECCION] == ELECCION_NO_ENCONTRADA


def test_elegir_un_registro_de_un_cum_que_vive_en_vencidos():
    gemanet = [_fila_gemanet("20012345-1", MARCA_MEDICAMENTO=201)]
    vencidos = [
        _fila_invima("20012345-1", TITULAR="ACME SAS"),
        _fila_invima("20012345-1", TITULAR="OTRO LABORATORIO SAS"),
    ]
    elecciones = {"20012345-1": _firma([_fila_invima("99999999-1")], "20012345-1", 2, vencidos)}
    aplicadas, normal, comparacion = _cruzar_con_eleccion(gemanet, [_fila_invima("99999999-1")], elecciones, vencidos)

    assert aplicadas.registro_por_clave == {"20012345-1": 2}
    assert normal.loc[0, "MARCA_MEDICAMENTO_VALIDACION"] == VALIDACION_COINCIDE
    assert normal.loc[0, "ESTADO_COHERENCIA"] == "vencido_en_invima"
    assert comparacion.resumen.loc[0, COLUMNA_REGISTRO_CRUZADO] == 2
