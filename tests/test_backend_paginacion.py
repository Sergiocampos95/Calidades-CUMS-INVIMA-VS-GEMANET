import json

import pandas as pd

from backend.app.paginacion import paginar, valores_distintos


def _df():
    return pd.DataFrame(
        {
            "CODIGO_INTERNO": ["1-1", "2-2", "3-3"],
            "ESTADO_COHERENCIA": ["correcto", "sin_correspondencia_invima", "con_diferencias"],
            "PORCENTAJE_CALIDAD": [100.0, None, 50.0],
        }
    )


def test_buscar_frase_con_espacios_encuentra_el_valor_guardado_con_guion_bajo():
    """Bug real reportado por el usuario (2026-08-28): escribir la frase tal
    como se lee en la pildora ("sin correspondencia") no encontraba nada,
    porque el valor guardado usa guion bajo ("sin_correspondencia_invima")."""
    pagina = paginar(_df(), q="sin correspondencia")
    assert pagina.total == 1
    assert pagina.filas[0]["CODIGO_INTERNO"] == "2-2"


def test_buscar_con_guion_bajo_literal_sigue_funcionando():
    """La normalizacion no debe romper una busqueda que ya funcionaba."""
    pagina = paginar(_df(), q="sin_correspondencia_invima")
    assert pagina.total == 1


def test_buscar_sin_texto_no_filtra_nada():
    pagina = paginar(_df(), q="")
    assert pagina.total == 3


def test_ordenar_por_columna_ascendente_y_descendente():
    ascendente = paginar(_df(), ordenar_por="PORCENTAJE_CALIDAD")
    # NaN va al final (na_position="last") -- 50.0, 100.0, luego el NaN.
    valores = [f["PORCENTAJE_CALIDAD"] for f in ascendente.filas]
    assert valores == [50.0, 100.0, None]

    descendente = paginar(_df(), ordenar_por="PORCENTAJE_CALIDAD", orden_descendente=True)
    valores_desc = [f["PORCENTAJE_CALIDAD"] for f in descendente.filas]
    assert valores_desc == [100.0, 50.0, None]


def test_ordenar_por_columna_inexistente_no_revienta():
    pagina = paginar(_df(), ordenar_por="NO_EXISTE")
    assert pagina.total == 3


def test_filtro_por_columna_via_json_selecciona_varios_valores():
    filtros = json.dumps({"ESTADO_COHERENCIA": ["correcto", "con_diferencias"]})
    pagina = paginar(_df(), filtros_json=filtros)
    codigos = {f["CODIGO_INTERNO"] for f in pagina.filas}
    assert codigos == {"1-1", "3-3"}


def test_filtro_por_dos_columnas_a_la_vez():
    filtros = json.dumps({"ESTADO_COHERENCIA": ["correcto"], "CODIGO_INTERNO": ["1-1"]})
    pagina = paginar(_df(), filtros_json=filtros)
    assert pagina.total == 1
    assert pagina.filas[0]["CODIGO_INTERNO"] == "1-1"


def test_filtro_json_invalido_se_ignora_sin_reventar():
    pagina = paginar(_df(), filtros_json="{esto no es json valido")
    assert pagina.total == 3


def test_filtro_columna_inexistente_se_ignora():
    filtros = json.dumps({"NO_EXISTE": ["algo"]})
    pagina = paginar(_df(), filtros_json=filtros)
    assert pagina.total == 3


def test_filtro_y_busqueda_libre_se_combinan_con_and():
    filtros = json.dumps({"ESTADO_COHERENCIA": ["correcto", "con_diferencias"]})
    pagina = paginar(_df(), q="3-3", filtros_json=filtros)
    assert pagina.total == 1
    assert pagina.filas[0]["CODIGO_INTERNO"] == "3-3"


def test_valores_distintos_cuenta_y_ordena_por_frecuencia():
    df = pd.DataFrame({"ESTADO_COHERENCIA": ["correcto", "correcto", "con_diferencias"]})
    valores = valores_distintos(df, "ESTADO_COHERENCIA")
    assert valores[0] == {"valor": "correcto", "conteo": 2}
    assert valores[1] == {"valor": "con_diferencias", "conteo": 1}


def test_valores_distintos_columna_inexistente_da_lista_vacia():
    assert valores_distintos(_df(), "NO_EXISTE") == []


def test_valores_distintos_por_encima_del_limite_da_lista_vacia():
    """Degradacion explicita: una columna de texto libre con miles de
    valores unicos (DESCRIPCION) no es el caso de uso del filtro por
    valores -- mejor una lista vacia y clara que truncar en silencio."""
    import backend.app.paginacion as modulo

    df = pd.DataFrame({"DESCRIPCION": [f"medicamento-{i}" for i in range(modulo.LIMITE_VALORES_DISTINTOS + 1)]})
    assert valores_distintos(df, "DESCRIPCION") == []
