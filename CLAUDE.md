# Gemma CUM Loader — contexto para agentes

Automatiza el cargue y la auditoria de medicamentos CUM/IUM entre el catalogo
oficial de INVIMA y la plataforma Gemma Net (Pijao Salud EPSI).

El `README.md` es la documentacion funcional completa y esta al dia: leelo antes
de tocar logica de negocio. Este archivo solo recoge lo que un agente necesita
para no romper convenciones.

Cuatro documentos mas, en `design/`, que evitan re-derivar lo ya decidido.
Responden preguntas DISTINTAS -- confundirlas es como una sesion (2026-09-09)
tuvo que releer ~150 lineas sueltas de codigo para explicar como se calcula
el veredicto de auditoria, porque esa mecanica no estaba en ningun lado:

- **`design/reglas_negocio.md`** — el QUE y el POR QUE: cada regla que el
  sistema aplica sobre los datos, con la medicion que la justifica y la fecha
  en que se decidio. Consultalo ANTES de cambiar un umbral, un filtro o un
  veredicto. Incluye las reglas que ya se probaron y se REVIRTIERON.
- **`design/mapa_del_proyecto.md`** — el DONDE: donde vive cada cosa, el ciclo
  de vida del dato (fuentes -> worker -> snapshot -> backend -> frontend) y la
  tabla "quiero cambiar X, toco Y".
- **`design/mecanismos/`** — el COMO: para los modulos mas densos, el
  mecanismo interno verificado linea por linea contra el codigo -- que formula
  exacta arma cada columna, en que orden, y por que ese orden importa. No es
  un resumen de `reglas_negocio.md`: es lo que hace falta leer para TOCAR la
  logica sin romperla. Hoy: `auditoria_coherencia.md`
  (`auditar_coherencia()` completo). Se agrega un archivo nuevo cuando una
  sesion tenga que releer codigo fuente para explicar un mecanismo que no
  esta documentado -- esa relectura es la senal de que falta el archivo.
- **`design/operacion.md`** — el COMO SE OPERA: cuando commitear, como
  arrancar/reiniciar cada pieza, y una tabla de sintoma -> causa -> mitigacion
  para los fallos ya vistos (proceso huerfano de multiprocessing sosteniendo
  un puerto, `--reload` sirviendo codigo viejo, `python` sin venv, Vite
  duplicado en 5174). Consultalo ANTES de reportar un fallo de entorno como
  nuevo -- varios ya se midieron y tienen mitigacion escrita.

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

# VERIFICAR EN PANTALLA (no solo contra la API):
python scripts\ver_app.py                          # portada
python scripts\ver_app.py auditoria priorizar      # una vista concreta
python scripts\ver_app.py invima --cum 20055681-1  # consultar un CUM
python scripts\ver_app.py auditoria entender --texto --tema oscuro
```

**Mirar la pantalla es parte de verificar, no un extra.** La suite y la API
pueden estar en verde con la vista rota: el 2026-09-08, con 657 pruebas
pasando, la consulta puntual anunciaba "CRÍTICO — se puede autorizar sin
registro vigente" tres líneas encima de su propia fila "coincide", otra vista
mandaba a copiar una fecha del año 3000, y 1.194 descripciones se mostraban con
mojibake. Los tres salieron de mirar, no de una prueba.

`scripts/ver_app.py` usa el **Edge que ya está instalado** (no baja los ~150 MB
del chromium de Playwright), guarda la captura en `data_runtime/capturas/` (en
`.gitignore`) e imprime los errores de la consola del navegador — un fallo de
JS deja la vista a medias y sin eso la captura sale "vacía" sin decir por qué.

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

Entorno: Python 3.12+, venv en `.venv/`. Desarrollo en Windows (scripts `.ps1`);
**produccion en el servidor Linux** como servicio (`deploy/`, puerto 8870, login con
usuario de GemaNet, listados de INVIMA en `INVIMA_LISTADOS_DIR`) -- ver la seccion
"Despliegue en Linux" del `README.md` y `design/operacion.md`. En Linux no hay
`.ps1`: `systemctl --user restart gemanet-cums-api gemanet-cums-worker` tras
`npm run build`. Instalacion: `pip install -e ".[dev]"`.

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

**Sistema de diseno (2026-09-14): el MISMO del dashboard "Auditoria de
Calidades"** (`auditoria_calidades/dashboard/app/static/pijaos.css`, paleta
Olympia de GemaNet): barra superior azul `#2F5D7A` con logo y enlaces planos,
fondo `#F4F4F4`, Segoe UI 14px, tarjetas blancas con borde superior por
riesgo, tablas con cabecera azul, badges, cajas "que detecta" azules. Un solo
tema claro (no hay modo oscuro). Los tokens semanticos (`--accent`, `--ok`,
`--warn`, `--danger`, `-soft`) siguen existiendo en `estilo.css` mapeados a esa
paleta: una vista nueva usa esos tokens, nunca hex sueltos. Navegacion: la
portada es la **Bandeja de calidades** (una tarjeta por calidad), de ahi a
"Casos por calidad" (chips de calidad y de tipo de diferencia sobre la tabla)
y de una fila a "Consultar INVIMA" (detalle del caso, Gemma Net contra INVIMA
campo a campo y que hacer).

