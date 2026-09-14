# Diseño — Servicio persistente, listados desde una carpeta del servidor y login con usuarios de GemaNet

- **Fecha:** 2026-09-14 · **Autor:** Claude Code (a petición del coordinador TIC)
- **Estado:** aprobado por el usuario en conversación (opciones A / carpeta del servidor con API deshabilitada / A / A); en implementación.
- **Rama:** `feature/servidor-login-listados` (sale de `main` ya fusionado con `fix/calidad-descripcion-criterios`).
- **Petición literal:** (1) que el proyecto persista como Auditoría de Calidades, sin arrancarlo a mano; (2) quitar la posibilidad de "subir" el archivo de INVIMA: se consume directo de una ruta del servidor; (3) login que reutilice la tabla `usuario` de Tableros_BI, exactamente como lo hace Auditoría de Calidades.

## 1. Decisiones (todas confirmadas por el usuario)

| # | Decisión | Razón |
|---|---|---|
| D1 | La app se expone a la red de la oficina en **un solo puerto, 8870**: la API FastAPI sirve además el frontend compilado (`frontend/dist`). | Otras áreas la van a usar; un solo origen evita CORS y un segundo servidor (Vite) en producción. |
| D2 | Los 4 listados de INVIMA se leen de una **carpeta del servidor** configurable con `INVIMA_LISTADOS_DIR` (defecto `~/gemanet/invima`). Nada vive en `data/` del repo. | Es el punto que `almacen_local.py` ya documentaba como "lo único que hay que cambiar para producción". |
| D3 | La fuente **API (Socrata) queda deshabilitada, no borrada**: `FUENTES_HABILITADAS = ("archivos",)`. El botón "Actualizar ahora" no pregunta. | El usuario: "maybe later it will work". Reactivar es una constante. |
| D4 | Login = **autenticación + módulos**, reutilizando `administrativo.usuario`, `aud_app_login_intento`, `aud_app_modulo` y `aud_app_usuario_modulo` de Tableros_BI. Se registra el módulo **`CUMS`**; los admins del ERP (`sw_administrador = 1`) entran sin módulo; el resto necesita el módulo, que se asigna desde `/admin/permisos` del dashboard de Auditoría de Calidades. | "Exactamente como Auditoría de Calidades", sin construir páginas de administración aquí. |
| D5 | Persistencia con **systemd --user** (dos unidades, `Restart=on-failure`, `EnvironmentFile`), más `loginctl enable-linger` una vez. | Reinicio automático ante fallo, arranque sin sesión abierta, logs en journal. |
| D6 | **Desviación asumida:** los módulos del usuario se re-verifican cada **5 minutos** (marca en la sesión), no en cada petición como el dashboard Flask. | Una pantalla de esta app dispara varias peticiones; cada verificación es un viaje a Tableros_BI por WAN. Un usuario revocado sale en ≤ 5 min. |

## 2. Listados desde el servidor (`src/gemma_cum_loader/ingesta/almacen_local.py`, `fuente_invima.py`, `worker/refresco.py`, `backend/app/routers/refrescar.py`, `frontend/src/refresco-manual.ts`, `api.ts`)

- `CARPETA_DATOS = Path(os.environ.get("INVIMA_LISTADOS_DIR", Path.home() / "gemanet" / "invima"))`, resuelto al importar. Los 4 listados, el export de Gemma Net y la malla se descubren ahí. `descubrir(..., carpeta=...)` sigue aceptando una carpeta explícita (pruebas).
- `fuente_invima.py`: `FUENTES_HABILITADAS = (FUENTE_ARCHIVOS,)`; `FUENTES_VALIDAS` se conserva para no romper importaciones.
- `POST /refrescar?fuente=api` → **422** "La fuente 'api' está deshabilitada". `fuente` por defecto sigue `archivos`.
- `worker/refresco.py::_ciclo`: si la fuente guardada en SQLite no está habilitada, usa `FUENTE_DEFECTO` y lo registra en el log.
- Frontend: el botón pide el refresco directo (`pedirRefresco("archivos")`); el cuadro de elección de fuente se retira (el código de la opción API queda en git).
- No existe endpoint de subida de archivos en la API; no hay nada que quitar allí. `guardar_subida` no se toca (solo la UI Streamlit descartada la usaba).

## 3. Login (`backend/app/auth/`)

### 3.1 Configuración (variables de entorno, sin valores en el repo)

| Variable | Defecto | Uso |
|---|---|---|
| `GEMANET_DB_DSN` | — (obligatoria) | Misma base de siempre; el rol debe poder **insertar** en `aud_app_login_intento` (`aux_consulta_bi_tic` es dueño). |
| `SECRET_KEY` | — (obligatoria) | Firma de la cookie de sesión. Sin ella la API no arranca. |
| `MAX_INTENTOS` | 5 | Fallos antes de bloquear. |
| `BLOQUEO_MINUTOS` | 15 | Ventana del bloqueo. |
| `SESION_HORAS` | 8 | Vida de la sesión. |

Los comodines del hash del ERP (`CLAVE_PREFIJO`, `CLAVE_SUFIJO`) son constantes en código, **idénticas** a `dashboard/app/config.py` del dashboard de Auditoría; `MODULO_APP = "CUMS"`.

### 3.2 Módulos

