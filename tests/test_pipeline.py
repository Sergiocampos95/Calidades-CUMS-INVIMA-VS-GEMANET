from dataclasses import dataclass, field

import openpyxl
import pandas as pd

from gemma_cum_loader.auditoria.coherencia_invima import EstadoCoherencia
from gemma_cum_loader.ingesta.invima_reader import leer_catalogo_invima
from gemma_cum_loader.pipeline import (
    auditar_coherencia_gemanet,
    guardar_reporte,
    procesar_invima_vigentes,
    procesar_invima_vigentes_desde_api,
)

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

_CAMPOS_OBLIGATORIOS_INTEGRIDAD = {
    "EXPEDIENTE", "EXPEDIENTE CUM", "CONSECUTIVO", "ESTADO REGISTRO",
    "ESTADO CUM", "TIPO ROL", "MUESTRA MEDICA",
}


def _fila_invima(expediente, consecutivo, **overrides):
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
        "MODALIDAD": "NACIONAL", "IUM": None,
    }
    base.update(overrides)
    return [base[c] for c in COLUMNAS_INVIMA]


def _crear_invima_xlsx(tmp_path, filas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Vigente"
    for _ in range(6):  # filas 1-6: titulo y banda "CUM", encabezado real en fila 7
        ws.append([None] * len(COLUMNAS_INVIMA))
    ws.append(COLUMNAS_INVIMA)
    for fila in filas:
        ws.append(fila)
    ruta = tmp_path / "invima.xlsx"
    wb.save(ruta)
    return ruta


def _crear_gemanet_export(tmp_path, codigos_existentes):
    ruta = tmp_path / "gemanet.xlsx"
    pd.DataFrame(
        {"Código Interno": codigos_existentes, "Descripción": ["X"] * len(codigos_existentes)}
    ).to_excel(ruta, index=False)
    return ruta


def _crear_gemanet_export_txt_roto(tmp_path, codigo_en_linea_rota):
    # simula el caso real: una linea con el delimitador metido dentro de un
    # valor de texto, que tumba el parser normal de pandas. Necesita al menos
    # una fila bien formada ademas de la rota -- con una sola fila y todas
    # las lineas "N+1 campos" por igual, pandas asume en silencio una columna
    # de indice implicita en vez de lanzar ParserError (no dispara el path
    # de recuperacion, y tampoco refleja el bug real: un archivo de 200k
    # filas con una sola linea mal formada, la mayoria calza con el header)
    contenido = (
        "CODIGO_INTERNO|DESCRIPCION|OTRO\n"
        "1-1|CAJA X 10|x\n"
        f"{codigo_en_linea_rota}|CAJA CON | TAPA|x\n"  # linea rota: 4 campos en vez de 3
    )
    ruta = tmp_path / "gemanet_roto.txt"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def _crear_catalogo_csv(tmp_path, nombre, filas):
    ruta = tmp_path / nombre
    contenido = "codigo,texto\n" + "\n".join(f"{codigo},{texto}" for codigo, texto in filas)
    ruta.write_text(contenido + "\n", encoding="utf-8")
    return ruta


def test_procesar_invima_vigentes_end_to_end(tmp_path):
    filas = [
        _fila_invima(500, 1),  # candidato nuevo, unidad y marca resuelven
        _fila_invima(600, 1, TITULAR="DESCONOCIDA SAS", **{"UNIDAD MEDIDA": "xyz-no-existe"}),
        _fila_invima(700, 1),  # ya cargado en Gemma Net
        _fila_invima(800, 1, **{"ESTADO REGISTRO": "Vencido"}),  # descartado en fase 2
    ]
    ruta_invima = _crear_invima_xlsx(tmp_path, filas)
    ruta_gemanet = _crear_gemanet_export(tmp_path, ["700-1"])
    ruta_catalogo_unidad = _crear_catalogo_csv(tmp_path, "unidad.csv", [(10, "MG - MILIGRAMO")])
    ruta_catalogo_marca = _crear_catalogo_csv(tmp_path, "marca.csv", [(200, "ACME SAS")])

    df = procesar_invima_vigentes(ruta_invima, ruta_gemanet, ruta_catalogo_unidad, ruta_catalogo_marca)

    # el "Vencido" (800-1) no pasa la depuracion de fase 2: ni siquiera aparece
    assert len(df) == 3
    por_codigo = df.set_index("CODIGO_INTERNO")

    fila_candidata = por_codigo.loc["500-1"]
    assert fila_candidata["accion"] == "candidato"
    assert fila_candidata["unidad_metodo"] == "exacto_sigla"
    assert fila_candidata["unidad_codigo"] == 10
    assert fila_candidata["marca_metodo"] == "exacto_sigla"
    assert fila_candidata["marca_codigo"] == 200

    fila_sin_resolver = por_codigo.loc["600-1"]
    assert fila_sin_resolver["accion"] == "candidato"
    assert fila_sin_resolver["unidad_metodo"] == "sin_resolver"
    # "DESCONOCIDA SAS" no se parece en nada a "ACME SAS" -- no hay
    # sugerencia util, el campo queda vacio en vez de mostrar ruido
    assert fila_sin_resolver["marca_sugerencia"] == ""

    fila_resuelta = por_codigo.loc["500-1"]
    # candidato cuya marca SI resolvio -- no se calcula sugerencia (seria
    # trabajo desperdiciado, nadie la va a mostrar)
    assert fila_resuelta["marca_sugerencia"] == ""

    fila_ya_existe = por_codigo.loc["700-1"]
    assert fila_ya_existe["accion"] == "ya_existe"


def test_marca_con_typo_cercano_trae_sugerencia_como_guia(tmp_path):
    # "AKME SAS" no pasa el umbral de auto-resolucion contra "ACME SAS" (un
    # typo), pero es lo bastante parecido para servir de guia manual
    filas = [_fila_invima(500, 1, TITULAR="AKME SAS")]
    ruta_invima = _crear_invima_xlsx(tmp_path, filas)
    ruta_gemanet = _crear_gemanet_export(tmp_path, [])
    ruta_catalogo_unidad = _crear_catalogo_csv(tmp_path, "unidad.csv", [(10, "MG - MILIGRAMO")])
    ruta_catalogo_marca = _crear_catalogo_csv(tmp_path, "marca.csv", [(200, "ACME SAS")])

    df = procesar_invima_vigentes(ruta_invima, ruta_gemanet, ruta_catalogo_unidad, ruta_catalogo_marca)

    fila = df.set_index("CODIGO_INTERNO").loc["500-1"]
    assert fila["marca_metodo"] == "sin_resolver"
    assert "ACME SAS" in fila["marca_sugerencia"]
    assert "codigo 200" in fila["marca_sugerencia"]


def test_fila_estructuralmente_incompleta_va_a_cuarentena(tmp_path):
    campos_vacios = {c: None for c in COLUMNAS_INVIMA if c not in _CAMPOS_OBLIGATORIOS_INTEGRIDAD}
    fila_rota = _fila_invima(999, 1, **campos_vacios)

    ruta_invima = _crear_invima_xlsx(tmp_path, [fila_rota])
    ruta_gemanet = _crear_gemanet_export(tmp_path, [])
    ruta_catalogo_unidad = _crear_catalogo_csv(tmp_path, "unidad.csv", [(10, "MG - MILIGRAMO")])
    ruta_catalogo_marca = _crear_catalogo_csv(tmp_path, "marca.csv", [(200, "ACME SAS")])

    df = procesar_invima_vigentes(ruta_invima, ruta_gemanet, ruta_catalogo_unidad, ruta_catalogo_marca)

    assert len(df) == 1
    assert df.iloc[0]["accion"] == "cuarentena"
    assert "desalineada" in df.iloc[0]["motivo"]


def test_expediente_con_error_de_digitacion_va_a_cuarentena(tmp_path):
    # "2B" en vez de un expediente numerico -> pd.to_numeric(errors="coerce")
    # lo vuelve NaN y la concatenacion de pandas propaga ese NaN a todo
    # CODIGO_INTERNO en silencio -- debe caer en cuarentena, no colarse como
    # candidato con una llave rota
    filas = [_fila_invima("2B", 1)]
    ruta_invima = _crear_invima_xlsx(tmp_path, filas)
    ruta_gemanet = _crear_gemanet_export(tmp_path, [])
    ruta_catalogo_unidad = _crear_catalogo_csv(tmp_path, "unidad.csv", [(10, "MG - MILIGRAMO")])
    ruta_catalogo_marca = _crear_catalogo_csv(tmp_path, "marca.csv", [(200, "ACME SAS")])

    df = procesar_invima_vigentes(ruta_invima, ruta_gemanet, ruta_catalogo_unidad, ruta_catalogo_marca)

    assert len(df) == 1
    assert df.iloc[0]["accion"] == "cuarentena"
    assert "digitacion" in df.iloc[0]["motivo"]


def test_codigo_interno_duplicado_entre_candidatos_va_a_cuarentena(tmp_path):
    # medicamento combinado real: mismo EXPEDIENTE-CONSECUTIVO, dos filas con
    # distinto principio activo -- no se debe cargar dos veces con la misma
    # llave ni fusionar a ciegas
    filas = [
        _fila_invima(900, 1, **{"PRINCIPIO ACTIVO": "CLORFENIRAMINA MALEATO"}),
        _fila_invima(900, 1, **{"PRINCIPIO ACTIVO": "DEXTROMETORFANO BROMHIDRATO"}),
    ]
    ruta_invima = _crear_invima_xlsx(tmp_path, filas)
    ruta_gemanet = _crear_gemanet_export(tmp_path, [])
    ruta_catalogo_unidad = _crear_catalogo_csv(tmp_path, "unidad.csv", [(10, "MG - MILIGRAMO")])
    ruta_catalogo_marca = _crear_catalogo_csv(tmp_path, "marca.csv", [(200, "ACME SAS")])

    df = procesar_invima_vigentes(ruta_invima, ruta_gemanet, ruta_catalogo_unidad, ruta_catalogo_marca)

    assert len(df) == 2
    assert (df["accion"] == "cuarentena").all()
    assert all("duplicado" in motivo for motivo in df["motivo"])


def test_candidato_que_coincide_con_linea_rota_de_gemanet_va_a_cuarentena(tmp_path):
    # el archivo de Gemma Net trae una linea rota (formato irregular) cuyo
    # codigo interno coincide con un candidato de esta corrida -- no se puede
    # confirmar si ya existe o no, asi que no debe tratarse como "candidato
    # nuevo" a ciegas (riesgo real: crearlo duplicado)
    filas = [_fila_invima(500, 1)]
    ruta_invima = _crear_invima_xlsx(tmp_path, filas)
    ruta_gemanet = _crear_gemanet_export_txt_roto(tmp_path, "500-1")
    ruta_catalogo_unidad = _crear_catalogo_csv(tmp_path, "unidad.csv", [(10, "MG - MILIGRAMO")])
    ruta_catalogo_marca = _crear_catalogo_csv(tmp_path, "marca.csv", [(200, "ACME SAS")])

    df = procesar_invima_vigentes(ruta_invima, ruta_gemanet, ruta_catalogo_unidad, ruta_catalogo_marca)

    assert len(df) == 1
    assert df.iloc[0]["accion"] == "cuarentena"
    assert "no se pudo confirmar" in df.iloc[0]["motivo"]
    assert df.attrs["advertencias"]
    assert df.attrs["lineas_omitidas_gemanet"]


def test_candidato_con_linea_rota_de_gemanet_y_marca_sin_resolver_muestra_ambos_motivos(tmp_path):
    # caso real reportado por el usuario: dos medicamentos combinados
    # (mismo CODIGO_INTERNO, distinto principio activo) coincidian con una
    # linea rota de Gemma Net Y ademas su marca no resolvia contra el
    # catalogo -- el motivo mostraba SOLO la primera razon, dando a entender
    # que bastaba con verificar Gemma Net a mano cuando en realidad
    # tambien faltaba resolver la marca. El motivo debe listar los dos.
    filas = [_fila_invima(500, 1, TITULAR="DESCONOCIDA SAS")]
    ruta_invima = _crear_invima_xlsx(tmp_path, filas)
    ruta_gemanet = _crear_gemanet_export_txt_roto(tmp_path, "500-1")
    ruta_catalogo_unidad = _crear_catalogo_csv(tmp_path, "unidad.csv", [(10, "MG - MILIGRAMO")])
    ruta_catalogo_marca = _crear_catalogo_csv(tmp_path, "marca.csv", [(200, "ACME SAS")])

    df = procesar_invima_vigentes(ruta_invima, ruta_gemanet, ruta_catalogo_unidad, ruta_catalogo_marca)

    assert len(df) == 1
    motivo = df.iloc[0]["motivo"]
    assert df.iloc[0]["accion"] == "cuarentena"
    assert "no se pudo confirmar" in motivo
    assert "MARCA MEDICAMENTO no se encontro" in motivo
    assert "UNIDAD DE MEDIDA" not in motivo  # la unidad SI resuelve en este caso, no debe mencionarse


@dataclass
class _RespuestaApiFalsa:
    status_code: int
    _datos: object

    def json(self):
        return self._datos


@dataclass
class _SesionApiFalsa:
    respuestas: list
    llamadas: list = field(default_factory=list)

    def get(self, url, params, headers, timeout):
        self.llamadas.append({"url": url, "params": params, "headers": headers})
        return self.respuestas[len(self.llamadas) - 1]


def _fila_api(expediente, consecutivo, **overrides):
    base = {
        "expediente": str(expediente), "producto": "PROD", "titular": "ACME SAS",
        "registrosanitario": "INVIMA 1", "estadoregistro": "Vigente",
        "expedientecum": str(expediente), "consecutivocum": str(consecutivo), "cantidadcum": "1",
        "descripcioncomercial": "CAJA X 10", "estadocum": "Activo", "muestramedica": "No",
        "unidad": "MG", "atc": "N02BE01", "descripcionatc": "ANALGESICO",
        "viaadministracion": "ORAL", "concentracion": "500 MG", "principioactivo": "ACETAMINOFEN",
        "unidadmedida": "mg", "cantidad": "500", "unidadreferencia": "TABLETA",
        "formafarmaceutica": "TABLETA", "nombrerol": "LAB", "tiporol": "FABRICANTE",
        "modalidad": "NACIONAL",
    }
    base.update(overrides)
    return base


def test_procesar_invima_vigentes_desde_api_end_to_end(tmp_path):
    # misma logica de negocio que la via archivo (candidatos_creacion,
    # resolucion de catalogo, cruce contra Gemma Net) -- solo cambia de
    # donde viene el catalogo INVIMA. Ver ingesta/invima_socrata.py.
    sesion = _SesionApiFalsa([_RespuestaApiFalsa(200, [_fila_api(500, 1)])])
    ruta_gemanet = _crear_gemanet_export(tmp_path, [])
    ruta_catalogo_unidad = _crear_catalogo_csv(tmp_path, "unidad.csv", [(10, "MG - MILIGRAMO")])
    ruta_catalogo_marca = _crear_catalogo_csv(tmp_path, "marca.csv", [(200, "ACME SAS")])

    df = procesar_invima_vigentes_desde_api(
        ruta_gemanet,
        token="t",
        sesion=sesion,
        ruta_catalogo_unidad=ruta_catalogo_unidad,
        ruta_catalogo_marca=ruta_catalogo_marca,
    )

    assert len(df) == 1
    assert df.iloc[0]["CODIGO_INTERNO"] == "500-1"
    assert df.iloc[0]["accion"] == "candidato"
    assert df.iloc[0]["unidad_metodo"] == "exacto_sigla"
    assert df.iloc[0]["marca_metodo"] == "exacto_sigla"


def test_guardar_reporte_escribe_una_hoja_por_accion(tmp_path):
    df = pd.DataFrame(
        {
            "CODIGO_INTERNO": ["1-1", "2-1", "3-1"],
            "accion": ["candidato", "cuarentena", "cuarentena"],
            "motivo": ["ok", "sin match", "sin match"],
        }
    )
    ruta = tmp_path / "reporte.xlsx"
    guardar_reporte(df, ruta)

    hojas = pd.read_excel(ruta, sheet_name=None)
    assert set(hojas.keys()) == {"candidato", "cuarentena"}
    assert len(hojas["candidato"]) == 1
    assert len(hojas["cuarentena"]) == 2


def test_auditar_coherencia_gemanet_pasa_otros_estados_y_renovacion_hasta_el_resultado(tmp_path):
    # auditar_coherencia_gemanet es un wrapper delgado sobre auditar_coherencia
    # (ver auditoria/coherencia_invima.py, ya probado a fondo ahi) -- esto solo
    # confirma que los 2 parametros nuevos SI llegan hasta el resultado final,
    # no vuelve a probar la logica de prioridad/deteccion en si
    ruta_invima = _crear_invima_xlsx(tmp_path, [_fila_invima(500, 1)])
    ruta_gemanet = _crear_gemanet_export(tmp_path, ["999-9"])
    ruta_catalogo_unidad = _crear_catalogo_csv(tmp_path, "unidad.csv", [(10, "MG - MILIGRAMO")])
    ruta_catalogo_marca = _crear_catalogo_csv(tmp_path, "marca.csv", [(200, "ACME SAS")])

    df_invima = leer_catalogo_invima(ruta_invima)
    df_otros_estados = pd.DataFrame([{"CODIGO_INTERNO": "999-9", "ESTADO_REGISTRO": "Inactivo"}])

    resultado = auditar_coherencia_gemanet(
        df_invima,
        ruta_gemanet,
        df_invima_otros_estados=df_otros_estados,
        ruta_catalogo_unidad=ruta_catalogo_unidad,
        ruta_catalogo_marca=ruta_catalogo_marca,
    )

    fila = resultado.set_index("CODIGO_INTERNO").loc["999-9"]
    assert fila["ESTADO_COHERENCIA"] == EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value
    assert fila["ESTADO_INVIMA_DETALLE"] == "Inactivo"
