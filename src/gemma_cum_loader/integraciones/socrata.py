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

import datetime as dt
import os
from collections.abc import Iterator
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


_sesion_compartida: SesionHTTP | None = None


def _sesion_por_defecto() -> SesionHTTP:
    """`requests.Session()` cacheada a nivel de modulo, no el modulo `requests`
    suelto. Con el modulo suelto, cada `requests.get()` abre y cierra una
    conexion TCP/TLS nueva -- en `consultar_todo` eso significa un handshake
    completo POR PAGINA (ej. ~40 handshakes para sincronizar el catalogo
    completo de INVIMA a 5000 filas/pagina). Una Session reutiliza la
    conexion via keep-alive entre paginas -- mismo resultado, menos tiempo
    de red. Un test que necesite aislar esto inyecta su propia `sesion=`
    (ver tests/test_socrata.py), nunca pasa por aca.
    """
    global _sesion_compartida
    if _sesion_compartida is None:
        import requests

        _sesion_compartida = requests.Session()
    return _sesion_compartida


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


def fecha_ultima_actualizacion(
    identificador_dataset: str,
    dominio: str = "www.datos.gov.co",
    token: str | None = None,
    sesion: SesionHTTP | None = None,
) -> dt.date | None:
    """Cuando actualizo la fuente ese dataset por ultima vez, o None.

    Va contra `/api/views/<id>.json` (metadatos), no contra los datos: es una
    respuesta chica y responde AUNQUE el dataset este devolviendo cero filas.
    Eso es justo lo que lo hace util -- medido el 2026-08-20, los 4 datasets
    de CUM de INVIMA estaban vacios y aun asi reportaban actualizacion el
    2026-08-16. Permite avisar "tu archivo local esta atrasado" sin descargar
    nada, y distinguir "nadie mantiene esto" de "lo actualizaron y quedo
    vacio", que se reclaman a personas distintas.

    Devuelve None en vez de propagar si algo falla: es un dato de contexto,
    no puede tumbar una corrida.
    """
    sesion = sesion or _sesion_por_defecto()
    if token is None:
        token = token_desde_entorno()
    headers = {"X-App-Token": token} if token else {}
    url = f"https://{dominio}/api/views/{identificador_dataset}.json"
    try:
        respuesta = sesion.get(url, params={}, headers=headers, timeout=TIMEOUT_SEGUNDOS)
        marca = respuesta.json().get("rowsUpdatedAt")
        return dt.datetime.fromtimestamp(int(marca)).date() if marca else None
    except Exception:
        return None


def consultar_todo(
    identificador_dataset: str,
    parametros: dict[str, Any] | None = None,
    dominio: str = "www.datos.gov.co",
    token: str | None = None,
    sesion: SesionHTTP | None = None,
    limite_pagina: int = LIMITE_PAGINA,
) -> list[dict]:
    """Devuelve todo el dataset en memoria.

    Los adaptadores que transforman el resultado a otro formato deben preferir
    `iterar_paginas()`: asi no mantienen a la vez la lista completa de JSON y
    su representacion transformada.
    """
    filas: list[dict] = []
    for pagina in iterar_paginas(
        identificador_dataset,
        parametros=parametros,
        dominio=dominio,
        token=token,
        sesion=sesion,
        limite_pagina=limite_pagina,
    ):
        filas.extend(pagina)
    return filas


def iterar_paginas(
    identificador_dataset: str,
    parametros: dict[str, Any] | None = None,
    dominio: str = "www.datos.gov.co",
    token: str | None = None,
    sesion: SesionHTTP | None = None,
    limite_pagina: int = LIMITE_PAGINA,
) -> Iterator[list[dict]]:
    """Pagina un dataset sin acumular sus respuestas en memoria.

    Socrata devuelve JSON por pagina. Quien consume un catalogo grande puede
    transformar cada pagina antes de pedir la siguiente, en vez de conservar
    todo el JSON ademas del DataFrame final.
    """
    if limite_pagina <= 0:
        raise ValueError("limite_pagina debe ser mayor que cero")

    offset = 0
    while True:
        pagina_parametros = {**(parametros or {}), "$limit": limite_pagina, "$offset": offset}
        pagina = consultar(identificador_dataset, pagina_parametros, dominio, token, sesion)
        yield pagina
        if len(pagina) < limite_pagina:
            break
        offset += limite_pagina
