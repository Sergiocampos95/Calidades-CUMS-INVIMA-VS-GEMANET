# Gemma CUM Loader — contexto para agentes

Automatiza el cargue y la auditoria de medicamentos CUM/IUM entre el catalogo
oficial de INVIMA y la plataforma Gemma Net (Pijao Salud EPSI).

El `README.md` es la documentacion funcional completa y esta al dia: leelo antes
de tocar logica de negocio. Este archivo solo recoge lo que un agente necesita
para no romper convenciones.

## Los dos flujos (no confundirlos)

| Pregunta | Flujo | Modulos |
|---|---|---|
| Que medicamentos de INVIMA **faltan** por cargar | Candidatos | `armado/`, `validacion/`, `exportacion/` |
| De lo **ya cargado**, que esta mal o desactualizado | Auditoria | `auditoria/coherencia_invima.py` |

## Comandos

```bash
pytest                                    # suite completa (597 pruebas)
pytest tests/test_reglas.py -q            # un modulo
ruff check src/ tests/                    # lint
cd frontend && npx tsc --noEmit           # tipos del frontend

# DESARROLLO (reinicia AUTOMÁTICAMENTE todo):
.\reinicia_todo.ps1                       # backend + refresco + frontend
.\reinicia_todo.ps1 -SinRefresco          # omite el refresco si el snapshot ya sirve
```

**Importante**: Tras cambios en `src/` o `backend/`, ejecuta `.\reinicia_todo.ps1` (no
hagas esto a mano). Hacen falta CUATRO cosas y olvidar una sola deja la pantalla
mostrando lo viejo **sin avisar**:

1. Matar el `python` del proyecto (solo ese, no todo `python.exe`).
2. Borrar `__pycache__`/`.pyc` — si no, se sirve el `.pyc` anterior.
3. Refrescar el snapshot — si no, faltan las **columnas** nuevas y las cifras
   salen en cero, que se lee como "no hay hallazgos".
4. Tener el frontend vivo en 5173 — si está caído se ve una página rancia.

Dos trampas ya medidas, y por las que el script no se puede "simplificar":

- `ejecutar_refresco()` (está en `worker/tareas.py`, **no** en `pipeline.py`)
  **nunca lanza excepción**: registra `ESTADO_ERROR` y devuelve el estado. Mirar
  `$LASTEXITCODE` daría "todo bien" sobre un refresco roto. El script inspecciona
  el `EstadoRefresco` devuelto **y** `desfases_de_esquema()`, y aborta sin
  levantar el backend sobre datos malos.
- Vite se enlaza a `::1` (IPv6). Un chequeo por `TcpClient`/`127.0.0.1` lo da por
  libre y arranca un **segundo** vite en 5174 mientras el navegador sigue en 5173
  mirando la instancia vieja. Se comprueba con `Get-NetTCPConnection -State Listen`.

Entorno: Python 3.12+, venv en `.venv/`, Windows. Instalacion: `pip install -e ".[dev]"`.

## Arquitectura

```
src/gemma_cum_loader/
├── ingesta/        Lectura INVIMA: invima_reader.py (Excel), invima_socrata.py (API)
├── integraciones/  socrata.py — cliente HTTP crudo de datos.gov.co
├── armado/         malla.py (universo), cruce_gemanet.py, reglas_negocio.py
├── catalogos/      resolver.py (cascada deterministica) + ia_client.py
├── validacion/     reglas.py — acepta / rechaza / descarta / cuarentena
├── auditoria/      coherencia_invima.py — 9 dimensiones de calidad
├── exportacion/    cargue.py, estructura_cargue.py — Excel final
├── normaliza/      texto.py, codigos.py
└── pipeline.py     orquestacion end-to-end
```

Datasets Socrata: Vigentes `i7cb-raxc` (obligatorio), Vencidos `vwwf-4ftk`,
Renovacion `vgr4-gemg`, Otros Estados `spzp-dfuc` (los tres opcionales e
independientes).

## Reglas de diseno — no negociables

1. **Sin decisiones a ciegas.** Lo ambiguo va a `cuarentena`, no se resuelve
   adivinando. Nunca fusionar filas con `CODIGO_INTERNO` duplicado: suelen ser
   medicamentos combinados y fusionarlas pierde un principio activo.
2. **Degradacion explicita, nunca suposicion silenciosa.** Si falta un archivo
   auxiliar se reporta; no se asume un valor por defecto.
3. **La cascada de resolucion es 100 % deterministica** (`exacto -> alias ->
   fuzzy -> sin_resolver`) y **nunca depende del modelo de IA**. Son 200.000
   filas: tiene que ser exacta y rapida, sin llamadas de red.