**La app real es el frontend Vite en http://localhost:5173, servido por la API
FastAPI de `backend/app/` en el 8000.** `ui_revision/app_streamlit.py` esta
DESCARTADO: no se toca ni se le agregan funcionalidades (regla dura, ver
`.claude/agents/ui-vite.md`). Si algo hay que cambiar en pantalla, es en
`frontend/src/`.

- **Toda tabla de medicamentos lleva filtros y busqueda libre.** Ninguna se
  muestra en crudo. El unico componente que dibuja tablas es
  `TablaFiltrable` (`frontend/src/tabla.ts`) -- no crear un segundo
  mecanismo de render.
- **Toda tabla se navega por paginas de `LIMITE_PREVISUALIZACION` (1.000)
  filas.** Ya NO existe un "cargar la tabla completa": traerse 59.000 filas
  de un golpe trababa el equipo (reporte del usuario, 2026-09-04). Para el
  conjunto entero estan los botones de descarga, que piden el archivo al
  backend. El recorte es solo de lo que se ENVIA al navegador y nunca se
  asume en silencio: el pie dice en que pagina se esta y cuantas filas trae
  el archivo.
- **La cache de tablas (`frontend/src/cache_tablas.ts`) va versionada por
  snapshot.** Vive a nivel de MODULO, no en la instancia de `TablaFiltrable`,
  porque cada navegacion la destruye. Una cache que no se invalida al
  refrescar serviria cifras viejas -- el mismo fallo que ya costo una sesion
  entera.
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

**Una sesion = un problema.** Una sesion atiende UN problema, en UNA rama que
lleva su nombre, y termina cuando ese problema esta resuelto, verificado en
pantalla y subido. Lo que aparezca por el camino y no sea ese problema se
anota (una nota al usuario al cerrar la sesion) y se trabaja DESPUES, en su
propia sesion.

Por que, medido en este repositorio: la sesion del 2026-09-08 dejo 8 commits
en la rama `ui/vocabulario-veredictos` -- un nombre que solo describe el
ultimo. Los otros siete tocan fechas centinela, universo auditable, worker,
eleccion de fuente, delimitador de exportacion, priorizacion y navegacion.
Son ocho arreglos buenos, cada uno con su porque escrito, pero llegaron
juntos y eso cuesta caro en tres sitios:

- **Revisar.** Nadie revisa ocho cambios no relacionados con el mismo
  cuidado con que revisa uno.
- **Revertir.** Si uno sale mal, la rama no se puede devolver sin llevarse
  los otros siete por delante.
- **Verificar.** Cada arreglo pide su propio `.\reinicia_todo.ps1` y su
  propia mirada en pantalla. Ocho a la vez es justo cuando se empieza a
  confiar en que "la suite esta verde" -- y la suite no ve la pantalla.

Un problema puede necesitar varios commits (el arreglo, la prueba, la
correccion de lo que el arreglo destapo). Eso sigue siendo una sesion. Lo que
NO es una sesion es una lista de temas distintos que comparten rama solo
porque se trabajaron el mismo dia.

**Ramas.** `master` es la rama estable y siempre debe quedar desplegable. Todo
trabajo va en una rama por tarea (`fix/<tema>` o `feature/<tema>`), que se
fusiona a `master` solo cuando esta verde Y verificada en pantalla. Nunca se
commitea directo a `master`. El nombre de la rama es el problema de la sesion:
si al terminar el nombre ya no describe lo que hay dentro, la sesion cubrio
mas de un problema.

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

**Cierre obligatorio de sesion.** Regla del usuario, 2026-09-09. Cuando un
cambio queda aplicado y verificado, la sesion NO termina en silencio: hay que
PREGUNTARLE al usuario si se cumplio el objetivo, y con su confirmacion cerrar
el ciclo entero -- **commit -> fusion a `master` -> push**. Los tres pasos, no
el primero solo.

