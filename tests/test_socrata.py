"""Tests de integraciones/socrata.py con una sesion HTTP falsa -- nunca
golpean la red real (ni Socrata ni ningun otro host)."""

from dataclasses import dataclass, field

import pytest

from gemma_cum_loader.integraciones.socrata import (
    ErrorAutenticacionSocrata,
    ErrorSocrata,
    consultar,
    consultar_todo,
    enmascarar_token,
    estado_token,
    hay_datos,
)


@dataclass
class _RespuestaFalsa:
    status_code: int
    _datos: object
    text: str = ""

    def json(self):
        return self._datos


@dataclass
class _SesionFalsa:
    respuestas: list
    llamadas: list = field(default_factory=list)

    def get(self, url, params, headers, timeout):
        self.llamadas.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return self.respuestas[len(self.llamadas) - 1]


def test_consultar_envia_el_token_en_el_encabezado_x_app_token():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [{"a": "1"}])])
    consultar("abcd-1234", token="mi-token-secreto", sesion=sesion)
    assert sesion.llamadas[0]["headers"]["X-App-Token"] == "mi-token-secreto"


def test_consultar_sin_token_no_envia_el_encabezado():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [])])
    consultar("abcd-1234", token="", sesion=sesion)
    assert "X-App-Token" not in sesion.llamadas[0]["headers"]


def test_consultar_devuelve_el_json_de_la_respuesta():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [{"expediente": "500"}])])
    assert consultar("abcd-1234", token="t", sesion=sesion) == [{"expediente": "500"}]


def test_consultar_401_lanza_error_autenticacion():
    sesion = _SesionFalsa([_RespuestaFalsa(401, {}, text="Unauthorized")])
    with pytest.raises(ErrorAutenticacionSocrata):
        consultar("abcd-1234", token="invalido", sesion=sesion)


def test_consultar_403_lanza_error_autenticacion():
    sesion = _SesionFalsa([_RespuestaFalsa(403, {}, text="Forbidden")])
    with pytest.raises(ErrorAutenticacionSocrata):
        consultar("abcd-1234", token="invalido", sesion=sesion)


def test_consultar_500_lanza_error_socrata_generico():
    sesion = _SesionFalsa([_RespuestaFalsa(500, {}, text="Internal Server Error")])
    with pytest.raises(ErrorSocrata):
        consultar("abcd-1234", token="t", sesion=sesion)


def test_consultar_fallo_de_red_lanza_error_socrata():
    class _SesionQueFalla:
        def get(self, **kwargs):
            raise ConnectionError("timeout")

    with pytest.raises(ErrorSocrata):
        consultar("abcd-1234", token="t", sesion=_SesionQueFalla())


def test_consultar_todo_pagina_hasta_que_una_pagina_no_esta_llena():
    pagina_1 = [{"id": i} for i in range(3)]
    pagina_2 = [{"id": i} for i in range(1)]  # menos que el limite -- fin
    sesion = _SesionFalsa([_RespuestaFalsa(200, pagina_1), _RespuestaFalsa(200, pagina_2)])

    filas = consultar_todo("abcd-1234", token="t", sesion=sesion, limite_pagina=3)

    assert len(filas) == 4
    assert sesion.llamadas[0]["params"]["$offset"] == 0
    assert sesion.llamadas[1]["params"]["$offset"] == 3


def test_consultar_todo_una_sola_pagina_si_ya_viene_incompleta():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [{"id": 1}])])
    filas = consultar_todo("abcd-1234", token="t", sesion=sesion, limite_pagina=100)
    assert len(filas) == 1
    assert len(sesion.llamadas) == 1


def test_estado_token_no_configurado_sin_variable_de_entorno(monkeypatch):
    monkeypatch.delenv("INVIMA_SOCRATA_APP_TOKEN", raising=False)
    estado = estado_token()
    assert estado.configurado is False
    assert estado.origen == "no_configurado"


def test_estado_token_configurado_desde_entorno(monkeypatch):
    monkeypatch.setenv("INVIMA_SOCRATA_APP_TOKEN", "abcd1234efgh5678")
    estado = estado_token()
    assert estado.configurado is True
    assert estado.origen == "entorno"
    # nunca el token completo -- solo enmascarado
    assert estado.token_enmascarado == "************5678"
    assert "abcd1234efgh5678" not in estado.token_enmascarado


def test_enmascarar_token_conserva_solo_los_ultimos_4_caracteres():
    assert enmascarar_token("abcd1234efgh5678") == "************5678"


def test_enmascarar_token_corto_lo_enmascara_completo():
    assert enmascarar_token("ab") == "**"


def test_hay_datos_true_cuando_count_es_mayor_a_cero():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [{"count": "101183"}])])
    assert hay_datos("abcd-1234", token="t", sesion=sesion) is True


def test_hay_datos_false_cuando_count_es_cero():
    # caso real 2026-08-18: el recurso responde 200 con count=0 -- ni error
    # de transporte ni de autenticacion, simplemente no hay filas ahora mismo
    sesion = _SesionFalsa([_RespuestaFalsa(200, [{"count": "0"}])])
    assert hay_datos("abcd-1234", token="t", sesion=sesion) is False


def test_hay_datos_false_si_la_respuesta_viene_vacia():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [])])
    assert hay_datos("abcd-1234", token="t", sesion=sesion) is False


def test_hay_datos_usa_select_count():
    sesion = _SesionFalsa([_RespuestaFalsa(200, [{"count": "5"}])])
    hay_datos("abcd-1234", token="t", sesion=sesion)
    assert sesion.llamadas[0]["params"]["$select"] == "count(*)"


def test_hay_datos_propaga_error_de_transporte():
    sesion = _SesionFalsa([_RespuestaFalsa(500, {}, text="Internal Server Error")])
    with pytest.raises(ErrorSocrata):
        hay_datos("abcd-1234", token="t", sesion=sesion)
