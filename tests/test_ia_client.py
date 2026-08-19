"""Tests de catalogos/ia_client.py con un cliente falso -- nunca golpean la
API real de Anthropic (no hay red ni API key en esta suite)."""

import json
from dataclasses import dataclass, field


from gemma_cum_loader.catalogos.ia_client import (
    ClienteExplicacionIA,
    ExplicacionIA,
    MODELO_IA,
)


@dataclass
class _BloqueTexto:
    text: str
    type: str = "text"


@dataclass
class _RespuestaFalsa:
    content: list
    stop_reason: str = "end_turn"


class _MessagesFalso:
    def __init__(self, padre):
        self._padre = padre

    def create(self, **kwargs):
        self._padre.llamadas.append(kwargs)
        if self._padre.excepcion is not None:
            raise self._padre.excepcion
        return _RespuestaFalsa(
            content=[_BloqueTexto(text=self._padre.texto_json)] if self._padre.texto_json else [],
            stop_reason=self._padre.stop_reason,
        )


@dataclass
class _ClienteFalso:
    texto_json: str | None = None
    stop_reason: str = "end_turn"
    excepcion: Exception | None = None
    llamadas: list = field(default_factory=list)

    def __post_init__(self):
        self.messages = _MessagesFalso(self)


def _respuesta_json(explicacion="El CUM no aparece en el corte vigente de INVIMA.", consejo="Verificar si es posterior al corte."):
    return json.dumps({"explicacion": explicacion, "consejo": consejo})


def test_explicar_motivo_devuelve_explicacion_parseada():
    cliente = _ClienteFalso(texto_json=_respuesta_json())
    servicio = ClienteExplicacionIA(client=cliente)

    resultado = servicio.explicar_motivo("cuarentena", "sin match en el corte INVIMA vigente")

    assert resultado == ExplicacionIA(
        explicacion="El CUM no aparece en el corte vigente de INVIMA.",
        consejo="Verificar si es posterior al corte.",
    )


def test_explicar_motivo_usa_el_modelo_configurado_y_pide_json_schema():
    cliente = _ClienteFalso(texto_json=_respuesta_json())
    servicio = ClienteExplicacionIA(client=cliente)

    servicio.explicar_motivo("cuarentena", "sin match en el corte INVIMA vigente")

    llamada = cliente.llamadas[0]
    assert llamada["model"] == MODELO_IA
    assert llamada["output_config"]["format"]["type"] == "json_schema"
    assert "sin match en el corte INVIMA vigente" in llamada["messages"][0]["content"]


def test_explicar_fila_incluye_los_valores_de_la_fila_en_el_prompt():
    cliente = _ClienteFalso(texto_json=_respuesta_json())
    servicio = ClienteExplicacionIA(client=cliente)

    servicio.explicar_fila(
        "cuarentena",
        "sin match en el corte INVIMA vigente",
        {"CODIGO_INTERNO": "10815-3", "MARCA_MEDICAMENTO": "TECNOQUIMICAS"},
    )

    prompt = cliente.llamadas[0]["messages"][0]["content"]
    assert "10815-3" in prompt
    assert "TECNOQUIMICAS" in prompt


def test_refusal_no_rompe_devuelve_explicacion_generica():
    cliente = _ClienteFalso(texto_json=None, stop_reason="refusal")
    servicio = ClienteExplicacionIA(client=cliente)

    resultado = servicio.explicar_motivo("rechaza", "cualquier motivo")

    assert resultado.explicacion
    assert resultado.consejo


def test_fallo_de_red_no_propaga_excepcion():
    cliente = _ClienteFalso(excepcion=ConnectionError("timeout"))
    servicio = ClienteExplicacionIA(client=cliente)

    resultado = servicio.explicar_motivo("rechaza", "cualquier motivo")

    assert isinstance(resultado, ExplicacionIA)
    assert resultado.explicacion
    assert resultado.consejo


def test_respuesta_sin_bloque_de_texto_no_rompe():
    cliente = _ClienteFalso(texto_json=None, stop_reason="end_turn")
    servicio = ClienteExplicacionIA(client=cliente)

    resultado = servicio.explicar_motivo("rechaza", "cualquier motivo")

    assert isinstance(resultado, ExplicacionIA)
