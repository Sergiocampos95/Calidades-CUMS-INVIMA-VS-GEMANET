"""Proceso en segundo plano que refresca los datos de INVIMA/Gemma Net cada
~50 minutos, independiente de que alguien tenga la app abierta.

No vive dentro de `src/gemma_cum_loader/`: es un consumidor de ese paquete,
igual que `ui_revision/app_streamlit.py` -- el core no sabe que este worker
existe. Fase 1 del plan de arquitectura (ver `.claude/plans`, migracion
Streamlit -> FastAPI + frontend propio, 2026-08-27).

Piezas:
- `tareas.py`      la unidad de trabajo: lee INVIMA + Gemma Net, corre el
                    pipeline, escribe el snapshot.
- `almacen_snapshots.py`  escritura/lectura de los snapshots Parquot con
                    puntero atomico -- lo consumen tambien Streamlit y el
                    futuro backend FastAPI.
- `estado.py`      registro de salud del ultimo refresco (SQLite), para
                    poder avisar de forma explicita si el worker esta
                    fallando o los datos quedaron desactualizados.
- `refresco.py`     entrypoint: agenda `tareas.ejecutar_refresco()` cada
                    ~50 min con apscheduler, sin solapar corridas.
"""

from __future__ import annotations
