# Mapa del proyecto — para qué sirve cada archivo

Dónde vive cada cosa y por qué está ahí. Si vas a cambiar algo, empezá por
aquí: la mitad de los errores de este proyecto han sido tocar la capa
equivocada.

Complemento de [`reglas_negocio.md`](reglas_negocio.md), que dice **qué**
significan los datos. Este dice **dónde** está el código.

---

## Los dos flujos

No confundirlos: son preguntas distintas y recorren módulos distintos.

| Pregunta | Flujo | Módulos |
|---|---|---|
| Qué medicamentos de INVIMA **faltan** por cargar | **Candidatos** | `armado/`, `validacion/`, `exportacion/` |
| De lo **ya cargado**, qué está mal o desactualizado | **Auditoría** | `auditoria/` |

---

## `src/gemma_cum_loader/` — la lógica de negocio

Sin dependencias de web ni de UI. Es la parte que se puede probar sola.

### `ingesta/` — leer las fuentes

| Archivo | Para qué |
|---|---|
| `invima_reader.py` | Lee los Excel de INVIMA (los 4 listados) |
| `invima_socrata.py` | Lee INVIMA desde la API de datos.gov.co |
| `invima_con_respaldo.py` | Intenta Socrata y **cae al archivo local si falla**. Además cachea cada descarga como parquet |
| `fuente_invima.py` | **Elegir** la fuente: `api` o `archivos`. No es lo mismo que el respaldo — el respaldo reacciona a un fallo, esto es una decisión |
| `gemanet_sql.py` | Lee el reporte de medicamentos desde la base de Gemma Net |
| `almacen_local.py` | Descubre qué archivos hay en `data/` y cuál usar. Tiene las exclusiones que evitan confundir Vigentes con Otros Estados |

### `armado/` — construir los candidatos

| Archivo | Para qué |
|---|---|
| `malla.py` | Arma las filas candidatas a creación desde el catálogo INVIMA vigente |
| `cruce_gemanet.py` | Cruza contra lo que ya existe en Gemma Net. Aquí vive `_DELIMITADORES_CANDIDATOS`, que prueba `\|` primero |
| `reglas_negocio.py` | Deriva los campos que exige el cargue y que no existen en ninguna fuente (edad, topes, copagos) |

### `auditoria/` — comparar lo ya cargado contra INVIMA

| Archivo | Para qué |
|---|---|
| `coherencia_invima.py` | **El corazón del flujo de auditoría.** ~3.000 líneas. Ver desglose abajo |
| `calidades.py` | Las 6 tarjetas de "Entender la calidad del catálogo" y sus secciones |
| `cadena_calidad.py` | La cadena H1..H6, encadenada por teoría de conjuntos |

**Qué hay dentro de `coherencia_invima.py`** (lo que más cuesta encontrar):

| Concepto | Símbolo |
|---|---|
| Mapeo de campos comparados | `_CAMPOS_DIRECTOS` |
| Fechas centinela pasadas / futuras | `FECHAS_CENTINELA`, `ANIO_CENTINELA_SIN_VENCIMIENTO` |
| Veredicto de vigencia y sus mensajes | `_contrastar_vigencia_invima()`, `NOVEDAD_*` |
| Los 5 niveles de prioridad | `clasificar_prioridad_accion()`, `PRIORIDAD_*` |
| Qué se audita y qué se ignora | `filtrar_universo_auditable()` |
| Clasificación de hallazgos | `_clasificar_naturaleza_hallazgo()`, `NATURALEZA_*` |
| Veredicto de exactitud (`ESTADO_COHERENCIA`, `PORCENTAJE_CALIDAD`, el trío `_GEMANET/_INVIMA/_VALIDACION`) | `auditar_coherencia()` — mecanismo completo, verificado línea por línea, en [`mecanismos/auditoria_coherencia.md`](mecanismos/auditoria_coherencia.md) |

### El resto