4. **La IA solo traduce**, no decide. `ia_client.py` convierte un `motivo`
   tecnico en lenguaje de negocio. `explicar_motivo()` se llama una vez por
   motivo distinto (vocabulario fijo y chico), nunca una vez por fila.
   `explicar_fila()` solo bajo accion explicita del usuario en la UI.
5. **`-999` es el centinela de "sin dato"** de Gemma Net, no un valor numerico.
   Si un campo supera el 90 % en `-999` se reporta como problema de proceso, no
   como miles de hallazgos sueltos.
6. **`PORCENTAJE_CALIDAD` queda vacio, no en 0 %,** cuando no hay
   correspondencia con INVIMA: no hay nada que comparar y no es lo mismo.

## Convenciones de codigo

- **Espanol sin tildes en el codigo fuente** (identificadores, docstrings y
  comentarios son ASCII: `codigos`, `deterministica`, `espanol`). El `README.md`
  y los `.md` de `design/` si llevan tildes.
- **Los comentarios explican el *porque*, no el *que*.** Varios documentan
  hallazgos reales contra datos de produccion (`-999`, hojas de Excel mal
  nombradas, medicamentos combinados). Son la memoria del proyecto: no los
  borres ni los "limpies".
- `from __future__ import annotations` al inicio de cada modulo.
- Dataclasses (a menudo `frozen=True`) para los valores de retorno.
- Type hints en todas las firmas publicas.
- Sin dependencias nuevas sin justificarlas: el `pyproject.toml` es corto a
  proposito.

## Pruebas

- **Nunca golpear APIs reales desde pytest.** El cliente se inyecta
  (`ClienteExplicacionIA(client=...)`); lo mismo para Socrata/HTTP.
- Cada modulo de `src/` tiene su `tests/test_<modulo>.py`.
- Los tests se construyen con DataFrames pequenos in-line, no con archivos de
  produccion.
- Nombres de test descriptivos en espanol, coherentes con los existentes.

## Datos

`data/` esta en `.gitignore` y contiene archivos reales de produccion (decenas
de MB). **Nunca subirlos al repositorio ni pegar su contenido en un reporte.**
Los archivos reales son la fuente para medir rendimiento, no para versionar.

## UI (Vite + TypeScript)

**La app real es el frontend Vite en http://localhost:5173, servido por la API
FastAPI de `backend/app/` en el 8000.** `ui_revision/app_streamlit.py` esta
DESCARTADO: no se toca ni se le agregan funcionalidades (regla dura, ver
`.claude/agents/ui-vite.md`). Si algo hay que cambiar en pantalla, es en
`frontend/src/`.

- **Toda tabla de medicamentos lleva filtros y busqueda libre.** Ninguna se
  muestra en crudo. El unico componente que dibuja tablas es
  `TablaFiltrable` (`frontend/src/tabla.ts`) -- no crear un segundo
  mecanismo de render.
- **Toda tabla recorta su previsualizacion a `LIMITE_PREVISUALIZACION`
  (1.000) filas, con la opcion explicita de cargar la tabla completa.** El
  recorte es solo de lo que se ENVIA al navegador; las descargas siempre
  usan el DataFrame completo del backend. Nunca se asume en silencio que el
  limite alcanza.
- Las advertencias van como **tarjeta corta**, nunca como parrafos largos
  dentro de un banner -- pedido explicito del usuario (2026-08-25): un
  desplegable "solo desperdicia espacio". (Esconder contenido sustancial --
  una tabla, una lista larga -- si es correcto; no es lo que la regla
  prohibe.)
- Las secciones y sub-vistas se declaran en un solo sitio, `SECCIONES` en
  `frontend/src/main.ts`, agrupadas en "Candidatos para cargue" y
  "Medicamentos ya cargados".
- **Una vista NUNCA recalcula un veredicto que el backend ya emitio.** Se lee
  el trio `<CAMPO>_GEMANET` / `_INVIMA` / `_VALIDACION` que la auditoria dejo
  en la fila. Reimplementar la comparacion en TypeScript es exactamente como
  se llega a que la consulta puntual y las tarjetas de calidades digan cosas
  distintas del mismo CUM (paso el 2026-09-03 y costo una sesion entera).
- **Una fila de comparacion solo existe si los dos lados se pueden
  contrastar.** Un dato que solo tiene INVIMA va como informacion fuera de la
  tabla, no como fila con "no aplica" y "sin comparar" -- eso llenaba la
  pantalla de veredictos que no significaban nada (2026-09-04).
