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


class CalidadResumen(BaseModel):
    """Una fila de la "tabla de calidades" (ver
    `auditoria/calidades.py::calidades_auditoria`) -- el entregable que pide
    el negocio: cuantos medicamentos caen en ella y que significa, sin la
    tabla completa (se pide aparte, GET /auditoria/calidades/{nombre})."""

    nombre: str
    explica: str
    medicamentos: int
    porcentaje_del_catalogo: float
    columnas: list[str]
    # Lenguaje de negocio (2026-09-10): las condiciones que definen la
    # calidad, una por linea, y que hacer con lo que sale. Con valor por
    # defecto para no romper a un cliente viejo que no los pida.
    criterios: list[str] = []
    que_hacer: str = ""


class SeccionCalidad(BaseModel):
    """Un TIPO de diferencia dentro de una calidad (ver
    `auditoria/calidades.py::secciones_de_diferencia`), para poder partir una
    tarjeta de decenas de miles de filas en cortes analizables.

    Las secciones NO son excluyentes: sus conteos no suman `medicamentos` de
    la calidad, porque una misma fila puede tener dos campos distintos.
    `derivado_de` marca el campo que es CONSECUENCIA de otro."""

    clave: str
    etiqueta: str
    medicamentos: int
    derivado_de: list[str]
    # Que se compara en esta seccion, para quien no es tecnico.
    explica: str = ""


class DimensionesCalidad(BaseModel):
    """Las 6 dimensiones de calidad de dato que todavia no tenian endpoint
    propio (Completitud, Unicidad, Validez de dominio, Razonabilidad
    numerica, Conformidad de formato, Integridad referencial) -- las otras
    4 (Exactitud, Vigencia, Consistencia, Correspondencia) ya se ven en
    ESTADO_COHERENCIA/NOVEDAD_VIGENCIA_INVIMA. `completitud_promedio` es
    `None` (no 0.0) cuando no hay filas que promediar."""

    n_total_auditado: int
    completitud_promedio: float | None
    duplicados: int
    fuera_de_dominio: int
    inconsistencia_numerica: int
    formato_invalido: int
    integridad_referencial: int


class HallazgoNaturaleza(BaseModel):
    """"Que hacer con cada hallazgo" (auditoria/coherencia_invima.py::
    ACCION_POR_NATURALEZA) -- cada medicamento lleva UNA sola etiqueta, la
    de la accion mas urgente que pide; estas cifras no se suman con las de
    ESTADO_COHERENCIA ni entre si."""

    naturaleza: str
    medicamentos: int
    que_hacer: str


class PasoProgresoAPI(BaseModel):
    """Un paso de la corrida del worker mas reciente (ver
    `worker/estado.py::PasoProgreso`) -- "una lista mostrando uno a uno los
    procesos que se van haciendo y su progreso" (pedido del usuario,
    2026-08-27). `estado` no trae un porcentaje: leer INVIMA/auditar/etc.
    son llamadas opacas de varios segundos, no hay un "40%" real de esa
    llamada que reportar sin inventarlo -- el checklist paso a paso es
    honesto con lo que se puede medir."""

    nombre: str
    estado: str  # "pendiente" | "en_curso" | "hecho" | "error"
    detalle: str


class ProgresoRefresco(BaseModel):
    """`en_curso=True` si algun paso esta `en_curso` ahora mismo -- lo usa
    el cliente para saber cuando dejar de sondear GET /refrescar/progreso."""

    en_curso: bool
    pasos: list[PasoProgresoAPI]


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


class DatosLogin(BaseModel):
    usuario: str
    clave: str


class UsuarioSesion(BaseModel):
    """Lo que la pantalla necesita saber de quien esta adentro."""

    usuario: str
    nombre: str
    admin: bool
