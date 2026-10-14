import openpyxl
import pandas as pd

from gemma_cum_loader.armado.indice_ium import ESTADO_UN_CUM
from gemma_cum_loader.pipeline_ium import auditar_coherencia_ium_gemanet

COLUMNAS_INVIMA = [
    "EXPEDIENTE", "PRODUCTO", "TITULAR", "REGISTRO SANITARIO",
    "FECHA EXPEDICION", "FECHA VENCIMIENTO", "ESTADO REGISTRO",
    "EXPEDIENTE CUM", "CONSECUTIVO", "CANTIDAD CUM", "DESCRIPCION COMERCIAL",
    "ESTADO CUM", "FECHA ACTIVO", "FECHA INACTIVO", "MUESTRA MEDICA",
    "UNIDAD", "ATC", "DESCRIPCION_ATC", "VIA ADMINISTRACION",
    "CONCENTRACION", "PRINCIPIO ACTIVO", "UNIDAD MEDIDA", "CANTIDAD",
    "UNIDAD REFERENCIA", "FORMA FARMACEUTICA", "NOMBRE ROL", "TIPO ROL",
    "MODALIDAD", "IUM",
]

_IUM = "1C1016781003102"


def _fila_invima(expediente, consecutivo, ium=None, **overrides):
    base = {
        "EXPEDIENTE": expediente, "PRODUCTO": "PROD", "TITULAR": "ACME SAS",
        "REGISTRO SANITARIO": "INVIMA 1", "FECHA EXPEDICION": None, "FECHA VENCIMIENTO": None,
        "ESTADO REGISTRO": "Vigente", "EXPEDIENTE CUM": expediente, "CONSECUTIVO": consecutivo,
        "CANTIDAD CUM": 1, "DESCRIPCION COMERCIAL": "CAJA X 10", "ESTADO CUM": "Activo",
        "FECHA ACTIVO": None, "FECHA INACTIVO": None, "MUESTRA MEDICA": "No",
        "UNIDAD": "MG", "ATC": "N02BE01", "DESCRIPCION_ATC": "ANALGESICO",
        "VIA ADMINISTRACION": "ORAL", "CONCENTRACION": "500 MG", "PRINCIPIO ACTIVO": "ACETAMINOFEN",
        "UNIDAD MEDIDA": "mg", "CANTIDAD": 500, "UNIDAD REFERENCIA": "TABLETA",
        "FORMA FARMACEUTICA": "TABLETA", "NOMBRE ROL": "LAB", "TIPO ROL": "FABRICANTE",
        "MODALIDAD": "NACIONAL", "IUM": ium,
    }
    base.update(overrides)
    return [base[c] for c in COLUMNAS_INVIMA]


def _crear_invima_xlsx(tmp_path, filas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Vigente"
    for _ in range(6):
        ws.append([None] * len(COLUMNAS_INVIMA))
    ws.append(COLUMNAS_INVIMA)
    for fila in filas:
        ws.append(fila)
    ruta = tmp_path / "invima.xlsx"
    wb.save(ruta)
    return ruta


def _crear_gemanet_export(tmp_path, codigos_existentes):
    datos = {"Código Interno": codigos_existentes, "Descripción": ["X"] * len(codigos_existentes)}
    ruta = tmp_path / "gemanet.xlsx"
    pd.DataFrame(datos).to_excel(ruta, index=False)
    return ruta


def _crear_catalogo_csv(tmp_path, nombre, filas):
    ruta = tmp_path / nombre
    contenido = "codigo,texto\n" + "\n".join(f"{codigo},{texto}" for codigo, texto in filas)
    ruta.write_text(contenido + "\n", encoding="utf-8")
    return ruta


def test_auditar_coherencia_ium_gemanet_sin_red(tmp_path):
    ruta_invima = _crear_invima_xlsx(tmp_path, [_fila_invima(500, 1, ium=_IUM)])
    ruta_gemanet = _crear_gemanet_export(tmp_path, [_IUM])
    ruta_catalogo_unidad = _crear_catalogo_csv(tmp_path, "unidad.csv", [(10, "MG - MILIGRAMO")])
    ruta_catalogo_marca = _crear_catalogo_csv(tmp_path, "marca.csv", [(200, "ACME SAS")])

    from gemma_cum_loader.ingesta.invima_reader import leer_catalogo_invima

    df_invima = leer_catalogo_invima(ruta_invima)
    resultado = auditar_coherencia_ium_gemanet(
        df_invima,
        ruta_gemanet,
        ruta_catalogo_unidad=ruta_catalogo_unidad,
        ruta_catalogo_marca=ruta_catalogo_marca,
    )

    assert list(resultado["CODIGO_INTERNO"]) == [_IUM]
    assert resultado.iloc[0]["ESTADO_IUM"] == ESTADO_UN_CUM
    assert resultado.iloc[0]["CUM_INVIMA"] == ["500-1"]
