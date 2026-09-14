# Servicio persistente, listados desde carpeta del servidor y login — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la app corra sola en el servidor Linux en `http://<host>:8870`, lea los 4 listados de INVIMA de una carpeta del servidor, y exija login con los usuarios de GemaNet (tabla `usuario` de Tableros_BI) con el módulo `CUMS`, calcando el login del dashboard de Auditoría de Calidades.

**Architecture:** Tres capas ya existentes se tocan en su borde: `ingesta/almacen_local.py` resuelve la carpeta desde el entorno; el backend FastAPI gana un paquete `backend/app/auth/` (config, base, servicio, router, dependencias), un `SessionMiddleware` con cookie firmada, y sirve `frontend/dist` como estático; el frontend gana una pantalla de ingreso (`sesion.ts`) que envuelve el arranque de `main.ts`. Dos unidades `systemd --user` en `deploy/` mantienen vivos worker y API.

**Tech Stack:** Python 3.12, FastAPI + Starlette `SessionMiddleware` (itsdangerous ya instalado), psycopg 3, pytest; Vite + TypeScript sin framework (Node 24 vía nvm en `~/.nvm/versions/node/v24.21.0/bin`); systemd user units.

## Global Constraints

- Spec aprobado: `.ai/planes/2026-09-14-servidor-login-listados.md`. Decisiones D1–D6 son fijas.
- Código fuente en español sin tildes (identificadores, docstrings, comentarios); textos que ve el usuario con tildes.
- Nunca un secreto en el repo: `SECRET_KEY`, DSN y clave viven en `~/.config/gemanet_cums/env`.
- Comodines del hash: `CLAVE_PREFIJO = '%&3*,'`, `CLAVE_SUFIJO = '@$#)?¿'` — idénticos a `auditoria_calidades/dashboard/app/config.py`.
- Módulo de la app: `CUMS`. Puerto: `8870`. Carpeta por defecto: `~/gemanet/invima`, variable `INVIMA_LISTADOS_DIR`.
- Comandos: `.venv/bin/python -m pytest -q`, `.venv/bin/ruff check src/ tests/ backend/ worker/`, `cd frontend && npx tsc --noEmit && npm run build` con `export PATH="$HOME/.nvm/versions/node/v24.21.0/bin:$PATH"`.
- Commits con trailer `Agente: Claude Code (<modo>)` y `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

### Task 1: Carpeta de listados desde el entorno

**Files:**
- Modify: `src/gemma_cum_loader/ingesta/almacen_local.py` (constante `CARPETA_DATOS`, `descubrir`, `descubrir_todo`, `guardar_descarga`, `guardar_subida`)
- Test: `tests/test_almacen_local.py`

**Interfaces:**
- Produces: `carpeta_datos() -> Path` (lee `INVIMA_LISTADOS_DIR`, defecto `Path.home() / "gemanet" / "invima"`). `CARPETA_DATOS` desaparece (ningún otro módulo la usaba).

- [x] **Step 1: Write the failing test** (al final de `tests/test_almacen_local.py`)

```python
def test_la_carpeta_de_datos_sale_de_la_variable_de_entorno(monkeypatch, tmp_path):
    """Produccion (2026-09-14): los listados viven en una carpeta del servidor
    elegida por operaciones, no dentro del repo."""
    from gemma_cum_loader.ingesta.almacen_local import carpeta_datos

    monkeypatch.setenv("INVIMA_LISTADOS_DIR", str(tmp_path))
    assert carpeta_datos() == tmp_path


def test_sin_variable_la_carpeta_es_gemanet_invima_en_el_home(monkeypatch):
    from pathlib import Path

    from gemma_cum_loader.ingesta.almacen_local import carpeta_datos

    monkeypatch.delenv("INVIMA_LISTADOS_DIR", raising=False)
    assert carpeta_datos() == Path.home() / "gemanet" / "invima"


def test_descubrir_usa_la_carpeta_del_entorno_cuando_no_le_pasan_una(monkeypatch, tmp_path):
    from gemma_cum_loader.ingesta.almacen_local import descubrir

    monkeypatch.setenv("INVIMA_LISTADOS_DIR", str(tmp_path))
    _crear(tmp_path, "ListadoCodigoUnicoVigentes2026.xlsx")
    assert descubrir("invima_vigentes").nombre == "ListadoCodigoUnicoVigentes2026.xlsx"
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -q tests/test_almacen_local.py -k "carpeta or entorno"`
Expected: FAIL, `ImportError: cannot import name 'carpeta_datos'`.

- [x] **Step 3: Write minimal implementation**

En `almacen_local.py` reemplazar el bloque `CARPETA_DATOS = RAIZ / "data"` y su comentario de "LIMITACION CONOCIDA" por:

```python
import os

RAIZ = Path(__file__).resolve().parents[3]
VARIABLE_CARPETA = "INVIMA_LISTADOS_DIR"


def carpeta_datos() -> Path:
    """La carpeta del servidor donde operaciones deja los 4 listados de INVIMA
    (y donde el worker busca ademas el export de Gemma Net y la malla).

    Hasta el 2026-09-14 era `data/` dentro del repo -- limitacion asumida
    mientras cada analista corria la app en su maquina. En produccion la app
    corre como servicio en Linux y la usan otras areas, asi que la carpeta la
    elige operaciones con `INVIMA_LISTADOS_DIR`; sin la variable se usa
    `~/gemanet/invima`, que existe sin permisos especiales. Se lee en cada
    llamada (no al importar) para que las pruebas puedan cambiarla sin
    recargar el modulo. Es el UNICO punto que sabe de donde salen los
    archivos: el resto del flujo solo recibe rutas."""
    configurada = os.environ.get(VARIABLE_CARPETA, "").strip()
    return Path(configurada) if configurada else Path.home() / "gemanet" / "invima"
```

y en `descubrir`, `descubrir_todo`, `guardar_descarga`, `guardar_subida` cambiar `carpeta if carpeta is not None else CARPETA_DATOS` (y `carpeta or CARPETA_DATOS`) por `carpeta if carpeta is not None else carpeta_datos()`.

- [x] **Step 4: Run tests** — `.venv/bin/python -m pytest -q tests/test_almacen_local.py tests/test_fuente_invima.py tests/test_worker_tareas.py` → PASS. `grep -rn CARPETA_DATOS src backend worker tests` → sin resultados.

- [x] **Step 5: Commit** — `git commit -m "Listados de INVIMA desde una carpeta del servidor (INVIMA_LISTADOS_DIR)"`.

---

### Task 2: Fuente API deshabilitada

**Files:**
- Modify: `src/gemma_cum_loader/ingesta/fuente_invima.py` (constantes), `backend/app/routers/refrescar.py` (`pedir_refresco`), `worker/refresco.py` (`_ciclo`)
- Test: `tests/test_backend_refrescar.py`, `tests/test_fuente_invima.py`

**Interfaces:**
- Produces: `FUENTES_HABILITADAS: tuple[str, ...] = (FUENTE_ARCHIVOS,)` en `fuente_invima.py`.

- [x] **Step 1: Failing tests**

`tests/test_backend_refrescar.py`:
```python
def test_la_fuente_api_esta_deshabilitada(tmp_path):
    """Decision del usuario (2026-09-14): los listados se leen de la carpeta del
    servidor; la API queda en el codigo para cuando vuelva a servir."""
    cliente, ruta = _cliente(tmp_path)
    try:
        registrar_latido_worker(ruta)
        r = cliente.post("/refrescar?fuente=api")
        assert r.status_code == 422
        assert "deshabilitada" in r.json()["detail"]
        assert hay_solicitud_pendiente(ruta) is False
    finally:
        app.dependency_overrides.clear()
