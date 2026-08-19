"""Cliente generico para la API SODA de Socrata (Datos Abiertos Colombia y
cualquier otro portal Socrata). Este modulo no sabe nada de INVIMA ni de
medicamentos -- solo paginacion, token de aplicacion, y errores de
transporte. Ver ingesta/invima_socrata.py para el adaptador que conoce la
forma del dataset de CUM vigentes.

El App Token identifica la APLICACION ante Socrata (evita el limite mas
estricto del acceso anonimo) -- no es una credencial de usuario de Pijao
Salud, no autoriza nada en Gemma Net, y nunca se guarda en un registro de
medicamento. Se administra por variable de entorno (`token_desde_entorno`),
nunca hardcodeado en el codigo, nunca impreso ni logueado -- mismo patron
ya usado en este proyecto para ANTHROPIC_API_KEY (ver catalogos/ia_client.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

NOMBRE_VARIABLE_ENTORNO = "INVIMA_SOCRATA_APP_TOKEN"
LIMITE_PAGINA = 5000  # SODA acepta hasta 50000, nos quedamos conservadores
TIMEOUT_SEGUNDOS = 30


class ErrorSocrata(Exception):
    """Error de transporte o de la API. Un dataset vacio o un CUM no
    encontrado NO es un ErrorSocrata -- es un resultado valido (0 filas);
    solo esto representa que la consulta en si fallo."""


class ErrorAutenticacionSocrata(ErrorSocrata):
    """401/403 -- el App Token es invalido, vencido, o fue rechazado."""


class SesionHTTP(Protocol):
    """Lo minimo que necesitamos de requests.Session -- permite inyectar un
    doble de prueba en los tests sin golpear la red real."""

    def get(self, url: str, params: dict, headers: dict, timeout: int) -> Any: ...


def _sesion_por_defecto() -> SesionHTTP:
    import requests

    return requests


@dataclass(frozen=True)
class EstadoToken:
    configurado: bool
    origen: str  # "entorno" | "no_configurado"
    token_enmascarado: str = ""


def token_desde_entorno() -> str | None:
    return os.environ.get(NOMBRE_VARIABLE_ENTORNO) or None


def enmascarar_token(token: str) -> str:
    if len(token) <= 4:
        return "*" * len(token)
    return "*" * (len(token) - 4) + token[-4:]


def estado_token() -> EstadoToken:
    """Prioridad: variable de entorno primero. Si no existe, "no_configurado"
    -- esta version no guarda el token dentro de la aplicacion (ver decision
    del usuario: solo variable de entorno para esta primera version)."""
    token = token_desde_entorno()
    if not token:
        return EstadoToken(configurado=False, origen="no_configurado")
    return EstadoToken(configurado=True, origen="entorno", token_enmascarado=enmascarar_token(token))


def consultar(
    identificador_dataset: str,
    parametros: dict[str, Any] | None = None,
    dominio: str = "www.datos.gov.co",
    token: str | None = None,
    sesion: SesionHTTP | None = None,
) -> list[dict]:
    """Una pagina de resultados del dataset -- el llamador pagina si hace
    falta (ver `consultar_todo`). `token=None` usa el de la variable de
    entorno; pasar explicitamente "" fuerza consulta anonima.
    """
    if token is None:
        token = token_desde_entorno()
    sesion = sesion or _sesion_por_defecto()

    headers = {"X-App-Token": token} if token else {}
    url = f"https://{dominio}/resource/{identificador_dataset}.json"
    try:
        respuesta = sesion.get(url, params=parametros or {}, headers=headers, timeout=TIMEOUT_SEGUNDOS)
    except Exception as exc:  # errores de red del transporte inyectado
        raise ErrorSocrata(f"No se pudo contactar Socrata: {exc}") from exc

    codigo = getattr(respuesta, "status_code", None)
    if codigo in (401, 403):
        raise ErrorAutenticacionSocrata(
            "Autenticacion rechazada por Socrata (401/403) -- revisar que el "
            f"App Token en la variable de entorno {NOMBRE_VARIABLE_ENTORNO} sea valido."
        )
    if codigo is not None and not (200 <= codigo < 300):
        raise ErrorSocrata(f"Socrata respondio {codigo}: {str(getattr(respuesta, 'text', ''))[:300]}")

    return respuesta.json()


def hay_datos(
    identificador_dataset: str,
    dominio: str = "www.datos.gov.co",
    token: str | None = None,
    sesion: SesionHTTP | None = None,
) -> bool:
    """Chequeo liviano (`$select=count(*)`, no trae filas) de si el dataset
    tiene al menos 1 fila disponible AHORA MISMO -- para poder avisar ANTES
    de intentar una sincronizacion completa, no solo despues de que ya
    fallo (ver `ingesta/invima_socrata.py::leer_catalogo_invima_api`, que
    trata un 0 en una sincronizacion completa como ErrorSocrata). Un
    problema de transporte (`ErrorSocrata`) se propaga igual -- el llamador
    decide si lo trata como "no disponible" o como un error aparte.
    """
    filas = consultar(identificador_dataset, {"$select": "count(*)"}, dominio, token, sesion)
    if not filas:
        return False
    try:
        return int(filas[0].get("count", 0)) > 0
    except (TypeError, ValueError):
        return False


def consultar_todo(
    identificador_dataset: str,
    parametros: dict[str, Any] | None = None,
    dominio: str = "www.datos.gov.co",
    token: str | None = None,
    sesion: SesionHTTP | None = None,
    limite_pagina: int = LIMITE_PAGINA,
) -> list[dict]:
    """Pagina sobre todo el dataset con $limit/$offset hasta que una pagina
    devuelva menos filas que el limite (fin de los datos)."""
    filas: list[dict] = []
    offset = 0
    while True:
        pagina_parametros = {**(parametros or {}), "$limit": limite_pagina, "$offset": offset}
        pagina = consultar(identificador_dataset, pagina_parametros, dominio, token, sesion)
        filas.extend(pagina)
        if len(pagina) < limite_pagina:
            break
        offset += limite_pagina
    return filas
