"""Backend FastAPI -- Fase 2 de la migracion fuera de Streamlit.

Arranque local:

    uvicorn backend.app.main:app --reload

Solo LEE lo que `worker/` ya calculo (ver `dependencies.py` para la regla
completa) -- nunca ejecuta el pipeline pesado ni habla con Gemma Net/INVIMA
dentro de un request. La unica excepcion, acotada y documentada en su
propio router, es POST /refrescar: escribe una senal para que el WORKER
adelante su corrida, nunca corre el pipeline aca (ver
`routers/refrescar.py`).

Desde el 2026-09-14 (despliegue como servicio en Linux, puerto 8870):

- Toda ruta exige sesion (cookie firmada), salvo `/auth/*`. El login calca
  el del dashboard de Auditoria de Calidades -- ver `backend/app/auth/`.
- Si existe `frontend/dist` (`cd frontend && npm run build`), la API lo
  sirve en `/`: la app entera vive en un solo origen.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.app.auth import config as config_auth
from backend.app.auth import router as auth
from backend.app.auth.dependencias import usuario_actual
from backend.app.routers import (
    admin,
    auditoria,
    cadena_calidad,
    calidades,
    candidatos,
    cargue,
    consulta_detalle,
    descargas,
    refrescar,
    salud,
    universo,
)

# El frontend compilado. Si existe, la API lo sirve en `/`; si no --
# desarrollo con Vite en 5173, o pruebas -- `/` sigue respondiendo el JSON
# de siempre.
RUTA_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

app = FastAPI(
    title="Gemma CUM Loader API",
    description="Lee los snapshots que deja worker/ -- candidatos, auditoria y salud del refresco.",
)

# Sesion en cookie firmada (itsdangerous), HttpOnly, SameSite=Lax. `https_only`
# en False porque la app se sirve por HTTP en la red de la oficina.
app.add_middleware(
    SessionMiddleware,
    secret_key=config_auth.secret_key(),
    session_cookie=config_auth.NOMBRE_COOKIE,
    max_age=config_auth.sesion_horas() * 3600,
    same_site="lax",
    https_only=False,
)

# Solo para desarrollo: Vite en 5173 llama a la API en 8000 con la cookie
# (`credentials: "include"`). En produccion todo es el mismo origen y esto no
# aplica a ninguna peticion.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(auth.router)
# Administracion (permisos del modulo CUMS): exige admin en su propio router.
app.include_router(admin.router)
# Todo lo demas exige sesion (ver backend/app/auth/dependencias.py).
protegido = [Depends(usuario_actual)]
for router in (
    salud.router,
    candidatos.router,
    auditoria.router,
    cadena_calidad.router,
    calidades.router,
    universo.router,
    consulta_detalle.router,
    cargue.router,
    descargas.router,
    refrescar.router,
):
    app.include_router(router, dependencies=protegido)


def montar_frontend(aplicacion: FastAPI, ruta_dist: Path) -> bool:
    """Sirve el frontend compilado en `/` (html=True devuelve index.html en
    la raiz). Va DESPUES de los routers: las rutas de la API ganan. Devuelve
    si monto algo, para que el llamador decida que hacer con `/`."""
    if not (ruta_dist / "index.html").is_file():
        return False
    aplicacion.mount("/", StaticFiles(directory=str(ruta_dist), html=True), name="frontend")
    return True


if not montar_frontend(app, RUTA_DIST):

    @app.get("/")
    def raiz() -> dict[str, str]:
        return {"servicio": "gemma-cum-loader-api", "salud": "/salud", "docs": "/docs"}
