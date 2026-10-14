"""Cada medicamento de Gemma Net comparado contra CADA registro distinto que
INVIMA publica para su CUM -- no solo contra el primero.

Por que existe (pedido del usuario, 2026-10-14): INVIMA publica varias filas
por EXPEDIENTE-CONSECUTIVO y `auditar_coherencia` cruza contra la primera
(`drop_duplicates(keep="first")`). Quien revisa ve "difiere" y cree que hay
que actualizar Gemma Net, cuando a veces el dato de Gemma Net calza con OTRA
fila del mismo CUM. El pedido: avisar que el cruce tiene mas de un registro,
decir cuantos y cuales, ordenarlos de mayor a menor coincidencia y dejar
elegir contra cual se mira la comparacion.

Medido sobre el snapshot del 2026-10-02 (133.369 CUM auditables), antes de
escribir esto -- y cambio el diseno:

- 79.460 tienen mas de una fila en INVIMA, pero las filas de un CUM NO son
  presentaciones distintas: la presentacion (DESCRIPCION_COMERCIAL,
  CANTIDAD_CUM, FORMA, CONCENTRACION) es identica en todas. Lo que varia es
  sobre todo el ROL (fabricante, importador...: 77.272 grupos), que no se
  compara. Avisar en esos 79.460 seria ruido: elegir otra fila no cambia
  ningun veredicto.
- Por eso un "registro distinto" es una combinacion distinta de las columnas
  que SI entran en la comparacion (`COLUMNAS_INVIMA_COMPARADAS`). Con ese
  criterio son ~30.000 CUM, casi todos combinados (un principio activo por
  fila); el resto, varios titulares o varias cantidades.

No cambia ninguna cifra de la auditoria: el cruce normal sigue siendo el
registro 1 (el primero del listado, igual que hoy). Esto AGREGA la
comparacion contra los demas para que la pantalla pueda mostrarla -- elegir
otro registro en la consulta es una vista, no una correccion guardada.

La comparacion contra cada registro la hace `auditar_coherencia` misma
(parametro `registros_a_comparar`), no una copia de su logica: una copia es
exactamente como la consulta puntual y las tarjetas llegaron a decir cosas
distintas del mismo CUM (2026-09-03). La prueba de que el mecanismo es fiel
es que el registro 1 reproduce el trio del cruce normal, fila por fila.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from gemma_cum_loader.auditoria.coherencia_invima import (
    _CAMPOS_DIRECTOS,
    _LISTADO_OTROS_ESTADOS,
    _LISTADO_RENOVACION,
    _LISTADO_VENCIDOS,
    _LISTADO_VIGENTES,
    CAMPOS_COMPARADOS_COHERENCIA,
    SUFIJO_INVIMA,
    SUFIJO_VALIDACION,
    VALIDACION_COINCIDE,
    VALIDACION_DIFIERE,
    auditar_coherencia,
    clave_cruce_con_invima,
)
from gemma_cum_loader.catalogos.resolver import EntradaCatalogo
from gemma_cum_loader.normaliza.codigos import clasificar_codigos

# Las columnas de una fila de INVIMA que alimentan la comparacion campo a
# campo: las directas, el TITULAR (contra la marca), la UNIDAD_MEDIDA, y las
# que arman las dos DESCRIPCION validas (PA + CANTIDAD + UNIDAD + FORMA, y PA +
# UNIDAD_REFERENCIA). Dos filas que solo difieren FUERA de esta lista (rol, via,
# fechas) dan exactamente el mismo veredicto y son, para esto, un solo
# registro. Lo cubre una prueba que muta cada columna que NO esta aca y exige
# el mismo trio: si `auditar_coherencia` empieza a comparar otra columna, esa
# prueba falla en vez de esconder registros distintos.
COLUMNAS_INVIMA_COMPARADAS: tuple[str, ...] = (
    *dict.fromkeys(col for _, col in _CAMPOS_DIRECTOS.values()),
    "TITULAR",
    "UNIDAD_MEDIDA",
    "CANTIDAD",
    "UNIDAD_REFERENCIA",
)

# Mismo orden de prioridad que el cruce normal: Vigentes por merge, y despues
# Vencidos > Otros Estados > Renovacion (`_completar_invima_desde_auxiliares`).
# El registro de un CUM sale del primero de estos listados que lo tiene.
_ORDEN_LISTADOS = (_LISTADO_VIGENTES, _LISTADO_VENCIDOS, _LISTADO_OTROS_ESTADOS, _LISTADO_RENOVACION)

# Lo que la consulta necesita para que el CASO ENTERO (diagnostico y "que
# hacer", no solo la tabla campo a campo) siga al registro elegido. Mismos
# nombres que en la auditoria: la pantalla los superpone a la fila tal cual.
# CAMPOS_CON_DIFERENCIA sale fiel de cualquier listado (se arma con la misma
# condicion `invima_tiene_datos` que el cruce normal). ESTADO_COHERENCIA y
# PORCENTAJE_CALIDAD solo cuando el registro es de VIGENTES: para un CUM de
# Vencidos/Otros Estados/Renovacion la llamada alternativa pasa ese listado
# como `df_invima` y su estado diria "correcto/con diferencias" donde el cruce
# normal dice "vencido". Vacio/NaN = "el mismo de la auditoria".
COLUMNAS_CASO_POR_REGISTRO: tuple[str, ...] = ("CAMPOS_CON_DIFERENCIA", "ESTADO_COHERENCIA", "PORCENTAJE_CALIDAD")

# Columnas de la tabla larga, en el orden en que se guardan.
COLUMNAS_TABLA_REGISTROS: tuple[str, ...] = (
    "FILA_AUDITORIA",
    "CODIGO_INTERNO",
    "LISTADO_INVIMA",
    "REGISTRO",
    "REGISTROS_DISTINTOS",
    "FILAS_INVIMA",
    "FILAS_DEL_REGISTRO",
    "ORDEN_COINCIDENCIA",
    "CAMPOS_COINCIDEN",
    "CAMPOS_COMPARADOS",
    "PORCENTAJE_COINCIDENCIA",
    *COLUMNAS_CASO_POR_REGISTRO,
    *(
        f"{campo}{sufijo}"
        for campo in CAMPOS_COMPARADOS_COHERENCIA
        for sufijo in (SUFIJO_INVIMA, SUFIJO_VALIDACION)
    ),
)

# Columnas que se agregan a la auditoria, una fila por fila del reporte.
COLUMNA_REGISTROS_DISTINTOS = "REGISTROS_INVIMA_DISTINTOS"
COLUMNA_FILAS_INVIMA = "FILAS_INVIMA"
COLUMNA_OTRO_COINCIDE_MAS = "OTRO_REGISTRO_INVIMA_COINCIDE_MAS"
# Texto, no booleano -- mismo criterio que VALIDACION_* en coherencia_invima.py:
# un valor que se filtra y se lee en la tabla sin traducirlo aparte. Vacio
# cuando el CUM tiene un solo registro distinto: no hay otro con que comparar,
# y "No" diria que se comparo.
OTRO_COINCIDE_MAS_SI = "Sí"
OTRO_COINCIDE_MAS_NO = "No"


@dataclass(frozen=True)
class ComparacionPorRegistro:
    """`registros`: tabla larga, una fila por (fila del reporte, registro
    distinto de INVIMA), solo para las filas con MAS de un registro distinto
    -- las demas no tienen nada que elegir. `resumen`: una fila por fila del
    reporte, alineada por posicion, con las tres columnas que se agregan a
    la auditoria."""

    registros: pd.DataFrame
    resumen: pd.DataFrame


def filas_invima_con_registro(
    df_invima: pd.DataFrame,
    df_invima_vencidos: pd.DataFrame | None = None,
    df_invima_otros_estados: pd.DataFrame | None = None,
    df_invima_renovacion: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """TODAS las filas de INVIMA de cada CUM -- del listado que el cruce normal
    usa para ese CUM -- con el numero de `REGISTRO` al que pertenecen. Es lo que
    la consulta muestra como "cuales son": dos filas con el mismo numero solo
    difieren en lo que no se compara (el rol, la via...).

    El numero se asigna por orden de PRIMERA aparicion en el archivo de
    INVIMA, asi que el registro 1 es siempre la fila que gana el
    `drop_duplicates(keep="first")` del cruce normal. `registros_distintos_por_
    clave` sale de aca: los dos no pueden numerar distinto.

    Agrega `_CLAVE`, `LISTADO_INVIMA`, `REGISTRO`, `REGISTROS_DISTINTOS`,
    `FILAS_INVIMA` (filas del CUM en ese listado) y `FILAS_DEL_REGISTRO`."""
    partes = []
    for prioridad, (listado, df) in enumerate(
        zip(_ORDEN_LISTADOS, (df_invima, df_invima_vencidos, df_invima_otros_estados, df_invima_renovacion))
    ):
        if df is None or df.empty or "CODIGO_INTERNO" not in df.columns:
            continue
        # _FILA_ORIGEN: la posicion de la fila en SU listado, antes de juntar los
        # cuatro. La comparacion se hace contra ESA fila (`.iloc`), no contra la
        # copia del concat: juntar listados puede cambiar el tipo de una
        # columna (una fecha comodin 3000-01-01 leida como texto en uno y como
        # objeto en otro) y el estado ya no seria el del cruce normal -- medido
        # el 2026-10-14: 2 de 13.652 registros 1 de Vigentes daban otro estado.
        parte = df.assign(_FILA_ORIGEN=np.arange(len(df))).dropna(subset=["CODIGO_INTERNO"])
        parte["_CLAVE"] = parte["CODIGO_INTERNO"].astype(str).str.strip()
        parte["LISTADO_INVIMA"] = listado
        parte["_PRIORIDAD"] = prioridad
        partes.append(parte)
    if not partes:
        return pd.DataFrame(
            columns=["_CLAVE", "LISTADO_INVIMA", "REGISTRO", "REGISTROS_DISTINTOS", "FILAS_INVIMA", "FILAS_DEL_REGISTRO"]
        )
    todo = pd.concat(partes, ignore_index=True)
    # Solo el listado de mayor prioridad de cada CUM: si esta en Vigentes, las
    # filas que tambien tenga en Vencidos no son el registro que se cruza.
    todo = todo[todo["_PRIORIDAD"].eq(todo.groupby("_CLAVE")["_PRIORIDAD"].transform("min"))]
    todo = todo.sort_values(["_CLAVE", "_FILA_ORIGEN"], kind="stable")

    firma = pd.Series("", index=todo.index, dtype="object")
    for columna in COLUMNAS_INVIMA_COMPARADAS:
        valores = todo[columna] if columna in todo.columns else pd.Series("", index=todo.index)
        firma = firma + "\x1f" + valores.fillna("").astype(str).str.strip()
    todo["_FIRMA"] = firma

    primeras = todo.drop_duplicates(["_CLAVE", "_FIRMA"])
    numero = pd.Series(primeras.groupby("_CLAVE").cumcount().to_numpy() + 1, index=pd.MultiIndex.from_frame(primeras[["_CLAVE", "_FIRMA"]]))
    llave = pd.MultiIndex.from_frame(todo[["_CLAVE", "_FIRMA"]])
    todo["REGISTRO"] = llave.map(numero).astype(int)
    todo["REGISTROS_DISTINTOS"] = todo.groupby("_CLAVE")["REGISTRO"].transform("max")
    todo["FILAS_INVIMA"] = todo.groupby("_CLAVE")["REGISTRO"].transform("size")
    todo["FILAS_DEL_REGISTRO"] = todo.groupby(["_CLAVE", "REGISTRO"])["REGISTRO"].transform("size")
    return todo.drop(columns=["_PRIORIDAD", "_FIRMA"]).reset_index(drop=True)


def registros_distintos_por_clave(
    df_invima: pd.DataFrame,
    df_invima_vencidos: pd.DataFrame | None = None,
    df_invima_otros_estados: pd.DataFrame | None = None,
    df_invima_renovacion: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Una fila por (CUM, registro distinto): la PRIMERA fila de cada registro
    de `filas_invima_con_registro`, con las columnas crudas de INVIMA."""
    filas = filas_invima_con_registro(df_invima, df_invima_vencidos, df_invima_otros_estados, df_invima_renovacion)
    return filas.drop_duplicates(["_CLAVE", "REGISTRO"]).reset_index(drop=True)


