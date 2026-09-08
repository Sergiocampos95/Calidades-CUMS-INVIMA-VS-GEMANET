"""Abre la app real en un navegador y guarda una captura -- para VERIFICAR en
pantalla, no solo contra la API.

Por que existe
--------------
Durante toda la sesion del 2026-09-08 se verificaron cifras contra el backend y
la suite, pero nunca la pantalla, y ahi se escondieron varios defectos que solo
se ven mirando: un banner que gritaba CRITICO tres lineas encima de su propia
fila "coincide", un veredicto que decia "falta actualizar" sobre una fecha
imposible, y columnas del snapshot entero volcadas en una tabla de 6. Todos
salieron de una captura del usuario, no de una prueba.

Usa MICROSOFT EDGE, que ya esta instalado (`channel="msedge"`), en vez de bajar
el chromium de Playwright: son ~150 MB que no hacen falta en una maquina que ya
tiene un navegador Chromium.

Uso
---
    .venv\\Scripts\\python.exe scripts\\ver_app.py                     # portada
    .venv\\Scripts\\python.exe scripts\\ver_app.py auditoria priorizar
    .venv\\Scripts\\python.exe scripts\\ver_app.py invima --texto
    .venv\\Scripts\\python.exe scripts\\ver_app.py auditoria entender --tema oscuro

    # Consultar un CUM concreto en "Consultar INVIMA":
    .venv\\Scripts\\python.exe scripts\\ver_app.py invima --cum 20055681-1

Secciones y sub-vistas: las declara `SECCIONES` en `frontend/src/main.ts`.

    resumen    principal | metodo | detalle
    decision   bandeja
    cargue     estructura | excel
    invima     unica
    auditoria  priorizar | entender | explorar | cadena

La captura sale en `data_runtime/capturas/`, que esta en .gitignore.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

URL = "http://localhost:5173"
CARPETA = RAIZ / "data_runtime" / "capturas"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("seccion", nargs="?", help="id de seccion (ver SECCIONES en main.ts)")
    ap.add_argument("sub", nargs="?", help="id de sub-vista")
    ap.add_argument("--cum", help="codigo a consultar en la vista 'invima'")
    ap.add_argument("--texto", action="store_true", help="ademas, volcar el texto visible")
    ap.add_argument("--tema", choices=("claro", "oscuro"), help="forzar tema")
    ap.add_argument("--ancho", type=int, default=1600)
    ap.add_argument("--alto", type=int, default=1000)
    ap.add_argument("--completa", action="store_true", help="capturar la pagina entera")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[X] Falta playwright. Instalalo con:")
        print("    .venv\\Scripts\\python.exe -m pip install playwright")
        return 1

    CARPETA.mkdir(parents=True, exist_ok=True)
    nombre = "-".join(p for p in (args.seccion, args.sub) if p) or "portada"
    destino = CARPETA / f"{nombre}-{datetime.now():%H%M%S}.png"

    with sync_playwright() as p:
        # channel="msedge": el navegador que ya esta en la maquina.
        navegador = p.chromium.launch(channel="msedge", headless=True)
        pagina = navegador.new_page(viewport={"width": args.ancho, "height": args.alto})
        # Los errores de la consola del navegador se imprimen: un fallo de JS
        # deja la vista a medias y sin esto la captura sale "vacia" sin decir
        # por que.
        errores: list[str] = []
        pagina.on("pageerror", lambda e: errores.append(str(e)))
        pagina.on(
            "console",
            lambda m: errores.append(f"console.{m.type}: {m.text}") if m.type == "error" else None,
        )

        pagina.goto(URL, wait_until="networkidle", timeout=30_000)

        if args.tema:
            # El toggle cicla; se fija el atributo directo para no depender de
            # en que estado estaba.
            valor = "dark" if args.tema == "oscuro" else "light"
            pagina.evaluate(f"document.documentElement.setAttribute('data-theme', '{valor}')")

        if args.seccion:
            pagina.click(f"[data-seccion='{args.seccion}']")
            pagina.wait_for_timeout(400)
        if args.sub:
            pagina.click(f"[data-sub='{args.sub}']")
            pagina.wait_for_timeout(400)

        if args.cum:
            campo = pagina.locator("input[type='text']").first
            campo.fill(args.cum)
            # exact=True y acotado a #vista: sin eso, `name="Consultar"` matchea
            # PRIMERO el item del riel "Consultar INVIMA" (tambien es un
            # <button>), y el resultado es una captura con el codigo escrito y
            # ninguna consulta hecha.
            pagina.locator("#vista").get_by_role("button", name="Consultar", exact=True).click()
            # La consulta pega al backend; sin esperar la respuesta se captura
            # la pantalla todavia vacia.
            pagina.wait_for_timeout(1200)

        # networkidle otra vez: las vistas piden su tabla despues de montarse,
        # y capturar antes deja "Cargando..." en la imagen.
        pagina.wait_for_load_state("networkidle", timeout=30_000)
        pagina.wait_for_timeout(600)

        pagina.screenshot(path=str(destino), full_page=args.completa)
        print(f"[OK] {destino}")

        if args.texto:
            texto = pagina.inner_text("body")
            ruta_txt = destino.with_suffix(".txt")
            ruta_txt.write_text(texto, encoding="utf-8")
            print(f"[OK] {ruta_txt}")

        if errores:
            print(f"[!] {len(errores)} error(es) en la consola del navegador:")
            for e in errores[:10]:
                print("   ", e[:200])

        navegador.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