```
`tests/test_fuente_invima.py`:
```python
def test_solo_los_archivos_estan_habilitados():
    from gemma_cum_loader.ingesta.fuente_invima import FUENTE_ARCHIVOS, FUENTES_HABILITADAS, FUENTES_VALIDAS

    assert FUENTES_HABILITADAS == (FUENTE_ARCHIVOS,)
    assert set(FUENTES_HABILITADAS) <= set(FUENTES_VALIDAS)
```

- [x] **Step 2: Run** → FAIL (`ImportError` / 202 en vez de 422).

- [x] **Step 3: Implementation**

`fuente_invima.py`, tras `FUENTES_VALIDAS`:
```python
# Las fuentes que se pueden PEDIR hoy. La API (Socrata) queda deshabilitada
# -- decision del usuario (2026-09-14): la app corre como servicio y lee los
# listados de una carpeta del servidor; "Consultar INVIMA" sigue sin procesar
# el JSON, asi que ofrecerla solo produciria snapshots que esa vista
# contradice. Se conserva el codigo y FUENTES_VALIDAS: reactivarla es volver
# a ponerla aqui.
FUENTES_HABILITADAS = (FUENTE_ARCHIVOS,)
```
`refrescar.py::pedir_refresco`, tras la validación de `FUENTES_VALIDAS`:
```python
    if fuente not in FUENTES_HABILITADAS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"La fuente '{fuente}' esta deshabilitada. Los listados de INVIMA se leen "
                "de la carpeta del servidor (INVIMA_LISTADOS_DIR)."
            ),
        )
```
(importar `FUENTES_HABILITADAS` junto a `FUENTE_DEFECTO, FUENTES_VALIDAS`).

`worker/refresco.py::_ciclo`, tras leer `fuente`:
```python
    if fuente not in FUENTES_HABILITADAS:
        _log.warning("La fuente '%s' guardada esta deshabilitada; se usa '%s'.", fuente, FUENTE_DEFECTO)
        fuente = FUENTE_DEFECTO
```
(importar `FUENTES_HABILITADAS` desde `gemma_cum_loader.ingesta.fuente_invima`).

- [x] **Step 4: Run** `.venv/bin/python -m pytest -q tests/test_backend_refrescar.py tests/test_fuente_invima.py tests/test_worker_tareas.py` → PASS.
- [x] **Step 5: Commit** — `"Fuente API de INVIMA deshabilitada: solo listados de la carpeta del servidor"`.

---

### Task 3: Frontend — botón sin pregunta, cliente con credenciales y origen relativo

**Files:**
- Modify: `frontend/src/refresco-manual.ts`, `frontend/src/api.ts`
- Create: `frontend/.env.development`

**Interfaces:**
- Produces: `api.ts` exporta `ENCABEZADOS_FETCH`, dispara `window` evento `gemanet:sesion-expirada` ante 401; `BASE_URL` es `""` en producción.

- [x] **Step 1: `api.ts`**

Reemplazar la línea de `BASE_URL` y la función `obtenerJSON` / `pedirRefresco`:
```ts
// En produccion la API sirve tambien el frontend compilado (mismo origen,
// puerto 8870), asi que la base es RELATIVA. En desarrollo Vite corre en
// 5173 y `.env.development` apunta al uvicorn local.
const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

// Todas las llamadas llevan la cookie de sesion y este encabezado: el backend
// exige `X-Requested-With` en cada POST como segunda defensa contra CSRF
// (un formulario de otro sitio no puede ponerlo). Ver backend/app/auth.
export const ENCABEZADOS_FETCH: Record<string, string> = { "X-Requested-With": "fetch" };

function urlAbsoluta(ruta: string): URL {
  return new URL(`${BASE_URL}${ruta}`, window.location.origin);
}

/** Un 401 en cualquier llamada significa "no hay sesion": se avisa una vez a
 * main.ts (que vuelve a la pantalla de ingreso) y se propaga el error para
 * que la vista no pinte datos vacios como si fueran reales. */
