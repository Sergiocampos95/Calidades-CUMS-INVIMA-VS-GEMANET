"""Motor de validacion por filas: filtros con severidad y accion explicita.

Dos piezas nuevas frente al diseno original (reporte tecnico §9, §7), a raiz
del diagnostico de los tres archivos reales:

- filtro_integridad_estructural: filtro #0, corre antes que cualquier
  validacion de campo. Caso real que lo motiva: 131 filas de
  LISTADO_MEDICAMENTOS12082026.xlsx con el contenido corrido de columna
  (ATC dentro de "Clasificado", importes dentro de "Restringido"/"Regulado").
  Esas filas no son un error de dato, son corrupcion de estructura: van a
  cuarentena para reconstruccion manual, no a rechazo automatico.

- filtro_cruce_invima: pasa de 2 resultados a 3. "Sin match en el corte"
  nunca se interpreta como "vencido" -- puede ser un registro posterior al
  corte del catalogo o un error de dato. Ese es un caso distinto de
  "vigente pero con CUM inactivo", que si existe en el catalogo pero con la
  presentacion descontinuada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from collections.abc import Mapping


class Accion(Enum):
    ACEPTA = "acepta"
    RECHAZA = "rechaza"
    DESCARTA = "descarta"
    CUARENTENA = "cuarentena"


@dataclass(frozen=True)
class ResultadoFiltro:
    accion: Accion
    motivo: str


def filtro_integridad_estructural(
    fila: Mapping[str, object],
    columnas_esperadas: list[str],
    tolerancia_vacias: float = 0.5,
) -> ResultadoFiltro | None:
    """La fila debe "parsear" antes de validar sus campos individuales.

    No intenta inferir tipos exactos por columna (seria fragil sin el archivo
    real para calibrar) - mide si la proporcion de columnas esperadas que
    llegaron vacias excede lo razonable, señal de que el contenido se corrio
    de columna. Devuelve None si la fila esta bien formada.
    """
    pobladas = sum(
        1
        for c in columnas_esperadas
        if str(fila.get(c, "")).strip() not in ("", "None", "nan")
    )
    proporcion_vacia = 1 - (pobladas / len(columnas_esperadas))
    if proporcion_vacia > tolerancia_vacias:
        return ResultadoFiltro(
            Accion.CUARENTENA,
            "fila desalineada: demasiadas columnas esperadas llegaron vacias",
        )
    return None


_PATRON_ERROR_EXCEL = re.compile(r"^#(NAME\?|N/A|REF!|VALUE!|DIV/0!|NULL!)$", re.IGNORECASE)
_MARCADORES_IDENTIDAD_ROTA = {"", "nan", "none", "<na>", "nat"}


def es_error_excel(valor: object) -> bool:
    """True si `valor` es un string de error de formula de Excel guardado
    como texto literal (#NAME?, #N/A, #REF!...) en vez del dato real.

    Caso real diagnosticado en LISTADO_MEDICAMENTOS12082026.xlsx (export de
    Gemma Net): filas con "#NAME?" como Descripcion, "#N/A" en la columna
    rota de la malla original -- estos strings pasan cualquier chequeo de
    "campo no vacio" pero no son un dato usable.
    """
    return bool(_PATRON_ERROR_EXCEL.match(str(valor).strip()))


def filtro_codigo_interno_valido(codigo_interno: object) -> ResultadoFiltro | None:
    """CODIGO_INTERNO es la llave de toda la fila: cruce INVIMA, cruce contra
    Gemma Net y cargue final dependen de que sea un texto real. Devuelve None
    si esta bien formado.

    Caso real diagnosticado: cuando EXPEDIENTE o CONSECUTIVO traen un error
    de digitacion (ej. "2B" en vez de "20"), pd.to_numeric(errors="coerce")
    los vuelve NaN, y la concatenacion de texto de pandas propaga ese NaN a
    todo CODIGO_INTERNO -- la fila queda con codigo_interno = float('nan')
    en silencio, no con un string vacio que fuera facil de detectar a ojo.
    """
    texto = str(codigo_interno).strip()
    if texto.lower() in _MARCADORES_IDENTIDAD_ROTA:
        return ResultadoFiltro(
            Accion.CUARENTENA,
            "CODIGO_INTERNO invalido o vacio -- probablemente EXPEDIENTE o "
            "CONSECUTIVO tienen un error de digitacion en el archivo de origen",
        )
    if es_error_excel(texto):
        return ResultadoFiltro(
            Accion.CUARENTENA,
            f"CODIGO_INTERNO trae un error de formula de Excel ({texto}) en "
            "vez de un valor real",
        )
    return None


def filtro_cruce_invima(
    codigo_interno: str,
    universo_activo_fabricante: set[str],
    universo_vigente_cualquier_estado: set[str],
) -> ResultadoFiltro:
    """Cruce de 3 vias contra el catalogo INVIMA vigente (no 2)."""
    if codigo_interno in universo_activo_fabricante:
        return ResultadoFiltro(Accion.ACEPTA, "vigente y activo en el corte INVIMA")
    if codigo_interno in universo_vigente_cualquier_estado:
        return ResultadoFiltro(
            Accion.CUARENTENA,
            "presentacion vigente pero con CUM inactivo - pendiente decision de negocio",
        )
    return ResultadoFiltro(
        Accion.CUARENTENA,
        "sin match en el corte INVIMA vigente - no implica vencido, puede ser posterior al corte o error de dato",
    )