- **Formatear no es transformar el dato.** `frontend/src/fechas.ts` escribe el
  mes con letras SOLO en pantalla, porque INVIMA publica en MM/DD/YYYY y
  Gemma Net en YYYY-MM-DD y "04/03/2017" contra "2017-03-04" parecen fechas
  distintas siendo la misma. Las descargas se arman en el backend y siguen
  llevando la fecha como fecha, no como texto. Si el valor no es reconocible
  se muestra el crudo: nunca se adivina.
- Navegacion: todo salto pasa por `navegarA` en `main.ts`, que alimenta el
  historial del boton "Volver" (y Alt+Flecha). Una vista pide navegar con el
  evento `gemma:navegar`, sin importar `main.ts` -- que ya importa las vistas,
  y el import inverso cerraria un ciclo.

## Flujo de trabajo y control de versiones

Reglas acordadas con el usuario el 2026-09-04, despues de una sesion en la que
se acumularon 55 commits sin subir y dos agentes se pisaron en la misma rama.

**Ramas.** `master` es la rama estable y siempre debe quedar desplegable. Todo
trabajo va en una rama por tarea (`fix/<tema>` o `feature/<tema>`), que se
fusiona a `master` solo cuando esta verde Y verificada en pantalla. Nunca se
commitea directo a `master`.

**Antes de empezar una tanda:** `git fetch origin && git status`. Si la rama
quedo atras, ponerse al dia antes de tocar nada.

**Verificacion automatica.** El hook `pre-push` (en `scripts/`, se instala una
vez con `.\scripts\instalar-hooks.ps1`) corre pytest + ruff + tsc y ABORTA el
push si algo falla. Va en push y no en commit a proposito: la suite tarda ~40 s
y en cada commit acabaria evitandose con `--no-verify` por costumbre, que es
peor que no tenerlo. Saltarlo (`git push --no-verify`) solo con una razon
concreta.

**Subir seguido.** El codigo solo esta a salvo cuando esta en `origin`
(https://github.com/soferf/gemma-cum.git). Un dia de trabajo sin push es un dia
que vive unicamente en un disco. Antes de cerrar una sesion: commit + push.

**Copias de seguridad.** Antes de una tanda que toque logica de negocio, una
rama de respaldo (`respaldo/AAAA-MM-DD-<tema>`) publicada en `origin` deja un
punto de retorno. Los datos NO se respaldan en git: `data/`, `data_runtime/` y
`snapshots/` estan en `.gitignore` porque son de PRODUCCION de Pijao Salud, y
ademas son regenerables con un refresco.

**El lint no acumula ruido.** Si una regla marca un patron deliberado del
proyecto, se declara en `[tool.ruff.lint] ignore` con el porque -- no se deja
como aviso permanente. Trece avisos cronicos obligan a leer la salida buscando
cual es nuevo, y asi es como se acaba ignorando el linter entero.

**Una cifra no es buena hasta verla contra un proceso reiniciado.** Ver
`.\reinicia_todo.ps1` arriba y las cuatro cosas que hacen falta. Un backend
vivo sirve el codigo que cargo al arrancar, y un snapshot viejo degrada a cero
en silencio: un 0 se lee como "no hay hallazgos" cuando significa "este
snapshot es de antes".

## Equipo de agentes

Este proyecto define agentes especializados en `.claude/agents/`. Ver
`.claude/AGENTES.md` para el reparto de responsabilidades y como encadenarlos.

## Contexto compartido entre herramientas (Copilot CLI, Claude Code, Copilot Chat)

- `AGENTS.md` en la raiz es el puente para Copilot CLI (lo lee
  automaticamente). Copilot Chat en VS Code lee `.github/copilot-instructions.md`
  y las reglas por carpeta de `.github/instructions/*.instructions.md`. Los tres
  apuntan a este archivo sin duplicar reglas.
- **El reparto de trabajo con Copilot esta en `.ai/planes/README.md`**: Claude
  Code decide y verifica, Copilot acelera dentro de una decision ya tomada.
  Cada tarea no trivial lleva un plan en `.ai/planes/<slug>.md` con un dueno
  por paso y tres marcas (`[ ]` libre, `[~]` tomado, `[x]` hecho). Comandos:
  `/plan-equipo`, `/tomar-paso`, `/bitacora`.
- `.ai/bitacora.jsonl` es un registro append-only de cambios no triviales
  (agente, fecha, resumen, archivos). Formato en `.ai/README.md`.
- Convencion de commits: si propones un mensaje, agrega un trailer
  `Agente: <nombre>` (ej. `Agente: Copilot CLI`) para poder filtrar
  `git log --grep="^Agente:"` por herramienta.
