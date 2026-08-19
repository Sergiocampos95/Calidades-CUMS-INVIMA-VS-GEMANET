"""Tests de ingesta/invima_socrata.py con una sesion HTTP falsa -- nunca
golpean la API real de Socrata/INVIMA."""

from dataclasses import dataclass, field

import pytest

from gemma_cum_loader.integraciones.socrata import ErrorSocrata
from gemma_cum_loader.ingesta.invima_socrata import (
    CAMPOS_API,
    DATASET_CUM_VENCIDOS,
    DATASET_CUM_VIGENTES,
    EstadoValidacionCUM,
    comparar_nombre,
    consultar_cum,
    leer_catalogo_invima_api,
)


@dataclass
class _RespuestaFalsa:
    status_code: int
    _datos: object

    def json(self):
        return self._datos


@dataclass
class _SesionFalsa:
    respuestas: list
    llamadas: list = field(default_factory=list)

    def get(self, url, params, headers, timeout):
        self.llamadas.append({"url": url, "params": params, "headers": headers})
        return self.respuestas[len(self.llamadas) - 1]


def _fila_api(**overrides):
    base = {
        "expediente": "500",
        "producto": "PROD",
        "titular": "TIT",
        "registrosanitario": "INVIMA 1",
        "estadoregistro": "Vigente",
        "expedientecum": "500",
        "consecutivocum": "1",
        "cantidadcum": "1",
        "descripcioncomercial": "DESC",
        "estadocum": "Activo",
        "muestramedica": "No",
        "unidad": "MG",
        "atc": "N02BE01",
        "descripcionatc": "ANALGESICO",
        "viaadministracion": "ORAL",
        "concentracion": "500 MG",
        "principioactivo": "ACETAMINOFEN",
        "unidadmedida": "mg",
        "cantidad": "500",
        "unidadreferencia": "TABLETA",
        "formafarmaceutica": "TABLETA",
        "nombrerol": "LAB",
        "tiporol": "FABRICANTE",
        "modalidad": "NACIONAL",
    }
    base.update(overrides)
    return base


def test_campos_api_cubre_las_29_columnas_confirmadas():
    assert len(CAMPOS_API) == 29


def test_leer_catalogo_invima_api_arma_codigo_interno():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [_fila_api()])])
    df = leer_catalogo_invima_api(token="t", sesion=sesion)
    assert "CODIGO_INTERNO" in df.columns
    assert list(df["CODIGO_INTERNO"]) == ["500-1"]


def test_leer_catalogo_invima_api_produce_las_mismas_columnas_normalizadas_que_el_excel():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [_fila_api()])])
    df = leer_catalogo_invima_api(token="t", sesion=sesion)
    # columnas clave que el resto del pipeline (armado/malla.py) exige
    for columna in ["EXPEDIENTE", "ESTADO_REGISTRO", "ESTADO_CUM", "TIPO_ROL", "PRINCIPIO_ACTIVO", "UNIDAD_REFERENCIA"]:
        assert columna in df.columns


def test_leer_catalogo_invima_api_pagina_todo_el_dataset():
    pagina_1 = [_fila_api(expediente=str(i), consecutivocum="1") for i in range(2)]
    sesion = _SesionFalsa([_RespuestaFalsa(200, pagina_1), _RespuestaFalsa(200, [])])
    df = leer_catalogo_invima_api(token="t", sesion=sesion, )
    assert len(df) == 2


def test_leer_catalogo_invima_api_dataset_vacio_lanza_error():
    # caso real verificado 2026-08-18: el recurso de datos de INVIMA en
    # Socrata respondio 200 OK con 0 filas para una sincronizacion completa
    # (sin filtro) -- eso nunca es legitimo, INVIMA siempre tiene registros.
    # Silenciarlo produciria un catalogo vacio que haria ver TODO lo cargado
    # en Gemma Net como sin vigencia -- se rechaza en vez de continuar.
    sesion = _SesionFalsa([_RespuestaFalsa(200, [])])
    with pytest.raises(ErrorSocrata):
        leer_catalogo_invima_api(token="t", sesion=sesion)


def test_leer_catalogo_invima_api_usa_vigentes_por_defecto():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [_fila_api()])])
    leer_catalogo_invima_api(token="t", sesion=sesion)
    assert DATASET_CUM_VIGENTES in sesion.llamadas[0]["url"]


def test_leer_catalogo_invima_api_puede_apuntar_al_dataset_de_vencidos():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [_fila_api(expediente="700", consecutivocum="2")])])
    df = leer_catalogo_invima_api(token="t", sesion=sesion, dataset=DATASET_CUM_VENCIDOS)
    assert DATASET_CUM_VENCIDOS in sesion.llamadas[0]["url"]
    assert list(df["CODIGO_INTERNO"]) == ["700-2"]


def test_consultar_cum_vacio():
    resultado = consultar_cum("", token="t")
    assert resultado.estado == EstadoValidacionCUM.VACIO


