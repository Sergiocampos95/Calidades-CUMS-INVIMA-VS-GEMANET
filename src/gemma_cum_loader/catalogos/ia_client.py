"""Explicaciones de IA para las filas en cuarentena/rechazo del pipeline.

No resuelve codigos ni participa en la cascada deterministica de resolver.py
(exacto -> alias -> fuzzy) -- esa cascada es la unica fuente de verdad para
codigos y nunca depende de un modelo (100.000+ filas, tiene que ser exacta y
agil sin llamadas de red). La IA aqui solo traduce el `motivo` tecnico que ya
calculo validacion/reglas.py a una explicacion legible para el equipo de
negocio que revisa la bandeja de cuarentena en Streamlit.

Costo bajo por diseno: los `motivo` posibles son un vocabulario fijo y chico
(ver reglas.py), asi que explicar_motivo() se piensa para llamarse una vez por
motivo distinto -- nunca una vez por fila, sin importar si la malla tiene 100 o
100.000 filas. explicar_fila() si manda los valores de una fila puntual, pero
solo cuando el usuario lo pide desde la UI (boton "Explicar este caso"), nunca
en el batch del pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping

MODELO_IA = "claude-haiku-4-5"

_SCHEMA_EXPLICACION = {
    "type": "object",
    "properties": {
        "explicacion": {
            "type": "string",
            "description": "Por que esta fila cayo en esta accion, en espanol claro, sin jerga tecnica.",
        },
        "consejo": {
            "type": "string",
            "description": "Que deberia hacer el equipo de negocio con este caso, en una frase.",
        },
    },
    "required": ["explicacion", "consejo"],
    "additionalProperties": False,
}

_SYSTEM = (
    "Explicas a un equipo de negocio (no tecnico) por que una fila de la malla "
    "de cargue de medicamentos fue rechazada, descartada o puesta en cuarentena "
    "por un pipeline de validacion contra el catalogo INVIMA. Recibes la accion "
    "tomada y el motivo tecnico. Responde en espanol claro y breve, sin jerga de "
    "programacion (no menciones nombres de funciones, columnas internas ni "
    "codigo). El objetivo es que la persona entienda que paso y que hacer, no "
    "como funciona el sistema por dentro."
)


@dataclass(frozen=True)
class ExplicacionIA:
    explicacion: str
    consejo: str


_EXPLICACION_FALLA_CONEXION = ExplicacionIA(
    explicacion="No se pudo generar la explicacion (fallo de conexion con el servicio de IA).",
    consejo="Revisar el motivo tecnico manualmente o reintentar mas tarde.",
)
_EXPLICACION_SIN_RESPUESTA = ExplicacionIA(
    explicacion="El servicio de IA no pudo generar una explicacion para este caso.",
    consejo="Revisar el motivo tecnico manualmente.",
)


@dataclass
class ClienteExplicacionIA:
    """Envuelve el cliente de Anthropic. Inyectar `client` en tests (nunca
    golpear la API real desde la suite de pytest)."""

    client: Any = None
    modelo: str = MODELO_IA

    def __post_init__(self) -> None:
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic()

    def explicar_motivo(self, accion: str, motivo: str) -> ExplicacionIA:
        """Explicacion generica del motivo, sin datos de fila.

        Llamar una vez por motivo distinto (ver reglas.py: son pocos y fijos),
        no una vez por fila -- es lo que mantiene esto barato a cualquier
        volumen de la malla.
        """
        prompt = f"Accion tomada: {accion}\nMotivo tecnico: {motivo}"
        return self._pedir_explicacion(prompt)

    def explicar_fila(self, accion: str, motivo: str, fila: Mapping[str, object]) -> ExplicacionIA:
        """Explicacion puntual con los valores reales de una fila.

        Para el boton "Explicar este caso" de la bandeja de cuarentena en
        Streamlit -- se dispara bajo demanda del usuario, nunca en el batch.
        """
        campos = "\n".join(f"- {campo}: {valor!r}" for campo, valor in fila.items())
        prompt = f"Accion tomada: {accion}\nMotivo tecnico: {motivo}\n\nDatos de la fila:\n{campos}"
        return self._pedir_explicacion(prompt)

    def _pedir_explicacion(self, prompt: str) -> ExplicacionIA:
        try:
            response = self.client.messages.create(
                model=self.modelo,
                max_tokens=512,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": _SCHEMA_EXPLICACION}},
            )
        except Exception:
            # Boundary con un servicio externo: un fallo de red/API no debe
            # tumbar la revision de las demas filas en cuarentena.
            return _EXPLICACION_FALLA_CONEXION

        if response.stop_reason == "refusal":
            return _EXPLICACION_SIN_RESPUESTA

        texto = next((b.text for b in response.content if b.type == "text"), None)
        if texto is None:
            return _EXPLICACION_SIN_RESPUESTA

        datos = json.loads(texto)
        return ExplicacionIA(explicacion=datos["explicacion"], consejo=datos["consejo"])
