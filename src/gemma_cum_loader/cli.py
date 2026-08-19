"""CLI: corre los dos flujos reales del aplicativo sin abrir la UI.

  candidatos -- que medicamentos de INVIMA FALTAN por cargar en Gemma Net
                (ver pipeline.procesar_invima_vigentes / armado/malla.py)
  auditoria  -- de lo que YA esta cargado en Gemma Net, que esta
                desactualizado o mal diligenciado frente a INVIMA
                (ver pipeline.auditar_coherencia_gemanet)

Ambos aceptan el catalogo INVIMA por archivo (--invima) o en vivo por la API
de Socrata (--api). La UI de Streamlit (ui_revision/app_streamlit.py) es la
via principal para el equipo de negocio; esta CLI existe para correr lo mismo
sin interfaz -- lotes programados, servidores sin navegador, o revisar un
archivo puntual sin levantar la app.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from gemma_cum_loader.ingesta.invima_reader import (
    leer_catalogo_invima,
    leer_catalogo_invima_otros_estados,
    leer_catalogo_invima_renovacion,
    leer_catalogo_invima_vencidos,
)
from gemma_cum_loader.ingesta.invima_socrata import leer_catalogo_invima_api
from gemma_cum_loader.pipeline import (
    auditar_coherencia_gemanet,
    guardar_reporte,
    procesar_desde_catalogo_invima,
)


def _cargar_catalogo_invima(args: argparse.Namespace) -> pd.DataFrame:
    """--api y --invima son mutuamente excluyentes y uno es obligatorio (lo
    exige argparse); esto solo elige la via ya validada."""
    if args.api:
        print("Descargando el catalogo INVIMA vigente desde la API de Socrata...", file=sys.stderr)
        return leer_catalogo_invima_api()
    return leer_catalogo_invima(args.invima)


def _cargar_auxiliar_opcional(ruta: str | None, lector, nombre: str) -> pd.DataFrame | None:
    """Los 3 datasets auxiliares (Vencidos / Tramite de Renovacion / Otros
    Estados) son opcionales e independientes: si uno no se pasa o no se puede
    leer, la auditoria sigue corriendo y esa distincion puntual simplemente
    no esta disponible -- degradacion explicita, nunca una suposicion
    silenciosa (mismo criterio que la UI)."""
    if ruta is None:
        return None
    try:
        return lector(ruta)
    except (OSError, ValueError) as exc:
        print(
            f"AVISO: no se pudo leer el archivo de {nombre} ({type(exc).__name__}: {exc}) -- "
            "la auditoria sigue, pero sin poder distinguir ese caso.",
            file=sys.stderr,
        )
        return None


def _comando_candidatos(args: argparse.Namespace) -> None:
    df_invima = _cargar_catalogo_invima(args)
    df = procesar_desde_catalogo_invima(df_invima, args.gemma_net)
    guardar_reporte(df, args.salida, columna_hoja="accion")
    print(f"{len(df):,} filas procesadas -> {args.salida}")
    print(df["accion"].value_counts().to_string())


def _comando_auditoria(args: argparse.Namespace) -> None:
    df_invima = _cargar_catalogo_invima(args)
    auditoria = auditar_coherencia_gemanet(
        df_invima,
        args.gemma_net,
        df_invima_vencidos=_cargar_auxiliar_opcional(
            args.vencidos, leer_catalogo_invima_vencidos, "Vencidos"
        ),
        df_invima_otros_estados=_cargar_auxiliar_opcional(
            args.otros_estados, leer_catalogo_invima_otros_estados, "Otros Estados"
        ),
        df_invima_renovacion=_cargar_auxiliar_opcional(
            args.renovacion, leer_catalogo_invima_renovacion, "Tramite de Renovacion"
        ),
    )
    guardar_reporte(auditoria, args.salida, columna_hoja="ESTADO_COHERENCIA")
    print(f"{len(auditoria):,} medicamentos auditados -> {args.salida}")
    print(auditoria["ESTADO_COHERENCIA"].value_counts().to_string())
    for advertencia in auditoria.attrs.get("advertencias", []):
        print(f"AVISO: {advertencia}", file=sys.stderr)


def _agregar_origen_invima(sub: argparse.ArgumentParser) -> None:
    origen = sub.add_mutually_exclusive_group(required=True)
    origen.add_argument("--invima", metavar="XLSX", help="Listado Codigo Unico de Medicamentos Vigentes (.xlsx)")
    origen.add_argument(
        "--api", action="store_true", help="Traer el catalogo vigente en vivo desde la API de Socrata"
    )
    sub.add_argument(
        "--gemma-net", required=True, metavar="ARCHIVO",
        help="Reporte exportado por Gemma Net (.xlsx o .txt)",
    )
    sub.add_argument("--salida", required=True, metavar="XLSX", help="Ruta del .xlsx de salida")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gemma-cum-loader",
        description="Cruza el catalogo INVIMA vigente contra lo cargado en Gemma Net (Pijao Salud).",
    )
    subcomandos = parser.add_subparsers(dest="comando", required=True)

    p_candidatos = subcomandos.add_parser(
        "candidatos", help="Medicamentos de INVIMA que FALTAN por cargar en Gemma Net"
    )
    _agregar_origen_invima(p_candidatos)
    p_candidatos.set_defaults(func=_comando_candidatos)

    p_auditoria = subcomandos.add_parser(
        "auditoria", help="Que tan alineado esta lo YA cargado en Gemma Net frente a INVIMA"
    )
    _agregar_origen_invima(p_auditoria)
    p_auditoria.add_argument("--vencidos", metavar="XLSX", help="Listado CUM Vencidos (.xlsx) -- opcional")
    p_auditoria.add_argument(
        "--renovacion", metavar="XLSX", help="Listado CUM en Tramite de Renovacion (.xlsx) -- opcional"
    )
    p_auditoria.add_argument(
        "--otros-estados", metavar="XLSX", help="Listado CUM Otros Estados (.xlsx) -- opcional"
    )
    p_auditoria.set_defaults(func=_comando_auditoria)

    args = parser.parse_args(argv)

    for ruta in [getattr(args, "invima", None), args.gemma_net]:
        if ruta is not None and not Path(ruta).exists():
            parser.error(f"no existe el archivo: {ruta}")

    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