| Archivo | Para qué |
|---|---|
| `catalogos/resolver.py` | Cascada `exacto → alias → fuzzy → sin_resolver`. **100 % determinística**, sin red |
| `catalogos/fuentes.py` | De dónde salen los catálogos (base de Gemma Net, con respaldo a CSV) |
| `catalogos/ia_client.py` | **La IA solo traduce** un motivo técnico a lenguaje de negocio. Nunca decide |
| `validacion/reglas.py` | Motor por filas: acepta / rechaza / descarta / cuarentena |
| `exportacion/cargue.py` | El Excel final de cargue |
| `exportacion/estructura_cargue.py` | La plantilla que exige el SOP |
| `normaliza/codigos.py` | `PATRON_CUM`, `PATRON_ATC`, `clasificar_codigos()` |
| `normaliza/texto.py` | Normalización para comparar (tildes, mayúsculas, espacios) |
| `pipeline.py` | Orquestación end-to-end |
| `cli.py` | Correr los dos flujos sin abrir la UI |
| `config.py` | Constantes compartidas |

---

## `worker/` — el proceso que refresca los datos

Proceso **separado** del backend. Se arranca con `python -m worker.refresco`.

| Archivo | Para qué |
|---|---|
| `refresco.py` | Entrypoint. Agenda el ciclo cada 50 min y vigila solicitudes manuales cada 5 s |
| `tareas.py` | `ejecutar_refresco()`: leer → procesar → auditar → guardar snapshot. **Nunca lanza excepción**: registra `ESTADO_ERROR` y devuelve el estado |
| `almacen_snapshots.py` | Escribe y lee los Parquet. `COLUMNAS_ESPERADAS`, `desfases_de_esquema()` |
| `estado.py` | SQLite de salud: último refresco, progreso paso a paso, solicitud manual, **latido del worker** |

**Cómo se comunican backend y worker.** No hay broker ni segundo servidor HTTP:
una tabla `control` en `data_runtime/estado_worker.sqlite3`.

| Clave | Quién escribe | Quién lee |
|---|---|---|
| `solicitud_pendiente` | Backend (`POST /refrescar`) | Worker, cada 5 s |
| `fuente_refresco` | Backend | Worker, al arrancar el ciclo |
| `latido_worker` | Worker, cada 5 s | Backend, para saber si hay alguien vivo |

⚠️ **`attrs` de pandas no se persiste en Parquet.** Las advertencias que
calcula el pipeline (`advertencias_calidad`) se pierden al escribir el
snapshot. Es una limitación conocida, no un bug reciente.

---

## `backend/app/` — la API

FastAPI en el puerto 8000. **No** ejecuta el pipeline: solo lee los snapshots
que dejó el worker y aplica máscaras vectorizadas.

| Archivo | Para qué |
|---|---|
| `routers/auditoria.py` | "Priorizar lo que requiere acción". `_priorizables` es el único filtro |
| `routers/calidades.py` | Las 6 tarjetas. **`_tabla_auditoria` (completa) vs `_tabla_auditable` (recortada)** — ver abajo |
| `routers/consulta_detalle.py` | Consulta puntual de un CUM |
| `routers/descargas.py` | xlsx / csv / txt. Sección completa, no la página visible |
| `routers/refrescar.py` | `POST /refrescar` + `GET /refrescar/progreso` |
| `routers/salud.py` | Estado del último refresco, desfases de esquema |
| `routers/candidatos.py`, `cargue.py`, `universo.py`, `cadena_calidad.py` | El flujo de candidatos y la cadena H1..H6 |
| `paginacion.py` | **El único** sitio que arma búsqueda + filtro + orden + paginado |
| `exportar.py` | `DELIMITADOR_EXPORTACION` y el adaptador a bytes |
| `dependencies.py` | Rutas de snapshots y de estado |

**La distinción de `calidades.py` que causó un bug real:**

- `_tabla_auditoria` → snapshot **completo**. Lo necesitan las dimensiones de
  auto-consistencia (formato, duplicados, completitud): son detección de basura
  y recortar antes escondería la fila con el problema.
- `_tabla_auditable` → **recortado** al universo auditable. Lo usan las tarjetas.

Mezclarlas hizo que las tarjetas midieran sobre la tabla cruda mientras
"Priorizar" medía sobre el universo filtrado.

---

## `frontend/src/` — la aplicación real

Vite + TypeScript en el 5173. **Es la app**, no un prototipo.