function avisarSesionExpirada(status: number): void {
  if (status === 401) window.dispatchEvent(new CustomEvent("gemanet:sesion-expirada"));
}
```
En `obtenerJSON`: `const url = urlAbsoluta(ruta);` y `fetch(url, { signal: controller.signal, credentials: "include", headers: ENCABEZADOS_FETCH })`; tras `if (!respuesta.ok) {` agregar `avisarSesionExpirada(respuesta.status);`.
En `pedirRefresco`: `fetch(urlAbsoluta(`/refrescar?fuente=${fuente}`), { method: "POST", credentials: "include", headers: ENCABEZADOS_FETCH })` y el mismo `avisarSesionExpirada`. Cambiar el defecto a `fuente: FuenteRefresco = "archivos"` y el comentario del tipo: la API está deshabilitada en el backend.
`urlDescarga` sigue devolviendo `${BASE_URL}${ruta}` (con base vacía queda relativo, y el `<a>` manda la cookie solo).

- [x] **Step 2: `refresco-manual.ts`**

Borrar `OPCIONES_FUENTE`, `preguntarFuente` y el delegado de clic del panel; el botón lanza directo:
```ts
  boton.addEventListener("click", () => {
    if (sondeo) return; // ya hay una corrida siendo seguida
    panel.classList.remove("oculto");
    lanzar("archivos");
  });
```
En `lanzar`, el título pasa a `Enviando la solicitud… (listados de la carpeta del servidor)`. Encabezado del archivo: nota de que la elección de fuente se retiró el 2026-09-14 (API deshabilitada, ver `FUENTES_HABILITADAS`); el código de la pregunta queda en git.

- [x] **Step 3: `frontend/.env.development`** (se versiona; no lleva secretos):
```
VITE_API_BASE_URL=http://127.0.0.1:8000
```

- [x] **Step 4: Verify** — `cd frontend && npx tsc --noEmit` → sin errores.
- [x] **Step 5: Commit** — `"Frontend: actualizar desde la carpeta del servidor sin preguntar; cliente con credenciales y origen relativo"`.

---

### Task 4: Servicio de autenticación (lógica pura, base inyectable)

**Files:**
- Create: `backend/app/auth/__init__.py`, `backend/app/auth/config.py`, `backend/app/auth/db.py`, `backend/app/auth/servicio.py`
- Test: `tests/test_auth_servicio.py`

**Interfaces:**
- Produces:
  - `config.py`: `CLAVE_PREFIJO`, `CLAVE_SUFIJO`, `MODULO_APP = "CUMS"`, `NOMBRE_COOKIE = "gemanet_cums_sesion"`, `secret_key() -> str` (lanza `RuntimeError` si falta `SECRET_KEY`), `max_intentos() -> int`, `bloqueo_minutos() -> int`, `sesion_horas() -> int`, `REVALIDAR_MODULO_SEGUNDOS = 300`.
  - `db.py`: `class BaseAuth` con `consultar(sql, params=()) -> list[dict]` y `ejecutar(sql, params=()) -> int`; `class ErrorBaseAuth(Exception)`.
  - `servicio.py`: `@dataclass(frozen=True) class Sesion(usuario: str, nombre: str, admin: bool)`; `class ErrorLogin(Exception)` con `.status: int` y `.mensaje: str`; `hash_clave(clave: str) -> str`; `autenticar(base, usuario: str, clave: str, origen_ip: str | None) -> Sesion`; `tiene_modulo(base, usuario: str, admin: bool) -> bool`.

- [x] **Step 1: Failing tests** (`tests/test_auth_servicio.py`)

```python
"""Login calcado de auditoria_calidades/dashboard/app/auth.py: mismas reglas,
mismo orden. La base se inyecta (regla del proyecto: las pruebas nunca tocan
un servicio externo)."""

import hashlib
from datetime import date, timedelta

import pytest

from backend.app.auth.config import CLAVE_PREFIJO, CLAVE_SUFIJO, MODULO_APP
from backend.app.auth.servicio import ErrorLogin, Sesion, autenticar, hash_clave, tiene_modulo


class BaseFalsa:
    """Responde a las 4 consultas del servicio mirando un fragmento del SQL."""

    def __init__(self, usuarios=None, modulos=None, fallos_recientes=0):
        self.usuarios = usuarios or {}
        self.modulos = set(modulos or [])
        self.fallos_recientes = fallos_recientes
        self.intentos = []

    def consultar(self, sql, params=()):
        if "aud_app_login_intento" in sql:
            return [{"n": self.fallos_recientes}]
        if "FROM administrativo.usuario" in sql:
            u = self.usuarios.get(params[0])
            return [u] if u else []
        if "aud_app_usuario_modulo" in sql:
            return [{"tiene": 1}] if (params[0], params[1]) in self.modulos else []
        raise AssertionError(f"consulta inesperada: {sql}")

    def ejecutar(self, sql, params=()):
        assert "aud_app_login_intento" in sql
        self.intentos.append(params)
        return 1


def _usuario(clave="secreta", **extra):
    base = {
        "usuario": "jperez", "clave": hash_clave(clave), "nombre": "Juan", "apellido": "Perez",
        "sw_activo": 1, "sw_administrador": 0, "sw_obliga_cambio_clave": 0,
        "fecha_proximo_cambio": date.today() + timedelta(days=30),
    }
    base.update(extra)
    return base


def test_el_hash_es_sha256_con_los_comodines_del_erp():
    esperado = hashlib.sha256((CLAVE_PREFIJO + "abc" + CLAVE_SUFIJO).encode("utf-8")).hexdigest()
    assert hash_clave("abc") == esperado


def test_credenciales_correctas_con_modulo_devuelven_la_sesion_y_registran_el_intento():
    base = BaseFalsa({"jperez": _usuario()}, modulos={("jperez", MODULO_APP)})
    sesion = autenticar(base, "jperez", "secreta", "10.0.0.1")
    assert sesion == Sesion(usuario="jperez", nombre="Juan Perez", admin=False)
    assert base.intentos == [("jperez", "10.0.0.1", 1)]


def test_clave_incorrecta_es_401_y_queda_registrada_como_fallo():
    base = BaseFalsa({"jperez": _usuario()})
    with pytest.raises(ErrorLogin) as e:
        autenticar(base, "jperez", "otra", "10.0.0.1")
    assert e.value.status == 401
    assert base.intentos == [("jperez", "10.0.0.1", 0)]


def test_usuario_inexistente_o_inactivo_es_401():
    base = BaseFalsa({"jperez": _usuario(sw_activo=0)})
    with pytest.raises(ErrorLogin) as e:
        autenticar(base, "jperez", "secreta", None)
    assert e.value.status == 401
    with pytest.raises(ErrorLogin) as e:
        autenticar(base, "nadie", "secreta", None)
    assert e.value.status == 401


def test_bloqueado_tras_demasiados_fallos_es_429_antes_de_mirar_la_clave():
    base = BaseFalsa({"jperez": _usuario()}, fallos_recientes=5)
    with pytest.raises(ErrorLogin) as e:
        autenticar(base, "jperez", "secreta", None)
    assert e.value.status == 429
    assert base.intentos == []


@pytest.mark.parametrize("extra", [
    {"sw_obliga_cambio_clave": 1},
    {"fecha_proximo_cambio": None},
    {"fecha_proximo_cambio": date.today() - timedelta(days=1)},
])
def test_clave_vencida_u_obligada_a_cambio_es_403_y_se_cambia_en_gemanet(extra):
    base = BaseFalsa({"jperez": _usuario(**extra)}, modulos={("jperez", MODULO_APP)})
    with pytest.raises(ErrorLogin) as e:
        autenticar(base, "jperez", "secreta", None)
    assert e.value.status == 403
    assert "GemaNet" in e.value.mensaje
    assert base.intentos == [("jperez", None, 0)]


def test_sin_el_modulo_cums_es_403_aunque_la_clave_sea_correcta():
    base = BaseFalsa({"jperez": _usuario()})
    with pytest.raises(ErrorLogin) as e:
        autenticar(base, "jperez", "secreta", None)
    assert e.value.status == 403
    assert "CUMS" in e.value.mensaje
    # La clave era correcta: no cuenta para el bloqueo.
    assert base.intentos == [("jperez", None, 1)]


def test_el_administrador_del_erp_entra_sin_modulo():
    base = BaseFalsa({"admin": _usuario(usuario="admin", sw_administrador=1)})
    sesion = autenticar(base, "admin", "secreta", None)
    assert sesion.admin is True
    assert tiene_modulo(base, "admin", admin=True) is True


def test_tiene_modulo_consulta_la_asignacion():
    base = BaseFalsa(modulos={("jperez", MODULO_APP)})
    assert tiene_modulo(base, "jperez", admin=False) is True
    assert tiene_modulo(base, "otro", admin=False) is False
```

- [x] **Step 2: Run** `.venv/bin/python -m pytest -q tests/test_auth_servicio.py` → FAIL (`ModuleNotFoundError: backend.app.auth`).

- [x] **Step 3: Implementation**

`backend/app/auth/__init__.py`:
```python
"""Login con los usuarios de GemaNet, calcado del dashboard de Auditoria de
Calidades (auditoria_calidades/dashboard/app/auth.py): mismo hash, mismas
reglas de vigencia, mismo control de intentos en aud_app_login_intento y el
mismo modelo de modulos (aud_app_modulo / aud_app_usuario_modulo). Ver
.ai/planes/2026-09-14-servidor-login-listados.md."""
```

`backend/app/auth/config.py`:
```python
"""Configuracion del login -- todo por variables de entorno, salvo los comodines
del hash, que son constantes del ERP."""

from __future__ import annotations

import os

# Comodines de Util.getSHA256 del ERP. Tienen que ser IDENTICOS a los de
# auditoria_calidades/dashboard/app/config.py o ningun login funciona. No
# registrar en logs.
CLAVE_PREFIJO = "%&3*,"
CLAVE_SUFIJO = "@$#)?¿"

# El modulo que da acceso a esta app en aud_app_usuario_modulo (ddl/01_modulo_cums.sql).
MODULO_APP = "CUMS"
NOMBRE_COOKIE = "gemanet_cums_sesion"
# Cada cuanto se vuelve a comprobar en la base que el usuario sigue teniendo
# el modulo (decision D6 del plan: no en cada peticion, la base esta al otro
# lado de una WAN y una pantalla dispara varias peticiones).
REVALIDAR_MODULO_SEGUNDOS = 300


def secret_key() -> str:
    valor = os.environ.get("SECRET_KEY", "").strip()
    if not valor:
        raise RuntimeError(
            "Falta SECRET_KEY en el entorno: sin ella no se puede firmar la cookie de sesion. "
            "Ver deploy/env.example."
        )
    return valor


def _entero(nombre: str, defecto: int) -> int:
    try:
        return int(os.environ.get(nombre, "") or defecto)
    except ValueError:
        return defecto


def max_intentos() -> int:
    return _entero("MAX_INTENTOS", 5)


def bloqueo_minutos() -> int:
    return _entero("BLOQUEO_MINUTOS", 15)


def sesion_horas() -> int:
    return _entero("SESION_HORAS", 8)
```

`backend/app/auth/db.py`:
```python
"""Acceso a Tableros_BI para el login. Aparte de `integraciones/gemanet_db.py`
a proposito: aquel abre la conexion en `read_only` como red de seguridad, y el
login necesita ESCRIBIR en aud_app_login_intento (el rol de la app es dueno de
esa tabla). Mismo DSN (GEMANET_DB_DSN). Una conexion por llamada: el login es
infrecuente y la sesion, una vez creada, no toca la base salvo la
re-verificacion del modulo cada 5 min."""

from __future__ import annotations

import os

NOMBRE_VARIABLE_ENTORNO = "GEMANET_DB_DSN"
TIMEOUT_MS = 30_000


class ErrorBaseAuth(Exception):
    """No se pudo consultar la base de usuarios."""


class BaseAuth:
    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn

    def _conectar(self):
        dsn = self._dsn or os.environ.get(NOMBRE_VARIABLE_ENTORNO, "").strip()
        if not dsn:
            raise ErrorBaseAuth(f"No hay credenciales de la base de Gemma Net ({NOMBRE_VARIABLE_ENTORNO}).")
        import psycopg
        from psycopg.rows import dict_row

        # El enlace a Tableros_BI cruza WAN/NAT: sin keepalives una conexion
        # ociosa muere en silencio (leccion del dashboard de Auditoria).
        return psycopg.connect(
            dsn,
            connect_timeout=10,
            options=f"-c statement_timeout={TIMEOUT_MS}",
            keepalives=1,
            keepalives_idle=60,
            keepalives_interval=10,
            keepalives_count=3,
            row_factory=dict_row,
        )

    def consultar(self, sql: str, params: tuple = ()) -> list[dict]:
        try:
            with self._conectar() as con:
                return list(con.execute(sql, params).fetchall())
        except ErrorBaseAuth:
            raise
        except Exception as exc:
            raise ErrorBaseAuth(f"Fallo consultando la base de usuarios: {exc}") from exc

    def ejecutar(self, sql: str, params: tuple = ()) -> int:
        try:
            with self._conectar() as con:
                return con.execute(sql, params).rowcount
        except ErrorBaseAuth:
            raise
        except Exception as exc:
            raise ErrorBaseAuth(f"Fallo escribiendo en la base de usuarios: {exc}") from exc
```

`backend/app/auth/servicio.py`:
```python
"""Reglas del login, sin FastAPI ni base concreta: `base` es cualquier objeto
con `consultar(sql, params)` / `ejecutar(sql, params)` (ver db.py y la
BaseFalsa de las pruebas). El orden de las comprobaciones es el del dashboard
de Auditoria: bloqueo -> credenciales -> vigencia de la clave -> modulo."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import date

from backend.app.auth import config


@dataclass(frozen=True)
class Sesion:
    usuario: str
    nombre: str
    admin: bool


class ErrorLogin(Exception):
    def __init__(self, status: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.status = status
        self.mensaje = mensaje


def hash_clave(clave: str) -> str:
    """sha256(prefijo + clave + sufijo) en hex minuscula -- Util.getSHA256 del ERP."""
    texto = config.CLAVE_PREFIJO + clave + config.CLAVE_SUFIJO
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _bloqueado(base, usuario: str) -> bool:
    filas = base.consultar(
        """SELECT count(*) AS n FROM administrativo.aud_app_login_intento
           WHERE usuario = %s AND exitoso = 0
             AND fecha > now() - make_interval(mins => %s)""",
        (usuario, config.bloqueo_minutos()),
    )
    return int(filas[0]["n"]) >= config.max_intentos()


def _registrar_intento(base, usuario: str, origen_ip: str | None, exitoso: bool) -> None:
    base.ejecutar(
        """INSERT INTO administrativo.aud_app_login_intento (usuario, origen_ip, exitoso)
           VALUES (%s, %s, %s)""",
        (usuario, origen_ip, 1 if exitoso else 0),
    )


def tiene_modulo(base, usuario: str, admin: bool) -> bool:
    """El administrador del ERP entra sin modulo; el resto necesita MODULO_APP
    asignado (lo asigna el admin desde /admin/permisos del dashboard de
    Auditoria de Calidades) y el modulo activo."""
    if admin:
        return True
    filas = base.consultar(
        """SELECT 1 AS tiene
           FROM administrativo.aud_app_usuario_modulo um
           JOIN administrativo.aud_app_modulo m ON m.id_modulo = um.id_modulo
           WHERE um.usuario = %s AND um.id_modulo = %s AND m.sw_activo = 1""",
        (usuario, config.MODULO_APP),
    )
    return bool(filas)


def autenticar(base, usuario: str, clave: str, origen_ip: str | None) -> Sesion:
    usuario = (usuario or "").strip()
    if not usuario or not clave:
        raise ErrorLogin(400, "Ingrese usuario y clave.")

    if _bloqueado(base, usuario):
        raise ErrorLogin(
            429, f"Demasiados intentos fallidos. Espere {config.bloqueo_minutos()} minutos."
        )

    filas = base.consultar(
        """SELECT usuario, clave, nombre, apellido, sw_activo, sw_administrador,
                  sw_obliga_cambio_clave, fecha_proximo_cambio
           FROM administrativo.usuario WHERE usuario = %s""",
        (usuario,),
    )
    u = filas[0] if filas else None
    ok = (
        u is not None
        and u["sw_activo"] == 1
        and secrets.compare_digest(u["clave"] or "", hash_clave(clave))
    )
    if not ok:
        _registrar_intento(base, usuario, origen_ip, False)
        raise ErrorLogin(401, "Usuario o clave incorrectos.")

    # Mismas reglas de vigencia que el ERP: la clave se cambia en GemaNet, no aqui.
    if (
        u["sw_obliga_cambio_clave"] == 1
        or u["fecha_proximo_cambio"] is None
        or u["fecha_proximo_cambio"] < date.today()
    ):
        _registrar_intento(base, usuario, origen_ip, False)
        raise ErrorLogin(403, "Su clave requiere actualización. Cámbiela en GemaNet e intente de nuevo.")

    admin = u["sw_administrador"] == 1
    # La clave era correcta: el intento cuenta como exitoso aunque falte el
    # modulo -- lo que falta es un permiso, no un secreto, y no debe bloquear.
    _registrar_intento(base, usuario, origen_ip, True)
    if not tiene_modulo(base, usuario, admin):
        raise ErrorLogin(
            403,
            f"Su usuario no tiene asignado el módulo {config.MODULO_APP}. "
            "Pídalo al administrador (Auditoría de Calidades › Permisos).",
        )
    nombre = f"{u['nombre'] or ''} {u['apellido'] or ''}".strip()
    return Sesion(usuario=u["usuario"], nombre=nombre, admin=admin)
```

- [x] **Step 4: Run** → PASS (11 pruebas). `ruff check backend/`.
- [x] **Step 5: Commit** — `"Auth: servicio de login calcado del dashboard de Auditoria (hash, bloqueo, vigencia, modulo CUMS)"`.

---

### Task 5: Router de auth, dependencia de sesión y cableado en `main.py`

**Files:**
- Create: `backend/app/auth/router.py`, `backend/app/auth/dependencias.py`, `tests/conftest.py`, `tests/test_backend_auth.py`
- Modify: `backend/app/main.py`, `backend/app/schemas.py`

**Interfaces:**
- Produces: `dependencias.obtener_base() -> BaseAuth` (override en pruebas), `dependencias.usuario_actual(request, base) -> Sesion`, `dependencias.exigir_encabezado_fetch(request)`, `dependencias.ahora()` (reloj inyectable, `time.time`). Router `/auth/login` (POST, JSON `{usuario, clave}` → `UsuarioSesion{usuario,nombre,admin}`), `/auth/logout` (POST → 204), `/auth/sesion` (GET → `UsuarioSesion` o 401). `main.py` exporta `montar_frontend(app, ruta_dist) -> bool` (Task 6).

- [x] **Step 1: `tests/conftest.py`** (nuevo; pytest lo carga antes que los tests)

```python
"""Fixtures compartidas.

`SECRET_KEY` tiene que existir ANTES de importar `backend.app.main` (el
SessionMiddleware firma con ella). Y todas las pruebas del backend que ya
existian llaman a la API sin sesion: se les inyecta una sesion de prueba por
defecto, para que sigan probando lo suyo (tablas, calidades...) y no el login.
Las pruebas de login retiran la inyeccion explicitamente."""

import os

import pytest

os.environ.setdefault("SECRET_KEY", "clave-solo-para-pruebas")

from backend.app.auth.servicio import Sesion  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.auth.dependencias import usuario_actual  # noqa: E402

SESION_DE_PRUEBA = Sesion(usuario="prueba", nombre="Usuario de Prueba", admin=True)


@pytest.fixture(autouse=True)
def _sesion_de_prueba():
    app.dependency_overrides[usuario_actual] = lambda: SESION_DE_PRUEBA
    yield
    app.dependency_overrides.pop(usuario_actual, None)
```

- [x] **Step 2: Failing tests** (`tests/test_backend_auth.py`)

```python
import time

from fastapi.testclient import TestClient

from backend.app.auth import dependencias
from backend.app.auth.dependencias import obtener_base, usuario_actual
from backend.app.main import app
from tests.test_auth_servicio import BaseFalsa, _usuario

ENCABEZADOS = {"X-Requested-With": "fetch"}


def _cliente(base):
    app.dependency_overrides.pop(usuario_actual, None)  # el login de verdad, no la sesion de prueba
    app.dependency_overrides[obtener_base] = lambda: base
    return TestClient(app)


def _limpiar():
    app.dependency_overrides.clear()


def test_sin_sesion_una_ruta_protegida_responde_401():
    cliente = _cliente(BaseFalsa())
    try:
        r = cliente.get("/salud")
        assert r.status_code == 401
        assert "iniciar sesión" in r.json()["detail"]
        assert cliente.get("/auth/sesion").status_code == 401
    finally:
        _limpiar()


def test_login_correcto_deja_cookie_y_abre_las_rutas():
    base = BaseFalsa({"jperez": _usuario()}, modulos={("jperez", "CUMS")})
    cliente = _cliente(base)
    try:
        r = cliente.post("/auth/login", json={"usuario": "jperez", "clave": "secreta"}, headers=ENCABEZADOS)
        assert r.status_code == 200
        assert r.json() == {"usuario": "jperez", "nombre": "Juan Perez", "admin": False}
        assert "gemanet_cums_sesion" in r.cookies
        assert cliente.get("/auth/sesion").json()["usuario"] == "jperez"
        assert cliente.get("/salud").status_code == 200
    finally:
        _limpiar()


def test_login_rechazado_propaga_el_estado_y_el_mensaje():
    cliente = _cliente(BaseFalsa({"jperez": _usuario()}))
    try:
        r = cliente.post("/auth/login", json={"usuario": "jperez", "clave": "mala"}, headers=ENCABEZADOS)
        assert r.status_code == 401
        assert r.json()["detail"] == "Usuario o clave incorrectos."
        assert cliente.get("/auth/sesion").status_code == 401
    finally:
        _limpiar()


def test_post_sin_el_encabezado_fetch_es_403():
    cliente = _cliente(BaseFalsa({"jperez": _usuario()}, modulos={("jperez", "CUMS")}))
    try:
        r = cliente.post("/auth/login", json={"usuario": "jperez", "clave": "secreta"})
        assert r.status_code == 403
        cliente.post("/auth/login", json={"usuario": "jperez", "clave": "secreta"}, headers=ENCABEZADOS)
        assert cliente.post("/refrescar").status_code == 403
    finally:
        _limpiar()


def test_logout_cierra_la_sesion():
    cliente = _cliente(BaseFalsa({"jperez": _usuario()}, modulos={("jperez", "CUMS")}))
    try:
        cliente.post("/auth/login", json={"usuario": "jperez", "clave": "secreta"}, headers=ENCABEZADOS)
        assert cliente.post("/auth/logout", headers=ENCABEZADOS).status_code == 204
        assert cliente.get("/auth/sesion").status_code == 401
    finally:
        _limpiar()


def test_el_modulo_se_revalida_cada_5_minutos_y_un_usuario_revocado_sale(monkeypatch):
    base = BaseFalsa({"jperez": _usuario()}, modulos={("jperez", "CUMS")})
    cliente = _cliente(base)
    try:
        cliente.post("/auth/login", json={"usuario": "jperez", "clave": "secreta"}, headers=ENCABEZADOS)
        base.modulos.clear()  # el admin le quito el modulo
        assert cliente.get("/salud").status_code == 200  # todavia dentro de la ventana
        monkeypatch.setattr(dependencias, "ahora", lambda: time.time() + 301)
        r = cliente.get("/salud")
        assert r.status_code == 403
        assert cliente.get("/auth/sesion").status_code == 401
    finally:
        _limpiar()
```

- [x] **Step 3: Run** → FAIL (`ModuleNotFoundError: backend.app.auth.dependencias`).

- [x] **Step 4: Implementation**

`backend/app/schemas.py`, al final:
```python
class DatosLogin(BaseModel):
    usuario: str
    clave: str


class UsuarioSesion(BaseModel):
    """Lo que la pantalla necesita saber de quien esta adentro."""

    usuario: str
    nombre: str
    admin: bool
```

`backend/app/auth/dependencias.py`:
```python
"""Dependencias FastAPI del login: la base (inyectable), la sesion actual y
la defensa CSRF."""

from __future__ import annotations

import time

from fastapi import Depends, HTTPException, Request, status

from backend.app.auth import config
from backend.app.auth.db import BaseAuth, ErrorBaseAuth
from backend.app.auth.servicio import Sesion, tiene_modulo

CLAVE_SESION = "sesion"
# Reloj inyectable (las pruebas lo adelantan para ejercitar la revalidacion).
ahora = time.time


def obtener_base() -> BaseAuth:
    return BaseAuth()


def exigir_encabezado_fetch(request: Request) -> None:
    """Todo POST tiene que traer `X-Requested-With: fetch`. Un formulario
    enviado desde otro sitio no puede ponerlo, asi que junto con
    SameSite=Lax cierra el CSRF sin token por peticion."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get(
        "x-requested-with", ""
    ).lower() != "fetch":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Petición rechazada: falta el encabezado X-Requested-With.",
        )


