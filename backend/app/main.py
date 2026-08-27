"""Backend FastAPI -- Fase 2 de la migracion fuera de Streamlit.

Arranque local:

    uvicorn backend.app.main:app --reload

Solo LEE lo que `worker/` ya calculo (ver `dependencies.py` para la regla
completa) -- nunca ejecuta el pipeline pesado ni habla con Gemma Net/INVIMA
dentro de un request.
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.routers import auditoria, candidatos, salud

app = FastAPI(
    title="Gemma CUM Loader API",
    description="Lee los snapshots que deja worker/ -- candidatos, auditoria y salud del refresco.",
)

app.include_router(salud.router)
app.include_router(candidatos.router)
app.include_router(auditoria.router)


@app.get("/")
def raiz() -> dict[str, str]:
    return {"servicio": "gemma-cum-loader-api", "salud": "/salud", "docs": "/docs"}
