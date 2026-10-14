# Modulo IUM y fuentes de INVIMA — nota de continuidad

Nota para retomar la sesion del 2026-09-28, no un plan formal por tareas: el
trabajo no alcanzo a cerrarse en una sola sesion y hay una fecha limite
(jueves 2026-10-01, fin de jornada / 4pm).

## Como se llego aca

Hasta el 2026-09-28 se trabajo sobre `Documents\gemma-cum-loader` (remoto
`origin` -> `soferf/gemma-cum`). Ese dia se establecio que **el rumbo real
del proyecto es este repositorio**
(`Sergiocampos95/Calidades-CUMS-INVIMA-VS-GEMANET`, clonado en
`Documents\Calidades-CUMS-INVIMA-VS-GEMANET`): ya tiene el login con usuario
de GemaNet, permisos de administrador, el rediseño con el sistema de diseño
de "Auditoria de Calidades", y el despliegue en Linux (`deploy/`, puerto
8870) que Carlos ya tiene corriendo en `192.168.20.123:8870`. Los dos repos
comparten ancestro en el commit `67eaba3` de `gemma-cum-loader` y divergieron
desde ahi; **no se hizo ningun merge entre ellos**, se decidio trabajar
directamente sobre el nuevo.

## Objetivo de esta tanda (limite: jueves 2026-10-01, 4pm)

1. Fuentes de INVIMA actualizadas y funcionando localmente.
2. Definir donde se opera de ahora en más: local (confirmado que alcanza,
   ver abajo) vs. que suba Carlos al servidor.
3. Corregir que el sistema no reconoce el nuevo formato de exportacion de
   INVIMA (ver "Formato nuevo del portal" abajo).
4. Disenar e implementar el **modulo IUM** (no "modelo") dentro de
   `gemma_cum_loader`, evaluando casos de todo tipo.

## Que quedo verificado

- **Local alcanza, no hace falta produccion.** `ingesta/almacen_local.py::
  carpeta_datos()` lee `INVIMA_LISTADOS_DIR`; sin esa variable cae a
  `~/gemanet/invima`. Se creo esa carpeta en esta maquina
  (`C:\Users\TECNOLGO TIC\gemanet\invima`) con los 4 listados de julio 2026
  (formato conocido-bueno: hoja reconocible, encabezado fila 7, 29 columnas)
  copiados desde `gemma-cum-loader\data\`. Con eso alcanza para levantar
  `reinicia_todo.ps1` en el repo nuevo sin depender de nadie mas.
- **`GEMANET_DB_DSN` configurado** como variable de entorno de **usuario**
  (persiste en sesiones nuevas) con las credenciales que dio el usuario:
  host `149.130.174.72`, puerto `5432`, usuario `tic_fernando_sp`, base
  `muzna`. Un refresco de prueba en `gemma-cum-loader` (el repo viejo) corrio
  de punta a punta con esta variable: "Refresco terminado en 121.8s", sin
  error.
  - **Pendiente de confirmar**: `deploy/env.example` de ESTE repo trae de
    ejemplo `.../Tableros_BI`, no `muzna`. Puede ser solo un ejemplo viejo,
    pero no se confirmo cual es la base real que esta app deberia usar antes
    de darlo por bueno aca.
- **No hay acceso de escritura todavia** a
  `Sergiocampos95/Calidades-CUMS-INVIMA-VS-GEMANET`: por la API publica de
  GitHub, los unicos colaboradores son `Sergiocampos95` (dueno) y
  `TIC-CARLOS-SAAVEDRA`. La cuenta usada aca (`soferf`) no figura. Se puede
  clonar y leer (repo publico) y commitear localmente, pero falta que Sergio
  agregue la cuenta como colaborador (o trabajar via fork) antes de poder
  subir una rama.
- **El servidor de Carlos** (`http://192.168.20.123:8870/`, IP privada,
  alcanzable solo dentro de la red local) muestra "Calidades CUMS" con login
  "Ingrese con su usuario de GemaNet" -- coincide con los commits ya
  fusionados en `main` de este repo (`a0f2fd4`/`5daefcb` rediseño,
  `5baafc4`/`2b3c5f6` admin y permisos). No se pudo ver mas alla del login
  por falta de credenciales de GemaNet (no se piden en este chat).

## Formato nuevo del portal de INVIMA (pendiente de resolver)

El 2026-09-28 se descargaron los 4 listados desde el portal de datos.gov.co
y **3 de los 4** (Vencidos, Renovacion, Otros Estados) trajeron esta vez el
juego completo de columnas, pero en un formato que **ni este repo ni el
viejo saben leer todavia**:

- Hoja llamada `"Data"` (no "Vencidos"/"Otros Estados"/etc. -- esto solo no
  rompe nada porque `_resolver_hoja_auxiliar` cae al fallback de "unica hoja
  del libro").
- Encabezado en la **fila 1**, no en la fila 7
  (`FILA_ENCABEZADO = 6` en `invima_reader.py` saltaria 6 filas de datos
  reales y tomaria una fila de datos como encabezado -- confirmado
  identico en ambos repos).
- Columnas en **formato API** (`registrosanitario`, `tiporol`,
  `descripcionatc`, pegado en minuscula) en vez de `"REGISTRO SANITARIO"`,
  `"TIPO ROL"` etc. Coinciden exactamente con `CAMPOS_API` en
  `ingesta/invima_socrata.py` -- se puede reusar ese mapeo, no hace falta
  inventar uno.
- **Vigentes sigue viniendo incompleto** (10 columnas: expediente,
  principioactivo, cantidad, unidadmedida, unidadreferencia,
  formafarmaceutica, registrosanitario, fechaexpedicion, fechavencimiento,
  estadoregistro) -- falta averiguar con el usuario si en el portal hay una
  opcion de descarga completa para Vigentes distinta a la que se uso, porque
  sin eso los otros 3 no sirven de mucho (Vigentes es el dataset
  obligatorio).

Los archivos crudos descargados ese dia quedaron en la carpeta de Descargas
del usuario, nombrados `*_20260928.csv` y `*_20260928.xlsx` (mismo contenido,
dos formatos) -- **no se copiaron a `data/`/`~/gemanet/invima`** porque
todavia no son ingeribles tal cual.

## Arranque local en esta maquina (2026-09-28, verificado)

- Este repo **no tenia `.venv`**: se creo con `py -3.14 -m venv .venv` +
  `pip install -e ".[dev]"`, y `frontend/` con `npm install`. Ambos ok.
- **`SECRET_KEY` es obligatoria y no existia en este entorno** (nueva en este
  repo, no estaba en `gemma-cum-loader`): `backend/app/auth/config.py::
  secret_key()` revienta al importar `backend.app.main` si falta -- por eso
  el primer intento de arranque se quedaba colgado sin log claro (el
  traceback del hijo de `--reload` no llegaba a la consola). Se genero una
  clave aleatoria SOLO para desarrollo local y se guardo como variable de
  entorno de **usuario** (persiste): no es la clave de produccion, no hace
  falta que coincida con ninguna.
- **`--reload` de uvicorn en Windows volvio a fallar en silencio** (mismo
  patron que `design/operacion.md` seccion 3 ya documenta: proceso huerfano
  de `multiprocessing.spawn` sosteniendo el puerto 8000, sin traceback
  visible). Para esta sesion se arranco **sin** `--reload`
  (`uvicorn backend.app.main:app --port 8000`, sin la bandera) -- mas lento
  para iterar (hay que reiniciar a mano tras cada cambio) pero confiable.
  `reinicia_todo.ps1` del repo sigue usando `--reload`; si vuelve a colgarse
  sin log, matar por PID directo el proceso que escucha el puerto (ver
  `design/operacion.md` seccion 3) en vez de asumir que "no arranco".
- Frontend confirmado en `http://localhost:5173` (recordar: Vite se enlaza a
  `::1`, probar con `curl http://localhost:5173`, NO `127.0.0.1`).
- Backend confirmado vivo: `GET /salud` devuelve 401 (correcto, exige login
  ahora) en vez de 200 -- la app SI esta arriba, el 401 es el login.
- **Todavia no se probo el login real** (usuario/clave de GemaNet) ni que
  `GEMANET_DB_DSN` apunte a la base correcta para ESTE repo (ver duda
  `muzna` vs `Tableros_BI` arriba) -- pendiente antes de dar por buena la
  autenticacion.

## Pasos siguientes (en orden sugerido)

1. Confirmar con el usuario/Carlos/Sergio: nombre real de la base
   (`muzna` vs `Tableros_BI`) y pedir acceso de colaborador al repo.
2. Conseguir (o volver a pedir) la descarga COMPLETA de Vigentes.
3. Extender `invima_reader.py` para reconocer el formato nuevo ("Data",
   encabezado fila 1, columnas API) ademas del formato Excel clasico --
   probablemente un `_leer_catalogo_invima_auxiliar` paralelo o una deteccion
   automatica de formato por las columnas presentes. Con pruebas en
   `tests/test_invima_reader.py`.
4. Disenar el modulo IUM (agente arquitecto): hoy IUM cubre ~9,3% del
   catalogo INVIMA (no es llave universal, ver docstring de
   `invima_reader.py`), asi que el diseño tiene que cubrir explicitamente
   los casos con IUM, sin IUM, e IUM ambiguo/duplicado -- nunca asumir en
   silencio.
5. Implementar con pruebas, verificar en pantalla (`reinicia_todo.ps1` +
   `scripts/ver_app.py`), suite completa + lint + tsc.
6. Cierre de sesion de siempre: preguntar al usuario si se cumplio el
   objetivo, commit, y (una vez haya acceso de escritura) push/PR a este
   repositorio.

## Fecha limite

Jueves 2026-10-01, fin de jornada (4pm).
