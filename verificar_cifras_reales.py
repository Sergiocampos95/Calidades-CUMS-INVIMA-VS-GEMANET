#!/usr/bin/env python3
"""Verifica cifras REALES de CUMs ACTIVOS (excluyendo IUMs y no-CUMs)"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from worker.almacen_snapshots import leer_tabla
from gemma_cum_loader.auditoria.coherencia_invima import EstadoCoherencia

def es_cum_valido(codigo):
    """NN-N (exactamente 2 partes, ambas numéricas)"""
    if not codigo or codigo == "":
        return False
    parts = str(codigo).split("-")
    return len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()

def main():
    print("="*80)
    print("VERIFICACION DE CIFRAS REALES - Solo CUMs ACTIVOS válidos")
    print("="*80)

    carpeta = Path("data_runtime/snapshots")
    auditoria = leer_tabla("auditoria", carpeta)

    # Filtros base
    activos = auditoria["ACTIVO"].fillna("").astype(str).str.upper() == "SI"
    es_cum = auditoria["CODIGO_INTERNO"].apply(es_cum_valido)

    print(f"\nTotal medicamentos: {len(auditoria):,}")
    print(f"Activos totales: {activos.sum():,}")
    print(f"CUMs válidos totales: {es_cum.sum():,}")
    print(f"CUMs ACTIVOS válidos: {(activos & es_cum).sum():,}")

    print("\n" + "="*80)
    print("CIFRAS CORRECTAS POR CALIDAD (solo CUMs ACTIVOS válidos)")
    print("="*80)

    # 1. Vigentes y correctos
    vigentes_correctos = (
        (auditoria["ESTADO_COHERENCIA"] == EstadoCoherencia.CORRECTO.value) &
        activos &
        es_cum &
        (auditoria["INCONSISTENCIA_FECHAS_ACTIVO"].fillna("").astype(str).str.strip() == "")
    ).sum()
    print(f"\n1. Vigentes y correctos: {vigentes_correctos:,}")

    # 2. CUMs que no existen (solo CUMs, sin IUMs)
    cums_no_existen = (
        (auditoria["ESTADO_COHERENCIA"] == EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value) &
        activos &
        es_cum
    ).sum()
    print(f"2. CUMs que no existen en INVIMA: {cums_no_existen:,}")

    # 3. Registro vencido en INVIMA (solo CUMs ACTIVOS)
    vencidos_invima = (
        (auditoria["ESTADO_COHERENCIA"] == EstadoCoherencia.VENCIDO_EN_INVIMA.value) &
        activos &
        es_cum
    ).sum()
    print(f"3. Registro vencido en INVIMA: {vencidos_invima:,}")

    # 4. En otro estado en INVIMA
    otro_estado = (
        (auditoria["ESTADO_COHERENCIA"] == EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value) &
        activos &
        es_cum
    ).sum()
    print(f"4. En otro estado en INVIMA: {otro_estado:,}")

    # 5. En trámite de renovación
    renovacion = (
        (auditoria["ESTADO_COHERENCIA"] == EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value) &
        activos &
        es_cum
    ).sum()
    print(f"5. En trámite de renovación: {renovacion:,}")

    # 6. Con algún campo distinto
    campos_distintos = (
        (auditoria["CAMPOS_CON_DIFERENCIA"].fillna("").astype(str).str.strip() != "") &
        activos &
        es_cum
    ).sum()
    print(f"6. Con algún campo distinto al de INVIMA: {campos_distintos:,}")

    # 7. Fechas que se contradicen
    fechas_contradicen = (
        (auditoria["INCONSISTENCIA_FECHAS_ACTIVO"].fillna("").astype(str).str.strip() != "") &
        activos &
        es_cum
    ).sum()
    print(f"7. Fechas que se contradicen: {fechas_contradicen:,}")

    # Total CUMs ACTIVOS cubiertos
    total_cums_cubiertos = (
        vigentes_correctos + cums_no_existen + vencidos_invima + otro_estado +
        renovacion + campos_distintos + fechas_contradicen
    )

    print("\n" + "="*80)
    print("RESUMEN")
    print("="*80)
    print(f"CUMs ACTIVOS válidos (NN-N): {(activos & es_cum).sum():,}")
    print(f"Cubiertos en 7 calidades: {total_cums_cubiertos:,}")
    print(f"Diferencia: {(activos & es_cum).sum() - total_cums_cubiertos:,}")

    # Análisis de qué falta
    if total_cums_cubiertos < (activos & es_cum).sum():
        print("\n[ADVERTENCIA] Hay CUMs ACTIVOS no cubiertos. Estados:")
        no_cubiertos = auditoria[activos & es_cum & ~(
            (auditoria["ESTADO_COHERENCIA"].isin([
                EstadoCoherencia.CORRECTO.value,
                EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value,
                EstadoCoherencia.VENCIDO_EN_INVIMA.value,
                EstadoCoherencia.ENCONTRADO_EN_OTRO_ESTADO_INVIMA.value,
                EstadoCoherencia.EN_TRAMITE_RENOVACION_INVIMA.value,
            ]))
        )]
        estados_faltantes = no_cubiertos["ESTADO_COHERENCIA"].value_counts()
        for estado, cnt in estados_faltantes.items():
            print(f"  {estado}: {cnt:,}")

    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()
