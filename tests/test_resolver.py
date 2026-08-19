import pytest

from gemma_cum_loader.catalogos.resolver import (
    ResolverCatalogo,
    cargar_catalogo,
    sigla_por_codigo,
    texto_por_codigo,
)
from gemma_cum_loader.normaliza.texto import normalizar_entidad

# Mismo formato "SIGLA - DESCRIPCION" que TABLAS DE REFERENCIA!I4:J895 en la
# malla real. Codigos empiezan en 10 para no chocar con FALLBACK_CODIGO=1.
CATALOGO_UNIDADES = {
    10: "MG - MILIGRAMO",
    11: "G - GRAMO",
    12: "MCG - MICROGRAMO",
    13: "UI - UNIDAD INTERNACIONAL",
    14: "ML - MILILITRO",
    15: "% (V/V) - PORCENTAJE VOLUMEN A VOLUMEN",
}

ALIAS_UNIDADES = {"IU": "UI"}


@pytest.fixture
def resolver():
    catalogo = cargar_catalogo(CATALOGO_UNIDADES.items())
    return ResolverCatalogo(catalogo, alias=ALIAS_UNIDADES)


def test_cargar_catalogo_preserva_codigos_repetidos_con_texto_distinto():
    # hallazgo real: TABLAS DE REFERENCIA tiene el mismo codigo con texto
    # distinto en filas distintas (ej. 10001000 = "MG - MILIGRAMO" y luego,
    # en otra fila, "miligramos"). Un dict {codigo: texto} pierde una de las dos.
    entradas = [(10, "MG - MILIGRAMO"), (10, "miligramos")]
    catalogo = cargar_catalogo(entradas)
    assert len(catalogo) == 2
    siglas = {e.sigla for e in catalogo}
    assert siglas == {"MG", "MILIGRAMOS"}


def test_dividir_sigla_descripcion_false_no_parte_el_texto():
    # caso real: una razon social trae un " - " en medio del nombre legal
    # ("LABORATORIO FRANCO COLOMBIANO - LAFRANCOL S.A.S."). Partirla como si
    # fuera "SIGLA - DESCRIPCION" (el formato de unidad de medida) generaba
    # dos entradas rotas que no calzaban con el texto completo normalizado
    # de la fila de origen -- MARCA MEDICAMENTO nunca debe dividirse.
    entradas = [(99, "LABORATORIO FRANCO COLOMBIANO - LAFRANCOL S.A.S.")]
    catalogo = cargar_catalogo(entradas, dividir_sigla_descripcion=False)
    assert len(catalogo) == 1
    # normalizado (sin puntos), pero completo -- no partido en " - "
    assert catalogo[0].sigla == "LABORATORIO FRANCO COLOMBIANO - LAFRANCOL SAS"
    assert catalogo[0].descripcion == catalogo[0].sigla


@pytest.mark.parametrize(
    "valor_origen,codigo_esperado,metodo_esperado",
    [
        # top de alias sucios reales que producian #N/D en la columna AP
        ("mg", 10, "exacto_sigla"),
        ("MG", 10, "exacto_sigla"),
        ("mg.", 10, "exacto_sigla"),
        ("g", 11, "exacto_sigla"),
        ("g.", 11, "exacto_sigla"),
        ("mcg", 12, "exacto_sigla"),
        ("UI", 13, "exacto_sigla"),
        ("U.I.", 13, "exacto_sigla"),
        ("mL", 14, "exacto_sigla"),
        ("% (V/V)", 15, "exacto_sigla"),
        ("IU", 13, "alias"),  # sigla en ingles, no resuelve con limpieza sola
    ],
)
def test_resuelve_alias_reales_del_bug_ap(resolver, valor_origen, codigo_esperado, metodo_esperado):
    resultado = resolver.resolver(valor_origen)
    assert resultado.codigo == codigo_esperado
    assert resultado.metodo == metodo_esperado


def test_valor_sin_match_cae_a_fallback(resolver):
    resultado = resolver.resolver("xyz-no-existe-en-el-catalogo")
    assert resultado.codigo == 1
    assert resultado.metodo == "sin_resolver"


def test_valor_vacio_cae_a_fallback(resolver):
    resultado = resolver.resolver("")
    assert resultado.codigo == 1
    assert resultado.metodo == "sin_resolver"


def test_typo_cercano_resuelve_por_fuzzy(resolver):
    resultado = resolver.resolver("MILIGRAMOS")  # plural, no esta en el catalogo
    assert resultado.metodo == "fuzzy"
    assert resultado.codigo == 10


def test_sugerencias_nunca_decide_un_codigo_aunque_encuentre_algo_parecido(resolver):
    # un valor demasiado distinto para el umbral de auto-resolucion (92) pero
    # con alguna coincidencia parcial en el catalogo -- resolver() debe
    # seguir devolviendo el fallback (sin_resolver), sugerencias() puede
    # devolver candidatos igual, son dos cosas independientes
    valor = "GRAMOX"
    resultado = resolver.resolver(valor)
    assert resultado.metodo == "sin_resolver"
    assert resultado.codigo == 1

    sugerencias = resolver.sugerencias(valor, n=2)
    assert len(sugerencias) <= 2


