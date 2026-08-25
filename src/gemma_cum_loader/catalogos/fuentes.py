"""De donde salen los catalogos de marca, unidad y modelo de servicio.

Dos fuentes con el mismo contrato: los CSV de `config/catalogos/` (por
defecto, funciona sin red ni credenciales) y la base PostgreSQL de Gemma Net
(en vivo). La cascada de resolucion no cambia -- sigue siendo
`exacto -> alias -> fuzzy -> sin_resolver`, 100 % deterministica y sin
llamadas de red por fila. Lo unico que cambia es de donde salen sus entradas.

QUE APORTA LEER EN VIVO, medido contra produccion el 2026-08-20 -- importa
porque la expectativa inicial era otra:

  - Marca: la base tiene 894 entradas y el CSV 894, con 892 identicas. El CSV
    NO estaba desactualizado. Leer en vivo recupera 1.092 filas (5 titulares,
    sobre todo LABORATORIOS BAXTER S.A.), no el grueso del problema.
  - Unidad: la base trae 3 codigos que el CSV no tiene, entre ellos
    `10001025 V/V`, que era la causa de 23 hallazgos "codigo huerfano" de la
    auditoria de coherencia. Eso si los elimina de raiz.
  - Modelo de servicio: 12 de 60 entradas habian derivado.

Las 12.803 filas restantes sin marca NO se arreglan por aqui: corresponden a
352 titulares de INVIMA que sencillamente no existen como marca en Gemma Net
y alguien tiene que crear (ver `reporte_marcas_a_crear.xlsx`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from gemma_cum_loader.catalogos.resolver import (
    EntradaCatalogo,
    cargar_alias_csv,
    cargar_catalogo,
    cargar_catalogo_csv,
)
from gemma_cum_loader.integraciones import gemanet_db
from gemma_cum_loader.normaliza.texto import normalizar_entidad

RAIZ = Path(__file__).resolve().parents[3]
RUTA_CATALOGO_UNIDAD = RAIZ / "config" / "catalogos" / "unidad_medida.csv"
RUTA_CATALOGO_MARCA = RAIZ / "config" / "catalogos" / "marca_medicamento.csv"
RUTA_CATALOGO_MODELO = RAIZ / "config" / "catalogos" / "modelo_servicio.csv"

# Consultas verificadas contra la base real (`muzna`, esquema administrativo)
# el 2026-08-20. Sin ORDER BY: las tres tablas son de decenas de kB y el orden
# no le importa a la cascada, asi que no se le pide trabajo extra al servidor.
SQL_MARCA = "SELECT marca_medicamento, descripcion FROM administrativo.tb_marca_medicamento"
SQL_UNIDAD = "SELECT consecutivo_unidad_medida, descripcion FROM administrativo.tb_unidad_medida"
# codigo_interno y NO consecutivo_concepto: son dos columnas distintas de la
# misma tabla y elegir mal rompe la resolucion en silencio. Verificado contra
# el CSV historico el 2026-08-20: por `codigo_interno` coinciden 60 de 60; por
# `consecutivo_concepto`, solo 48. El export de Gemma Net tambien trae el
# codigo_interno (ej. 39 = SUMINISTRO DE MEDICAMENTOS, cuyo consecutivo es
# 1044), asi que es la columna con la que el resto del sistema ya trabaja.
SQL_MODELO = (
    "SELECT codigo_interno, descripcion FROM administrativo.tb_concepto_nota_tecnica "
    "WHERE codigo_interno ~ '^[0-9]+$'"
)


RUTA_ALIAS_UNIDADES = RAIZ / "config" / "catalogos" / "alias_unidades.csv"


class FuenteCatalogos(Protocol):
    """Contrato que consume el pipeline. Nombrar la fuente y no la ruta es lo
    que permite que "traelo de la base" sea una opcion: una ruta de archivo
    no puede representar eso."""

    def unidad(self) -> list[EntradaCatalogo]: ...
    def marca(self) -> list[EntradaCatalogo]: ...
    def modelo_servicio(self) -> list[EntradaCatalogo]: ...
    def alias_unidad(self) -> dict[str, str]: ...


def _alias_unidades() -> dict[str, str]:
    """Alias literales de unidad, comunes a todas las fuentes.

    Viven en un CSV y no en la base porque NO son dato de Gemma Net: son
    equivalencias que la normalizacion de texto no puede deducir sola ("IU"
    es la sigla inglesa de "UI"). Auditadas a mano, no derivadas.

    Este paso de la cascada (`exacto -> alias -> fuzzy -> sin_resolver`)
    estuvo MUERTO: el CSV existia, el lector existia y `ResolverCatalogo`
    aceptaba `alias=`, pero nadie se lo pasaba. Medido el 2026-08-21: 747
    filas (333 con "IU", 414 con "%") caian en fuzzy o sin_resolver pudiendo
    resolver exacto.
    """
    try:
        return cargar_alias_csv(RUTA_ALIAS_UNIDADES)
    except OSError:
        # Sin el archivo la cascada sigue funcionando, solo pierde el atajo.
        return {}


def _entradas_marca(pares: list[tuple[int, str]]) -> list[EntradaCatalogo]:
    """normalizar_entidad y dividir_sigla_descripcion=False: una razon social
    real puede traer " - " en medio del nombre legal y partirla ahi genera
    entradas rotas (ver `cargar_catalogo`)."""
    return cargar_catalogo(pares, normalizador=normalizar_entidad, dividir_sigla_descripcion=False)


class FuenteCatalogosCSV:
    """Los CSV de `config/catalogos/`. Comportamiento identico al historico:
    funciona sin credenciales, sin red y sin driver de base de datos."""

    def __init__(
        self,
        ruta_unidad: str | Path = RUTA_CATALOGO_UNIDAD,
        ruta_marca: str | Path = RUTA_CATALOGO_MARCA,
        ruta_modelo: str | Path = RUTA_CATALOGO_MODELO,
    ) -> None:
        self._ruta_unidad = ruta_unidad
        self._ruta_marca = ruta_marca
        self._ruta_modelo = ruta_modelo

    def unidad(self) -> list[EntradaCatalogo]:
        return cargar_catalogo(cargar_catalogo_csv(self._ruta_unidad))

    def marca(self) -> list[EntradaCatalogo]:
        return _entradas_marca(cargar_catalogo_csv(self._ruta_marca))

    def modelo_servicio(self) -> list[EntradaCatalogo]:
        return cargar_catalogo(cargar_catalogo_csv(self._ruta_modelo))

    def alias_unidad(self) -> dict[str, str]:
        return _alias_unidades()


class FuenteCatalogosGemaNet:
    """Los catalogos en vivo desde la base de Gemma Net.

    `conexion` es inyectable para las pruebas: la suite nunca golpea la base
    real, igual que con Socrata. Si la base falla, el error sube como
    `ErrorGemaNetDB` para que el llamador decida -- aqui NO se cae al CSV en
    silencio: degradar sin avisar es exactamente lo que el proyecto prohibe.
    Quien quiera respaldo automatico usa `con_respaldo()`.
    """

    def __init__(self, conexion: gemanet_db.Conexion | None = None) -> None:
        self._conexion = conexion

    def _pares(self, sql: str) -> list[tuple[int, str]]:
        filas = gemanet_db.consultar(sql, conexion=self._conexion)
        return [(int(codigo), str(texto or "")) for codigo, texto in filas]

    def unidad(self) -> list[EntradaCatalogo]:
        return cargar_catalogo(self._pares(SQL_UNIDAD))

    def marca(self) -> list[EntradaCatalogo]:
        return _entradas_marca(self._pares(SQL_MARCA))

    def modelo_servicio(self) -> list[EntradaCatalogo]:
        return cargar_catalogo(self._pares(SQL_MODELO))

    def alias_unidad(self) -> dict[str, str]:
        # Igual que en CSV: los alias no son dato de Gemma Net.
        return _alias_unidades()


class FuenteCatalogosConRespaldo:
    """Intenta la base y, si falla, usa el CSV -- dejando constancia.

    `advertencias` queda poblada con el motivo del fallo para que la UI y la
    CLI lo reporten. Degradacion EXPLICITA: la corrida sigue, pero nadie se
    entera tarde de que trabajo con un catalogo distinto al que pidio.
    """

    def __init__(
        self,
        principal: FuenteCatalogos | None = None,
        respaldo: FuenteCatalogos | None = None,
    ) -> None:
        self._principal = principal if principal is not None else FuenteCatalogosGemaNet()
        self._respaldo = respaldo if respaldo is not None else FuenteCatalogosCSV()
        self.advertencias: list[str] = []

    def _intentar(self, nombre: str) -> list[EntradaCatalogo]:
        try:
            return getattr(self._principal, nombre)()
        except gemanet_db.ErrorGemaNetDB as exc:
            self.advertencias.append(
                f"No se pudo leer el catalogo de {nombre} desde la base de Gemma Net "
                f"-- se usa el CSV local, que puede estar desactualizado. Detalle tecnico: {exc}"
            )
            return getattr(self._respaldo, nombre)()

    def unidad(self) -> list[EntradaCatalogo]:
        return self._intentar("unidad")

    def marca(self) -> list[EntradaCatalogo]:
        return self._intentar("marca")

    def modelo_servicio(self) -> list[EntradaCatalogo]:
        return self._intentar("modelo_servicio")

    def alias_unidad(self) -> dict[str, str]:
        return _alias_unidades()
