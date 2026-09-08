"""De donde sale el catalogo de INVIMA en un refresco: la API de Socrata o
los Excel de listados que hay en `data/`.

Por que hace falta elegir
-------------------------
Las dos fuentes dan cifras MUY distintas para el mismo codigo, porque INVIMA
movio registros de listado en los anos que las separan. Medido contra
produccion el 2026-09-07, sobre los 55.572 activos auditables:

                          Excel de listados      API en vivo
    en tramite renovacion            16.479              215
    no existe en INVIMA               5.459                4
    vigencia confirmada              31.210           42.732

Ninguna esta "mal". Pero una sesion que mezcla las dos vuelve imposible
explicar una cifra, y las explicaciones que el equipo ya dio al negocio estan
hechas sobre los Excel. De ahi el pedido del usuario (2026-09-07): "hay que
dar la opcion si quiero hacer un cargue con los listados o directo a la API".

Por que no alcanza con el respaldo que ya existe
------------------------------------------------
`LectorInvimaConRespaldo` cae al archivo local solo si Socrata FALLA, asi que
no sirve para ELEGIR. Y ademas cachea cada descarga exitosa como parquet en
`data/`, con lo cual "el archivo local mas reciente" pasa a ser el de la API:
pedir "archivos" y dejar que el descubrimiento normal decida devolveria las
cifras de la API igual. Por eso `LectorInvimaDeArchivos` restringe el
descubrimiento a `.xlsx` -- los parquet cacheados quedan fuera por
construccion, no por suerte de fechas.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from gemma_cum_loader.ingesta.almacen_local import ArchivoDescubierto, descubrir
from gemma_cum_loader.ingesta.invima_reader import (
    leer_catalogo_invima,
    leer_catalogo_invima_otros_estados,
    leer_catalogo_invima_renovacion,
    leer_catalogo_invima_vencidos,
)
from gemma_cum_loader.ingesta.invima_socrata import (
    DATASET_CUM_OTROS_ESTADOS,
    DATASET_CUM_RENOVACION,
    DATASET_CUM_VENCIDOS,
    DATASET_CUM_VIGENTES,
)

FUENTE_API = "api"
FUENTE_ARCHIVOS = "archivos"
FUENTES_VALIDAS = (FUENTE_API, FUENTE_ARCHIVOS)

# La PRIMARIA son los archivos -- decision del usuario (2026-09-07): "por
# preferencia vamos a usar las lecturas de los archivos Excel primario, ya que
# para usar el [JSON] tendriamos que adaptar el apartado de Consulta INVIMA
# para poder validar contra Gemma Net".
#
# O sea: la API todavia no esta soportada de punta a punta. El refresco si la
# sabe leer, pero "Consultar INVIMA" (la vista que abre un CUM puntual) no
# procesa el JSON de Socrata, asi que un snapshot armado desde la API deja esa
# vista contradiciendo a las tarjetas. Hasta que eso se resuelva, el defecto
# tiene que ser la fuente que funciona en TODA la aplicacion, no solo en el
# refresco. La API queda como opcion explicita.
FUENTE_DEFECTO = FUENTE_ARCHIVOS

LectorExcel = Callable[[str | Path], pd.DataFrame]

# dataset de Socrata -> (tipo logico de almacen_local.PATRONES, lector del Excel)
_POR_DATASET: dict[str, tuple[str, LectorExcel]] = {
    DATASET_CUM_VIGENTES: ("invima_vigentes", leer_catalogo_invima),
    DATASET_CUM_VENCIDOS: ("invima_vencidos", leer_catalogo_invima_vencidos),
    DATASET_CUM_OTROS_ESTADOS: ("invima_otros_estados", leer_catalogo_invima_otros_estados),
    DATASET_CUM_RENOVACION: ("invima_renovacion", leer_catalogo_invima_renovacion),
}

# Solo Excel: ver el docstring del modulo -- los `.parquet` de `data/` son
# cache de la API, no listados que alguien haya puesto ahi.
_EXTENSIONES_DE_LISTADO = (".xlsx",)


class LectorInvimaDeArchivos:
    """`leer(dataset=...)` con el mismo contrato que `leer_catalogo_invima_api`,
    para poder inyectarse como `lector_invima_api` en `ejecutar_refresco` sin
    tocar la orquestacion.

    NUNCA cae a la API: si falta el Excel de un listado, levanta
    `FileNotFoundError`. Quien pide "archivos" quiere la linea base conocida;
    darle calladamente las cifras de hoy seria exactamente la suposicion
    silenciosa que el proyecto prohibe -- y ademas invisible, porque las dos
    fuentes producen un snapshot que se ve igual de sano.
    """

    def __init__(
        self,
        carpeta_local: Path | None = None,
        por_dataset: dict[str, tuple[str, LectorExcel]] | None = None,
    ) -> None:
        self._carpeta_local = carpeta_local
        # Inyectable (misma convencion que el resto del proyecto): los lectores
        # reales esperan los 6 renglones de encabezado del Excel de INVIMA, asi
        # que una prueba que quiera ejercitar la ELECCION de archivo necesita
        # poner uno falso en vez de fabricar ese formato.
        self._por_dataset = por_dataset if por_dataset is not None else _POR_DATASET
        # Mismo atributo que `LectorInvimaConRespaldo`, que `worker/tareas.py`
        # lee para anotar el origen en el detalle del paso -- asi las dos
        # clases son intercambiables tambien en el reporte de progreso.
        self.advertencias: list[str] = []

    def leer(self, dataset: str = DATASET_CUM_VIGENTES) -> pd.DataFrame:
        tipo, lector_excel = self._por_dataset[dataset]
        hallado = self._descubrir(tipo)
        self.advertencias.append(
            f"Cargue desde archivo local para {tipo}: {hallado.nombre} "
            f"(modificado {hallado.modificado}). NO se consulto la API de INVIMA."
        )
        return lector_excel(hallado.ruta)

    def _descubrir(self, tipo: str) -> ArchivoDescubierto:
        hallado = descubrir(tipo, self._carpeta_local, extensiones=_EXTENSIONES_DE_LISTADO)
        if hallado is None:
            raise FileNotFoundError(
                f"No hay ningun Excel de listado para '{tipo}' en la carpeta de datos. "
                "El cargue desde archivos necesita los 4 listados de INVIMA; "
                "no se cae a la API a proposito (las cifras no serian comparables)."
            )
        return hallado


def lector_para_fuente(
    fuente: str, carpeta_local: Path | None = None
) -> Callable[..., pd.DataFrame] | None:
    """El `lector_invima_api` que corresponde a la fuente elegida.

    Devuelve None para `FUENTE_API`: es el valor que `ejecutar_refresco`
    interpreta como "construi vos el lector por defecto"
    (`LectorInvimaConRespaldo`, con su respaldo automatico). Asi la fuente API
    conserva exactamente el comportamiento que ya tenia, sin una segunda
    implementacion que se pueda desincronizar.
    """
    if fuente == FUENTE_ARCHIVOS:
        return LectorInvimaDeArchivos(carpeta_local).leer
    if fuente == FUENTE_API:
        return None
    raise ValueError(f"Fuente de INVIMA desconocida: {fuente!r}. Validas: {FUENTES_VALIDAS}")