def guardar_sesion(request: Request, sesion: Sesion) -> None:
    request.session.clear()
    request.session[CLAVE_SESION] = {
        "usuario": sesion.usuario,
        "nombre": sesion.nombre,
        "admin": sesion.admin,
        "modulo_verificado_en": ahora(),
    }


def borrar_sesion(request: Request) -> None:
    request.session.clear()


def usuario_actual(request: Request, base: BaseAuth = Depends(obtener_base)) -> Sesion:
    """La sesion de la cookie, o 401. Cada REVALIDAR_MODULO_SEGUNDOS vuelve a
    comprobar en la base que el usuario conserva el modulo: si se lo
    quitaron, la sesion se borra y responde 403 (decision D6 del plan)."""
    exigir_encabezado_fetch(request)
    datos = request.session.get(CLAVE_SESION)
    if not datos:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Debe iniciar sesión.")
    sesion = Sesion(usuario=datos["usuario"], nombre=datos["nombre"], admin=bool(datos["admin"]))
    if ahora() - float(datos.get("modulo_verificado_en", 0)) > config.REVALIDAR_MODULO_SEGUNDOS:
        try:
            sigue = tiene_modulo(base, sesion.usuario, sesion.admin)
        except ErrorBaseAuth:
            # Si la base no responde no se expulsa a nadie por eso: se
            # reintenta en la proxima peticion.
            return sesion
        if not sigue:
            borrar_sesion(request)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Su usuario ya no tiene el módulo {config.MODULO_APP}. Vuelva a ingresar.",
            )
        datos["modulo_verificado_en"] = ahora()
        request.session[CLAVE_SESION] = datos
    return sesion
