#!/usr/bin/env python3
"""Identifica puntos de fallo en la auditoría"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from worker.almacen_snapshots import leer_tabla
from gemma_cum_loader.auditoria.calidades import calidades_auditoria
from gemma_cum_loader.auditoria.coherencia_invima import EstadoCoherencia

def main():
    print("="*80)
    print("DETECCION DE FALLOS - Ciclo 2")
    print("="*80)

    carpeta = Path("data_runtime/snapshots")
    auditoria = leer_tabla("auditoria", carpeta)

    print("\n[FALLO 1] Cobertura de calidades incompleta")
    print("-" * 80)
    cals = calidades_auditoria(auditoria)
    total_en_cals = sum(c.medicamentos for c in cals)
    activos = (auditoria["ACTIVO"].fillna("").astype(str).str.upper() == "SI").sum()

    print(f"Medicamentos activos totales: {activos:,}")
    print(f"Medicamentos en calidades: {total_en_cals:,}")
    print(f"Diferencia: {activos - total_en_cals:,}")
    print(f"Cobertura: {total_en_cals/activos*100:.1f}%")

    if total_en_cals != activos:
        print(f"\n[PROBLEMA] Hay {activos - total_en_cals:,} medicamentos activos que NO estan en calidades")
        activos_mask = auditoria["ACTIVO"].fillna("").astype(str).str.upper() == "SI"
        estados_activos = auditoria[activos_mask]["ESTADO_COHERENCIA"].value_counts()
        print("\nDistribucion de estados en activos:")
        for estado, cnt in estados_activos.items():
            print(f"  {estado}: {cnt:,}")

    print("\n[FALLO 2] Overlap de medicamentos en calidades")
    print("-" * 80)

    # Buscar duplicados
    todas_filas = []
    for cal in cals:
        if len(cal.df_tabla) > 0 and "CODIGO_INTERNO" in cal.df_tabla.columns:
            todas_filas.append((cal.nombre, cal.df_tabla["CODIGO_INTERNO"].tolist()))

    codigos_por_calidad = {}
    for cal_nombre, codigos in todas_filas:
        for codigo in codigos:
            if codigo not in codigos_por_calidad:
                codigos_por_calidad[codigo] = []
            codigos_por_calidad[codigo].append(cal_nombre)

    duplicados = {k: v for k, v in codigos_por_calidad.items() if len(v) > 1}
    print(f"Medicamentos en multiples calidades: {len(duplicados):,}")

    if duplicados:
        print("\nPrimeros 5 ejemplos de overlap:")
        for codigo, calidades in list(duplicados.items())[:5]:
            print(f"  {codigo}: {', '.join(calidades)}")

    print("\n[FALLO 3] Medicamentos ancestrales (CLASIFICADO)")
    print("-" * 80)
    ancestrales = (auditoria["CLASIFICADO"] == "Medicamento Ancestral").sum()
    print(f"Medicamentos ancestrales totales: {ancestrales:,}")

    estado_ancestral = auditoria[auditoria["CLASIFICADO"] == "Medicamento Ancestral"]["ESTADO_COHERENCIA"].value_counts()
    print("\nEstados de medicamentos ancestrales:")
    for estado, cnt in estado_ancestral.items():
        print(f"  {estado}: {cnt:,}")

    print("\n[FALLO 4] Medicamentos con ACTIVO pero NO en calidades")
    print("-" * 80)

    activos_mask = auditoria["ACTIVO"].fillna("").astype(str).str.upper() == "SI"
    codigos_activos = set(auditoria[activos_mask]["CODIGO_INTERNO"].unique())
    codigos_en_cals = set()

    for cal in cals:
        if "CODIGO_INTERNO" in cal.df_tabla.columns:
            codigos_en_cals.update(cal.df_tabla["CODIGO_INTERNO"].unique())

    faltantes = codigos_activos - codigos_en_cals
    print(f"Medicamentos activos que faltan en calidades: {len(faltantes):,}")

    if faltantes:
        print("\nPrimeros 5 ejemplos de medicamentos faltantes:")
        faltantes_df = auditoria[auditoria["CODIGO_INTERNO"].isin(list(faltantes)[:5])]
        for _, fila in faltantes_df.iterrows():
            codigo = fila.get("CODIGO_INTERNO", "N/A")
            estado = fila.get("ESTADO_COHERENCIA", "N/A")
            activo = fila.get("ACTIVO", "N/A")
            print(f"  {codigo}: ACTIVO={activo}, ESTADO={estado}")

    print("\n[FALLO 5] Inconsistencia en fechas de medicamentos vencidos")
    print("-" * 80)

    vencidos_mask = auditoria["ESTADO_COHERENCIA"] == EstadoCoherencia.VENCIDO_EN_INVIMA.value
    vencidos = auditoria[vencidos_mask]

    con_inconsistencia = (vencidos["INCONSISTENCIA_FECHAS_ACTIVO"] != "").sum()
    print(f"Medicamentos vencidos: {len(vencidos):,}")
    print(f"Vencidos con inconsistencia de fecha: {con_inconsistencia:,}")

    if con_inconsistencia > 0:
        print("\nPrimeros 3 ejemplos:")
        ejemplos = vencidos[vencidos["INCONSISTENCIA_FECHAS_ACTIVO"] != ""].head(3)
        for _, fila in ejemplos.iterrows():
            codigo = fila.get("CODIGO_INTERNO", "N/A")
            inconsistencia = str(fila.get("INCONSISTENCIA_FECHAS_ACTIVO", ""))[:60]
            print(f"  {codigo}: {inconsistencia}")

    print("\n[FALLO 6] Campos con diferencia pero estado CORRECTO")
    print("-" * 80)

    contradiccion = (
        (auditoria["ESTADO_COHERENCIA"] == EstadoCoherencia.CORRECTO.value) &
        (auditoria["CAMPOS_CON_DIFERENCIA"] != "")
    ).sum()

    print(f"Medicamentos con estado=CORRECTO pero CAMPOS_CON_DIFERENCIA no vacio: {contradiccion:,}")

    if contradiccion > 0:
        print("\nEsto es una CONTRADICCION LOGICA - revisar la logica de estados")
        ejemplos = auditoria[
            (auditoria["ESTADO_COHERENCIA"] == EstadoCoherencia.CORRECTO.value) &
            (auditoria["CAMPOS_CON_DIFERENCIA"] != "")
        ].head(2)
        for _, fila in ejemplos.iterrows():
            print(f"  {fila.get('CODIGO_INTERNO')}: campos={fila.get('CAMPOS_CON_DIFERENCIA')[:50]}")

    print("\n" + "="*80)
    print("RESUMEN DE FALLOS DETECTADOS")
    print("="*80)
    print(f"[1] Cobertura incompleta: {activos - total_en_cals:,} medicamentos sin clasificar")
    print(f"[2] Overlap de medicamentos: {len(duplicados):,} en multiples calidades")
    print(f"[3] Medicamentos ancestrales: solo {ancestrales:,}")
    print(f"[4] Medicamentos activos sin calidad: {len(faltantes):,}")
    print(f"[5] Vencidos con inconsistencia: {con_inconsistencia:,}")
    print(f"[6] Contradicciones de estado: {contradiccion:,}")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
