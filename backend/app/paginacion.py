"""Filtro de texto libre + orden + filtro por columna (estilo Excel) +
recorte de previsualizacion, compartido por todos los endpoints que
exponen una tabla grande (auditoria, candidatos, universo, cargue, cadena
de calidad, calidades).

Un solo lugar que arma esto -- igual que `_tabla_filtrable` es el unico
lugar que dibuja una tabla en la UI de Streamlit -- para que la regla de
"recorte a 1.000 filas + opcion de cargar todo" (CLAUDE.md) no se
reimplemente distinto en cada router, y para que el filtro/orden por
columna (pedido del usuario, 2026-08-28: "un filtro como los de excel que
permite buscar especificamente aprox y ordenar") se comporte igual "en
general" en TODAS las tablas, no solo en la que lo pidio primero.
"""

from __future__ import annotations

import json

import pandas as pd

from backend.app.schemas import LIMITE_PREVISUALIZACION_DEFECTO, PaginaTabla

# Cuantos valores distintos como maximo devuelve valores_distintos() para
# el checkbox-list del filtro estilo Excel. Una columna de texto libre
# (DESCRIPCION) puede tener decenas de miles de valores unicos -- ese no es
# el caso de uso del filtro por valores (Excel tampoco lo intenta, ofrece
# "Filtros de texto" en su lugar); mas alla de este tope, la busqueda
# libre de la tabla sigue siendo la herramienta correcta.
LIMITE_VALORES_DISTINTOS = 500


def _buscar_texto_libre(df: pd.DataFrame, q: str | None) -> pd.DataFrame:
    """Busca en TODAS las columnas, igual que `_buscar_texto_libre` de la
    UI de Streamlit cuando no se le pasa un subconjunto de columnas.

    Normaliza guion_bajo -> espacio en ambos lados antes de comparar. Bug
    real reportado por el usuario (2026-08-28): los codigos internos
    (ESTADO_COHERENCIA="sin_correspondencia_invima", NATURALEZA_HALLAZGO,
    accion...) se guardan con guion bajo, pero la pildora que el usuario VE
    en pantalla los muestra con espacios ("Sin correspondencia con
    INVIMA") -- escribir la frase tal como se lee en pantalla no
    encontraba nada. La normalizacion es monotona (solo agrega
    coincidencias, nunca quita una que ya funcionaba): un "_" literal en
    el texto buscado tambien se normaliza, asi que sigue calzando con una
    columna que de casualidad tuviera un "_" real.
    """
    texto = (q or "").strip().lower().replace("_", " ")
    if not texto:
        return df
    coincide = pd.Series(False, index=df.index)
    for columna in df.columns:
        coincide = coincide | df[columna].astype(str).str.lower().str.replace(
            "_", " ", regex=False
        ).str.contains(texto, na=False, regex=False)
    return df[coincide]


def _filtrar_por_columnas(df: pd.DataFrame, filtros_json: str | None) -> pd.DataFrame:
    """`filtros_json` es un dict JSON {columna: [valores]} -- un solo
    parametro para poder filtrar VARIAS columnas a la vez (el filtro
    estilo Excel de una tabla real casi siempre se usa asi: una columna
    hoy, otra manana, encima de la anterior). JSON invalido o una columna
    que no existe en esta tabla se ignora silenciosamente por columna --
    degradacion explicita seria rechazar todo el request por un solo campo
    mal armado, y el resto de filtros validos igual deben aplicar."""
    if not filtros_json:
        return df
    try:
        filtros = json.loads(filtros_json)
    except (json.JSONDecodeError, TypeError):
        return df
    if not isinstance(filtros, dict):
        return df
    for columna, valores in filtros.items():
        if columna not in df.columns or not valores:
            continue
        valores_texto = {str(v) for v in valores}
        df = df[df[columna].astype(str).isin(valores_texto)]
    return df


def _ordenar(df: pd.DataFrame, ordenar_por: str | None, orden_descendente: bool) -> pd.DataFrame:
    if not ordenar_por or ordenar_por not in df.columns:
        return df
    # kind="stable" (mergesort): dos filas con el mismo valor conservan su
    # orden relativo anterior -- un vaiven de orden en cada pagina/busqueda
    # sin motivo real seria confuso para quien esta revisando una tabla.
    return df.sort_values(ordenar_por, ascending=not orden_descendente, na_position="last", kind="stable")


