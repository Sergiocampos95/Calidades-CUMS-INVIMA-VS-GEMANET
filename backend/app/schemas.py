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
