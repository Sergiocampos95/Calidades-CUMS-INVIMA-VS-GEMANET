"""Guarda contra "Failed to construct 'URL': Invalid URL" en el frontend.

Bug real (2026-09-14, reportado por el usuario con captura): `urlDescargaCalidad`
y `urlDescargaEslabon` armaban `new URL("/descargas/...")` SIN base. En
desarrollo BASE_URL era `http://127.0.0.1:8000` y la URL salia absoluta; en
produccion (la API sirve el frontend en el mismo origen, BASE_URL vacio) la
cadena era relativa y `new URL` revento al pintar los botones de descarga --
la tabla de "Casos por calidad" y la de "Trazabilidad H1-H6" quedaban en rojo
aunque la pagina de datos ya habia llegado bien.

Regla que fija esta prueba: TODO `new URL(` del frontend vive en `urlAbsoluta`
(api.ts) y lleva `window.location.origin` como base; los demas modulos la
llaman en vez de construir la URL por su cuenta. No hay suite de TypeScript
en el proyecto (solo `tsc`), y `tsc` no ve esto: la firma es valida con y sin
base. Por eso la guarda vive en pytest, leyendo las fuentes.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ_FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"


def _fuentes_ts() -> list[Path]:
    fuentes = sorted(RAIZ_FRONTEND.rglob("*.ts"))
    assert fuentes, f"no se encontraron fuentes en {RAIZ_FRONTEND}"
    return fuentes


def test_new_url_solo_en_url_absoluta_y_con_origen_como_base():
    apariciones = [
        (ruta.name, numero, linea.strip())
        for ruta in _fuentes_ts()
        for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1)
        if "new URL(" in linea
    ]
    assert len(apariciones) == 1, (
        "solo urlAbsoluta (api.ts) puede construir una URL; el resto la llama. "
        f"Encontrado: {apariciones}"
    )
    archivo, _numero, linea = apariciones[0]
    assert archivo == "api.ts", apariciones
    assert "window.location.origin" in linea, linea


def test_las_descargas_pasan_por_url_absoluta():
    api = (RAIZ_FRONTEND / "api.ts").read_text(encoding="utf-8")
    for funcion in ("urlDescargaCalidad", "urlDescargaEslabon"):
        cuerpo = re.search(rf"export function {funcion}\((?:.|\n)*?\n}}", api)
        assert cuerpo, f"no se encontro {funcion} en api.ts"
        assert "urlAbsoluta(" in cuerpo.group(0), f"{funcion} no usa urlAbsoluta"
