"""Tipos de respuesta de la API. Espejo tipado de lo que ya devolvia
Streamlit en pantalla, no un contrato nuevo inventado."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# Mismo limite y misma regla que ya rige toda tabla de la UI de Streamlit
# (CLAUDE.md, seccion UI): recorte de previsualizacion a 1.000 filas por
# defecto, con opcion explicita (`todo=true`) de traer todas.
LIMITE_PREVISUALIZACION_DEFECTO = 1000


class PaginaTabla(BaseModel):
    """Una pagina de resultados de una tabla grande (auditoria, candidatos).

    `limite_aplicado=True` es la senal explicita de "esto no es todo lo que
    hay" -- el cliente (frontend) la usa para mostrar el mismo tipo de aviso
    que hoy muestra `_mostrar_tabla_estandar` en Streamlit ("Cargar la tabla
    completa"), nunca en silencio."""

    total: int
    visibles: int
    limite_aplicado: bool
    filas: list[dict[str, Any]]


class EslabonResumen(BaseModel):
    """Un peldano de la cadena de calidad H1-H6 (ver
    `auditoria/cadena_calidad.py`): que campos valida hasta este punto,
    cuantas filas entraron a evaluarse, y que porcentaje paso -- sin la
    tabla completa, que se pide aparte (GET /auditoria/cadena/{nombre})
    porque puede ser grande.

    `columnas_trio` y `columna_estado` son las columnas REALES de esa tabla
    (INVIMA/Gemma Net/veredicto + vigencia desde H1, acumuladas) -- el
    frontend las usa tal cual para armar la tabla en vez de re-derivarlas a
    mano. Bug real (2026-08-27): la version anterior del frontend
    reconstruia las columnas solo a partir de `campos_acumulados`, que para
    H1 esta vacio (no agrega un campo del trio, valida la correspondencia
    misma) -- eso dejaba a H1 mostrando unicamente CODIGO_INTERNO/PRODUCTO,
    sin ESTADO_COHERENCIA ni NOVEDAD_VIGENCIA_INVIMA/DETALLE_VIGENCIA_INVIMA,
    justo la vigencia que el usuario pidio poder ver."""

    nombre: str
    campos_acumulados: list[str]
    universo: int
    porcentaje_total: float | None
    columnas_trio: list[str]
    columna_estado: str


class EstadoSalud(BaseModel):
    """Sostiene la regla de "degradacion explicita, nunca fallo silencioso":
    cualquier cliente (Streamlit hoy, el frontend nuevo despues) puede
    consultar esto y avisar de forma visible si los datos estan
    desactualizados o el ultimo refresco fallo -- nunca servir datos viejos
    como si fueran frescos sin decirlo."""

    estado: str  # "ok" | "desactualizado" | "error" | "sin_datos"
    ultima_actualizacion_utc: str | None
    antiguedad_segundos: float | None
    duracion_ultimo_refresco_segundos: float | None
    detalle_error: str
