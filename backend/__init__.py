"""Backend FastAPI -- Fase 2 de la migracion fuera de Streamlit (ver plan
de arquitectura en `.claude/plans`). API delgada de solo lectura sobre los
snapshots que deja `worker/`: nunca ejecuta el pipeline pesado ni habla con
Gemma Net/INVIMA dentro de un request HTTP (ver `backend/app/dependencies.py`
para la regla exacta)."""

from __future__ import annotations
