"""Filtro de texto libre + recorte de previsualizacion, compartido por
todos los endpoints que exponen una tabla grande (auditoria, candidatos).

Un solo lugar que arma esto -- igual que `_tabla_filtrable` es el unico
lugar que dibuja una tabla en la UI de Streamlit -- para que la regla de
"recorte a 1.000 filas + opcion de cargar todo" (CLAUDE.md) no se reimplemente
distinto en cada router.
"""

from __future__ import annotations

import json

import pandas as pd

from backend.app.schemas import LIMITE_PREVISUALIZACION_DEFECTO, PaginaTabla


def _buscar_texto_libre(df: pd.DataFrame, q: str | None) -> pd.DataFrame:
    """Busca en TODAS las columnas, igual que `_buscar_texto_libre` de la
    UI de Streamlit cuando no se le pasa un subconjunto de columnas."""
    texto = (q or "").strip().lower()
    if not texto:
        return df
    coincide = pd.Series(False, index=df.index)
    for columna in df.columns:
        coincide = coincide | df[columna].astype(str).str.lower().str.contains(
            texto, na=False, regex=False
        )
    return df[coincide]


def paginar(
    df: pd.DataFrame,
    *,
    q: str | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
) -> PaginaTabla:
    """`todo=True` es la contraparte exacta del checkbox "Cargar la tabla
    completa" de Streamlit -- nunca se asume en silencio que el limite
    alcanza, el cliente lo pide explicitamente."""
    filtrado = _buscar_texto_libre(df, q)
    total = len(filtrado)

    if todo:
        visible = filtrado
    else:
        visible = filtrado.iloc[offset : offset + limite]

    # to_json (no to_dict): convierte NaN a null de forma nativa y los
    # tipos numpy (int64/float64) a tipos JSON validos -- to_dict deja
    # escapar ambos problemas.
    filas = json.loads(visible.to_json(orient="records", date_format="iso"))

    return PaginaTabla(
        total=total,
        visibles=len(filas),
        limite_aplicado=(not todo) and total > limite,
        filas=filas,
    )
