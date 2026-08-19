"""Deriva los campos de regla de negocio que exige el cargue final y que no
existen en ningun archivo de INVIMA ni en el export de Gemma Net (edad,
topes de uso, copagos, cuota moderadora, modelo/nivel de servicio...). La
fuente es la malla de referencia ("Estructura Cargue Medicamentos"), el
archivo real donde esas reglas ya viven para los medicamentos existentes --
vuelve a ser una entrada de la aplicacion solo para esto, no para armar
candidatos (eso lo hace armado/malla.py a partir de INVIMA).

Diagnostico contra el archivo real (66.019 filas del corte actual): de los
27 campos pendientes, 22 son CONSTANTES al 100% en toda la malla -- se usan
tal cual, no hay ambiguedad real (ver `_CAMPOS_CONSTANTES`). ACTIVO y
FECHA_INICIO tienen una respuesta correcta por definicion para un
medicamento que se esta creando ahora mismo, sin depender de la malla.
FECHA_FIN queda en blanco a proposito: 78% de la malla real tampoco tiene
fecha fin (vigencia indefinida), ese ES el dato correcto para la mayoria de
los casos.

POS y CODIGO_INTERNO_MODELO_SERVICIO son distintos a los demas: no son un
dato tecnico, son la clasificacion oficial PBS/POS de Pijao Salud EPSI, y
esa clasificacion NO es aleatoria por fila -- esta atada al EXPEDIENTE
(el registro sanitario INVIMA), no a la presentacion puntual. Confirmado
contra la malla real: de 9.799 EXPEDIENTE distintos, solo 2 tienen POS
mixto entre sus presentaciones (99.98% consistentes) y solo 26 tienen
MODELO DE SERVICIO mixto (99.73% consistentes). Por eso `derivar_reglas_
negocio` clasifica POS/MODELO_SERVICIO por EXPEDIENTE, no por un valor
mayoritario global:

- Si el EXPEDIENTE del candidato ya aparece en la malla de referencia con
  un valor consistente en todas sus presentaciones -> se usa ese valor,
  sin advertencia (es un hecho ya clasificado por Pijao Salud, no una
  suposicion).
- Si el EXPEDIENTE aparece pero con valores mixtos (los 2/26 casos reales)
  -> no se puede confiar, se marca para revision manual puntual.
- Si el EXPEDIENTE no aparece nunca en la malla (medicamento de un registro
  INVIMA totalmente nuevo, sin ninguna presentacion previa clasificada) ->
  no hay ninguna fuente que lo diga, se marca para clasificacion manual.

El codigo de MODELO DE SERVICIO derivado se valida ademas contra el
catalogo real (TABLAS DE REFERENCIA!F3:G62, extraido a config/catalogos/
modelo_servicio.csv) para confirmar que no es un codigo inventado.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

HOJA_MALLA_REFERENCIA = "plantilla (2)"

RAIZ = Path(__file__).resolve().parent.parent.parent.parent
RUTA_CATALOGO_MODELO_SERVICIO = RAIZ / "config" / "catalogos" / "modelo_servicio.csv"

# TABLAS DE REFERENCIA!D3:D6 y B4:B7 -- enums chicos y estables, no ameritan
# un CSV aparte como unidad/marca/modelo de servicio.
NIVELES_SERVICIO_VALIDOS = ["Nivel 1", "Nivel 2", "Nivel 3", "Nivel 4"]
CLASIFICADO_VALORES_VALIDOS = ["SI", "NO", "Medicamento Ancestral", "Planta Medicinal"]

# campo de salida -> columna real en la malla de referencia (nombres tal
# como los devuelve pandas, sin normalizar -- confirmados contra el archivo real)
_CAMPOS_CONSTANTES = {
    "CLASIFICADO": "CLASIFICADO(1:SI, 2:NO, 3.MEDICAMENTO ANCESTRAL, 4. PLAN MEDICINAL)",
    "CRES": "CRES(SI/NO)",
    "GENERA_COPAGO_RS": "GENERA COPAGO RS(SI/NO)",
    "GENERA_COPAGO_RC": "GENERA COPAGO RC(SI/NO)",
    "GENERA_CUOTA_MODERADORA": "GENERA CUOTA MODERADORA(SI/NO)",
    "AUTOMATICO": "AUTOMATICO(SI/NO)",
    "CAMBIO_CANTIDAD": "CAMBIO CANTIDAD(SI/NO)",
    "VALOR": "VALOR",
    "REGULADO": "REGULADO(SI/NO)",
    "VALOR_REGULADO": "VALOR REGULADO",
    "RESTRINGIDO": "RESTRINGIDO(SI/NO)",
    "EDAD_MINIMA": "EDAD MÍN. AÑOS",
    "EDAD_MAXIMA": "EDAD MÁX. AÑOS",
    "MAXIMA_VECES_DIA": "MÁX. VECES DÍA",
    "MAXIMA_VECES_MESES": "MÁX. VECES MES",
    "MAXIMA_VECES_ANO": "MÁX. VECES AÑO",
    "MAXIMA_VECES_VIDA": "MÁX. VECES VIDA",
    "TIEMPO_LIMITE_DIAS": "TIEMPO LÍMITE DÍAS",
    "GRUPO_MEDICAMENTO": "GRUPO MEDICAMENTO",
    "CODIGO_NIVEL_SERVICIO": "CÓDIGO NIVEL SERVICIO",
    "POSOLOGIA": "POSOLOGÍA",
    "DIAS": "DÍAS",
}

# campo de salida -> (columna EXPEDIENTE, columna valor) en la malla de referencia
_CAMPOS_POR_EXPEDIENTE = {
    "POS": "POS(SI/NO)",
    "CODIGO_INTERNO_MODELO_SERVICIO": "CÓDIGO INTERNO MODELO SERVICIO",
}
_COLUMNA_EXPEDIENTE = "EXPEDIENTE"


@dataclass(frozen=True)
class ClasificacionExpediente:
    """Resultado de clasificar un campo (POS, MODELO_SERVICIO) para un
    EXPEDIENTE puntual contra la malla de referencia."""

    valor: object
    cierta: bool  # False si el expediente no aparece, o aparece con valores mixtos
    motivo: str = ""


@dataclass(frozen=True)
class ReglasNegocio:
    valores: dict[str, object]
    advertencias: dict[str, str] = field(default_factory=dict)
    clasificaciones_por_expediente: dict[str, dict[int, ClasificacionExpediente]] = field(
        default_factory=dict
    )

    def valor(self, campo: str) -> object:
        return self.valores.get(campo, "")

    def clasificar(self, campo: str, expediente: object) -> ClasificacionExpediente:
        """campo: uno de _CAMPOS_POR_EXPEDIENTE (hoy "POS" o
        "CODIGO_INTERNO_MODELO_SERVICIO"). Nunca inventa: si no hay
        precedente cierto para este EXPEDIENTE, `cierta=False`."""
        mapa = self.clasificaciones_por_expediente.get(campo, {})
        try:
            expediente_int = int(expediente)
        except (TypeError, ValueError):
            return ClasificacionExpediente(
                valor=None, cierta=False, motivo="EXPEDIENTE invalido, no se pudo clasificar"
            )
        if expediente_int in mapa:
            return mapa[expediente_int]
        return ClasificacionExpediente(
            valor=None,
            cierta=False,
            motivo=(
                f"EXPEDIENTE {expediente_int} no tiene ninguna presentacion previa en la malla "
                "de referencia -- es un registro INVIMA nuevo, sin precedente de clasificacion "
                f"{campo} en Pijao Salud. Verificar manualmente: en 'Estructura Cargue "
                "Medicamentos...xlsx', hoja 'plantilla (2)', columna EXPEDIENTE, buscar "
                f"{expediente_int} (ej. =CONTAR.SI(K:K;{expediente_int}) si esa es la columna "
                "EXPEDIENTE) -- si el resultado es 0, se confirma que requiere clasificacion "
                f"{campo} nueva por parte de Autorizaciones."
            ),
        )


def _resolver_hoja_malla(hojas_disponibles: list[str]) -> str:
    if HOJA_MALLA_REFERENCIA in hojas_disponibles:
        return HOJA_MALLA_REFERENCIA
    # variantes reales vistas: el nombre exacto de hoja cambia entre copias
    # del archivo (ej. sin el "(2)", con mayusculas distintas) -- buscar por
    # coincidencia antes de fallar
    candidatas = [h for h in hojas_disponibles if "plantilla" in h.lower()]
    if len(candidatas) == 1:
        return candidatas[0]
    if len(hojas_disponibles) == 1:
        return hojas_disponibles[0]
    raise ValueError(
        f"No se encontro una hoja de datos reconocible en el archivo de "
        f"referencia (se esperaba '{HOJA_MALLA_REFERENCIA}'). Hojas "
        f"encontradas: {hojas_disponibles}. Sube la hoja que trae CODIGO "
        "INTERNO, DESCRIPCION, EDAD MIN/MAX, etc., o renombrala a "
        f"'{HOJA_MALLA_REFERENCIA}'."
    )


def leer_malla_referencia(archivo: str | Path | Any) -> pd.DataFrame:
    """archivo: ruta o objeto tipo-archivo (ej. UploadedFile de Streamlit)."""
    if hasattr(archivo, "seek"):
        archivo.seek(0)
    libro = pd.ExcelFile(archivo)
    hoja = _resolver_hoja_malla(libro.sheet_names)
    # sin usecols fijo: solo se buscan columnas puntuales por nombre despues
    # (ver _CAMPOS_CONSTANTES/_CAMPOS_POR_EXPEDIENTE), no hace falta fijar un
    # rango de columnas que solo tiene sentido para el archivo real completo
    df = pd.read_excel(libro, sheet_name=hoja, header=0)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _cargar_codigos_modelo_servicio(ruta: str | Path = RUTA_CATALOGO_MODELO_SERVICIO) -> set[int]:
    with open(ruta, newline="", encoding="utf-8") as f:
        return {int(fila["codigo"]) for fila in csv.DictReader(f)}


def _clasificar_por_expediente(
    malla_referencia: pd.DataFrame, columna_valor: str
) -> dict[int, ClasificacionExpediente]:
    resultado: dict[int, ClasificacionExpediente] = {}
    expedientes = pd.to_numeric(malla_referencia[_COLUMNA_EXPEDIENTE], errors="coerce")
    agrupado = malla_referencia.assign(_expediente=expedientes).dropna(subset=["_expediente"])
    for expediente, grupo in agrupado.groupby("_expediente")[columna_valor]:
        valores_distintos = grupo.dropna().unique()
        if len(valores_distintos) == 0:
            continue
        if len(valores_distintos) == 1:
            resultado[int(expediente)] = ClasificacionExpediente(
                valor=valores_distintos[0], cierta=True
            )
        else:
            resultado[int(expediente)] = ClasificacionExpediente(
                valor=None,
                cierta=False,
                motivo=(
                    f"EXPEDIENTE {int(expediente)} tiene valores distintos entre sus propias "
                    f"presentaciones en la malla de referencia ({list(valores_distintos)}) -- "
                    "no se puede confiar en un solo valor. Verificar manualmente: en "
                    "'Estructura Cargue Medicamentos...xlsx', hoja 'plantilla (2)', filtrar la "
                    f"columna EXPEDIENTE por {int(expediente)} y comparar los valores de la "
                    f"columna '{columna_valor}' fila por fila."
                ),
            )
    return resultado


def derivar_reglas_negocio(
    malla_referencia: pd.DataFrame,
    ruta_catalogo_modelo_servicio: str | Path = RUTA_CATALOGO_MODELO_SERVICIO,
) -> ReglasNegocio:
    valores: dict[str, object] = {}
    advertencias: dict[str, str] = {}

    for campo, columna in _CAMPOS_CONSTANTES.items():
        if columna not in malla_referencia.columns:
            advertencias[campo] = f"columna '{columna}' no encontrada en la malla de referencia"
            continue
        moda = malla_referencia[columna].mode(dropna=True)
        if moda.empty:
            advertencias[campo] = "la malla de referencia no tiene datos para este campo"
            continue
        valor_dominante = moda.iloc[0]
        proporcion = (malla_referencia[columna] == valor_dominante).mean()
        valores[campo] = valor_dominante
        if proporcion < 1.0:
            advertencias[campo] = (
                f"solo {proporcion:.1%} de la malla de referencia coincide con "
                f"'{valor_dominante}' -- revisar manualmente antes de confiar en este valor"
            )

    if "CLASIFICADO" in valores and valores["CLASIFICADO"] not in CLASIFICADO_VALORES_VALIDOS:
        advertencias["CLASIFICADO"] = (
            f"'{valores['CLASIFICADO']}' no esta en los valores validos de TABLAS DE REFERENCIA "
            f"({CLASIFICADO_VALORES_VALIDOS})"
        )
    if "CODIGO_NIVEL_SERVICIO" in valores and valores["CODIGO_NIVEL_SERVICIO"] not in NIVELES_SERVICIO_VALIDOS:
        advertencias["CODIGO_NIVEL_SERVICIO"] = (
            f"'{valores['CODIGO_NIVEL_SERVICIO']}' no esta en los niveles validos de "
            f"TABLAS DE REFERENCIA ({NIVELES_SERVICIO_VALIDOS})"
        )

    clasificaciones_por_expediente: dict[str, dict[int, ClasificacionExpediente]] = {}
    for campo, columna in _CAMPOS_POR_EXPEDIENTE.items():
        if columna not in malla_referencia.columns or _COLUMNA_EXPEDIENTE not in malla_referencia.columns:
            advertencias[campo] = (
                f"columna '{columna}' o '{_COLUMNA_EXPEDIENTE}' no encontrada en la malla de "
                "referencia -- no se puede clasificar por expediente"
            )
            continue
        clasificaciones_por_expediente[campo] = _clasificar_por_expediente(malla_referencia, columna)

    if "CODIGO_INTERNO_MODELO_SERVICIO" in clasificaciones_por_expediente:
        codigos_validos = _cargar_codigos_modelo_servicio(ruta_catalogo_modelo_servicio)
        invalidos = [
            (expediente, c.valor)
            for expediente, c in clasificaciones_por_expediente["CODIGO_INTERNO_MODELO_SERVICIO"].items()
            if c.cierta and int(c.valor) not in codigos_validos
        ]
        if invalidos:
            advertencias["CODIGO_INTERNO_MODELO_SERVICIO"] = (
                f"{len(invalidos)} expediente(s) de la malla de referencia tienen un codigo de "
                "modelo de servicio que no existe en el catalogo real -- revisar"
            )

    valores["ACTIVO"] = "SI"  # un medicamento que se esta creando ahora nace activo
    valores["FECHA_INICIO"] = dt.date.today().strftime("%Y/%m/%d")
    valores["FECHA_FIN"] = ""  # 78% de la malla real no tiene fecha fin -- vacio es el dato correcto

    return ReglasNegocio(
        valores=valores,
        advertencias=advertencias,
        clasificaciones_por_expediente=clasificaciones_por_expediente,
    )
