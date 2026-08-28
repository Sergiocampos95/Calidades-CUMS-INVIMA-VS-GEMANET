"""Respaldo local automatico para los 4 datasets de INVIMA cuando Socrata
no responde -- decision YA TOMADA por el usuario, documentada en el propio
mensaje de error de `leer_catalogo_invima_api` ("si persiste, usa el Excel
de respaldo mientras tanto") y en su docstring ("la subida de archivo se
mantiene como respaldo si Socrata no esta disponible"). Hasta ahora ese
respaldo solo estaba conectado a mano, en la consulta puntual de un CUM en
Streamlit (`_consultar_cum_en_respaldo`) -- el pipeline automatico del
worker no lo usaba: un outage de Socrata (como el real del 2026-08-28,
dataset 'i7cb-raxc' devolviendo 0 filas) tumbaba el refresco completo aunque
hubiera un archivo local perfectamente utilizable.

Mismo patron que `catalogos/fuentes.py::FuenteCatalogosConRespaldo`: intenta
la fuente en vivo y, si falla, cae al archivo local mas reciente que
`ingesta/almacen_local.py::descubrir()` encuentre en `data/` -- nunca en
silencio, `advertencias` queda poblada con el motivo exacto. Ademas, cada
lectura en vivo exitosa se guarda como parquet local (`guardar_descarga`)
para que la PROXIMA falla tenga un respaldo mas fresco que buscar, sin que
nadie tenga que bajar un Excel a mano -- "escanear los Excel y guardarlos
de forma optima" (pedido del usuario, 2026-08-28) ya lo hacia
`almacen_local.py` para la Estructura de Cargue; esto extiende el mismo
mecanismo a los 4 catalogos de INVIMA.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from gemma_cum_loader.ingesta.almacen_local import (
    ArchivoDescubierto,
    ResultadoSincronizacion,
    descubrir,
    guardar_descarga,
    leer_descarga,
)
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
    leer_catalogo_invima_api,
)
from gemma_cum_loader.integraciones.socrata import ErrorSocrata

LectorExcel = Callable[[str | Path], pd.DataFrame]

# dataset de Socrata -> (tipo logico en almacen_local.PATRONES, lector del
# Excel correspondiente si el respaldo hallado no es un parquet ya cacheado).
_CONFIGURACION_POR_DATASET: dict[str, tuple[str, LectorExcel]] = {
    DATASET_CUM_VIGENTES: ("invima_vigentes", leer_catalogo_invima),
    DATASET_CUM_VENCIDOS: ("invima_vencidos", leer_catalogo_invima_vencidos),
    DATASET_CUM_OTROS_ESTADOS: ("invima_otros_estados", leer_catalogo_invima_otros_estados),
    DATASET_CUM_RENOVACION: ("invima_renovacion", leer_catalogo_invima_renovacion),
}


class LectorInvimaConRespaldo:
    """`leer(dataset=...)` con el mismo contrato que `leer_catalogo_invima_api`
    -- mismo dataset por defecto, mismo DataFrame de salida -- para que sea
    un reemplazo directo de `lector_invima_api` en `worker/tareas.py` sin
    tocar el resto de la orquestacion.

    Sin respaldo local disponible, el `ErrorSocrata` original sube igual --
    nunca se inventa un catalogo vacio para poder seguir."""

    def __init__(
        self,
        lector_api: Callable[..., pd.DataFrame] = leer_catalogo_invima_api,
        localizador: Callable[..., ArchivoDescubierto | None] = descubrir,
        guardador: Callable[..., ResultadoSincronizacion] = guardar_descarga,
        lector_parquet: Callable[[Path], pd.DataFrame] = leer_descarga,
        carpeta_local: Path | None = None,
        configuracion: dict[str, tuple[str, LectorExcel]] | None = None,
    ) -> None:
        self._lector_api = lector_api
        self._localizador = localizador
        self._guardador = guardador
        self._lector_parquet = lector_parquet
        self._carpeta_local = carpeta_local
        self._configuracion = configuracion if configuracion is not None else _CONFIGURACION_POR_DATASET
        self.advertencias: list[str] = []

    def leer(self, dataset: str = DATASET_CUM_VIGENTES) -> pd.DataFrame:
        tipo, lector_excel = self._configuracion.get(dataset, (None, None))
        try:
            df = self._lector_api(dataset=dataset)
        except ErrorSocrata as exc:
            if tipo is None:
                # Dataset desconocido para esta clase (no deberia pasar con
                # los 4 datasets reales, pero degradacion explicita: no hay
                # con que respaldar algo que no se sabe ubicar en data/).
                raise
            hallado = self._localizador(tipo, self._carpeta_local)
            if hallado is None:
                raise
            self.advertencias.append(
                f"Socrata no respondio para {tipo} -- se uso el archivo local mas reciente "
                f"({hallado.nombre}, modificado {hallado.modificado}). Detalle tecnico: {exc}"
            )
            if hallado.ruta.suffix == ".parquet":
                return self._lector_parquet(hallado.ruta)
            return lector_excel(hallado.ruta)
        else:
            if tipo is not None:
                # Cachea la descarga exitosa -- la proxima falla de Socrata
                # tiene un respaldo mas fresco que buscar, sin intervencion
                # manual. guardar_descarga() ya se niega a guardar un
                # DataFrame vacio, asi que esto nunca sobrescribe un buen
                # respaldo con uno malo.
                self._guardador(df, tipo, self._carpeta_local)
            return df