| Archivo | Para qué |
|---|---|
| `main.ts` | `SECCIONES` (único sitio donde se declaran las vistas), navegación, migajas, historial |
| `tabla.ts` | **`TablaFiltrable`: el único componente que dibuja tablas.** No crear un segundo |
| `cache_tablas.ts` | Caché de páginas **versionada por snapshot**. A nivel de módulo, no de instancia |
| `pildoras.ts` | Vocabulario compartido: estados, prioridades, validaciones. Traduce el valor técnico a la etiqueta que se lee |
| `fechas.ts` | Escribe el mes con letras **solo en pantalla**. Formatear no es transformar |
| `refresco-manual.ts` | El botón "Actualizar ahora" y la pregunta de fuente |
| `salud.ts` | El anillo de antigüedad del snapshot |
| `api.ts`, `tipos.ts` | Cliente HTTP y tipos |
| `vistas/auditoria.ts` | Priorizar, Entender la calidad, Explorar, Trazabilidad |
| `vistas/consulta_detalle.ts` | Consultar INVIMA |
| `vistas/resumen.ts`, `decision.ts`, `cargue.ts` | El flujo de candidatos |

⚠️ `ui_revision/app_streamlit.py` está **DESCARTADO**. No se toca ni se le
agregan funcionalidades.

---

## Datos y configuración

| Ruta | Qué es |
|---|---|
| `data/` | Archivos reales de producción. **En `.gitignore`. Nunca subirlos ni pegar su contenido en un reporte** |
| `data_runtime/snapshots/` | Los Parquet que deja el worker + `actual.json` |
| `data_runtime/estado_worker.sqlite3` | Salud, progreso y control |
| `config/catalogos/` | Catálogos de marca y unidad |
| `design/` | Esta documentación |
| `.ai/planes/` | Un plan por tarea no trivial |
| `.ai/bitacora.jsonl` | Registro append-only de cambios no triviales |

---

## Scripts

| Script | Qué hace |
|---|---|
| `reinicia_todo.ps1` | Mata el backend, limpia `__pycache__`, refresca, levanta frontend y backend |
| `reinicia_todo.ps1 -SinRefresco` | Igual pero sin refrescar |
| `reinicia_worker.ps1` | Arranca el worker. **`reinicia_todo.ps1` NO lo arranca** — el worker refresca al arrancar y eso contradiría `-SinRefresco` |
| `scripts/pre-push` | Hook: pytest + ruff + tsc. Aborta el push si algo falla |
| `scripts/instalar-hooks.ps1` | Instala el hook una vez |
| `scripts/ver_app.py` | **Abre la app en un navegador y captura la pantalla.** Ver abajo |

### Verificar en pantalla

```bash
python scripts/ver_app.py                          # portada
python scripts/ver_app.py auditoria priorizar      # una vista
python scripts/ver_app.py invima --cum 20055681-1  # consultar un CUM
python scripts/ver_app.py auditoria entender --texto --tema oscuro
```

Usa el **Edge instalado** (`channel="msedge"`), no baja el chromium de
Playwright. La captura va a `data_runtime/capturas/` (en `.gitignore`).

**La suite en verde no garantiza que la vista esté bien.** El 2026-09-08, con
657 pruebas pasando: un banner gritaba CRÍTICO tres líneas encima de su propia
fila "coincide", un veredicto mandaba a copiar una fecha del año 3000, una tabla
volcaba las 92 columnas del snapshot, y 1.194 descripciones salían con mojibake.
Ninguno lo atrapaba una prueba.

**Sin worker corriendo, el botón "Actualizar ahora" responde 503**: el backend
solo deja la solicitud, quien la ejecuta es el worker.

---

## Las cuatro trampas que ya costaron sesiones

1. **Un backend vivo sirve el código que cargó al arrancar.** Tras tocar `src/`
   o `backend/`, hay que reiniciarlo. Verificar contra un proceso viejo es
   perder el tiempo dos veces.
2. **`__pycache__` sirve el `.pyc` anterior.** Limpiarlo es parte del reinicio.
3. **Un snapshot viejo degrada a cero en silencio.** Un `0` se lee como "no hay
   hallazgos" cuando significa "este snapshot es de antes de esa columna".
4. **Vite se enlaza a `::1` (IPv6).** Un chequeo por `127.0.0.1` lo da por libre
   y arranca un segundo Vite en 5174 mientras el navegador sigue en 5173.
