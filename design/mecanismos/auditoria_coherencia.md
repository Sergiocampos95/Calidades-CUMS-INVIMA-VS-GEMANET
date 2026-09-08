# Mecanismo: `auditar_coherencia()` — cómo se calcula el veredicto de exactitud

Complementa a [`reglas_negocio.md`](../reglas_negocio.md) (qué significan los
datos) y [`mapa_del_proyecto.md`](../mapa_del_proyecto.md) (dónde vive cada
cosa). Este documento es el tercero que faltaba: **cómo** calcula el código
cada resultado, paso a paso, verificado línea por línea contra
`src/gemma_cum_loader/auditoria/coherencia_invima.py` — no derivado de otra
documentación.

Nació de una comprobación real (2026-09-09): una sesión tuvo que releer
~150 líneas de código disperso para responder "¿cómo se estructura el
veredicto de auditoría?", porque `reglas_negocio.md` documenta las decisiones
de negocio pero no la mecánica interna. Si volvés a necesitar tocar
`auditar_coherencia()`, empezá por acá.

---

## 1. Los 7 campos comparables

`CAMPOS_COMPARADOS_COHERENCIA` (línea 231):

```python
CAMPOS_COMPARADOS_COHERENCIA = [*_CAMPOS_DIRECTOS.keys(), "DESCRIPCION", "MARCA_MEDICAMENTO", "UNIDAD_MEDIDA"]
```

4 salen de `_CAMPOS_DIRECTOS` (línea 219, mapeo documentado en
`reglas_negocio.md` §4) + 3 que se arman aparte:

| Campo | Cómo se arma |
|---|---|
| `DESCRIPCION` | `_descripcion_esperada_invima()` reconstruye la forma esperada a partir de los campos crudos de INVIMA |
| `MARCA_MEDICAMENTO` | Gemma Net guarda un **código numérico**; se resuelve contra el catálogo (`sigla_por_codigo`) antes de comparar |
| `UNIDAD_MEDIDA` | Igual: código numérico resuelto contra catálogo |

## 2. Un solo par normalizado por campo (línea ~2093 en adelante)

Para cada uno de los 7 campos se arma una tupla `(local, oficial)` en el
dict `pares`, **normalizada una vez**. De ahí salen tanto el veredicto
binario como la similitud — nunca se recalculan por separado, así que no
pueden contradecirse.

```python
pares["DESCRIPCION"] = (_normalizada(...), _normalizada(...))
pares["MARCA_MEDICAMENTO"] = (combinado["_MARCA_TEXTO"], TITULAR_INVIMA.map(normalizar_entidad))
pares["UNIDAD_MEDIDA"] = (_normalizada(...), _normalizada(...))
```

`normalizar_entidad` para MARCA (no `normalizar` a secas): mismo criterio
que usa la resolución de marca, para no generar un falso "con_diferencias"
por sufijo societario o calificador de planta.

**Los valores CRUDOS se guardan aparte** (`crudos_invima`, `crudos_gemanet`,
línea 2127) — la normalización es para comparar, no para mostrar. Lo que
viaja en las columnas `_GEMANET`/`_INVIMA` del resultado es el dato real tal
como está guardado.

## 3. La matriz de diferencias (línea 2144)

```python
matriz_diferencias = pd.DataFrame(
    {campo: local.ne(oficial) for campo, (local, oficial) in pares.items()}
)
```

Comparación exacta (`.ne()`) sobre el texto ya normalizado. Es un
`DataFrame` de booleanos, una columna por campo, una fila por CUM.

### MARCA y UNIDAD tienen una vía especial (línea 2154)

No se comparan como texto libre: Gemma Net guarda un **código de catálogo**,
y ese código puede tener varias formas válidas en el catálogo interno (varias
siglas para el mismo código). El veredicto se decide sobre el código:

```python
coincide = _coincide_con_alguna_sigla(codigos, oficial, siglas, normalizador, alias) | local.eq(oficial)
matriz_diferencias[campo] = ~coincide
```

Coincide si INVIMA calza con **cualquiera** de las formas que ese código
tiene en el catálogo — no solo con la que se muestra como representativa.

### "Sin dato" se resta de la matriz, no cuenta como diferencia (línea 2168)

```python
matriz_diferencias = matriz_diferencias & ~matriz_sin_dato
```

