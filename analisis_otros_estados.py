#!/usr/bin/env python3
"""Analiza QUE hay en 'Otros estados activos' y clasifica por tipo"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from worker.almacen_snapshots import leer_tabla
from gemma_cum_loader.auditoria.coherencia_invima import EstadoCoherencia
import pandas as pd

def main():
    print("="*80)
    print("ANALISIS: QUE HAY EN 'OTROS ESTADOS ACTIVOS'")
    print("="*80)

    carpeta = Path("data_runtime/snapshots")
    auditoria = leer_tabla("auditoria", carpeta)

    # Filtrar medicamentos en "Otros estados activos"
    mask_otros = (
        auditoria["ESTADO_COHERENCIA"].isin([
            EstadoCoherencia.VIGENTE_NO_COMERCIALIZADO_INVIMA.value,
            EstadoCoherencia.NO_VALIDA_CONTRA_INVIMA.value,
        ]) &
        (auditoria["ACTIVO"].fillna("").astype(str).str.upper() == "SI")
    )

    otros = auditoria[mask_otros].copy()
    print(f"\nTotal en 'Otros estados activos': {len(otros):,}")

    # 1. Clasificacion por CLASIFICADO
    print("\n[1] Clasificacion por CLASIFICADO (sw_resolucion):")
    clasificados = otros["CLASIFICADO"].value_counts()
    for clase, cnt in clasificados.items():
        print(f"    {clase}: {cnt:,}")

    # 2. Plantas medicinales
    plantas = otros[otros["CLASIFICADO"] == "Planta Medicinal"]
    print(f"\n[2] PLANTAS MEDICINALES: {len(plantas):,}")
    if len(plantas) > 0:
        print("    Ejemplos:")
        for _, fila in plantas.head(3).iterrows():
            print(f"      - {fila.get('CODIGO_INTERNO')}: {fila.get('DESCRIPCION')[:50]}")

    # 3. Medicamentos ancestrales
    ancestrales = otros[otros["CLASIFICADO"] == "Medicamento Ancestral"]
    print(f"\n[3] MEDICAMENTOS ANCESTRALES: {len(ancestrales):,}")
    if len(ancestrales) > 0:
        print("    Ejemplos:")
        for _, fila in ancestrales.head(3).iterrows():
            print(f"      - {fila.get('CODIGO_INTERNO')}: {fila.get('DESCRIPCION')[:50]}")

    # 4. Análisis de CODIGO_INTERNO: ¿tienen expediente-consecutivo?
    print("\n[4] Formato de CODIGO_INTERNO - ¿tienen EXPEDIENTE-CONSECUTIVO?")

    def tiene_expediente_consecutivo(codigo):
        """Valida si tiene formato EXPEDIENTE-CONSECUTIVO: NN-NNNNNNNN-NN"""
        if pd.isna(codigo) or codigo == "":
            return False
        parts = str(codigo).split("-")
        return len(parts) == 3 and all(p.isdigit() for p in parts)

    otros["tiene_exp_cons"] = otros["CODIGO_INTERNO"].apply(tiene_expediente_consecutivo)

    con_expediente = otros[otros["tiene_exp_cons"]].shape[0]
    sin_expediente = otros[~otros["tiene_exp_cons"]].shape[0]

    print(f"    Con EXPEDIENTE-CONSECUTIVO: {con_expediente:,}")
    print(f"    Sin EXPEDIENTE-CONSECUTIVO: {sin_expediente:,}")

    # 5. Ejemplos de SIN expediente-consecutivo
    sin_exp = otros[~otros["tiene_exp_cons"]]
    print("\n[5] Ejemplos de medicamentos SIN EXPEDIENTE-CONSECUTIVO:")
    print(f"    Total: {len(sin_exp):,}")
    if len(sin_exp) > 0:
        print("    Primeros 5:")
        for _, fila in sin_exp.head(5).iterrows():
            codigo = fila.get('CODIGO_INTERNO', "N/A")
            desc = str(fila.get('DESCRIPCION', "N/A"))[:50]
            clasificado = fila.get('CLASIFICADO', "N/A")
            print(f"      - {codigo}: {desc} [{clasificado}]")

    # 6. Analisis de tipo de producto
    print("\n[6] Palabras clave en DESCRIPCION (detecta tipo de producto):")

    palabras_clave = {
        "PLANTA": "Plantas medicinales",
        "SUPLEMENTO": "Suplementos",
        "INSUMO": "Insumos",
        "VARILLA": "Artefactos de cirugía",
        "INJERTO": "Artefactos/Injertos",
        "IMPLANTE": "Implantes",
        "PRÓTESIS": "Prótesis",
        "ARTÍCULO": "Artículos diversos",
    }

    descripcion_upper = otros["DESCRIPCION"].fillna("").astype(str).str.upper()

    for palabra, tipo in palabras_clave.items():
        conts = (descripcion_upper.str.contains(palabra, case=False, na=False)).sum()
        if conts > 0:
            print(f"    {tipo} (contiene '{palabra}'): {conts:,}")

    # 7. Distribucion por ESTADO_COHERENCIA en "Otros"
    print("\n[7] Estados de coherencia en 'Otros estados activos':")
    estados = otros["ESTADO_COHERENCIA"].value_counts()
    for estado, cnt in estados.items():
        print(f"    {estado}: {cnt:,}")

    # 8. ¿Estan en algún listado de INVIMA?
    print("\n[8] ¿Aparecen en listados de INVIMA?")
    sin_correspondencia = (otros["ESTADO_COHERENCIA"] == EstadoCoherencia.SIN_CORRESPONDENCIA_INVIMA.value).sum()
    with_invima = len(otros) - sin_correspondencia
    print(f"    Con correspondencia en INVIMA: {with_invima:,}")
    print(f"    Sin correspondencia (no en INVIMA): {sin_correspondencia:,}")

    print("\n" + "="*80)
    print("CONCLUSIONES PRELIMINARES")
    print("="*80)
    print(f"[A] Total medicamentos en 'Otros': {len(otros):,}")
    print(f"[B] Con EXPEDIENTE-CONSECUTIVO: {con_expediente:,} (son potenciales CUMs)")
    print(f"[C] Sin EXPEDIENTE-CONSECUTIVO: {sin_expediente:,} (son NO-CUMs)")
    print(f"[D] No-CUMs que deberian ir a lista separada: {sin_expediente:,}")
    print(f"[E] Plantas/Ancestrales/Suplementos: {len(plantas) + len(ancestrales):,}")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