```

`backend/app/auth/router.py`:
```python
"""POST /auth/login, POST /auth/logout, GET /auth/sesion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend.app.auth.db import BaseAuth, ErrorBaseAuth
from backend.app.auth.dependencias import (
    CLAVE_SESION,
    borrar_sesion,
    exigir_encabezado_fetch,
    guardar_sesion,
    obtener_base,
)
from backend.app.auth.servicio import ErrorLogin, autenticar
from backend.app.schemas import DatosLogin, UsuarioSesion

router = APIRouter(prefix="/auth", tags=["sesion"])


@router.post("/login", response_model=UsuarioSesion, dependencies=[Depends(exigir_encabezado_fetch)])
def login(datos: DatosLogin, request: Request, base: BaseAuth = Depends(obtener_base)) -> UsuarioSesion:
    origen_ip = request.client.host if request.client else None
    try:
        sesion = autenticar(base, datos.usuario, datos.clave, origen_ip)
    except ErrorLogin as exc:
        raise HTTPException(status_code=exc.status, detail=exc.mensaje) from exc
    except ErrorBaseAuth as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo consultar la base de usuarios de GemaNet. Intente de nuevo en un momento.",
        ) from exc
    guardar_sesion(request, sesion)
    return UsuarioSesion(usuario=sesion.usuario, nombre=sesion.nombre, admin=sesion.admin)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(exigir_encabezado_fetch)])
def logout(request: Request) -> Response:
    borrar_sesion(request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sesion", response_model=UsuarioSesion)
def sesion_actual(request: Request) -> UsuarioSesion:
    datos = request.session.get(CLAVE_SESION)
    if not datos:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Debe iniciar sesión.")
    return UsuarioSesion(usuario=datos["usuario"], nombre=datos["nombre"], admin=bool(datos["admin"]))
```

`backend/app/main.py` (reemplazo completo del cuerpo tras el docstring, que se actualiza para mencionar el login y el estático):
```python
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

# El frontend compilado (`cd frontend && npm run build`). Si existe, la API lo
# sirve en `/` y la app entera vive en un solo origen (puerto 8870). Si no
# existe -- desarrollo con Vite en 5173, o pruebas -- `/` sigue respondiendo
# el JSON de siempre.
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
```

- [x] **Step 5: Run** `.venv/bin/python -m pytest -q` (toda la suite: las pruebas viejas del backend siguen pasando gracias al conftest) → PASS; `ruff check`.
- [x] **Step 6: Commit** — `"Auth: login por API con cookie de sesion; todas las rutas exigen sesion"`.

---

### Task 6: Prueba del estático

**Files:**
- Test: `tests/test_backend_main.py`

- [x] **Step 1: Test**
```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.main import montar_frontend


def test_sirve_el_index_del_frontend_compilado(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Calidades CUMS</h1>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")
    aplicacion = FastAPI()
    assert montar_frontend(aplicacion, tmp_path) is True
    cliente = TestClient(aplicacion)
    assert "Calidades CUMS" in cliente.get("/").text
    assert cliente.get("/app.js").status_code == 200


def test_sin_dist_no_monta_nada(tmp_path):
    assert montar_frontend(FastAPI(), tmp_path) is False
```
- [x] **Step 2: Run** → PASS (la función ya existe desde la Task 5). Commit junto con la Task 7.

---

### Task 7: Pantalla de ingreso en el frontend

**Files:**
- Create: `frontend/src/sesion.ts`, `frontend/public/logo-pijaos.jpg` (copia de `auditoria_calidades/dashboard/app/static/logo-pijaos.jpg`)
- Modify: `frontend/index.html`, `frontend/src/main.ts`, `frontend/src/estilo.css`, `frontend/src/api.ts` (funciones `sesionActual`, `iniciarSesion`, `cerrarSesion`), `frontend/src/tipos.ts` (`UsuarioSesion`)

- [x] **Step 1: `tipos.ts`**
```ts
/** Espejo de backend/app/schemas.py::UsuarioSesion. */
export interface UsuarioSesion {
  usuario: string;
  nombre: string;
  admin: boolean;
}
```

- [x] **Step 2: `api.ts`** (al final)
```ts
/** GET /auth/sesion -- quien esta adentro, o null si no hay sesion (401). */
export async function sesionActual(): Promise<UsuarioSesion | null> {
  const respuesta = await fetch(urlAbsoluta("/auth/sesion"), { credentials: "include", headers: ENCABEZADOS_FETCH });
  if (respuesta.status === 401) return null;
  if (!respuesta.ok) throw new ErrorAPI(`Error ${respuesta.status} consultando la sesión`, respuesta.status);
  return (await respuesta.json()) as UsuarioSesion;
}

export async function iniciarSesion(usuario: string, clave: string): Promise<UsuarioSesion> {
  const respuesta = await fetch(urlAbsoluta("/auth/login"), {
    method: "POST",
    credentials: "include",
    headers: { ...ENCABEZADOS_FETCH, "Content-Type": "application/json" },
    body: JSON.stringify({ usuario, clave }),
  });
  if (!respuesta.ok) {
    const cuerpo = await respuesta.json().catch(() => null);
    throw new ErrorAPI(cuerpo?.detail ?? `Error ${respuesta.status} al ingresar`, respuesta.status);
  }
  return (await respuesta.json()) as UsuarioSesion;
}

export async function cerrarSesion(): Promise<void> {
  await fetch(urlAbsoluta("/auth/logout"), { method: "POST", credentials: "include", headers: ENCABEZADOS_FETCH });
}
```
(agregar `UsuarioSesion` al import de tipos; `sesionActual` NO dispara `gemanet:sesion-expirada`: el 401 ahi es la respuesta normal antes de ingresar.)

- [x] **Step 3: `sesion.ts`**
```ts
/**
 * Pantalla de ingreso y estado de sesion. Calca el ingreso del dashboard de
 * Auditoria de Calidades (logo, "Ingrese con su usuario de GemaNet"): son las
 * mismas credenciales y el mismo modulo, asi que tiene que verse igual.
 *
 * La app entera (rail, topbar, vistas) no se monta hasta que hay sesion:
 * montarla antes dispararia el sondeo de /salud y cada tabla contra un 401.
 */

import { cerrarSesion, iniciarSesion, sesionActual } from "./api";
import type { UsuarioSesion } from "./tipos";

function esc(valor: unknown): string {
  return String(valor).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}

export { sesionActual };

/** Pinta la pantalla de ingreso en `pantalla` y esconde `shell`. Cuando el
 * usuario entra, invierte la visibilidad y llama `alEntrar`. */
export function mostrarIngreso(
  pantalla: HTMLElement,
  shell: HTMLElement,
  alEntrar: (usuario: UsuarioSesion) => void,
  mensajeInicial = "",
): void {
  shell.classList.add("oculto");
  pantalla.classList.remove("oculto");
  pantalla.innerHTML = `<form class="ingreso" id="form-ingreso" autocomplete="on">
    <img class="ingreso__logo" src="logo-pijaos.jpg" alt="Pijaos Salud EPSI">
    <h1 class="ingreso__titulo">Calidades CUMS</h1>
    <p class="ingreso__sub">Ingrese con su usuario de GemaNet</p>
    <input class="ingreso__campo" name="usuario" type="text" placeholder="Usuario" autocomplete="username" autofocus required>
    <input class="ingreso__campo" name="clave" type="password" placeholder="Clave" autocomplete="current-password" required>
    <p class="ingreso__error${mensajeInicial ? "" : " oculto"}" id="ingreso-error">${esc(mensajeInicial)}</p>
    <button class="btn btn--primario ingreso__boton" type="submit">Ingresar</button>
  </form>`;
  const form = pantalla.querySelector<HTMLFormElement>("#form-ingreso")!;
  const error = pantalla.querySelector<HTMLElement>("#ingreso-error")!;
  const boton = form.querySelector<HTMLButtonElement>("button")!;
  form.addEventListener("submit", (evento) => {
    evento.preventDefault();
    const datos = new FormData(form);
    boton.disabled = true;
    error.classList.add("oculto");
    iniciarSesion(String(datos.get("usuario") ?? ""), String(datos.get("clave") ?? ""))
      .then((usuario) => {
        pantalla.classList.add("oculto");
        pantalla.innerHTML = "";
        shell.classList.remove("oculto");
        alEntrar(usuario);
      })
      .catch((e) => {
        error.textContent = e instanceof Error ? e.message : String(e);
        error.classList.remove("oculto");
        boton.disabled = false;
      });
  });
}

/** Nombre y boton "Salir" en la topbar. */
export function pintarUsuario(contenedor: HTMLElement, usuario: UsuarioSesion, alSalir: () => void): void {
  contenedor.innerHTML = `<span class="usuario__nombre" title="${esc(usuario.usuario)}">${esc(usuario.nombre || usuario.usuario)}</span>
    <button type="button" class="btn btn--suave" id="boton-salir" title="Cerrar la sesión">Salir</button>`;
  contenedor.querySelector("#boton-salir")?.addEventListener("click", () => {
    void cerrarSesion().finally(alSalir);
  });
}
```

- [x] **Step 4: `index.html`** — antes de `<div class="app-shell">` insertar `<div class="pantalla-ingreso oculto" id="pantalla-ingreso"></div>`; en la topbar, antes del botón de tema, insertar `<div class="usuario" id="usuario-sesion"></div>`; `<title>Calidades CUMS</title>`.

- [x] **Step 5: `main.ts`** — reemplazar las tres últimas líneas (`inicializarSalud(); inicializarRefrescoManual(); render();`) por:
```ts
// ---- Arranque con sesion (2026-09-14): nada se monta sin login ----------
import { mostrarIngreso, pintarUsuario, sesionActual } from "./sesion";
import type { UsuarioSesion } from "./tipos";

let appIniciada = false;

function iniciarApp(usuario: UsuarioSesion): void {
  const contenedorUsuario = document.getElementById("usuario-sesion");
  if (contenedorUsuario) pintarUsuario(contenedorUsuario, usuario, () => window.location.reload());
  if (appIniciada) {
    render();
    return;
  }
  appIniciada = true;
  inicializarSalud();
  inicializarRefrescoManual();
  render();
}

function pedirIngreso(mensaje = ""): void {
  const pantalla = document.getElementById("pantalla-ingreso");
  const shell = document.querySelector<HTMLElement>(".app-shell");
  if (!pantalla || !shell) return;
  mostrarIngreso(pantalla, shell, iniciarApp, mensaje);
}

// Cualquier 401 posterior (sesion vencida, modulo retirado) vuelve al ingreso.
window.addEventListener("gemanet:sesion-expirada", () => pedirIngreso("La sesión terminó. Vuelva a ingresar."));

void sesionActual().then(
  (usuario) => (usuario ? iniciarApp(usuario) : pedirIngreso()),
  () => pedirIngreso("No se pudo consultar la sesión. Revise que la API esté arriba."),
);
```
(el `import` va arriba con los demás; `reload` tras salir limpia todo estado en memoria en vez de desmontar vista por vista.)

- [x] **Step 6: `estilo.css`** (al final)
```css
/* Pantalla de ingreso (sesion.ts): misma caja que el dashboard de Auditoria
   de Calidades, con los tokens de esta app. */
.pantalla-ingreso { min-height: 100vh; display: flex; align-items: flex-start; justify-content: center; background: var(--bg); padding-top: 8vh; }
.ingreso { width: min(380px, 92vw); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radio-md); box-shadow: var(--shadow-md); padding: 28px 30px; text-align: center; display: flex; flex-direction: column; gap: 10px; }
.ingreso__logo { height: 90px; width: 90px; object-fit: cover; border-radius: 50%; margin: 0 auto 4px; }
.ingreso__titulo { font-family: var(--font-display); font-size: 1.2rem; font-weight: 800; margin: 0; color: var(--accent-deep); }
.ingreso__sub { margin: 0 0 8px; font-size: 0.82rem; color: var(--text-muted); }
.ingreso__campo { width: 100%; padding: 10px 12px; font-size: 0.9rem; border: 1px solid var(--border); border-radius: var(--radio-sm); background: var(--surface); color: var(--text); }
.ingreso__campo:focus { outline: 2px solid var(--accent); border-color: var(--accent); }
.ingreso__error { margin: 0; font-size: 0.8rem; color: var(--danger); background: var(--danger-soft); padding: 8px 10px; border-radius: var(--radio-sm); }
.ingreso__boton { justify-content: center; width: 100%; }
.usuario { display: flex; align-items: center; gap: 10px; font-size: 0.8rem; color: var(--text-muted); }
.usuario__nombre { font-weight: 600; color: var(--text); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
```
(en `[data-theme="dark"]` los tokens ya cambian; el logo va sobre `--surface`.)

- [x] **Step 7: Verify** — `cd frontend && npx tsc --noEmit && npm run build` → `dist/index.html` existe. `.venv/bin/python -m pytest -q tests/test_backend_main.py` → PASS.
- [x] **Step 8: Commit** — `"Frontend: pantalla de ingreso con usuario de GemaNet; la API sirve el compilado"`.

---

### Task 8: Módulo `CUMS` en la base

**Files:**
- Create: `ddl/01_modulo_cums.sql`

- [x] **Step 1: Archivo**
```sql
-- Modulo de acceso de esta app en el modelo de permisos compartido con el
-- dashboard de Auditoria de Calidades (auditoria_calidades/ddl/07_acceso_modulos.sql).
-- Los administradores del ERP (usuario.sw_administrador = 1) entran sin modulo;
-- el resto lo recibe desde /admin/permisos de ese dashboard.
-- Ejecutar UNA vez con el rol de la app (dueno de aud_app_modulo):
--   psql "$GEMANET_DB_DSN" -f ddl/01_modulo_cums.sql
INSERT INTO administrativo.aud_app_modulo (id_modulo, nombre, sw_activo, descripcion)
VALUES (
    'CUMS',
    'Calidades CUMS (INVIMA vs Gemma Net)',
    1,
    'Auditoria de los medicamentos CUM de Gemma Net contra los listados de INVIMA. App en el puerto 8870.'
)
ON CONFLICT (id_modulo) DO NOTHING;
```
- [x] **Step 2: Ejecutar** con el DSN del entorno; verificar `SELECT id_modulo, sw_activo FROM administrativo.aud_app_modulo` → aparece `CUMS`.
- [x] **Step 3: Commit** — `"DDL: modulo CUMS en aud_app_modulo"`.

---

### Task 9: Unidades systemd, instalador y documentación

**Files:**
- Create: `deploy/gemanet-cums-worker.service`, `deploy/gemanet-cums-api.service`, `deploy/env.example`, `deploy/instalar.sh`
- Modify: `README.md` (nueva sección "Despliegue en Linux"), `design/operacion.md` (arranque/reinicio en el servidor), `CLAUDE.md` (comandos Linux junto a los .ps1), `.gitignore` (nada nuevo: `frontend/dist/` ya está).

- [x] **Step 1: Unidades** (`%h` = home del usuario; la ruta del repo tiene espacio, por eso va entre comillas)

`deploy/gemanet-cums-api.service`:
```ini
[Unit]
Description=Calidades CUMS - API y frontend (puerto 8870)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/home/pijaossaludepsi-tic/Escritorio/CALIDADES CUMS
EnvironmentFile=%h/.config/gemanet_cums/env
ExecStart="/home/pijaossaludepsi-tic/Escritorio/CALIDADES CUMS/.venv/bin/python" -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8870
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```
`deploy/gemanet-cums-worker.service`: igual con `Description=Calidades CUMS - worker de refresco (cada 50 min)` y `ExecStart="/home/pijaossaludepsi-tic/Escritorio/CALIDADES CUMS/.venv/bin/python" -m worker.refresco`.

`deploy/env.example`:
```
# Copiar a ~/.config/gemanet_cums/env (modo 600). deploy/instalar.sh lo hace.
GEMANET_DB_DSN=postgresql://usuario:clave@host:5432/Tableros_BI
SECRET_KEY=
INVIMA_LISTADOS_DIR=/home/pijaossaludepsi-tic/gemanet/invima
MAX_INTENTOS=5
BLOQUEO_MINUTOS=15
SESION_HORAS=8
```

`deploy/instalar.sh`:
```bash
#!/usr/bin/env bash
# Instala y arranca los dos servicios de Calidades CUMS para ESTE usuario.
# Toma GEMANET_DB_DSN del shell actual (exportala antes) y genera SECRET_KEY.
# Idempotente: no pisa un env existente.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$HOME/.config/gemanet_cums"
ENV_FILE="$CONF/env"
UNITS="$HOME/.config/systemd/user"
LISTADOS="${INVIMA_LISTADOS_DIR:-$HOME/gemanet/invima}"

mkdir -p "$CONF" "$UNITS" "$LISTADOS"
if [[ ! -f "$ENV_FILE" ]]; then
  : "${GEMANET_DB_DSN:?Exporta GEMANET_DB_DSN antes de correr este script}"
  umask 077
  {
    echo "GEMANET_DB_DSN=$GEMANET_DB_DSN"
    echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    echo "INVIMA_LISTADOS_DIR=$LISTADOS"
    echo "MAX_INTENTOS=5"
    echo "BLOQUEO_MINUTOS=15"
    echo "SESION_HORAS=8"
  } > "$ENV_FILE"
  echo "Creado $ENV_FILE"
else
  echo "Ya existe $ENV_FILE (no se toca)"
fi
cp "$REPO/deploy/gemanet-cums-api.service" "$REPO/deploy/gemanet-cums-worker.service" "$UNITS/"
systemctl --user daemon-reload
systemctl --user enable --now gemanet-cums-worker.service gemanet-cums-api.service
systemctl --user --no-pager status gemanet-cums-worker.service gemanet-cums-api.service || true
echo
echo "Listados de INVIMA: dejar los 4 .xlsx en $LISTADOS"
echo "Logs: journalctl --user -u gemanet-cums-api -f   (o -u gemanet-cums-worker)"
if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]]; then
  echo "Para que arranquen al reiniciar sin abrir sesion, una sola vez: sudo loginctl enable-linger $USER"
fi
```

- [x] **Step 2: Docs** — README: sección "Despliegue en Linux (servicio)": requisitos (venv, Node vía nvm para `npm run build`), `deploy/instalar.sh`, carpeta de listados, login y módulo `CUMS`, cómo actualizar (`git pull`, `npm run build`, `systemctl --user restart gemanet-cums-api gemanet-cums-worker`). `design/operacion.md`: mismo resumen + tabla síntoma→causa ("401 en todo" = sin `SECRET_KEY`/sesión vencida; "422 fuente deshabilitada"; "worker muere en Leyendo INVIMA" = carpeta vacía). `CLAUDE.md` comandos: los equivalentes Linux.

- [x] **Step 3: Ejecutar `deploy/instalar.sh`** con el DSN exportado; `systemctl --user status` ambos `active (running)`; `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8870/` → 200 (index.html); `curl -s http://127.0.0.1:8870/salud` → 401.
- [x] **Step 4: Commit** — `"Despliegue: unidades systemd --user, instalador y documentacion"`.

---

### Task 10: Verificación en vivo y cierre

- [x] Copiar los 4 listados a `~/gemanet/invima`; `systemctl --user restart gemanet-cums-worker`; esperar `GET /refrescar/progreso` (con sesión) hasta 10 pasos `hecho`; `/salud` → `ok`.
- [x] Con el navegador integrado: abrir `http://127.0.0.1:8870`, captura de la pantalla de ingreso; login incorrecto muestra "Usuario o clave incorrectos."; (si el usuario facilita un usuario de prueba con módulo, captura de una vista con el nombre en la topbar y "Salir").
- [x] `.venv/bin/python -m pytest -q` → todo verde; `ruff`; `tsc`; `npm run build`.
- [x] `/bitacora`: entrada en `.ai/bitacora.jsonl`, `design/operacion.md` alineado; commit final. No fusionar ni subir sin confirmación del usuario.