def test_sugerencias_no_repite_el_mismo_codigo(resolver):
    # MG - MILIGRAMO (10) tiene variantes cercanas en el catalogo real
    # (ej. "mg" y "mg." resuelven al mismo codigo) -- las sugerencias no
    # deben mostrar el mismo codigo dos veces
    sugerencias = resolver.sugerencias("MILIGRAMO", n=5)
    codigos = [s.codigo for s in sugerencias]
    assert len(codigos) == len(set(codigos))


def test_sugerencias_vacio_sin_match_alguno(resolver):
    assert resolver.sugerencias("") == []


def test_sugerencias_no_muestra_coincidencias_demasiado_debiles(resolver):
    # un valor sin relacion real con nada del catalogo no debe generar una
    # "sugerencia" -- un score bajísimo no es una guia util, es ruido que
    # podria mandar a alguien a buscar en el lugar equivocado
    sugerencias = resolver.sugerencias("ZZZZZZZZZZZZZZZZZZ-NO-EXISTE-NI-PARECIDO")
    assert sugerencias == []


# Catalogo de MARCA real (texto plano, sin formato sigla-descripcion), con el
# normalizador de entidad inyectado -- caso real diagnosticado: la malla trae
# sufijo societario + calificador de planta/estado que el catalogo no tiene.
CATALOGO_MARCA = {
    100: "TECNOQUIMICAS SAS",
    101: "QUIBI SAS",
    102: "NOVARTIS PHARMA A.G.",
    103: "LABORATORIO FRANCO COLOMBIANO - LAFRANCOL S.A.S.",
}


@pytest.fixture
def resolver_marca():
    # dividir_sigla_descripcion=False: mismo flag que usa pipeline.py para el
    # catalogo real de marca -- ver test_dividir_sigla_descripcion_false_no_parte_el_texto
    catalogo = cargar_catalogo(
        CATALOGO_MARCA.items(), normalizador=normalizar_entidad, dividir_sigla_descripcion=False
    )
    return ResolverCatalogo(catalogo, normalizador=normalizar_entidad)


@pytest.mark.parametrize(
    "valor_origen,codigo_esperado",
    [
        ("TECNOQUIMICAS S.A. (PLANTA JAMUNDI)", 100),
        ("TECNOQUIMICAS S.A. PLANTA JAMUNDI", 100),
        ("QUIBI S.A. EN REESTRUCTURACION", 101),
    ],
)
def test_resolver_marca_ignora_sufijo_y_calificador_de_planta(resolver_marca, valor_origen, codigo_esperado):
    resultado = resolver_marca.resolver(valor_origen)
    assert resultado.codigo == codigo_esperado
    assert resultado.metodo == "exacto_sigla"


def test_resolver_marca_no_fusiona_filial_con_matriz_extranjera(resolver_marca):
    # "NOVARTIS DE COLOMBIA S.A." (filial) no debe resolver al codigo de
    # "NOVARTIS PHARMA A.G." (matriz suiza) solo por compartir "NOVARTIS" --
    # son entidades legales distintas, fusionarlas seria un error de negocio
    resultado = resolver_marca.resolver("NOVARTIS DE COLOMBIA S.A.")
    assert resultado.codigo != 102
    assert resultado.metodo == "sin_resolver"


def test_resolver_marca_con_guion_en_el_nombre_legal_resuelve_exacto(resolver_marca):
    # caso real diagnosticado: sin dividir_sigla_descripcion=False, esto
    # resolvia por casualidad via fuzzy contra una entrada de catalogo rota
    # (partida en el " - " como si fuera formato SIGLA - DESCRIPCION), no de
    # forma confiable por match exacto
    resultado = resolver_marca.resolver("LABORATORIO FRANCO COLOMBIANO - LAFRANCOL S.A.S.")
    assert resultado.codigo == 103
    assert resultado.metodo == "exacto_sigla"


def test_texto_por_codigo_devuelve_el_texto_completo_original():
    catalogo = cargar_catalogo([(10, "MG - MILIGRAMO")])
    assert texto_por_codigo(catalogo) == {10: "MG - MILIGRAMO"}


def test_sigla_por_codigo_devuelve_la_forma_corta_no_el_texto_completo():
    # bug real que esto corrige (ver auditoria/coherencia_invima.py): INVIMA
    # reporta la unidad en su forma corta ("mg"), nunca como "SIGLA -
    # DESCRIPCION" -- comparar contra texto_por_codigo() nunca calzaba
    catalogo = cargar_catalogo([(10, "MG - MILIGRAMO")])
    assert sigla_por_codigo(catalogo) == {10: "MG"}


def test_sigla_por_codigo_en_catalogo_sin_dividir_es_igual_al_texto_completo_normalizado():
    # MARCA MEDICAMENTO (dividir_sigla_descripcion=False): sigla == texto
    # completo normalizado, no una sub-parte -- no hay nada que dividir
    catalogo = cargar_catalogo(
        [(200, "ACME SAS")], normalizador=normalizar_entidad, dividir_sigla_descripcion=False
    )
    assert sigla_por_codigo(catalogo) == {200: "ACME"}
