"""Cascada de resolucion de catalogos: exacto -> alias -> fuzzy -> sin resolver.

Generaliza el fix del bug diagnosticado en la columna AP de la malla de cargue:
el catalogo (TABLAS DE REFERENCIA) guarda entradas "SIGLA - DESCRIPCION" (ej.
"MG - MILIGRAMO") mientras el origen trae solo la sigla ("mg"), lo que producia
65.686 de 66.019 filas en #N/D (99,5%). El mismo formato de catalogo aplica a
MARCA y MODELO DE SERVICIO, asi que esta cascada es la misma para los tres.

Esta cascada es 100% deterministica y nunca depende de un modelo de IA -- a
100.000+ filas tiene que ser exacta y agil sin llamadas de red. Lo que queda
en "sin_resolver" va a la bandeja de cuarentena tal cual; catalogos/ia_client.py
no participa en la resolucion, solo explica en lenguaje de negocio por que una
fila cayo ahi (ver su docstring).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from collections.abc import Callable, Iterable

from rapidfuzz import fuzz, process

from gemma_cum_loader.normaliza.texto import normalizar

Normalizador = Callable[[object], str]

FALLBACK_CODIGO = 1  # "SIN INFORMACION", ver reporte tecnico §8 paso 4
UMBRAL_FUZZY = 92  # token_set_ratio minimo, ver reporte tecnico §8 paso 2
UMBRAL_SUGERENCIA = 40  # piso para no mostrar "sugerencias" que en realidad no dicen nada

Metodo = Literal["exacto_sigla", "exacto_descripcion", "alias", "fuzzy", "sin_resolver"]


@dataclass(frozen=True)
class EntradaCatalogo:
    codigo: int
    sigla: str
    descripcion: str
    texto_original: str


@dataclass(frozen=True)
class ResolucionCatalogo:
    codigo: int
    confianza: float
    metodo: Metodo
    coincidencia: str | None = None


def texto_por_codigo(catalogo: list[EntradaCatalogo]) -> dict[int, str]:
    """Lookup inverso codigo -> texto_original -- lo opuesto de lo que hace
    ResolverCatalogo (texto -> codigo). Uso: mostrarle a un humano el nombre
    real de una MARCA/UNIDAD que Gemma Net ya guarda como codigo.

    Un codigo con varias entradas de texto (ej. FALLBACK_CODIGO=1, o una
    marca con mas de un nombre alterno cargado) se queda con la ultima del
    catalogo -- aceptable aqui porque esto es solo para mostrar, nunca para
    decidir una resolucion.

    NO usar esto para comparar contra el texto crudo de otra fuente (ej.
    INVIMA) -- ver `sigla_por_codigo` para eso.
    """
    return {entrada.codigo: entrada.texto_original for entrada in catalogo}


def sigla_por_codigo(catalogo: list[EntradaCatalogo]) -> dict[int, str]:
    """Lookup inverso codigo -> sigla, ya normalizada con el mismo
    normalizador que arma el catalogo (ver `cargar_catalogo`). A diferencia
    de `texto_por_codigo` (texto completo tal cual, ej. "MG - MILIGRAMO"),
    esto devuelve la forma corta ("MG") -- la comparable contra el dato
    crudo de una fuente externa como INVIMA, que reporta la unidad como
    abreviatura ("mg"), no como "SIGLA - DESCRIPCION".

    Bug real que motiva esto: auditoria/coherencia_invima.py comparaba
    texto_por_codigo() contra el campo crudo de INVIMA y NUNCA calzaba para
    UNIDAD_MEDIDA (compara "MG - MILIGRAMO" contra "mg"), inflando a
    ciegas el conteo de "con_diferencias"/"sin_correspondencia" incluso en
    filas correctas.

    Para un catalogo sin division (dividir_sigla_descripcion=False, ej.
    MARCA MEDICAMENTO), sigla == descripcion == el texto completo
    normalizado, asi que esto tambien sirve como la forma comparable ahi.
    """
    return {entrada.codigo: entrada.sigla for entrada in catalogo}


@dataclass(frozen=True)
class SugerenciaCatalogo:
    """Una coincidencia aproximada por debajo de UMBRAL_FUZZY -- nunca se usa
    para resolver un codigo automaticamente, solo como guia para que un
    humano sepa donde buscar manualmente (ver ResolverCatalogo.sugerencias)."""

    codigo: int
    texto: str
    score: float


def cargar_catalogo(
    entradas: Iterable[tuple[int, str]],
    normalizador: Normalizador = normalizar,
    dividir_sigla_descripcion: bool = True,
) -> list[EntradaCatalogo]:
    """entradas: pares (codigo, texto) tal como viven en TABLAS DE REFERENCIA.

    Debe ser un iterable de pares, no un dict: el catalogo real tiene codigos
    repetidos con texto distinto (ej. 10001000 aparece como "MG - MILIGRAMO"
    en una fila y como "miligramos" en otra). Un dict {codigo: texto} pierde
    silenciosamente todas las filas menos la ultima para cada codigo repetido.

    normalizador: por defecto normalizar() (UNIDAD DE MEDIDA). Para MARCA
    MEDICAMENTO se usa normalizar_entidad() -- ver catalogos/resolver.py.

    dividir_sigla_descripcion: True solo tiene sentido para catalogos en
    formato "SIGLA - DESCRIPCION" (unidad de medida). Caso real que motiva
    el flag: una razon social real trae un " - " en medio del nombre legal
    ("LABORATORIO FRANCO COLOMBIANO - LAFRANCOL S.A.S.") -- partirla ahi
    generaba dos entradas de catalogo rotas (sigla="LABORATORIO FRANCO
    COLOMBIANO", descripcion="LAFRANCOL") que no calzaban con el texto
    completo normalizado de la fila de origen. MARCA MEDICAMENTO debe
    llamarse con dividir_sigla_descripcion=False.
    """
    catalogo = []
    for codigo, texto in entradas:
        texto = str(texto)
        if dividir_sigla_descripcion:
            sigla, _, descripcion = texto.partition(" - ")
        else:
            sigla, descripcion = texto, texto
        catalogo.append(
            EntradaCatalogo(
                codigo=codigo,
                sigla=normalizador(sigla),
                descripcion=normalizador(descripcion or texto),
                texto_original=texto,
            )
        )
    return catalogo


def cargar_catalogo_desde_dataframe(
    df: Any, col_codigo: str, col_texto: str, normalizador: Normalizador = normalizar
) -> list[EntradaCatalogo]:
    """Conveniencia para construir el catalogo directamente desde TABLAS DE REFERENCIA."""
    return cargar_catalogo(
        zip(df[col_codigo], df[col_texto], strict=True), normalizador=normalizador
    )


def cargar_catalogo_csv(ruta: str | Path) -> list[tuple[int, str]]:
    """Lee un CSV de 2 columnas (codigo,texto) -- catalogo interno bundled en
    config/catalogos/ (unidad_medida.csv, marca_medicamento.csv), extraido una
    sola vez de la hoja TABLAS DE REFERENCIA de la malla real. Ya no se le pide
    este archivo al usuario en cada corrida: se actualiza reemplazando el CSV.
    """
    entradas: list[tuple[int, str]] = []
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            entradas.append((int(fila["codigo"]), fila["texto"]))
    return entradas


def cargar_alias_csv(ruta: str | Path) -> dict[str, str]:
    """Lee un CSV de 2 columnas (origen,destino_sigla) - mapeo literal, no fuzzy.

    Solo para alias que la normalizacion de texto no resuelve por si sola
    (ej. "IU" en vez de "UI" - sigla en ingles que no existe en el catalogo).
    """
    alias: dict[str, str] = {}
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            alias[fila["origen"]] = fila["destino_sigla"]
    return alias


class ResolverCatalogo:
    def __init__(
        self,
        catalogo: list[EntradaCatalogo],
        alias: dict[str, str] | None = None,
        normalizador: Normalizador = normalizar,
    ):
        """normalizador debe ser el mismo que se uso para construir `catalogo`
        (via cargar_catalogo), o las claves de busqueda no van a coincidir con
        las de EntradaCatalogo.sigla/descripcion.
        """
        self._normalizador = normalizador
        self._alias = {normalizador(k): normalizador(v) for k, v in (alias or {}).items()}
        self._por_sigla = {e.sigla: e for e in catalogo}
        self._por_descripcion = {e.descripcion: e for e in catalogo}

    def resolver(self, valor: object) -> ResolucionCatalogo:
        origen = self._normalizador(valor)
        if not origen:
            return ResolucionCatalogo(FALLBACK_CODIGO, 0.0, "sin_resolver")

        if origen in self._por_sigla:
            e = self._por_sigla[origen]
            return ResolucionCatalogo(e.codigo, 1.0, "exacto_sigla", e.texto_original)
        if origen in self._por_descripcion:
            e = self._por_descripcion[origen]
            return ResolucionCatalogo(e.codigo, 1.0, "exacto_descripcion", e.texto_original)

        destino_alias = self._alias.get(origen)
        if destino_alias and destino_alias in self._por_sigla:
            e = self._por_sigla[destino_alias]
            return ResolucionCatalogo(e.codigo, 1.0, "alias", e.texto_original)

        candidatos = {**self._por_sigla, **self._por_descripcion}
        mejor = process.extractOne(origen, candidatos.keys(), scorer=fuzz.token_set_ratio)
        if mejor is not None:
            texto_match, score, _ = mejor
            if score >= UMBRAL_FUZZY:
                e = candidatos[texto_match]
                return ResolucionCatalogo(e.codigo, score / 100, "fuzzy", e.texto_original)

        return ResolucionCatalogo(FALLBACK_CODIGO, 0.0, "sin_resolver")

    def sugerencias(self, valor: object, n: int = 3) -> list[SugerenciaCatalogo]:
        """Top `n` coincidencias aproximadas del catalogo por encima de
        UMBRAL_SUGERENCIA (mucho mas bajo que UMBRAL_FUZZY) -- a diferencia
        de resolver(), esto nunca decide un codigo por si solo. Es para
        cuando resolver() devuelve "sin_resolver" y se le quiere mostrar a
        un humano una guia de por donde empezar a buscar manualmente (ej. en
        Gemma Net), nunca como respuesta confirmada -- el llamador es
        responsable de dejarlo claro en el mensaje que le muestra al
        usuario. Con un catalogo chico, un score muy bajo (ej. 15%) no es
        una guia util, es ruido -- por eso el piso.
        """
        origen = self._normalizador(valor)
        if not origen:
            return []
        candidatos = {**self._por_sigla, **self._por_descripcion}
        mejores = process.extract(origen, candidatos.keys(), scorer=fuzz.token_set_ratio, limit=n * 2)
        sugerencias: list[SugerenciaCatalogo] = []
        codigos_vistos: set[int] = set()
        for texto_match, score, _ in mejores:
            if score < UMBRAL_SUGERENCIA:
                continue
            e = candidatos[texto_match]
            if e.codigo in codigos_vistos:
                continue
            codigos_vistos.add(e.codigo)
            sugerencias.append(SugerenciaCatalogo(codigo=e.codigo, texto=e.texto_original, score=score))
            if len(sugerencias) >= n:
                break
        return sugerencias
