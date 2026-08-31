#!/usr/bin/env python3
"""Test completo de todas las funciones de auditoría con ejemplos verificables"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from worker.almacen_snapshots import leer_tabla
from gemma_cum_loader.auditoria.calidades import calidades_auditoria
from gemma_cum_loader.auditoria.coherencia_invima import (
    EstadoCoherencia,
    ACCION_POR_NATURALEZA,
)

def main():
    print("="*80)
    print("TEST COMPLETO DE AUDITORÍA - Ciclo 2")
    print("="*80)

    carpeta = Path("data_runtime/snapshots")

    # 1. CARGAR SNAPSHOT
    print("\n[1] Cargando snapshot de auditoría...")
    auditoria = leer_tabla("auditoria", carpeta)
    print(f"    Total filas: {len(auditoria):,}")

    # 2. VERIFICAR FILTRO ACTIVO
    print("\n[2] VERIFICACIÓN: Filtro ACTIVO=SI")
    activos = (auditoria["ACTIVO"].fillna("").astype(str).str.upper() == "SI").sum()
    inactivos = (auditoria["ACTIVO"].fillna("").astype(str).str.upper() != "SI").sum()
    print(f"    Activos (SI): {activos:,}")
    print(f"    Inactivos (NO): {inactivos:,}")
    print(f"    Total: {len(auditoria):,}")

    # 3. CALIDADES - TODAS LAS DIMENSIONES
    print("\n[3] CALIDADES - 8 dimensiones de calidad:")
    cals = calidades_auditoria(auditoria)
    print(f"    Total calidades: {len(cals)}")
    total_medicamentos = sum(c.medicamentos for c in cals)
    print(f"    Total medicamentos en calidades: {total_medicamentos:,}")
    print(f"    % del catálogo: {total_medicamentos/len(auditoria)*100:.1f}%")

    for i, cal in enumerate(cals, 1):
        print(f"\n    {i}. {cal.nombre}")
        print(f"       Medicamentos: {cal.medicamentos:,} ({cal.porcentaje_del_catalogo:.1f}%)")
        print(f"       Columnas: {len(cal.columnas)}")

        # Ejemplo concreto de 2 filas
        if cal.medicamentos > 0:
            ejemplos = cal.df_tabla.head(2)
            for idx, (_, fila) in enumerate(ejemplos.iterrows(), 1):
                codigo = fila.get("CODIGO_INTERNO", "N/A")
                desc = str(fila.get("DESCRIPCION", "N/A"))[:50]
                print(f"       Ej {idx}: {codigo} - {desc}...")

    # 4. ESTADOS DE COHERENCIA
    print("\n[4] ESTADOS DE COHERENCIA - Distribución:")
    if "ESTADO_COHERENCIA" in auditoria.columns:
        estados = auditoria["ESTADO_COHERENCIA"].value_counts()
        for estado, cantidad in estados.items():
            print(f"    {estado}: {cantidad:,}")

    # 5. NATURALEZA DE HALLAZGOS
    print("\n[5] NATURALEZA DE HALLAZGOS - Categorización:")
    if "NATURALEZA_HALLAZGO" in auditoria.columns:
        naturalezas = auditoria["NATURALEZA_HALLAZGO"].value_counts()
        for naturaleza, cantidad in naturalezas.items():
            if pd.notna(naturaleza) and naturaleza != "":
                accion = ACCION_POR_NATURALEZA.get(naturaleza, "N/A")
                print(f"    {naturaleza}: {cantidad:,}")
                print(f"      >> Accion: {accion}")

    # 6. CAMPOS CON DIFERENCIA
    print("\n[6] CAMPOS CON DIFERENCIA - Inconsistencias:")
    if "CAMPOS_CON_DIFERENCIA" in auditoria.columns:
        con_diff = (auditoria["CAMPOS_CON_DIFERENCIA"] != "").sum()
        print(f"    Medicamentos con diferencias: {con_diff:,}")
        ejemplos = auditoria[auditoria["CAMPOS_CON_DIFERENCIA"] != ""].head(2)
        for idx, (_, fila) in enumerate(ejemplos.iterrows(), 1):
            campos = str(fila.get("CAMPOS_CON_DIFERENCIA", ""))[:60]
            print(f"    Ej {idx}: {fila.get('CODIGO_INTERNO')} - {campos}...")

    # 7. INCONSISTENCIAS DE FECHA
    print("\n[7] INCONSISTENCIAS DE FECHA - Validación temporal:")
    if "INCONSISTENCIA_FECHAS_ACTIVO" in auditoria.columns:
        con_fecha = (auditoria["INCONSISTENCIA_FECHAS_ACTIVO"] != "").sum()
        print(f"    Medicamentos con inconsistencia: {con_fecha:,}")
        ejemplos = auditoria[auditoria["INCONSISTENCIA_FECHAS_ACTIVO"] != ""].head(2)
        for idx, (_, fila) in enumerate(ejemplos.iterrows(), 1):
            inconsistencia = str(fila.get("INCONSISTENCIA_FECHAS_ACTIVO", ""))[:60]
            print(f"    Ej {idx}: {fila.get('CODIGO_INTERNO')} - {inconsistencia}...")

    # 8. CÓDIGOS HUÉRFANOS
    print("\n[8] CÓDIGOS HUÉRFANOS - Medicamentos sin INVIMA:")
    sin_correspondencia = (auditoria["ESTADO_COHERENCIA"] == EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value).sum()
    print(f"    Sin correspondencia INVIMA: {sin_correspondencia:,}")

    # 9. COMPLETITUD
    print("\n[9] COMPLETITUD - Calidad de campos:")
    if "PORCENTAJE_COMPLETITUD_REPORTE" in auditoria.columns:
        completitud_prom = auditoria["PORCENTAJE_COMPLETITUD_REPORTE"].mean()
        print(f"    Promedio completitud: {completitud_prom:.1f}%")
        min_compl = auditoria["PORCENTAJE_COMPLETITUD_REPORTE"].min()
        max_compl = auditoria["PORCENTAJE_COMPLETITUD_REPORTE"].max()
        print(f"    Rango: {min_compl:.1f}% - {max_compl:.1f}%")

    # 10. CLASIFICADO (SW_RESOLUCION)
    print("\n[10] CLASIFICADO (SW_RESOLUCION) - Categorización:")
    if "CLASIFICADO" in auditoria.columns:
        clasificados = auditoria["CLASIFICADO"].value_counts()
        for clasificado, cantidad in clasificados.items():
            if pd.notna(clasificado):
                print(f"    {clasificado}: {cantidad:,}")

    print("\n" + "="*80)
    print("RESUMEN EJECUTIVO")
    print("="*80)
    print(f"[OK] Snapshot analizado: {len(auditoria):,} medicamentos")
    print(f"[OK] Filtro ACTIVO: {activos:,} medicamentos activos en calidades")
    print(f"[OK] Cobertura calidades: {total_medicamentos/len(auditoria)*100:.1f}%")
    print(f"[OK] Calidades disponibles: {len(cals)}")
    print("="*80 + "\n")

if __name__ == "__main__":
    import pandas as pd
    main()