Un campo vacío en Gemma Net (`""`, `-999`, código `1` = "SIN INFORMACION")
no "difiere": no hay con qué comparar. Esa ausencia sí cuenta, pero en la
dimensión de **completitud** (#4), no aquí — ver `_sin_dato_local()`.

### 3.5. Medicamento combinado: `DESCRIPCION` / `PRINCIPIO_ACTIVO` a Garantía y Calidad (línea ~2186)

```python
pendiente_gyc_por_campo = _campos_en_pendiente_gyc(
    combinado["_CLAVE_CRUCE_INVIMA"],
    {"DESCRIPCION": ..., "PRINCIPIO_ACTIVO": ...},
    df_invima,          # el Vigentes CRUDO, ANTES del drop_duplicates
)
matriz_diferencias = matriz_diferencias & ~matriz_pendiente_gyc
```

INVIMA publica el combinado como **N filas** (una por principio activo); la
plataforma Gemma Net lo guarda en **1 fila** con esos textos pegados. El merge
se quedó con la primera fila de INVIMA, así que comparar campo a campo no dice
nada. `_campos_en_pendiente_gyc()` marca un campo cuando pasan **las dos**:

1. `df_invima["CODIGO_INTERNO"]` (crudo, sin deduplicar) tiene **>1 fila** para
   esa clave de cruce.
2. El valor local, normalizado, contiene como subcadena el texto normalizado
   de **≥2** de esas filas (`_bloques_distintos_en()` descarta el bloque que
   es subcadena de otro más largo — "IBUPROFENO" dentro de "IBUPROFENO
   ARGININA" no es un segundo principio activo).

Solo `DESCRIPCION` y `PRINCIPIO_ACTIVO` (`_CAMPOS_COMBINADO_GYC`): el resto de
campos es idéntico para todos los principios activos del combinado. El
veredicto `VALIDACION_PENDIENTE_GYC` se asigna **al final** de la cascada de
`{campo}_VALIDACION` (§8), y `matriz_pendiente_gyc` se suma a
`sin_dato_en_ambos` para sacar el campo del denominador de `PORCENTAJE_CALIDAD`
(§5). Se expone aparte en `CAMPOS_PENDIENTE_GYC`. `ESTADO_COHERENCIA` **no** se
tocó (decisión del usuario: "solo los campos afectados"). Ver
`reglas_negocio.md` §4.

## 4. Similitud: `token_set_ratio`, vectorizado (línea 1010, `similitud_de_campo`)

```python
puntajes = process.cpdist(izq, der, scorer=fuzz.token_set_ratio, workers=-1)
```

- `token_set_ratio` (no `ratio` a secas): compara **conjuntos** de palabras,
  no penaliza el orden ni las repetidas. "ACETAMINOFEN 500 MG TABLETA" vs
  "TABLETA ACETAMINOFEN 500MG" da alto — es el mismo medicamento escrito
  distinto.
- `process.cpdist` con `workers=-1`: compara par a par (fila *i* contra fila
  *i*) liberando el GIL. Medido: 199.689 pares en 0,05 s, los 7 campos en
  ~0,35 s. **Nunca uses `.apply()` fila a fila aquí** — a 200.000 filas eso
  es la diferencia entre 0,35 s y varios minutos.
- Si algún lado está vacío, da `NaN`, no `0`: "no hay con qué comparar" no es
  "no se parece en nada" — mismo criterio que `PORCENTAJE_CALIDAD`.

El binario (`matriz_diferencias`) dice que hay un problema; `SIMILITUD_<CAMPO>`
dice si es una tilde o si son dos medicamentos distintos. Cambia quién revisa
y con qué urgencia.

## 5. `PORCENTAJE_CALIDAD`: el denominador es por fila (línea 2200)

Cuatro categorías por campo:

| Categoría | Condición | ¿Entra al denominador? | ¿Cuenta como fallo? |
|---|---|---|---|
| Comparable | ambos lados tienen dato | Sí | Solo si difiere |
| `sin_dato_en_ambos` | ninguna fuente lo trae | **No** | — |
| `sin_dato_solo_local` | Gemma Net vacío, INVIMA **sí** lo trae | Sí | **Sí, siempre** |
| `matriz_pendiente_gyc` | medicamento combinado (ver §3.5) — solo `DESCRIPCION` / `PRINCIPIO_ACTIVO` | **No** (se le agrega a `sin_dato_en_ambos`) | — |

```python
campos_comparables_fila = len(matriz_diferencias.columns) - sin_dato_en_ambos.sum(axis=1)
campos_ok = campos_comparables_fila - matriz_diferencias.sum(axis=1) - sin_dato_solo_local.sum(axis=1)
porcentaje_calidad = (campos_ok / campos_comparables_fila * 100).round(1)
```

`sin_dato_solo_local` cuenta como fallo por decisión explícita del usuario
(2026-09-03, caso `20055212-21`: "sin marca en gemma net, pero invima sí
tiene, entonces correcto no está"). Antes se sacaba del denominador y el
medicamento quedaba en 100,0 % con el campo en blanco — justo lo contrario
de lo que esta columna debe medir.

`NaN` (no `0`) cuando `~invima_tiene_datos` o `campos_comparables_fila == 0`:
no hay nada que comparar, no es lo mismo que "0 % de calidad" (regla §6 de
`CLAUDE.md`).

## 6. `ESTADO_COHERENCIA`: cascada de `.where()`, no de `if`/`elif` (línea 2234)

```python
estado = pd.Series(CORRECTO, ...)
estado = estado.where(campos_con_diferencia == "", CON_DIFERENCIAS)
estado = estado.where(tiene_correspondencia, SIN_CORRESPONDENCIA_INVIMA)
```

`.where(cond, valor)` conserva el valor actual donde `cond` es `True` y lo
reemplaza donde es `False` — la lectura es "sigue en X salvo que…". Cada paso
solo puede *degradar* lo que puso el paso anterior, nunca lo mejora: si una
fila no tiene correspondencia, el segundo `.where()` la marcó
`CON_DIFERENCIAS` si tenía diferencias, y el tercero la vuelve a pisar con
`SIN_CORRESPONDENCIA_INVIMA` de todas formas — el orden importa porque el
último `.where()` gana.

### Un cuarto paso, después, degrada CORRECTO por tres motivos más (línea 2462)

No es una cascada de estados nueva: es un único `.mask()` que solo toca las
filas que **siguen** en `CORRECTO`, por si un hallazgo de fecha, un dato que
falta pero INVIMA sí trae, o una discrepancia de vigencia las alcanza:

```python
estado = estado.mask(
    estado.eq(CORRECTO) & (hallazgo_de_fecha | falta_dato_que_invima_si_trae | discrepancia_vigencia),
    CON_DIFERENCIAS,
)
```

`discrepancia_vigencia` (línea 2458) es el hallazgo de mayor riesgo del
sistema: `ACTIVO` local y `ESTADO_CUM_INVIMA` en direcciones opuestas, en
**cualquier** dirección. Nació de un bug real: la consulta puntual gritaba
"CRÍTICO — activo sin vigencia" mientras la tabla de hallazgos listaba el
mismo CUM como "Correcto / 100 %" — porque hasta entonces esta condición no
tocaba `ESTADO_COHERENCIA`.

### Los datasets auxiliares solo completan `SIN_CORRESPONDENCIA_INVIMA`

`_aplicar_dataset_auxiliar()` (línea 1490), llamada **5 veces** en cascada
de prioridad (línea 2290 en adelante) — no 3, porque Otros Estados se
reparte en varios orígenes según lo que su propio texto declara:

```python
aun_sin_resolver = estado == SIN_CORRESPONDENCIA_INVIMA
coincide = aun_sin_resolver & gemanet_codigos.isin(auxiliar_indexado.index)
estado = estado.where(~coincide, estado_valor)
```

1. **Vencidos** → `VENCIDO_EN_INVIMA`
2. **Otros Estados, subset "Vigente" en su propio texto** → `VIGENTE_NO_COMERCIALIZADO_INVIMA` (va antes que el resto: 2.887 de 10.469 filas de Otros Estados en realidad dicen que siguen vigentes, y si un código cae en las dos pasadas gana la que dice vigente)
3. **Otros Estados, el resto** → `ENCONTRADO_EN_OTRO_ESTADO_INVIMA`
4. **Renovación** (dataset dedicado) → `EN_TRAMITE_RENOVACION_INVIMA`
5. **Otros Estados, subset que declara "En Trámite Renov" en su propio texto** → también `EN_TRAMITE_RENOVACION_INVIMA` (459 códigos medidos 2026-09-02; mismo veredicto que el 4, pero `listado_invima` queda en `otros_estados` porque ahí es donde de verdad está el archivo — el listado no se deriva del veredicto, se pasa aparte)

Solo puede tocar una fila que **sigue** en `SIN_CORRESPONDENCIA_INVIMA` — no
puede pisar un `CORRECTO` o un `CON_DIFERENCIAS` ya resuelto contra Vigentes.
El mismo patrón "completa vacíos, nunca pisa" se repite para las 3 fechas
(`FECHA_ACTIVO/INACTIVO/VENCIMIENTO_INVIMA`) y para `ESTADO_CUM_INVIMA`.

### Al final de la cascada: ancestrales y plantas medicinales ganan sobre todo (línea 2349)

```python
estado = estado.where(~es_creacion_propia, EstadoCoherencia.NO_VALIDA_CONTRA_INVIMA.value)
```

`CLASIFICADO` en un valor de creación propia (ancestral/planta) pisa
**cualquier** estado anterior, incluso `SIN_CORRESPONDENCIA_INVIMA` — no es
un error que no aparezca en INVIMA, es que INVIMA no aplica. Va al final a
propósito: solo una vez resuelta toda la cascada de datasets sabemos con
certeza que nada más lo reclamó.

## 7. El trío por campo — lo que consume la UI (línea 2529)

```python
resultado[f"{campo}_GEMANET"] = local.values          # crudo, sin normalizar
resultado[f"{campo}_INVIMA"] = crudos_invima[campo].values
veredicto = SIN_COMPARAR (por defecto)
veredicto[invima_tiene_datos & ~matriz_diferencias[campo]] = COINCIDE
veredicto[invima_tiene_datos & matriz_diferencias[campo]]  = DIFIERE
veredicto[invima_tiene_datos & matriz_sin_dato[campo]]     = SIN_DATO_LOCAL   # ¡al final!
veredicto[matriz_pendiente_gyc[campo]]                     = PENDIENTE_GYC    # más al final (§3.5)
resultado[f"{campo}_VALIDACION"] = veredicto.values
```

**El orden de las asignaciones importa.** `SIN_DATO_LOCAL` se asigna
**último de las tres primeras**, a propósito: como `matriz_diferencias` ya
excluyó "sin dato" de las diferencias (paso 3), sin esa línea esas celdas
quedarían indistinguibles de `COINCIDE`. Es la misma regla del §3 aplicada al
trío que ve la UI. `PENDIENTE_GYC` (§3.5) va **después** de todas: un
combinado siempre tiene dato local, así que no compite con `SIN_DATO_LOCAL`,
pero se deja al final para que el orden no dependa de ese detalle.

**La UI nunca recalcula este veredicto.** Lee `<CAMPO>_GEMANET` /
`_INVIMA` / `_VALIDACION` directo. Reimplementar la comparación en TypeScript
es exactamente cómo se llegó a que la consulta puntual y las tarjetas de
calidad dijeran cosas distintas del mismo CUM (2026-09-03) — ver
`reglas_negocio.md` §7 (regla de la UI: nunca recalcular un veredicto).

---

## Constantes de referencia

```python
PREFIJO_SIMILITUD = "SIMILITUD_"
SUFIJO_GEMANET    = "_GEMANET"
SUFIJO_INVIMA     = "_INVIMA"
SUFIJO_VALIDACION = "_VALIDACION"

VALIDACION_COINCIDE       = "coincide"
VALIDACION_DIFIERE        = "difiere"
VALIDACION_SIN_COMPARAR   = "sin comparar"
VALIDACION_SIN_DATO_LOCAL = "sin dato en Gemma Net"
VALIDACION_PENDIENTE_GYC  = "pendiente de decision - Garantia y Calidad"   # §3.5, solo DESCRIPCION/PRINCIPIO_ACTIVO
_CAMPOS_COMBINADO_GYC     = ("DESCRIPCION", "PRINCIPIO_ACTIVO")
```

## Dónde seguir leyendo desde acá

- El resultado de esta función es la entrada de `filtrar_universo_auditable()`
  (qué se ignora vs qué se audita — ver `reglas_negocio.md` §3) y de las 6
  tarjetas de `calidades.py` (§8).
- La cadena H1–H6 (`cadena_calidad.py`) **no recalcula nada de esto**: lee las
  mismas columnas `_GEMANET`/`_INVIMA`/`_VALIDACION` que esta función ya dejó.
- `clasificar_prioridad_accion()` (línea 1769) usa `ESTADO_CUM_INVIMA` +
  `ESTADO_LISTADO_INVIMA`, **no** `ESTADO_COHERENCIA` — ver `reglas_negocio.md`
  §13, es una de las reglas revertidas.