def test_consultar_cum_formato_incorrecto():
    resultado = consultar_cum("no-es-un-codigo", token="t")
    assert resultado.estado == EstadoValidacionCUM.FORMATO_INCORRECTO


def test_consultar_cum_sin_token_configurado_y_sin_token_explicito(monkeypatch):
    monkeypatch.delenv("INVIMA_SOCRATA_APP_TOKEN", raising=False)
    resultado = consultar_cum("500-1")
    assert resultado.estado == EstadoValidacionCUM.API_NO_CONFIGURADA


def test_consultar_cum_encontrado():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [_fila_api(expediente="500", consecutivocum="1")])])
    resultado = consultar_cum("500-1", token="t", sesion=sesion)
    assert resultado.estado == EstadoValidacionCUM.VALIDO_VIGENTE
    assert resultado.datos_oficiales["producto"] == "PROD"
    assert resultado.fecha_consulta is not None


def test_consultar_cum_no_encontrado():
    # 1ra llamada: la consulta puntual (vacia). 2da llamada: el chequeo de
    # "el dataset en general SI tiene datos" (count > 0) -- solo con eso
    # confirmado se puede concluir que este CUM puntual no existe
    sesion = _SesionFalsa([_RespuestaFalsa(200, []), _RespuestaFalsa(200, [{"count": "101183"}])])
    resultado = consultar_cum("999-9", token="t", sesion=sesion)
    assert resultado.estado == EstadoValidacionCUM.NO_ENCONTRADO


def test_consultar_cum_dataset_completo_vacio_no_se_confunde_con_no_encontrado():
    # caso real 2026-08-18: si el dataset ENTERO de INVIMA esta vacio (0
    # filas incluso sin filtro), un "no encontrado" en la consulta puntual
    # seria enganoso -- no es que el medicamento no exista, es que INVIMA
    # no tiene nada que mostrar ahora mismo
    sesion = _SesionFalsa([_RespuestaFalsa(200, []), _RespuestaFalsa(200, [{"count": "0"}])])
    resultado = consultar_cum("999-9", token="t", sesion=sesion)
    assert resultado.estado == EstadoValidacionCUM.SERVICIO_NO_DISPONIBLE
    assert "no es que este CUM puntual no exista" in resultado.mensaje


def test_consultar_cum_no_encontrado_si_falla_el_chequeo_de_disponibilidad_trata_como_servicio_no_disponible():
    # si ni siquiera se puede confirmar que el dataset tiene datos (fallo de
    # transporte en el chequeo), no hay base para decir "no existe" --
    # mejor pecar de cauteloso que dar un falso "no encontrado"
    sesion = _SesionFalsa([_RespuestaFalsa(200, []), _RespuestaFalsa(500, {})])
    resultado = consultar_cum("999-9", token="t", sesion=sesion)
    assert resultado.estado == EstadoValidacionCUM.SERVICIO_NO_DISPONIBLE


def test_consultar_cum_usa_where_con_expediente_y_consecutivo():
    sesion = _SesionFalsa([_RespuestaFalsa(200, []), _RespuestaFalsa(200, [{"count": "1"}])])
    consultar_cum("500-1", token="t", sesion=sesion)
    where = sesion.llamadas[0]["params"]["$where"]
    assert "expediente='500'" in where
    assert "consecutivocum='1'" in where


def test_consultar_cum_error_autenticacion():
    sesion = _SesionFalsa([_RespuestaFalsa(401, {})])
    resultado = consultar_cum("500-1", token="invalido", sesion=sesion)
    assert resultado.estado == EstadoValidacionCUM.ERROR_AUTENTICACION


def test_consultar_cum_servicio_no_disponible():
    sesion = _SesionFalsa([_RespuestaFalsa(500, {})])
    resultado = consultar_cum("500-1", token="t", sesion=sesion)
    assert resultado.estado == EstadoValidacionCUM.SERVICIO_NO_DISPONIBLE


def test_comparar_nombre_coincide_no_cambia_el_estado():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [_fila_api(producto="ACETAMINOFEN TABLETAS")])])
    resultado = consultar_cum("500-1", token="t", sesion=sesion)
    assert comparar_nombre("ACETAMINOFEN TABLETAS", resultado) == EstadoValidacionCUM.VALIDO_VIGENTE


def test_comparar_nombre_diferente_degrada_a_con_diferencias():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [_fila_api(producto="ACETAMINOFEN TABLETAS")])])
    resultado = consultar_cum("500-1", token="t", sesion=sesion)
    assert comparar_nombre("IBUPROFENO CAPSULAS", resultado) == EstadoValidacionCUM.CON_DIFERENCIAS


def test_comparar_nombre_no_toca_estados_que_no_son_valido_vigente():
    sesion = _SesionFalsa([_RespuestaFalsa(200, []), _RespuestaFalsa(200, [{"count": "1"}])])
    resultado = consultar_cum("999-9", token="t", sesion=sesion)
    assert comparar_nombre("CUALQUIER COSA", resultado) == EstadoValidacionCUM.NO_ENCONTRADO