def filtrar_tabla(
    df: pd.DataFrame,
    *,
    q: str | None = None,
    filtros_json: str | None = None,
    ordenar_por: str | None = None,
    orden_descendente: bool = False,
) -> pd.DataFrame:
    """Busqueda libre + filtro por columna + orden -- el mismo recorte que ve
    la pantalla, SIN paginar ni convertir a JSON. `paginar()` la usa para la
    previsualizacion; la exportacion de una calidad filtrada
    (`descargas.py::descargar_calidad`) la usa para traer TODAS las filas del
    filtro, no solo la pagina visible. Extraida a proposito (plan
    tablas-por-seccion-y-exportacion.md, paso 4): que pantalla y archivo
    llamen a la misma funcion es lo que garantiza que nunca discrepen."""
    filtrado = _filtrar_por_columnas(_buscar_texto_libre(df, q), filtros_json)
    return _ordenar(filtrado, ordenar_por, orden_descendente)


def _con_fechas_cortas(df: pd.DataFrame) -> pd.DataFrame:
    """Las columnas de fecha salen como "2026-04-21", no como
    "2026-04-21T00:00:00.000".

    `to_json(date_format="iso")` expande TODA fecha a fecha+hora, incluidas
    las que son `datetime.date` puras. Aca no hay ni una hora que mostrar --
    INVIMA y Gemma Net publican dias de calendario (vigencias, vencimientos),
    no instantes -- asi que ese sufijo solo ensancha la columna en pantalla y
    obliga a truncar el dato que si importa: se veia "2010-12-15T00:0...".
    Reportado por el usuario (2026-09-07).

    Solo toca columnas que de verdad contienen fechas. Las que son TEXTO con
    una fecha adentro (`universo`/`invima_listados` traen "12/20/1999", el
    formato crudo de INVIMA) se dejan como estan: reformatearlas seria
    cambiar el dato, no como se muestra."""
    columnas_fecha = [
        c
        for c in df.columns
        if pd.api.types.is_datetime64_any_dtype(df[c])
        or (df[c].dtype == object and pd.api.types.infer_dtype(df[c], skipna=True) == "date")
    ]
    if not columnas_fecha:
        return df
    # Copia: el DataFrame llega desde el cache compartido entre requests (ver
    # _CACHE_CALIDADES y leer_tabla) y mutarlo lo contaminaria para todos.
    salida = df.copy()
    for columna in columnas_fecha:
        salida[columna] = pd.to_datetime(salida[columna], errors="coerce").dt.strftime("%Y-%m-%d")
    return salida


def paginar(
    df: pd.DataFrame,
    *,
    q: str | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    ordenar_por: str | None = None,
    orden_descendente: bool = False,
    filtros_json: str | None = None,
) -> PaginaTabla:
    """`todo=True` es la contraparte exacta del checkbox "Cargar la tabla
    completa" de Streamlit -- nunca se asume en silencio que el limite
    alcanza, el cliente lo pide explicitamente."""
    filtrado = filtrar_tabla(df, q=q, filtros_json=filtros_json, ordenar_por=ordenar_por, orden_descendente=orden_descendente)
    total = len(filtrado)

    if todo:
        visible = filtrado
    else:
        visible = filtrado.iloc[offset : offset + limite]

    # to_json (no to_dict): convierte NaN a null de forma nativa y los
    # tipos numpy (int64/float64) a tipos JSON validos -- to_dict deja
    # escapar ambos problemas.
    filas = json.loads(_con_fechas_cortas(visible).to_json(orient="records", date_format="iso"))

    return PaginaTabla(
        total=total,
        visibles=len(filas),
        limite_aplicado=(not todo) and total > limite,
        filas=filas,
    )


def valores_distintos(df: pd.DataFrame, columna: str) -> list[dict[str, object]]:
    """Los valores distintos de una columna con su conteo, ordenados por
    frecuencia (igual que Excel los muestra) -- alimenta el checkbox-list
    del filtro por columna. Lista vacia si la columna no existe (no hay
    nada que filtrar) o si tiene mas de `LIMITE_VALORES_DISTINTOS` valores
    unicos (degradacion explicita: no se trunca en silencio una lista que
    el usuario podria interpretar como completa)."""
    if columna not in df.columns:
        return []
    conteo = df[columna].astype(str).value_counts()
    if len(conteo) > LIMITE_VALORES_DISTINTOS:
        return []
    return [{"valor": valor, "conteo": int(n)} for valor, n in conteo.items()]
