"""Fixtures compartidas.

`SECRET_KEY` tiene que existir ANTES de importar `backend.app.main` (el
SessionMiddleware firma con ella). Y todas las pruebas del backend que ya
existian llaman a la API sin sesion: se les inyecta una sesion de prueba por
defecto, para que sigan probando lo suyo (tablas, calidades...) y no el login.
Las pruebas de login retiran la inyeccion explicitamente."""

import os

import pytest

os.environ.setdefault("SECRET_KEY", "clave-solo-para-pruebas")

from backend.app.auth.dependencias import usuario_actual
from backend.app.auth.servicio import Sesion
from backend.app.main import app

SESION_DE_PRUEBA = Sesion(usuario="prueba", nombre="Usuario de Prueba", admin=True)


@pytest.fixture(autouse=True)
def _sesion_de_prueba():
    app.dependency_overrides[usuario_actual] = lambda: SESION_DE_PRUEBA
    yield
    app.dependency_overrides.pop(usuario_actual, None)