Por que los tres, medido en este repositorio el 2026-09-09: habia 47 commits
bien hechos, con su mensaje y su porque, y aun asi la pregunta del usuario fue
"por que arreglo una cosa y se devuelven los avances de otra". Commitear no
era el eslabon que faltaba. `master` seguia en `54ca88f` del 2026-09-04 y las
ramas se habian ido apilando en CADENA -- cada una creada sobre la anterior,
no sobre `master`. Consecuencias que el usuario vivio:

- **`master` desplegable era falso.** 47 commits y 81 archivos de diferencia
  (+6.597 / -1.554). Cualquier `git checkout master` devolvia la aplicacion al
  4 de septiembre. El reflog registra dos de esos saltos el 2026-09-08: ahi es
  donde "se devolvieron los avances".
- **Pararse en una rama de mas atras de la cadena parece perdida de trabajo.**
  No lo es -- lo posterior esta adelante en la cadena -- pero en pantalla es
  indistinguible de un cambio revertido.
- **Ramas que divergen sin que nadie lo note.**
  `fix/concentracion-cruza-contra-concentracion-invima` acumulo un `Revert` y
  un `Reapply` del mismo cambio, y quedo con un commit en `origin` que el
  local no tenia.

De ahi tambien la mitad que suele olvidarse: **cada rama nueva sale de
`master` actualizado, nunca de la rama anterior.** Fusionar sin volver a
`master` para la siguiente tanda reconstruye la misma cadena.

Antes de dar por cumplido el objetivo, la verificacion es la de siempre: suite
verde Y mirada en pantalla tras `.\reinicia_todo.ps1` (ver arriba). Una cifra
contra un proceso viejo no cuenta como objetivo cumplido.

Cuando el usuario responde que el objetivo NO se cumplio, no se fusiona: la
rama se queda viva y la sesion sigue siendo la misma sesion.

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

## Registro de trabajo

**Claude Code es el unico agente que trabaja este repositorio** (decision del
usuario, 2026-09-08). Ya NO hay plan compartido ni reparto de pasos con
Copilot: un cambio inesperado en el arbol es propio, no de otra herramienta.

- `.ai/bitacora.jsonl` es un registro append-only de cambios no triviales
  (agente, fecha, resumen, archivos). Formato en `.ai/README.md`. Sigue
  vigente: es la memoria en una linea de por que se hizo cada tanda, sin
  abrir el log de git. **Comando: `/bitacora` -- correlo SIEMPRE al cerrar
  una sesion que toco codigo**, no solo cuando el cambio parezca grande. Ya
  no es solo un registro: verifica que `design/reglas_negocio.md` y
  `design/mecanismos/` queden alineados con lo que se cambio (actualizarlos
  ahi mismo, o decir explicitamente por que no hacia falta), revisa si la
  memoria persistente necesita la misma correccion, y recuerda subir los
  commits pendientes. Es el cierre del ciclo de sostenibilidad: los hooks
  de `.claude/hooks/` (documentados en `.claude/AGENTES.md`) avisan EN VIVO,
  durante la edicion, si se toco un modulo sensible sin leer su documento o
  si el documento quedo mas viejo que el codigo; `/bitacora` es el punto
  donde esa alineacion se resuelve antes de que la sesion termine, en vez de
  quedar como un aviso que nadie atendio.
- Los planes de `.ai/planes/` quedan como HISTORIA de tareas ya ejecutadas.
  **No se editan**: si un plan viejo dice algo que hoy es falso, lo que vale
  es `design/reglas_negocio.md`. Varios mencionan a Copilot y el reparto de
  pasos, y es correcto: asi se trabajo en ese momento.
- El andamiaje de Copilot se BORRO el 2026-09-08, ya sin funcion: `AGENTS.md`,
  `.github/copilot-instructions.md`, `.github/instructions/`,
  `.github/prompts/`, `.ai/planes/PLANTILLA.md` (llevaba un dueno por paso) y
  los comandos `/plan-equipo` y `/tomar-paso`. Todo esta en el historial de
  git si alguna vez hace falta.
- Comandos que SIGUEN vigentes: `/bitacora` y `/revisar-reglas`.
- `.claude/agents/` y `.claude/AGENTES.md` no tienen nada que ver con esto:
  son los subagentes de Claude Code y siguen en uso.
