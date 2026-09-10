"""GET /auditoria/calidades, /auditoria/dimensiones, /auditoria/naturaleza --
la "tabla de calidades" que pide el negocio (ver `auditoria/calidades.py`),
las 6 dimensiones de calidad que todavia no tenian endpoint propio, y "que
hacer con cada hallazgo" (`ACCION_POR_NATURALEZA`). Las tres se calculan
sobre el snapshot de auditoria que ya dejo el worker: son mascaras
booleanas vectorizadas sobre un DataFrame ya materializado, NO el pipeline
pesado -- mismo criterio ya documentado en cadena_calidad.py."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import carpeta_snapshots
from backend.app.paginacion import filtrar_tabla, paginar, valores_distintos
from backend.app.schemas import (
    LIMITE_PREVISUALIZACION_DEFECTO,
    CalidadResumen,
    DimensionesCalidad,
    HallazgoNaturaleza,
    PaginaTabla,
    SeccionCalidad,
)
from gemma_cum_loader.auditoria.calidades import (
    ETIQUETAS_CAMPO_DIFERENCIA,
    Calidad,
    calidad_admite_secciones,
    calidades_auditoria,
    columnas_de_seccion,
    filtrar_por_seccion,
    secciones_de_diferencia,
)
from gemma_cum_loader.auditoria.coherencia_invima import (
    ACCION_POR_NATURALEZA,
    filtrar_universo_auditable,
)
from worker.almacen_snapshots import leer_tabla, snapshot_actual

router = APIRouter(prefix="/auditoria", tags=["calidad del catalogo"])

_MENSAJE_SIN_AUDITORIA = (
    "El worker todavia no genero ningun snapshot de auditoria. "
    "Consulta /salud para ver el estado del ultimo refresco."
)


def _tabla_auditoria(carpeta: Path):
    """El snapshot COMPLETO, sin recortar -- 199.611 filas.

    Lo necesitan las dimensiones de auto-consistencia (`/auditoria/dimensiones`):
    formato, duplicados y completitud miden el reporte de Gemma Net contra si
    mismo, y son deteccion de basura. Recortar antes esconderia justo la fila
    con el problema. Para lo que se AUDITA contra INVIMA, usar
    `_tabla_auditable`."""
    df = leer_tabla("auditoria", carpeta)
    if df is None:
        raise HTTPException(status_code=503, detail=_MENSAJE_SIN_AUDITORIA)
    return df


def _tabla_auditable(carpeta: Path):
    """El snapshot recortado al universo auditable -- lo que se compara contra
    INVIMA, y lo que miden las 6 tarjetas de calidades.

    Antes NINGUN endpoint de este router aplicaba el recorte, asi que las
    tarjetas median sobre la tabla cruda mientras "Priorizar lo que requiere
    accion" (auditoria.py) medi­a sobre el universo filtrado. Las dos pantallas
    coincidian solo porque las mascaras de `calidades.py` repiten a mano los
    mismos criterios -- hasta que dejaron de coincidir.

    Lo destapo el usuario (2026-09-08): 4 codigos con formato de CUM valido que
    INVIMA no reconoce (alimentos: ENSURE CLINICAL, ALIMENTO LACTEO EN POLVO)
    seguian saliendo en la tarjeta "No existe en INVIMA" DESPUES de que
    `filtrar_universo_auditable` ya los hubiera sacado de la auditoria. Medido:
    el recorte deja esa tarjeta en 0 y las otras cinco intactas.

    La tarjeta se conserva aunque quede en cero -- pedido del usuario: sirve
    para ver si alguien vuelve a cargar en Gemma Net algo que no es un
    medicamento, "aun si no hay casos actualmente"."""
    return filtrar_universo_auditable(_tabla_auditoria(carpeta))


# Cache de las 6 calidades ya calculadas, por snapshot. Mismo patron y misma
# razon que `_CACHE_TABLAS` en worker/almacen_snapshots.py: alli el cuello era
# releer el Parquet en cada request, aca es RECALCULARLO.
#
# Medido el 2026-09-04 sobre el snapshot real (199.611 filas): `leer_tabla` ya
# cacheada tarda 0 ms, `filtrar_por_seccion` 34 ms, y `calidades_auditoria`
# **666 ms** -- o sea, TODO el coste de una peticion era rehacer las 6 mascaras
# y las columnas derivadas sobre 200.000 filas para devolver 1.000. Se pagaba
# en cada request de tabla, de valores de columna, de secciones y de descarga.
#
# Cachear es seguro por la misma razon que alli: los Parquet de un snapshot son
# inmutables, asi que para un `snapshot.nombre` dado el resultado no cambia. Al
# llegar un snapshot nuevo la marca no calza y la entrada se reemplaza sola --
# no crece sin limite (una entrada por carpeta).
#
# Los `Calidad` que devuelve quedan COMPARTIDOS entre requests: sus `df_tabla`
# NO deben mutarse in place. Los llamadores actuales solo filtran (que crea un
# DataFrame nuevo) o copian antes de tocar.
_CACHE_CALIDADES: dict[str, tuple[str, list[Calidad]]] = {}


# Ya no se post-procesa cada Calidad para inyectarle ESTADO_CUM_INVIMA: todas
# las definiciones la piden en `base` (auditoria/calidades.py) y `_definiciones`
# solo conserva las columnas que existen en el DataFrame, asi que si el
# snapshot la trae ya viene incluida, y si no la trae tampoco habria de donde
# sacarla. La funcion que lo hacia (`_con_estado_listado_invima`) solo copiaba
# los 6 df_tabla para devolverlos identicos -- gasto de memoria en el camino
# degradado, que es justo donde menos conviene.
def _calidades(carpeta: Path) -> list[Calidad]:
    auditoria = _tabla_auditable(carpeta)
    snapshot = snapshot_actual(carpeta)
    # Sin snapshot no hay nombre con el que versionar la entrada: se calcula
    # sin cachear en vez de arriesgar servir un resultado que no se puede
    # invalidar. Con `_tabla_auditoria` habiendo respondido, este caso no
    # deberia darse; es una guarda, no un camino esperado.
    if snapshot is None:
        return calidades_auditoria(auditoria)

    clave = str(carpeta)
    en_cache = _CACHE_CALIDADES.get(clave)
    if en_cache is not None and en_cache[0] == snapshot.nombre:
        return en_cache[1]

    cals = calidades_auditoria(auditoria)
    _CACHE_CALIDADES[clave] = (snapshot.nombre, cals)
    return cals


@router.get("/calidades", response_model=list[CalidadResumen])
def listar_calidades(carpeta: Path = Depends(carpeta_snapshots)) -> list[CalidadResumen]:
    cals = _calidades(carpeta)
    return [
        CalidadResumen(
            nombre=c.nombre,
            explica=c.explica,
            medicamentos=c.medicamentos,
            porcentaje_del_catalogo=c.porcentaje_del_catalogo,
            columnas=list(c.columnas),
            criterios=list(c.criterios),
            que_hacer=c.que_hacer,
        )
        for c in cals
    ]


def _calidad_o_404(nombre: str, carpeta: Path) -> Calidad:
    calidades = {c.nombre: c for c in _calidades(carpeta)}
    calidad = calidades.get(nombre)
    if calidad is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{nombre}' no es una calidad reconocida. Calidades disponibles: "
            f"{', '.join(calidades)}.",
        )
    return calidad


@router.get("/calidades/{nombre}/secciones", response_model=list[SeccionCalidad])
def listar_secciones_calidad(
    nombre: str, carpeta: Path = Depends(carpeta_snapshots)
) -> list[SeccionCalidad]:
    """Los tipos de diferencia dentro de una calidad, de mayor a menor.

    Existe porque una sola tarjeta puede traer decenas de miles de filas de
    las que el 97 % es un unico problema (medido: 57.255 de 59.005 son
    FECHA_FIN), y en una tabla unica los seis problemas chicos quedan
    invisibles -- pedido del usuario (2026-09-02). Devuelve [] cuando la
    calidad no tiene ninguna diferencia que partir (ej. "No existe en
    INVIMA"), y tambien cuando la calidad no es de las que se seccionan (ver
    CALIDADES_CON_SECCIONES): la UI entonces no dibuja secciones."""
    calidad = _calidad_o_404(nombre, carpeta)
    if not calidad_admite_secciones(nombre):
        return []
    return [
        SeccionCalidad(
            clave=s.clave,
            etiqueta=s.etiqueta,
            medicamentos=s.medicamentos,
            # Humanizado aca y no en el frontend: el mapa de etiquetas vive en
            # calidades.py junto a los campos que nombra, y duplicarlo en TS
            # es garantia de que se desincronicen.
            derivado_de=[ETIQUETAS_CAMPO_DIFERENCIA.get(c, c) for c in s.derivado_de],
            explica=s.explica,
        )
        for s in secciones_de_diferencia(calidad.df_tabla)
    ]


def _con_columnas_de_seccion(tabla: pd.DataFrame, seccion: str) -> pd.DataFrame:
    """Recorta la tabla a las columnas de la seccion abierta (paso 1,
    `columnas_de_seccion`): de 38 columnas a 8, la ganancia principal del
    plan (medido: 2,0 MB por pagina de 1.000, 79 % de mas que viaja hoy sin
    usarse). Clave sin reconocer -> `columnas_de_seccion` devuelve tupla
    vacia, que aca se interpreta como "no recortar" (degradacion explicita
    acordada en el plan: nunca una tabla sin columnas por una clave vieja).

    Una columna de la lista que no llego a esta tarjeta se omite en vez de
    romper con KeyError -- mismo patron que ya usa `calidades_auditoria()`
    al armar cada `Calidad` (filtrar contra `df.columns` antes de indexar)."""
    columnas = columnas_de_seccion(seccion)
    if not columnas:
        return tabla
    presentes = [c for c in columnas if c in tabla.columns]
    return tabla[presentes]


def tabla_calidad_filtrada(
    nombre: str,
    carpeta: Path,
    *,
    seccion: str | None = None,
    q: str | None = None,
    filtros_json: str | None = None,
) -> pd.DataFrame:
    """La tabla de una calidad recortada a su seccion (filas Y columnas, pasos
    1-2 del plan) y con la busqueda/filtro de columna ya aplicados -- SIN
    paginar. La comparten `obtener_calidad` (que pagina el resultado para la
    pantalla) y `GET /descargas/calidad/{nombre}` (que exporta TODAS las
    filas que deja el filtro, no solo la pagina visible): que pantalla y
    archivo llamen a la misma funcion es lo que evita que discrepen -- ya paso
    en otras vistas de este proyecto y llevo dias arreglarlo.

    Lanza 404 (via `_calidad_o_404`) si `nombre` no es una calidad reconocida,
    y 503 (via `_tabla_auditoria`, adentro de `_calidades`) si el worker
    todavia no dejo ningun snapshot -- ambos casos antes de tocar ningun
    filtro."""
    calidad = _calidad_o_404(nombre, carpeta)
    # El gate por calidad va aca tambien, y no solo en /secciones: si no, un
    # enlace viejo con ?seccion= seguiria recortando una calidad que ya no se
    # secciona, y la tabla mostraria menos filas de las que anuncia su tarjeta.
    aplica = seccion is not None and calidad_admite_secciones(nombre)
    tabla = filtrar_por_seccion(calidad.df_tabla, seccion) if aplica else calidad.df_tabla
    if aplica and seccion is not None:
        tabla = _con_columnas_de_seccion(tabla, seccion)
    else:
        # Sin seccion se muestran solo las columnas VISIBLES de la calidad.
        # `df_tabla` trae ademas las que necesita cada seccion para recortarse
        # (los trios campo-a-campo), y sin esta linea salian todas: 38 columnas
        # de las que 22 eran "Coincide" repetido -- exactamente la redundancia
        # que el usuario reporto dos veces. Ver el comentario de
        # `columnas_para_secciones` en calidades.py.
        tabla = tabla[[c for c in calidad.columnas if c in tabla.columns]]
    return filtrar_tabla(tabla, q=q, filtros_json=filtros_json)


@router.get("/calidades/{nombre}", response_model=PaginaTabla)
def obtener_calidad(
    nombre: str,
    q: str | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    ordenar_por: str | None = None,
    orden_descendente: bool = False,
    filtros_json: str | None = None,
    seccion: str | None = None,
    carpeta: Path = Depends(carpeta_snapshots),
) -> PaginaTabla:
    tabla = tabla_calidad_filtrada(nombre, carpeta, seccion=seccion, q=q, filtros_json=filtros_json)
    # q/filtros_json ya se aplicaron arriba (misma funcion que usa la
    # descarga); aca solo falta ordenar y paginar para la pantalla.
    return paginar(
        tabla,
        limite=limite,
        offset=offset,
        todo=todo,
        ordenar_por=ordenar_por,
        orden_descendente=orden_descendente,
    )


@router.get("/calidades/{nombre}/valores")
def valores_columna_calidad(
    nombre: str,
    columna: str,
    seccion: str | None = None,
    carpeta: Path = Depends(carpeta_snapshots),
) -> list[dict[str, object]]:
    # Acota FILAS a la seccion abierta: ofrecer como filtro un valor que
    # no existe en lo que se esta viendo lleva a una tabla vacia sin explicar
    # por que. NO se recorta a las COLUMNAS de la seccion (a diferencia de
    # obtener_calidad): `columna` ya llega elegida por el frontend entre las
    # que la tabla recortada esta mostrando, y `valores_distintos` solo mira
    # esa columna puntual -- aplicar ademas el recorte de columnas aca
    # arriesgaria dejar el filtro sin opciones si alguna vez discreparan.
    tabla = _calidad_o_404(nombre, carpeta).df_tabla
    if seccion is not None and calidad_admite_secciones(nombre):
        tabla = filtrar_por_seccion(tabla, seccion)
    return valores_distintos(tabla, columna)


# Cada dimension -> (columna que la marca, columnas utiles para entenderla).
# Pedido del usuario (2026-09-01): "esas tarjetas deberian permitir ver cuales
# son los medicamentos que se marcan con esa condicion" -- es el mismo
# principio que ya rige las calidades ("cada cifra se puede abrir, no solo
# mirar"), que a las dimensiones les faltaba.
_COLUMNAS_BASE_DIMENSION = ["CODIGO_INTERNO", "DESCRIPCION", "ACTIVO", "ESTADO_LISTADO_INVIMA"]
DIMENSIONES_ABRIBLES: dict[str, tuple[str, list[str]]] = {
    "completitud": ("PORCENTAJE_COMPLETITUD_REPORTE", ["PORCENTAJE_COMPLETITUD_REPORTE"]),
    "duplicados": ("CODIGO_DUPLICADO_EN_REPORTE", ["CODIGO_DUPLICADO_EN_REPORTE"]),
    "fuera_de_dominio": ("VALORES_FUERA_DE_DOMINIO", ["VALORES_FUERA_DE_DOMINIO"]),
    "inconsistencia_numerica": ("INCONSISTENCIA_NUMERICA", ["INCONSISTENCIA_NUMERICA"]),
    "formato_invalido": ("FORMATO_CODIGO_INTERNO_INVALIDO", ["FORMATO_CODIGO_INTERNO_INVALIDO"]),
    "integridad_referencial": ("INTEGRIDAD_REFERENCIAL_CATALOGO", ["INTEGRIDAD_REFERENCIAL_CATALOGO"]),
}


def _tabla_dimension(clave: str, carpeta: Path) -> pd.DataFrame:
    """Los medicamentos que caen en una dimension. Sobre el snapshot COMPLETO,
    igual que el contador de esa dimension: si se recortara al universo
    auditable, la tabla no cuadraria con el numero de la tarjeta."""
    if clave not in DIMENSIONES_ABRIBLES:
        raise HTTPException(
            status_code=404,
            detail=f"'{clave}' no es una dimension reconocida. Disponibles: {', '.join(DIMENSIONES_ABRIBLES)}.",
        )
    columna, extra = DIMENSIONES_ABRIBLES[clave]
    auditoria = _tabla_auditoria(carpeta)
    if columna not in auditoria.columns:
        return pd.DataFrame(columns=[*_COLUMNAS_BASE_DIMENSION, *extra])
    serie = auditoria[columna]
    if clave == "completitud":
        # "Abrir" completitud = los que NO estan completos, ordenados por los
        # peores primero. Un 100 % no es un hallazgo que revisar.
        mascara = pd.to_numeric(serie, errors="coerce").fillna(100) < 100
        filtrado = auditoria[mascara].sort_values(columna)
    elif serie.dtype == bool:
        filtrado = auditoria[serie]
    else:
        filtrado = auditoria[serie.fillna("").astype(str).str.strip().ne("")]
    columnas = [c for c in [*_COLUMNAS_BASE_DIMENSION, *extra] if c in filtrado.columns]
    return filtrado[columnas].copy()


@router.get("/dimensiones/{clave}", response_model=PaginaTabla)
def obtener_dimension(
    clave: str,
    q: str | None = None,
    limite: int = LIMITE_PREVISUALIZACION_DEFECTO,
    offset: int = 0,
    todo: bool = False,
    ordenar_por: str | None = None,
    orden_descendente: bool = False,
    filtros_json: str | None = None,
    carpeta: Path = Depends(carpeta_snapshots),
) -> PaginaTabla:
    return paginar(
        _tabla_dimension(clave, carpeta),
        q=q,
        limite=limite,
        offset=offset,
        todo=todo,
        ordenar_por=ordenar_por,
        orden_descendente=orden_descendente,
        filtros_json=filtros_json,
    )


@router.get("/dimensiones/{clave}/valores")
def valores_columna_dimension(
    clave: str, columna: str, carpeta: Path = Depends(carpeta_snapshots)
) -> list[dict[str, object]]:
    return valores_distintos(_tabla_dimension(clave, carpeta), columna)


@router.get("/dimensiones", response_model=DimensionesCalidad)
def dimensiones_calidad(carpeta: Path = Depends(carpeta_snapshots)) -> DimensionesCalidad:
    """Las dimensiones de AUTO-consistencia del reporte contra si mismo
    (duplicados, formato invalido, dominio, razonabilidad numerica).

    Estas cuentan sobre el reporte COMPLETO a proposito, no sobre el universo
    auditable: son deteccion de basura, y si el recorte corriera antes la fila
    con el problema ya no existiria para contarla (medido: `formato_invalido`
    pasaba de 1 a 0 -- no porque se arreglara el dato, sino porque la fila
    desaparecio). Es la misma razon por la que el worker persiste el snapshot
    entero (ver pipeline.py).

    `n_total_auditado` SI es el universo auditable: es la cifra que la UI
    muestra como "lo que auditamos", y despues de la decision del usuario
    (2026-09-01) ese numero es el de CUMs activos, no las 199.611 filas del
    catalogo. Los contadores de arriba y este total responden preguntas
    distintas a proposito -- por eso no coinciden, y por eso se documenta.
    """
    auditoria = _tabla_auditoria(carpeta)
    n_auditable = len(filtrar_universo_auditable(auditoria))
    completitud = (
        auditoria["PORCENTAJE_COMPLETITUD_REPORTE"].mean()
        if "PORCENTAJE_COMPLETITUD_REPORTE" in auditoria.columns
        else None
    )

    def _contar_no_vacio(columna: str) -> int:
        if columna not in auditoria.columns:
            return 0
        return int((auditoria[columna] != "").sum())

    return DimensionesCalidad(
        n_total_auditado=n_auditable,
        completitud_promedio=None if completitud is None or pd.isna(completitud) else round(float(completitud), 1),
        duplicados=int(auditoria["CODIGO_DUPLICADO_EN_REPORTE"].sum()) if "CODIGO_DUPLICADO_EN_REPORTE" in auditoria.columns else 0,
        fuera_de_dominio=_contar_no_vacio("VALORES_FUERA_DE_DOMINIO"),
        inconsistencia_numerica=_contar_no_vacio("INCONSISTENCIA_NUMERICA"),
        formato_invalido=_contar_no_vacio("FORMATO_CODIGO_INTERNO_INVALIDO"),
        integridad_referencial=_contar_no_vacio("INTEGRIDAD_REFERENCIAL_CATALOGO"),
    )


@router.get("/naturaleza", response_model=list[HallazgoNaturaleza])
def naturaleza_hallazgos(carpeta: Path = Depends(carpeta_snapshots)) -> list[HallazgoNaturaleza]:
    """"Que hacer con cada hallazgo" -- una fila por NATURALEZA_HALLAZGO con
    conteo > 0, en el mismo orden de prioridad de atencion que
    ACCION_POR_NATURALEZA (lo que pone en riesgo una autorizacion primero,
    lo residual de la migracion al final). Filtrado al universo auditable
    (mismo criterio que /resumen, ver auditoria.py) -- sin esto, un hallazgo
    en un CUM inactivo o en un codigo que no es CUM infla el conteo de algo
    que no hay que accionar. El recorte ya lo hace `_tabla_auditoria`, que es
    el unico punto de entrada del router: aplicarlo dos veces daria el mismo
    resultado pero recorreria 199.611 filas de mas por request."""
    auditoria = _tabla_auditable(carpeta)
    if "NATURALEZA_HALLAZGO" not in auditoria.columns:
        return []
    conteo = auditoria["NATURALEZA_HALLAZGO"].value_counts()
    return [
        HallazgoNaturaleza(naturaleza=etiqueta, medicamentos=int(conteo[etiqueta]), que_hacer=que_hacer)
        for etiqueta, que_hacer in ACCION_POR_NATURALEZA.items()
        if etiqueta in conteo.index and conteo[etiqueta] > 0
    ]
