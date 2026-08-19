import pandas as pd
import pytest

from gemma_cum_loader.armado.cruce_gemanet import leer_codigos_gemanet


def test_lee_codigos_desde_xlsx(tmp_path):
    ruta = tmp_path / "export.xlsx"
    pd.DataFrame({"Código Interno": ["1-1", "2-1"], "Descripción": ["A", "B"]}).to_excel(
        ruta, index=False
    )
    resultado = leer_codigos_gemanet(ruta)
    assert resultado.codigos == {"1-1", "2-1"}
    assert resultado.advertencias == []


def test_lee_codigos_desde_txt_delimitado(tmp_path):
    ruta = tmp_path / "export.txt"
    ruta.write_text("CODIGO_INTERNO|DESCRIPCION\n1-1|A\n2-1|B\n", encoding="utf-8")
    assert leer_codigos_gemanet(ruta).codigos == {"1-1", "2-1"}


def test_lee_codigos_desde_txt_en_windows_1252(tmp_path):
    # caso real: un .txt exportado desde Excel en configuracion regional
    # latinoamericana llega en cp1252 ("ANSI"), no UTF-8 -- con tildes en el
    # encabezado, decodificar como UTF-8 a secas revienta con
    # UnicodeDecodeError en el primer byte de una vocal acentuada
    ruta = tmp_path / "export_ansi.txt"
    ruta.write_bytes("CÓDIGO_INTERNO|DESCRIPCIÓN\n1-1|Á\n2-1|B\n".encode("cp1252"))
    assert leer_codigos_gemanet(ruta).codigos == {"1-1", "2-1"}


def test_linea_con_delimitador_de_mas_no_tumba_la_corrida(tmp_path):
    # caso real: pandas.errors.ParserError "Expected 3 fields, saw 4" -- una
    # fila trae el delimitador metido dentro de un valor de texto sin
    # comillas (ej. una descripcion con un "|" literal). Antes esto reventaba
    # toda la lectura; ahora se salta esa fila puntual, cuenta cuantas fueron
    # y sigue con el resto.
    contenido = (
        "CODIGO_INTERNO|DESCRIPCION|OTRO\n"
        "1-1|CAJA X 10|x\n"
        "2-1|CAJA CON | TAPA|x\n"  # linea rota: 4 campos en vez de 3
        "3-1|CAJA X 20|x\n"
    )
    ruta = tmp_path / "export_roto.txt"
    ruta.write_text(contenido, encoding="utf-8")

    resultado = leer_codigos_gemanet(ruta)

    assert resultado.codigos == {"1-1", "3-1"}
    assert len(resultado.advertencias) == 1
    assert "1 medicamento" in resultado.advertencias[0]
    # el codigo de la fila rota (2-1) se recupera de forma aproximada -- no
    # entra al set de "ya existe" confirmado, pero queda disponible para que
    # pipeline.py lo cruce contra los candidatos de la corrida y no lo trate
    # como "no existe" a ciegas
    assert resultado.codigos_no_verificables == {"2-1"}
    assert len(resultado.lineas_omitidas) == 1
    assert "2-1" in resultado.lineas_omitidas[0]
    # a diferencia del set (sin orden), esta lista tiene el mismo largo y
    # orden que lineas_omitidas -- necesario para mostrarle a un humano,
    # linea por linea, que codigo se recupero de cada una
    assert resultado.codigos_no_verificables_por_linea == ["2-1"]


def test_excluye_codigos_con_error_de_formula_de_excel(tmp_path):
    # visto en el export real: "#N/A" guardado como texto literal en la
    # columna -- no es un codigo real, no debe entrar al set de comparacion
    ruta = tmp_path / "export.xlsx"
    pd.DataFrame({"Código Interno": ["1-1", "#N/A", "2-1"]}).to_excel(ruta, index=False)
    assert leer_codigos_gemanet(ruta).codigos == {"1-1", "2-1"}


def test_falla_con_mensaje_claro_si_no_hay_columna_codigo_interno(tmp_path):
    # un set vacio aqui haria que todo se trate como "nuevo" -- mejor fallar claro
    ruta = tmp_path / "export.txt"
    ruta.write_text("OTRA_COLUMNA\nvalor\n", encoding="utf-8")
    with pytest.raises(ValueError, match="CODIGO_INTERNO"):
        leer_codigos_gemanet(ruta)