def comparar_contra_cada_registro_invima(
    reporte_gemanet: pd.DataFrame,
    df_invima: pd.DataFrame,
    catalogo_unidad: list[EntradaCatalogo],
    catalogo_marca: list[EntradaCatalogo],
    df_invima_vencidos: pd.DataFrame | None = None,
    df_invima_otros_estados: pd.DataFrame | None = None,
    df_invima_renovacion: pd.DataFrame | None = None,
    alias_unidad: dict[str, str] | None = None,
) -> ComparacionPorRegistro:
    """Mismas entradas que `auditar_coherencia`. Ver el docstring del modulo."""
    registros = registros_distintos_por_clave(
        df_invima, df_invima_vencidos, df_invima_otros_estados, df_invima_renovacion
    )
    gemanet = reporte_gemanet.reset_index(drop=True)
    codigos = gemanet["CODIGO_INTERNO"].astype(str).str.strip()
    claves = clave_cruce_con_invima(codigos, clasificar_codigos(codigos))

    por_clave = registros.drop_duplicates("_CLAVE").set_index("_CLAVE")
    resumen = pd.DataFrame(
        {
            COLUMNA_REGISTROS_DISTINTOS: claves.map(por_clave["REGISTROS_DISTINTOS"]).fillna(0).astype(int),
            COLUMNA_FILAS_INVIMA: claves.map(por_clave["FILAS_INVIMA"]).fillna(0).astype(int),
            COLUMNA_OTRO_COINCIDE_MAS: "",
        }
    )

    con_varios = registros[registros["REGISTROS_DISTINTOS"] > 1]
    con_varios = con_varios[con_varios["_CLAVE"].isin(set(claves))]
    if con_varios.empty:
        return ComparacionPorRegistro(registros=pd.DataFrame(columns=list(COLUMNAS_TABLA_REGISTROS)), resumen=resumen)

    listados = dict(
        zip(_ORDEN_LISTADOS, (df_invima, df_invima_vencidos, df_invima_otros_estados, df_invima_renovacion))
    )
    piezas = []
    for prioridad, listado in enumerate(_ORDEN_LISTADOS):
        de_este_listado = con_varios[con_varios["LISTADO_INVIMA"] == listado]
        if de_este_listado.empty:
            continue
        claves_listado = set(de_este_listado["_CLAVE"])

        def recortar(df: pd.DataFrame | None, claves_listado: set[str] = claves_listado) -> pd.DataFrame | None:
            # Solo las filas de estos CUM: lo unico de los listados que miran
            # el combinado (GyC) y el completado. Sin recortar, cada llamada
            # arrastraba los ~424.000 registros de INVIMA.
            if df is None or df.empty or "CODIGO_INTERNO" not in df.columns:
                return None
            return df[df["CODIGO_INTERNO"].astype(str).str.strip().isin(claves_listado)]

        # El listado de origen va como `df_invima` y como auxiliares SOLO los
        # de menor prioridad. Asi el completado de campos vacios hace lo mismo
        # que en el cruce normal (de Vencidos hacia abajo) sin rellenar el
        # registro 2 con datos del registro 1 del mismo listado, y el combinado
        # (GyC) sigue viendo todas las filas crudas del CUM.
        menores = [
            recortar(listados[nombre]) if posicion > prioridad else None
            for posicion, nombre in enumerate(_ORDEN_LISTADOS)
            if nombre != _LISTADO_VIGENTES
        ]
        fuente = recortar(listados[listado])
        for numero in range(1, int(de_este_listado["REGISTRO"].max()) + 1):
            registros_numero = de_este_listado[de_este_listado["REGISTRO"] == numero]
            filas = claves.isin(set(registros_numero["_CLAVE"])).to_numpy()
            if not filas.any():
                continue
            resultado = auditar_coherencia(
                gemanet[filas],
                fuente,
                catalogo_unidad,
                catalogo_marca,
                df_invima_vencidos=menores[0],
                df_invima_otros_estados=menores[1],
                df_invima_renovacion=menores[2],
                alias_unidad=alias_unidad,
                registros_a_comparar=listados[listado].iloc[registros_numero["_FILA_ORIGEN"].to_numpy()],
            )
            pieza = pd.DataFrame(
                {
                    "FILA_AUDITORIA": np.flatnonzero(filas),
                    "CODIGO_INTERNO": codigos[filas].to_numpy(),
                    "_CLAVE": claves[filas].to_numpy(),
                    "REGISTRO": numero,
                }
            )
            for campo in CAMPOS_COMPARADOS_COHERENCIA:
                for sufijo in (SUFIJO_INVIMA, SUFIJO_VALIDACION):
                    pieza[f"{campo}{sufijo}"] = resultado[f"{campo}{sufijo}"].to_numpy()
            pieza["CAMPOS_CON_DIFERENCIA"] = resultado["CAMPOS_CON_DIFERENCIA"].to_numpy()
            es_vigentes = listado == _LISTADO_VIGENTES
            pieza["ESTADO_COHERENCIA"] = resultado["ESTADO_COHERENCIA"].to_numpy() if es_vigentes else ""
            pieza["PORCENTAJE_CALIDAD"] = resultado["PORCENTAJE_CALIDAD"].to_numpy() if es_vigentes else np.nan
            piezas.append(pieza)

    tabla = pd.concat(piezas, ignore_index=True)
    tabla = tabla.merge(
        con_varios[["_CLAVE", "REGISTRO", "LISTADO_INVIMA", "REGISTROS_DISTINTOS", "FILAS_INVIMA", "FILAS_DEL_REGISTRO"]],
        on=["_CLAVE", "REGISTRO"],
        how="left",
    )

    # Coincidencia = de los campos que se pudieron comparar contra ESTE
    # registro (coincide o difiere), cuantos coinciden. "Sin dato en Gemma
    # Net", "sin comparar" y "pendiente GyC" no ordenan nada: el lado de Gemma
    # Net es el mismo para todos los registros del CUM.
    validaciones = tabla[[f"{campo}{SUFIJO_VALIDACION}" for campo in CAMPOS_COMPARADOS_COHERENCIA]]
    coinciden = validaciones.eq(VALIDACION_COINCIDE).sum(axis=1)
    comparados = coinciden + validaciones.eq(VALIDACION_DIFIERE).sum(axis=1)
    tabla["CAMPOS_COINCIDEN"] = coinciden
    tabla["CAMPOS_COMPARADOS"] = comparados
    # NaN, no 0 %, si no hubo nada que comparar (regla 6 del proyecto).
    tabla["PORCENTAJE_COINCIDENCIA"] = (coinciden / comparados * 100).round(1).where(comparados > 0)

    # De mayor a menor coincidencia; a igualdad, el orden del archivo de
    # INVIMA, asi el registro que usa el cruce normal queda primero entre
    # empatados y nunca se sugiere "otro" que en realidad no mejora nada.
    tabla = tabla.sort_values(
        ["FILA_AUDITORIA", "PORCENTAJE_COINCIDENCIA", "CAMPOS_COINCIDEN", "REGISTRO"],
        ascending=[True, False, False, True],
        na_position="last",
        kind="stable",
    )
    tabla["ORDEN_COINCIDENCIA"] = tabla.groupby("FILA_AUDITORIA").cumcount() + 1

    porcentaje = tabla["PORCENTAJE_COINCIDENCIA"].fillna(-1)
    del_cruzado = porcentaje.where(tabla["REGISTRO"] == 1).groupby(tabla["FILA_AUDITORIA"]).max()
    del_mejor = porcentaje.groupby(tabla["FILA_AUDITORIA"]).max()
    otro_mejor = del_mejor > del_cruzado
    resumen.loc[otro_mejor.index, COLUMNA_OTRO_COINCIDE_MAS] = np.where(
        otro_mejor.to_numpy(), OTRO_COINCIDE_MAS_SI, OTRO_COINCIDE_MAS_NO
    )

    return ComparacionPorRegistro(
        registros=tabla[list(COLUMNAS_TABLA_REGISTROS)].reset_index(drop=True),
        resumen=resumen,
    )
