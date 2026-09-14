"""GET /consulta-detalle/medicamento -- consulta puntual de uno o varios
codigos, lado a lado (INVIMA vs Gemma Net). Complementa /universo y
/auditoria (que ya sirven la tabla completa paginada): esta vista busca por
codigo exacto y arma el detalle completo de esa fila puntual, no una pagina
de resultados."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.app.dependencies import carpeta_snapshots
from gemma_cum_loader.ingesta.invima_socrata import consultar_cum_en_listados
from worker.almacen_snapshots import leer_tabla

router = APIRouter(prefix="/consulta-detalle", tags=["consulta-detalle"])

# Columnas de INVIMA que coherencia_invima.py ya deja pobladas en la propia
# fila de auditoria para los 4 listados (Vigentes, Vencidos, Renovacion,
# Otros Estados) -- no solo Vigentes, que es todo lo que trae el snapshot
# "universo" (ver `_fila_invima_sintetica`).
_COLUMNAS_INVIMA_EN_AUDITORIA = (
    "ESTADO_LISTADO_INVIMA",  # Listado donde aparece: vigente/vencido/renovacion/otros_estados
    "ESTADO_CUM_INVIMA",       # Vigencia real: Activo/Inactivo (nuevo 2026-09-02)
    "ESTADO_INVIMA_DETALLE",
    "FECHA_ACTIVO_INVIMA",
    "FECHA_INACTIVO_INVIMA",
    "FECHA_VENCIMIENTO_INVIMA",
)


def _sanitizar_valor(valor: object) -> object:
    """Convierte un valor de pandas/numpy a algo serializable en JSON.

    pd.isna() se evalua ANTES de la rama de date/datetime: pd.NaT se
    comporta como instancia de datetime para isinstance() pero no es una
    fecha real. Sin este orden, pd.NaT caia en la rama de date/datetime y
    se serializaba como el string literal "NaT" -- el frontend solo trata
    null/undefined/"" como vacio, asi que el texto "NaT" quedaba visible en
    pantalla (bug real, revisado 2026-09-01)."""
    if valor is None:
        return None
    if isinstance(valor, (bool, int, str)):
        return valor
    if isinstance(valor, float):
        if math.isnan(valor) or math.isinf(valor):
            return None
        return round(valor, 10)
    if isinstance(valor, Decimal):
        return None if valor.is_nan() else float(valor)
    if pd.isna(valor):
        return None
    if isinstance(valor, (date, datetime)):
        return str(valor)
    return str(valor)


def _sanitizar_fila(fila: dict) -> dict:
    return {k: _sanitizar_valor(v) for k, v in fila.items()}


def _limpiar_codigo(codigo: str) -> str:
    return codigo.strip().upper()


def _fila_invima_sintetica(fila_auditoria: dict) -> dict | None:
    """Construye una fila de INVIMA a partir de las columnas *_INVIMA que ya
    trae la propia fila de auditoria, para el caso en que el codigo SI tiene
    correspondencia en INVIMA pero en un listado distinto de Vigentes
    (Vencidos / Renovacion / Otros Estados) -- esos 3 listados no estan en
    el snapshot "universo" (solo Vigentes, ver leer_tabla("universo")), asi
    que sin esto el panel INVIMA quedaba vacio para un codigo que la propia
    auditoria ya sabe que existe (caso real reportado por el usuario:
    20102710-2, vencido). Devuelve None si la fila no trae ningun dato de
    INVIMA -- ese si es el caso correcto de "no existe en INVIMA"."""
    estado = str(fila_auditoria.get("ESTADO_LISTADO_INVIMA") or "").strip()
    tiene_fecha = any(
        fila_auditoria.get(columna)
        for columna in ("FECHA_ACTIVO_INVIMA", "FECHA_INACTIVO_INVIMA", "FECHA_VENCIMIENTO_INVIMA")
    )
    if not estado and not tiene_fecha:
        return None
    return {
        "CODIGO_INTERNO": fila_auditoria.get("CODIGO_INTERNO"),
        "TITULAR": fila_auditoria.get("TITULAR"),
        "ESTADO_LISTADO_INVIMA": fila_auditoria.get("ESTADO_LISTADO_INVIMA"),
        "ESTADO_CUM_INVIMA": fila_auditoria.get("ESTADO_CUM_INVIMA"),
        "ESTADO_INVIMA_DETALLE": fila_auditoria.get("ESTADO_INVIMA_DETALLE"),
        "FECHA_ACTIVO_INVIMA": fila_auditoria.get("FECHA_ACTIVO_INVIMA"),
        "FECHA_INACTIVO_INVIMA": fila_auditoria.get("FECHA_INACTIVO_INVIMA"),
        "FECHA_VENCIMIENTO_INVIMA": fila_auditoria.get("FECHA_VENCIMIENTO_INVIMA"),
    }


def _leer_snapshot_o_error(nombre: str, carpeta: Path) -> tuple[pd.DataFrame | None, str | None]:
    """`leer_tabla` devuelve None cuando el worker simplemente no ha
    generado ese snapshot todavia -- estado normal, no es un error. Si en
    cambio LANZA una excepcion (ej. parquet corrupto en disco), es una
    falla de infraestructura real: se aisla aca (una fuente rota no debe
    tumbar la consulta si la otra fuente si sirve) pero el mensaje real se
    conserva y viaja en el campo `error` de la respuesta -- nunca se finge
    'sin dato' silenciosamente, porque el frontend interpreta 'sin dato en
    Gemma Net' como 'candidato a cargar', un diagnostico completamente
    distinto de 'no se pudo leer el snapshot' (bug real, revisado
    2026-09-01)."""
    try:
        return leer_tabla(nombre, carpeta), None
    except (OSError, ValueError) as error:
        return None, f"No se pudo leer el snapshot '{nombre}': {error}"


@router.get("/medicamento")
def consultar_medicamento(codigo: str, carpeta: Path = Depends(carpeta_snapshots)):
    """Consulta uno o varios codigos (separados por coma) en INVIMA y
    Gemma Net para comparacion lado a lado."""
    codigos_consultados = [_limpiar_codigo(c) for c in codigo.split(",") if _limpiar_codigo(c)]
    if not codigos_consultados:
        return JSONResponse(
            status_code=400,
            content={
                "invima": [],
                "gemma_net": None,
                "total_encontrados": 0,
                "codigos_consultados": [],
                "error": "Codigo vacio",
            },
        )

    df_universo, error_universo = _leer_snapshot_o_error("universo", carpeta)
    df_auditoria, error_auditoria = _leer_snapshot_o_error("auditoria", carpeta)
    # Los 4 listados de INVIMA. Un snapshot anterior a esta tabla devuelve
    # None y la consulta sigue funcionando con "universo" + la fila sintetica
    # (degradacion explicita): se pierde el registro real de lo no vigente,
    # no la respuesta entera.
    df_listados, error_listados = _leer_snapshot_o_error("invima_listados", carpeta)

    if df_universo is None and df_auditoria is None:
        mensaje = " ".join(m for m in (error_universo, error_auditoria) if m) or (
            "Todavía no hay datos: la primera actualización no ha terminado. " + "Intente de nuevo en unos minutos; el indicador de la barra superior muestra el estado de la actualización."
        )
        return JSONResponse(
            status_code=503,
            content={
                "invima": [],
                "gemma_net": None,
                "total_encontrados": 0,
                "codigos_consultados": codigos_consultados,
                "error": mensaje,
            },
        )

    codigos_normalizados = set(codigos_consultados)

    # Gemma Net primero -- de paso se junta CUM_RECONSTRUIDO de cada codigo
    # encontrado, que hace falta para buscar en INVIMA (ver mas abajo).
    gemma_rows: list[dict] = []
    claves_reconstruidas: set[str] = set()
    if df_auditoria is not None and "CODIGO_INTERNO" in df_auditoria.columns:
        columna_auditoria = df_auditoria["CODIGO_INTERNO"].fillna("").astype(str).str.strip()
        for fila in df_auditoria[columna_auditoria.isin(codigos_normalizados)].to_dict("records"):
            fila_s = _sanitizar_fila(fila)
            fila_s["ACTIVO_GEMMA_NET"] = fila_s.get("ACTIVO")
            gemma_rows.append(fila_s)
            reconstruido = str(fila.get("CUM_RECONSTRUIDO") or "").strip()
            if reconstruido:
                claves_reconstruidas.add(reconstruido)

    # INVIMA (snapshot "universo" = solo Vigentes) -- por el codigo tal cual
    # Y por su CUM_RECONSTRUIDO. Bug real (2026-09-01): un codigo "CUM con
    # sufijo ATC" (formato EXPEDIENTE(8)-CONSECUTIVO(2)-0ATC(7), ej.
    # "00040284-02-0N03AG01") trae el EXPEDIENTE-CONSECUTIVO real EMBEBIDO
    # en el codigo, distinto del que usa INVIMA como llave ("40284-2").
    # coherencia_invima.py YA lo reconstruye para poder cruzar (columna
    # CUM_RECONSTRUIDO) -- sin usar esa misma llave aca, 46 de 79 filas
    # cum_con_sufijo_atc vigentes quedaban sin match aunque SI existieran en
    # INVIMA.
    invima_por_codigo: dict[str, dict] = {}
    invima_rows: list[dict] = []
    todas_las_claves = codigos_normalizados | claves_reconstruidas

    # "invima_listados" son los 4 datasets tal cual (Vigentes, Vencidos, Otros
    # Estados, Renovacion) con una columna LISTADO que dice de cual salio la
    # fila -- ver worker/tareas.py::_listados_invima_unificados. Se busca aca
    # PRIMERO porque es la unica fuente que tiene el registro REAL de un CUM
    # que no esta vigente: "universo" es solo Vigentes, y la fila sintetica de
    # abajo solo puede reconstruir estado y fechas, no TITULAR, PRODUCTO ni
    # DESCRIPCION_COMERCIAL. Caso real 20102710-2 (vive solo en Vencidos).
    for nombre_df, df_fuente in (("invima_listados", df_listados), ("universo", df_universo)):
        if df_fuente is None or "CODIGO_INTERNO" not in df_fuente.columns:
            continue
        columna = df_fuente["CODIGO_INTERNO"].fillna("").astype(str).str.strip()
        for fila in df_fuente[columna.isin(todas_las_claves)].to_dict("records"):
            fila_s = _sanitizar_fila(fila)
            codigo_fila = str(fila_s.get("CODIGO_INTERNO") or "").strip()
            # El primero que responde gana: un CUM vigente aparece en los dos
            # snapshots y no debe salir dos veces en el panel.
            if codigo_fila in invima_por_codigo:
                continue
            fila_s.setdefault("LISTADO", None)
            fila_s["_FUENTE_SNAPSHOT"] = nombre_df
            invima_por_codigo[codigo_fila] = fila_s
            invima_rows.append(fila_s)

    # En el detalle lado a lado se muestran tambien el estado y las fechas
    # de ambas fuentes con nombres claros. ESTADO_LISTADO_INVIMA /
    # ESTADO_INVIMA_DETALLE / FECHA_ACTIVO_INVIMA / FECHA_INACTIVO_INVIMA /
    # FECHA_VENCIMIENTO_INVIMA ya vienen completos (los 4 listados de
    # INVIMA) desde `df_auditoria` -- coherencia_invima.py los puebla ahi
    # directamente, asi que ya viajan con `fila` sin tocar nada mas. Lo que
    # sigue es COMPLEMENTARIO: agrega lo que "universo" (solo Vigentes)
    # tiene y auditoria no (ej. TITULAR, ESTADO_REGISTRO crudo), y si el
    # codigo no aparece en "universo" pero SI tiene datos de INVIMA en sus
    # propias columnas (osea, esta en Vencidos/Renovacion/Otros Estados),
    # construye una fila sintetica para que el panel INVIMA no quede vacio.
    for fila in gemma_rows:
        codigo_fila = str(fila.get("CODIGO_INTERNO") or "").strip()
        reconstruido = str(fila.get("CUM_RECONSTRUIDO") or "").strip()
        if not codigo_fila:
            continue
        invima = invima_por_codigo.get(codigo_fila) or (invima_por_codigo.get(reconstruido) if reconstruido else None)
        if invima is not None:
            if invima.get("ESTADO_REGISTRO") and not fila.get("ESTADO_INVIMA_DETALLE"):
                fila["ESTADO_INVIMA_DETALLE"] = invima["ESTADO_REGISTRO"]
            if invima.get("TITULAR") and not fila.get("TITULAR"):
                fila["TITULAR"] = invima["TITULAR"]
            # La fila de "universo" (Vigentes) no trae sus propias fechas de
            # vigencia con nombre util para comparar -- se completan con las
            # mismas columnas *_INVIMA que ya calculo coherencia_invima.py
            # para ESTE codigo, asi la tabla lado a lado tambien puede
            # mostrar fecha activo/vencimiento del lado INVIMA (pedido del
            # usuario, 2026-09-01: comparar visualmente FECHA_INICIO/
            # FECHA_FIN de Gemma Net contra FECHA_ACTIVO_INVIMA/
            # FECHA_VENCIMIENTO_INVIMA de INVIMA en la misma tabla).
            for columna in _COLUMNAS_INVIMA_EN_AUDITORIA:
                if not invima.get(columna) and fila.get(columna):
                    invima[columna] = fila.get(columna)
            continue
        sintetica = _fila_invima_sintetica(fila)
        if sintetica is not None:
            invima_rows.append(sintetica)

    contenido = {
        "invima": invima_rows,
        "gemma_net": gemma_rows if gemma_rows else None,
        "total_encontrados": len(invima_rows) + len(gemma_rows),
        "codigos_consultados": codigos_consultados,
    }
    error_lecturas = " ".join(
        m for m in (error_universo, error_auditoria, error_listados) if m
    )
    if error_lecturas:
        contenido["error"] = error_lecturas
    return JSONResponse(content=contenido)


@router.get("/invima-en-vivo")
def consultar_invima_en_vivo(codigo: str):
    """Pregunta por uno o varios codigos a los 4 datasets de INVIMA AHORA
    MISMO, sin pasar por el snapshot.

    Existe para poder corroborar lo que muestra `/medicamento`, que resuelve
    contra el snapshot: si el ultimo refresco cayo al respaldo local (Socrata
    caido), ese snapshot puede traer datos viejos y un CUM aparece en un
    listado que ya no le corresponde. Caso real 2026-09-03: el snapshot del
    dia anterior venia de los Excel de 2022 (101.183 vigentes contra los
    157.756 que la API servia ese dia), y un CUM hoy vigente se veia en
    renovacion.

    Va bajo accion explicita del usuario, nunca automatico al abrir la vista:
    son 4 llamadas de red por codigo y la vista debe seguir sirviendo sin
    conexion (regla 4 del proyecto para `explicar_fila`, mismo criterio)."""
    codigos = [_limpiar_codigo(c) for c in codigo.split(",") if _limpiar_codigo(c)]
    if not codigos:
        return JSONResponse(
            status_code=400,
            content={"error": "Escribe al menos un codigo para consultar.", "resultados": []},
        )

    resultados = []
    for cod in codigos:
        consulta = consultar_cum_en_listados(cod)
        resultados.append(
            {
                "codigo": consulta.codigo_interno,
                "encontrado": consulta.encontrado,
                "apariciones": [
                    {
                        "listado": a.listado,
                        "estado_cum": a.estado_cum,
                        "estado_registro": a.estado_registro,
                        "producto": a.producto,
                        "filas": a.filas,
                    }
                    for a in consulta.apariciones
                ],
                "listados_no_consultados": list(consulta.listados_no_consultados),
                "error": consulta.error,
                "consultado_utc": consulta.fecha_consulta.isoformat(),
            }
        )
    return JSONResponse(content={"resultados": resultados})