- `backend/app/auth/config.py` — lectura de entorno y constantes.
- `backend/app/auth/db.py` — `consultar(sql, params)` / `ejecutar(sql, params)` con psycopg 3 sobre `GEMANET_DB_DSN`, **sin** `read_only`, `connect_timeout=10`, `statement_timeout` de 30 s y keepalives (misma lección del dashboard: el enlace cruza WAN/NAT). Una conexión por llamada; el login es infrecuente y la sesión no toca la base.
- `backend/app/auth/servicio.py` — lógica pura, con la base inyectable:
  - `hash_clave(clave)` = `sha256(prefijo + clave + sufijo).hexdigest()`.
  - `autenticar(usuario, clave, origen_ip)` → `Sesion(usuario, nombre, admin)` o lanza `ErrorLogin(codigo, mensaje)` con `codigo` ∈ {`credenciales` (401), `clave_vencida` (403), `sin_modulo` (403), `bloqueado` (429)}. Orden y reglas calcadas de `auth.py` del dashboard: bloqueo por `count(*)` de fallos en la ventana; usuario existe + `sw_activo = 1` + `secrets.compare_digest`; vigencia de clave (`sw_obliga_cambio_clave`, `fecha_proximo_cambio`); registra **cada** intento en `aud_app_login_intento(usuario, origen_ip, exitoso)`.
  - `tiene_modulo(usuario, admin)` → `True` si admin; si no, `EXISTS` en `aud_app_usuario_modulo` × `aud_app_modulo` con `id_modulo = 'CUMS'` y `sw_activo = 1`.
- `backend/app/auth/router.py` — `POST /auth/login` (JSON `{usuario, clave}` → 200 `{usuario, nombre, admin}` y cookie; errores con el `detail` en lenguaje de negocio), `POST /auth/logout` (204), `GET /auth/sesion` (200 con el usuario o 401).
- `backend/app/auth/dependencias.py` — `usuario_actual(request)`: lee la sesión; sin sesión → 401 `"Debe iniciar sesión"`. Si `modulos_verificados_en` tiene más de 5 min, vuelve a llamar `tiene_modulo`; si ya no tiene acceso, borra la sesión y responde 403. Para `POST` exige el encabezado `X-Requested-With: fetch` (defensa CSRF adicional a `SameSite=Lax`).
- `backend/app/main.py` — `SessionMiddleware` (cookie `gemanet_cums_sesion`, `same_site="lax"`, `https_only=False`, `max_age = SESION_HORAS·3600`); todos los routers existentes con `dependencies=[Depends(usuario_actual)]`; `/auth/*` abierto; CORS reducido al origen de Vite (5173) con `allow_credentials=True`; al final, `StaticFiles(frontend/dist, html=True)` en `/` si la carpeta existe (si no, `/` sigue devolviendo el JSON de siempre).
- `ddl/01_modulo_cums.sql` — `INSERT ... ON CONFLICT DO NOTHING` del módulo `CUMS` en `aud_app_modulo`. Se ejecuta una vez con el rol de la app.

### 3.3 Frontend

- `api.ts`: `BASE_URL` por defecto `""` (mismo origen); `.env.development` con `VITE_API_BASE_URL=http://127.0.0.1:8000` para desarrollo; todo `fetch` con `credentials: "include"` y `X-Requested-With: fetch`; un 401 dispara el evento `gemanet:sesion-expirada`.
- `sesion.ts`: al cargar, `GET /auth/sesion`. Sin sesión → pantalla de ingreso a página completa (logo, "Calidades CUMS", "Ingrese con su usuario de GemaNet", usuario, clave, botón, mensaje de error tal cual lo manda el backend). Con sesión → se pinta la app; la barra superior muestra el nombre y un botón "Salir". `gemanet:sesion-expirada` vuelve a la pantalla de ingreso.
- `index.html`: el logo `logo-pijaos.jpg` copiado del dashboard de Auditoría a `frontend/public/`.

## 4. Servicio (`deploy/`)

- `gemanet-cums-worker.service`: `ExecStart=<repo>/.venv/bin/python -m worker.refresco`.
- `gemanet-cums-api.service`: `ExecStart=<repo>/.venv/bin/python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8870`.
- Ambas: `WorkingDirectory=<repo>`, `EnvironmentFile=%h/.config/gemanet_cums/env`, `Restart=on-failure`, `RestartSec=10`, `WantedBy=default.target`.
- `env.example`: las variables de §3.1 más `INVIMA_LISTADOS_DIR`, sin valores.
- `instalar.sh`: crea `~/.config/gemanet_cums/env` (modo 600) tomando `GEMANET_DB_DSN` del shell actual y generando `SECRET_KEY`; crea la carpeta de listados; copia las unidades a `~/.config/systemd/user/`; `daemon-reload`; `enable --now`; imprime el `sudo loginctl enable-linger $USER` que falta y cómo ver logs (`journalctl --user -u gemanet-cums-api -f`).
- `README.md` / `design/operacion.md`: sección "Despliegue en Linux" (arranque, dónde dejar los listados, cómo reiniciar tras un deploy: `npm run build` + `systemctl --user restart gemanet-cums-api`).

## 5. Verificación

- Pruebas nuevas: `tests/test_auth_servicio.py` (hash contra el vector `sha256(prefijo+clave+sufijo)`; 200/401/403 clave vencida/403 sin módulo/429; admin sin módulo entra; se registra cada intento), `tests/test_backend_auth.py` (login deja cookie; ruta protegida sin cookie → 401; con cookie → 200; POST sin encabezado → 403; logout borra; re-verificación de módulo tras 5 min con reloj inyectado), `tests/test_backend_refrescar.py` (`fuente=api` → 422), `tests/test_almacen_local.py` (carpeta desde `INVIMA_LISTADOS_DIR`), `tests/test_backend_main.py` (sirve `index.html` cuando existe `dist`).
- `npx tsc --noEmit` y `npm run build`.
- En vivo: unidades activas, `http://192.168.20.123:8870` muestra el ingreso, un ciclo del worker desde `~/gemanet/invima`, captura de pantalla del ingreso y de una vista. La única escritura en la base durante la verificación: el módulo `CUMS` y una fila de intento fallido.
