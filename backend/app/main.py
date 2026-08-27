"""Backend FastAPI -- Fase 2 de la migracion fuera de Streamlit.

Arranque local:

    uvicorn backend.app.main:app --reload

Solo LEE lo que `worker/` ya calculo (ver `dependencies.py` para la regla
completa) -- nunca ejecuta el pipeline pesado ni habla con Gemma Net/INVIMA
dentro de un request.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.routers import auditoria, candidatos, salud

app = FastAPI(
    title="Gemma CUM Loader API",
    description="Lee los snapshots que deja worker/ -- candidatos, auditoria y salud del refresco.",
)

# Solo para desarrollo local: el frontend (Fase 3, `frontend/`) corre en el
# servidor de Vite (puerto 5173 por defecto) y necesita poder llamar a esta
# API en otro puerto. En produccion esto se acota a la URL real del
# frontend, nunca se deja "*" -- pendiente cuando exista un dominio real.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(salud.router)
app.include_router(candidatos.router)
app.include_router(auditoria.router)


@app.get("/")
def raiz() -> dict[str, str]:
    return {"servicio": "gemma-cum-loader-api", "salud": "/salud", "docs": "/docs"}
