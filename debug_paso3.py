#!/usr/bin/env python3
"""
Script de debug para Paso 3 - Filtro de inactivos

Ejecuta esto localmente para diagnosticar por qué el endpoint HTTP devuelve 182K
en lugar de 33K medicamentos.

Uso:
    python debug_paso3.py
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from worker.almacen_snapshots import leer_tabla
from gemma_cum_loader.auditoria.calidades import calidades_auditoria

def main():
    print("=" * 80)
    print("DEBUG PASO 3 - FILTRO DE INACTIVOS")
    print("=" * 80)

    carpeta = Path("data_runtime/snapshots")

    # Load snapshot
    print("\n1. Cargando snapshot de auditoria...")
    df = leer_tabla("auditoria", carpeta)
    print(f"   Total filas: {len(df)}")

    # Count activos/inactivos
    print("\n2. Contando ACTIVOS/INACTIVOS en el dataset...")
    inactivos = (df["ACTIVO"].fillna("").astype(str).str.upper() != "SI").sum()
    activos = (df["ACTIVO"].fillna("").astype(str).str.upper() == "SI").sum()
    print(f"   Activos (SI): {activos}")
    print(f"   Inactivos (NO): {inactivos}")
    print(f"   Total: {activos + inactivos}")

    # Call calidades_auditoria
    print("\n3. Llamando calidades_auditoria()...")
    cals = calidades_auditoria(df)
    total_en_cals = sum(c.medicamentos for c in cals)
    print(f"   Calidades devueltas: {len(cals)}")
    print(f"   Total medicamentos en calidades: {total_en_cals}")

    # Detail
    print("\n4. Detalles por calidad:")
    for i, cal in enumerate(cals, 1):
        print(f"   {i}. {cal.nombre}: {cal.medicamentos} medicamentos")

    # Verificación
    print("\n5. VERIFICACIÓN:")
    if total_en_cals == activos:
        print(f"   ✓ CORRECTO: {total_en_cals} == {activos} (solo activos)")
    elif total_en_cals == len(df):
        print(f"   ✗ ERROR: {total_en_cals} == {len(df)} (incluye inactivos)")
    else:
        print(f"   ? DESCONOCIDO: {total_en_cals} (esperaba {activos} o {len(df)})")

    print("\n" + "=" * 80)
    print("Si ves CORRECTO: el código está bien, el bug es en el endpoint HTTP")
    print("Si ves ERROR: el código está mal y necesita investigación")
    print("=" * 80)

if __name__ == "__main__":
    main()
