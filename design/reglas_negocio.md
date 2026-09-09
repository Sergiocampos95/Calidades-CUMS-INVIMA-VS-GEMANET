# Reglas de negocio — Gemma CUM Loader

Lo que hay que saber **antes** de tocar la lógica. Cada regla nació de un caso
real contra datos de producción; donde hay una cifra, se midió.

> Este documento existe porque el conocimiento estaba disperso en comentarios
> dentro de archivos de 3.000 líneas. El usuario fue a validar el campo
> `CONCENTRACION`, vio que el cruce traía una descripción, y lo leyó como un
> error — con razón: nada en pantalla ni en la documentación decía que ese
> campo contiene un empaque. Si una regla de aquí no se sostiene sola, está
> mal escrita.

---

## 1. Alcance: esto es solo para CUMs

**El software audita CUMs. Nada más.**

La base de datos de Gemma Net contiene muchas cosas que no son CUMs (IUM,
códigos propios, códigos de la capa legada, insumos, alimentos). Esas filas no
se "excluyen de la auditoría": **nunca tuvieron por qué entrar**. Se ignoran.

La distinción importa y confundirla apaga la alarma que sí importa:

| | Significa | Qué hace el sistema |
|---|---|---|
| **Ignorar** | No es un CUM, no es asunto nuestro | Fuera del universo auditable. Sin veredicto ni prioridad. No cuenta en el denominador |
| **Auditar** | Es un CUM | Se compara contra INVIMA y se le da un veredicto |

## 2. Ante la duda se reporta, no se decide

Cuando no hay forma **verificable** de determinar algo, el sistema lo reporta
como hallazgo y decide una persona. Nunca resuelve adivinando.

Esto va más allá de una fila: un veredicto de esta aplicación puede derivar en
que alguien borre un registro de la base. Si ese producto no era un CUM pero sí
lo necesita otra área **por lo que realmente es** (un alimento, un insumo),
limpiar nuestra vista habría perjudicado a un sector que no participó de la
decisión.

**Caso que fijó la regla (2026-09-08).** El código `20199440-1`, "ALIMENTO EN
POLVO A BASE DE MALTODEXTRINA", tiene formato de CUM válido, no está en INVIMA,
y su `CODIGO_ATC` es `V06DX` — un ATC legítimo (nutrientes). Se intentó
excluirlo buscando la palabra "ALIMENTO" en la descripción y **se revirtió**:
no hay forma verificable de demostrar que no es un CUM. Se queda como hallazgo.

## 3. Qué es un CUM, y cómo se reconoce lo que no lo es

Un CUM tiene la forma `EXPEDIENTE-CONSECUTIVO` (`PATRON_CUM = ^\d+-\d+$`,
`normaliza/codigos.py`) y **lo reconoce INVIMA**.

El formato **no alcanza**: hay códigos con expediente de 8 dígitos y
consecutivo válido que no son medicamentos. Lo que sí distingue es el
`CODIGO_ATC`:

- Un ATC empieza siempre por **letra + 2 dígitos** (`PATRON_ATC = ^[A-Z]\d{2}`).
  `D01AC01`, `J06BA02`, `V06DX` son todos válidos — los niveles inferiores son
  opcionales, `V06DX` (nivel 4) es tan válido como uno completo de 7.
- Un `RSA-001241-2016` es un **Registro Sanitario de ALIMENTOS**. Identifica
  positivamente otro tipo de registro; no es una inferencia sobre el producto.

**Regla:** se ignora solo cuando fallan **las dos** cosas — no está en ningún
listado de INVIMA **y** su ATC ni siquiera tiene forma de ATC. Con una sola no
alcanza: un ATC raro en un medicamento que INVIMA sí lista no prueba nada, y un
ATC válido ausente de INVIMA es justo el hallazgo que hay que mostrar.

**No se filtra por grupo ATC.** Se evaluó excluir el grupo `V06` (nutrientes) y
se descartó: de sus 10 filas en el universo auditado, **9 son "V06DC01 GLUCOSA
ANHIDRA 5G SOLUCIÓN INYECTABLE"**, que sí es un medicamento. Habría ignorado 9
medicamentos reales para atrapar 1 alimento.

## 4. Los campos: qué contiene cada uno **realmente**

Los nombres de columna de Gemma Net no siempre describen su contenido. Estos
son los casos donde el nombre engaña:

### `CONCENTRACION`: ninguna de las dos fuentes guarda ahí una concentración

- **Gemma Net `CONCENTRACION`** (`m.concentracion` de `tb_medicamento`) trae la
  **presentación comercial** ("RECIPIENTE EN ALUMINIO CON 200 DOSIS MEDIDAS…"),
  palabra por palabra igual a la `DESCRIPCION_COMERCIAL` de INVIMA.
- **INVIMA `CONCENTRACION`** trae un **código de una sola letra**. Valores
  distintos en todo el listado de Vigentes: `A B C D E F S` — nada más
  (157.756 filas, cero con un dígito). La concentración real de INVIMA vive
  partida en `CANTIDAD` (`0.215`) + `UNIDAD_MEDIDA` (`% (W/W)`).
- La concentración de verdad ("120 MCG") solo aparece **dentro del texto** de
  `DESCRIPCION` / `PRINCIPIO_ACTIVO`, en los dos lados.

Medido el 2026-09-08 sobre las 57.736 filas con correspondencia, cuánto
coincide el campo local exacto contra cada candidato de INVIMA:

| Contra | Coincidencias exactas |
|---|---|
| `DESCRIPCION_COMERCIAL` | 52.116 (90,3 %) |
| `CONCENTRACION` (código de letra) | 3.508 (6,1 %) |
| `CANTIDAD` + `UNIDAD_MEDIDA` | 1 (0,0 %) |

**El cruce es homónimo: `CONCENTRACION` contra `CONCENTRACION`** — decisión
**explícita** del usuario (2026-09-09), tomada después de ver esta evidencia:
"lo que debe importar es si hay diferencias de campos, sin importar cuál sea
la cifra". Resultado medido: ~4.000 `coincide` (filas donde Gemma Net también
guarda la letra) y ~129.000 `difiere` comparando `"RECIPIENTE EN ALUMINIO…"`
contra `"F"`. Es el comportamiento aceptado, no un bug.

Historia, para no re-derivarla: entre el **2026-08-21 y el 2026-09-09** este
cruce apuntó a `DESCRIPCION_COMERCIAL` (empaque contra empaque, útil pero con
nombre engañoso). El cruce homónimo se intentó, se revirtió y se **reaplicó**
el 2026-09-09, todo en la misma sesión, una vez que el usuario confirmó que
lo quería así a pesar del volumen de `difiere`.

Auditar la concentración **de verdad** sería otra cosa: extraer número+unidad
del texto de Gemma Net y compararlo contra `CANTIDAD` + `UNIDAD_MEDIDA` de
INVIMA. Es una feature aparte, no un cambio de mapeo.

El nombre técnico no se toca: viaja en el snapshot, en el trío
`CONCENTRACION_GEMANET/_INVIMA/_VALIDACION` y en el Excel de cargue.

### El mapeo completo de campos comparados

`_CAMPOS_DIRECTOS` en `auditoria/coherencia_invima.py`:

| Campo de salida | Gemma Net | INVIMA |
|---|---|---|
| `CONCENTRACION` | `CONCENTRACION` | `CONCENTRACION` |
| `FORMA_FARMACEUTICA` | `FORMA_FARMACEUTICA` | `FORMA_FARMACEUTICA` |
| `PRINCIPIO_ACTIVO` | `PRINCIPIO_ACTIVO` | `PRINCIPIO_ACTIVO` |
| `CODIGO_ATC` | `CODIGO_ATC` | `ATC` |

`DESCRIPCION`, `MARCA_MEDICAMENTO` y `UNIDAD_MEDIDA` se arman aparte:
las dos últimas se guardan en Gemma Net como **código numérico** y hay que
resolverlas contra un catálogo antes de comparar.

### Medicamento combinado: `DESCRIPCION` y `PRINCIPIO_ACTIVO` van a Garantía y Calidad

Un medicamento combinado (varios principios activos, mismo
EXPEDIENTE-CONSECUTIVO) lo modelan las dos fuentes distinto:

| | INVIMA | Gemma Net (plataforma oficial) |
|---|---|---|
| Combinado | **N filas**, una por principio activo | **1 fila**, con las N descripciones y principios activos **pegados** en el mismo campo |

La auditoría cruza 1:1 por `CODIGO_INTERNO` y, cuando INVIMA trae varias filas,
se queda con la primera (`drop_duplicates(keep="first")`). Comparar
`DESCRIPCION` y `PRINCIPIO_ACTIVO` campo a campo contra esa única fila da un
"difiere" que **no significa nada**: la concatenación la hace Gemma Net, no
esta herramienta, y el dato hay que **entenderlo, no corregirlo**.

Regla (2026-09-08, pedido del usuario): en ese caso esos dos campos —y solo
esos dos— reciben el veredicto **`pendiente de decisión — Garantía y Calidad`**
(`VALIDACION_PENDIENTE_GYC`). El resto de campos se compara normal contra la
fila que ganó. Un campo en manos de GyC **no es acierto ni fallo**: sale del
denominador de `PORCENTAJE_CALIDAD` igual que un campo que ninguna fuente trae,
y no aparece en `CAMPOS_CON_DIFERENCIA` (se lista aparte en
`CAMPOS_PENDIENTE_GYC`).

Se marca solo cuando pasan **las dos** cosas: (1) INVIMA trae >1 fila para ese
`CODIGO_INTERNO` **y** (2) el valor de Gemma Net contiene, como subcadena
normalizada, el **nombre del principio activo** de **dos o más** de esas filas.
Si contiene uno solo, se compara normal —puede ser una diferencia real, no un
combinado pegado—. Medido sobre el snapshot del 2026-09-08: ~12.500 filas
marcan `DESCRIPCION` (la plataforma pega los principios activos en la
descripción casi siempre) y solo 1 marca también `PRINCIPIO_ACTIVO` (ese
campo casi nunca lo pega).

Pendiente de decisión de GyC (anotado 2026-09-08): `ESTADO_COHERENCIA` de la
fila **no** se tocó —una fila cuyos únicos hallazgos son de este tipo puede
quedar en `correcto`—. El usuario eligió explícitamente "solo los campos
afectados"; revisar si la fila también necesita un estado propio.

### Centinelas de "sin dato"

- **`-999`** es el centinela de Gemma Net. No es un número. Si un campo supera
  el 90 % en `-999`, es un problema de proceso, no miles de hallazgos sueltos.
- **`PORCENTAJE_CALIDAD` queda vacío, no en 0 %**, cuando no hay
  correspondencia con INVIMA: no hay nada que comparar, y no es lo mismo.

## 5. Vigencia: dos columnas que **no** significan lo mismo

Es la confusión que más veces ha roto esta aplicación.

| Columna | Qué es | Qué NO es |
|---|---|---|
| `ESTADO_CUM_INVIMA` | **El veredicto de vigencia.** `Activo` / `Inactivo` según INVIMA | — |
| `ESTADO_LISTADO_INVIMA` | **Ubicación**: en cuál de los 4 archivos aparece el registro | No es un veredicto de vigencia |

Un CUM puede estar en el listado de **Vencidos** con `ESTADO_CUM = Activo`, y al
revés.

### Gracia de lotes

Listado `vencido` (u `otros_estados`) **+** `ESTADO_CUM_INVIMA = Activo` =
**vigencia temporal mientras se agotan los lotes ya fabricados**. Hoy sí hay
respaldo sanitario. No es "autorizar sin registro vigente".

Cae a riesgo pleno solo cuando INVIMA cambie `ESTADO_CUM`, y ocurre solo: cada
refresco reclasifica, sin código especial. Tiene su propia novedad,
`NOVEDAD_VIGENCIA_TEMPORAL`, para no compartir el mensaje de riesgo máximo.

**Caso real (2026-09-08):** `20055681-1` mostraba "CRÍTICO — se puede autorizar
un medicamento sin registro vigente" tres líneas encima de su propia fila
"Estado del registro: Activo / Activo / coincide".

### Responsable según la dirección de la discrepancia

| Situación | Responsable |
|---|---|
| Activo aquí, sin vigencia en INVIMA | **GyC** (Garantía y Calidad) |
| Inactivo aquí, activo en INVIMA | **TIC** (saneamiento de base) |

## 6. Fechas centinela

Ninguna de estas es una fecha: todas significan "sin dato".

| | Valor | Origen |
|---|---|---|
| **Pasadas** | `1900-01-01`, `1899-12-30`, `2999-12-31` | `FECHAS_CENTINELA`. `1899-12-30` es el cero del calendario serial de Excel |
| **Futuras** | **cualquier año ≥ 2100** | `ANIO_CENTINELA_SIN_VENCIMIENTO` |

Las futuras se cortan **por año** y no con una lista, porque se reparten en
decenas de variantes: `3000-01-01`, `3000-12-31`, `3001-01-01`, `3000-10-10`,
`2199-01-01`, `2900-01-01`…

**Por qué 2100** (medido el 2026-09-08 sobre el snapshot real): la fecha
plausible más lejana de toda la base es **2036** — coherente con un registro
sanitario, que se otorga a 10 años renovables. Entre 2050 y 2999 no queda nada
que parezca real: 2999 (48.498), 2199 (124), 2099 (16), 2050 (13), 2300 (1),
2900 (1), 2056 (1). El corte deja 64 años de margen sobre el máximo real, así
que no puede matar una vigencia legítima.

El corte estuvo en 3000 hasta que los listados de julio 2026 destaparon
variantes por debajo (`2199-01-01`, 124 filas) que se comparaban como fechas de
verdad.

**Ojo:** las fechas se comparan como enteros `AAAAMMDD` y no como `Timestamp`
porque `2999-12-31` está **fuera del rango** de `datetime64[ns]` de pandas
(tope 2262-04-11).

## 7. Los 5 niveles de prioridad

`PRIORIDAD_ACCION`, en `clasificar_prioridad_accion()`. Ordena por **dirección
del riesgo**, no por el archivo de INVIMA donde apareció el CUM: un vencido y un
"con diferencias" son igual de graves si en los dos INVIMA marcó el CUM como
Inactivo.

| Nivel | Criterio | Qué hacer |
|---|---|---|
| `1_critico` | `ESTADO_CUM_INVIMA = Inactivo` | No autorizar sin revisar |
| `2_alto` | No aparece en ningún listado | Verificar el código |
| `3_medio` | Vencido/otro estado **pero CUM activo** | Vigilar: va a caer |
| `4_bajo` | Renovación en curso | Esperar |
| `5_informativo` | Vigente en ambos, solo difieren campos | Actualizar el campo |

El prefijo numérico no es decorativo: la tabla ordena por texto, y sin él
`2_alto` iría antes que `1_critico`.

**Se apoya en `ESTADO_CUM_INVIMA` + `ESTADO_LISTADO_INVIMA`, el mismo par que
usan las máscaras de `calidades.py`** — no en `ESTADO_COHERENCIA`. Una versión
que usó `ESTADO_COHERENCIA` daba 17.043 en renovación donde la tarjeta ya
verificada decía 16.479. Dos cifras para el mismo concepto en dos pantallas es
exactamente lo que hay que evitar.

**Invariante:** los 5 niveles suman el total de la tabla. Hay una prueba que lo
fija.

## 8. Las 7 calidades

En `auditoria/calidades.py`. Todas miden sobre el **universo auditable**.

1. **Vigencia confirmada** — activo aquí, `ESTADO_CUM = Activo`, en Vigentes
2. **Registro vencido en INVIMA** — por ubicación (listado `vencido`), sin
   filtrar por `ESTADO_CUM`: dentro conviven el vencido pleno y la gracia de lotes
3. **En trámite de renovación**
4. **En otro estado en INVIMA**
5. **No existe en INVIMA** — CUMs activos que INVIMA no tiene. **Se conserva
   aunque quede en cero**: sirve para ver si alguien carga algo que no es un
   medicamento (decisión del usuario, 2026-09-08)
6. **Estado** — SOLO la discrepancia de vigencia, sin mirar otros campos:
   CUM activo en Gemma Net + `ESTADO_CUM_INVIMA = Inactivo` (se excluye
   listado `vencido`, que ya vive en la calidad 2), y CUM inactivo en Gemma
   Net + `ESTADO_CUM_INVIMA = Activo` (el de mayor riesgo). Es un
   **subconjunto exacto** de la parte de estado de la calidad 7 — misma
   máscara factorizada (`discrepancia_vigencia`) — y **no repite** las
   columnas de comparación campo a campo: para eso está la 7. Pedido del
   usuario (2026-09-09): quería la discrepancia de estado como tarjeta propia,
   independiente, aun aceptando el solape con la 7. Valida `ESTADO_CUM_INVIMA`
   y `ESTADO_LISTADO_INVIMA`.
7. **Diferencia de estado o campos** — discrepancia de vigencia en cualquier
   dirección (misma máscara `discrepancia_vigencia` que la calidad 6), o
   diferencias de otros campos

## 9. Fuentes de INVIMA: archivos o API

Las dos fuentes dan **cifras muy distintas** para el mismo código, porque INVIMA
mueve registros de listado con los años. Medido sobre los 55.572 activos
auditables (2026-09-07):

| | Excel de listados | API en vivo |
|---|---|---|
| En trámite de renovación | 16.479 | 215 |
| No existe en INVIMA | 5.459 | 4 |
| Vigencia confirmada | 31.210 | 42.732 |

Ninguna está "mal". Pero **mezclarlas en una sesión vuelve imposible explicar
una cifra**, así que la elección es explícita: el botón "Actualizar ahora"
pregunta cada vez.

**La fuente primaria son los ARCHIVOS** (`FUENTE_DEFECTO = "archivos"`), porque
la API todavía no está soportada de punta a punta: la vista "Consultar INVIMA"
no procesa el JSON de Socrata. El defecto tiene que ser la fuente que funciona
en **toda** la aplicación, no solo en el refresco.

El ciclo periódico también respeta la fuente elegida: que la corrida de los 50
minutos cambie las cifras sin avisar volvería imposible sostener una explicación.

## 10. Exportación

El delimitador de todo lo que se exporta en texto plano (`.csv` y `.txt`) es el
**pipe** (`DELIMITADOR_EXPORTACION` en `backend/app/exportar.py`).

Medido sobre las 199.613 filas del snapshot, cuántas celdas de texto **ya
contienen** cada candidato:

| Delimitador | Celdas |
|---|---|
| coma | 231.410 |
| punto y coma | 62.777 |
| tab | 27 |
| **pipe** | **26** |

`to_csv` entrecomilla, así que el archivo nunca estuvo mal formado — pero
cualquiera que lo abriera con un split ingenuo o con el importador de Excel mal
configurado obtenía columnas corridas.

Cierra además el círculo con la lectura: `_DELIMITADORES_CANDIDATOS` en
`armado/cruce_gemanet.py` prueba `"|"` **primero**, así que un archivo exportado
por la app y vuelto a cargar se detecta sin configurar nada.

Los archivos llevan **BOM UTF-8** (`utf-8-sig`): sin él, Excel en Windows abre
el archivo interpretando mal cada tilde.

## 11. Dimensiones de auto-consistencia

Miden el reporte de Gemma Net **contra sí mismo**, no contra INVIMA. Son
detección de basura, y por eso corren sobre el snapshot **completo**: recortar
al universo auditable antes escondería justo la fila con el problema.

`DIMENSIONES_ABRIBLES` en `backend/app/routers/calidades.py`:

| Dimensión | Qué detecta |
|---|---|
| `completitud` | Campos sin diligenciar |
| `duplicados` | `CODIGO_INTERNO` repetido |
| `fuera_de_dominio` | Valores que no están en el dominio permitido |
| `inconsistencia_numerica` | Números que se contradicen entre sí |
| `formato_invalido` | Código interno con formato que no corresponde |
| `integridad_referencial` | Códigos de marca/unidad que no existen en el catálogo |

⚠️ Su total **no coincide** con el del universo auditable, y es a propósito:
responden preguntas distintas. `n_total_auditado` sí es el universo auditable.

## 12. Cadena de calidad H1–H6

Encadenada por teoría de conjuntos: cada eslabón parte del subconjunto que pasó
el anterior. `CADENA_CALIDAD_DEFAULT` en `auditoria/cadena_calidad.py`:

| Eslabón | Campo que agrega |
|---|---|
| H1 | (base: tiene correspondencia en INVIMA) |
| H2 | `DESCRIPCION` |
| H3 | `PRINCIPIO_ACTIVO` |
| H4 | `CONCENTRACION` |
| H6 | `UNIDAD_MEDIDA` |

**H5 (laboratorio) está excluido a propósito**, a la espera de que el negocio
confirme el campo. Agregarlo es una sola línea en ese módulo.

**Un eslabón vacío NO es un bug.** Como la cadena es acumulativa, si un campo
intermedio coincide poco, el universo de los siguientes cae casi a cero. Hoy
pasa con H4 (`CONCENTRACION`): desde el cruce homónimo del 2026-09-09 (§sobre
`CONCENTRACION`), ~97 % de las filas dan «difiere» a propósito, así que H4 baja
a ~0 % y H6 se queda sin filas que evaluar y muestra «—» (vacío, nunca 0 %). La
vista lo dice con una tarjeta corta en vez de dejar la tabla vacía sin
explicación.

**La `DESCRIPCION` plana solo aparece en H1.** Desde H2, `DESCRIPCION_GEMANET`
(el lado Gemma Net del trío) trae el mismo texto; mostrar las dos era una
columna repetida.

**Cada tabla de la cadena se puede descargar** (`GET /descargas/cadena/{H}`),
igual que las calidades: el eslabón completo, sin la paginación de pantalla.

## 13. Reglas que se probaron y se REVIRTIERON

Están aquí para que no se vuelvan a proponer. Todas parecían razonables.

| Regla descartada | Por qué |
|---|---|
| Excluir por la palabra **"ALIMENTO"** en la descripción | No es verificable. Un veredicto que derive en borrar el registro perjudica a las áreas que lo necesitan por lo que realmente es (2026-09-08) |
| Filtrar el **grupo ATC `V06`** | De sus 10 filas, 9 son GLUCOSA ANHIDRA SOLUCIÓN INYECTABLE — medicamento real. Habría ignorado 9 para atrapar 1 |
| Exigir **ATC completo de 7 caracteres** | `V06DX` es un ATC de nivel 4 tan válido como uno completo. Rechazarlo por incompleto es decidir a ciegas |
| Excluir **todo lo ausente de INVIMA** | Apaga la alarma que importa: un CUM real que INVIMA no tiene ES un hallazgo |
| Cortar los centinelas de fecha en el **año 3000** | Dejaba pasar `2199-01-01` (124 filas), `2900-01-01`, `2300` |
| Usar **`ESTADO_COHERENCIA`** para los niveles de prioridad | Daba 17.043 en renovación donde la tarjeta verificada decía 16.479 |
| Usar **`hay_solicitud_pendiente()`** como "hay un refresco en curso" | Son preguntas distintas. Dejaba el botón bloqueado para siempre |

## 14. Invariantes verificables

Si alguna falla, hay un bug. Varias tienen prueba automatizada.

1. **La suma de los 5 niveles de prioridad = el total de la tabla de
   "Priorizar".** Si divergen, dos pantallas están midiendo universos distintos.
2. **`GET /refrescar/progreso` y `POST /refrescar` nunca se contradicen**: si el
   progreso dice que no hay nada en curso, el POST no puede rechazar por
   "ya hay un refresco en curso".
3. **Cada fila del universo auditable cae en exactamente un nivel** de
   prioridad. Ninguna queda sin clasificar.
4. **Un archivo exportado y vuelto a cargar se detecta solo**: el delimitador de
   escritura (`|`) es el primero que prueba el lector.
5. **La descarga de una sección trae TODAS sus filas**, no la página visible.
6. **Una vista nunca recalcula un veredicto que el backend ya emitió.** Se lee
   el trío `<CAMPO>_GEMANET` / `_INVIMA` / `_VALIDACION`.
7. **`desfases_de_esquema()` vacío** tras un refresco: si el snapshot no trae
   una columna esperada, las cifras salen en cero y eso se lee como
   "no hay hallazgos".

## 15. El flujo de candidatos

La otra mitad de la aplicación, que esta documentación toca menos porque las
sesiones recientes fueron de auditoría.

Responde **qué medicamentos de INVIMA faltan por cargar en Gemma Net**, y
reemplaza un procedimiento que antes se hacía a mano sobre una malla de Excel.

1. `armado/malla.py` arma las filas candidatas desde el catálogo INVIMA vigente.
2. `armado/cruce_gemanet.py` cruza contra lo que ya existe → candidato / ya
   existe / cuarentena.
3. `catalogos/resolver.py` resuelve marca y unidad con la cascada
   determinística `exacto → alias → fuzzy → sin_resolver`.
4. `armado/reglas_negocio.py` deriva los campos que exige el cargue y que no
   están en ninguna fuente (edad, topes, copagos).
5. `validacion/reglas.py` aplica acepta / rechaza / descarta / cuarentena.
6. `exportacion/cargue.py` produce el Excel final.

**Quien carga en Gemma Net es una persona, no la aplicación.** El entregable
son los hallazgos y el Excel.

---

## Cifras de referencia

Medidas el **2026-09-08**, con los listados de INVIMA de **julio 2026**. Son una
foto, no invariantes: cambian con cada refresco y con la fuente elegida.

```
snapshot completo      199.613 filas
universo auditable      57.482
ignorados (no son CUM)       2   (20109427-1, 20113570-1 — ambos con RSA en CODIGO_ATC)

PRIORIDAD_ACCION                CALIDADES
  1_critico        7.737          Vigencia confirmada           42.732
  2_alto               2          Registro vencido en INVIMA        32
  3_medio          6.265          En trámite de renovación         215
  4_bajo             279          En otro estado en INVIMA       4.882
  5_informativo   43.199          No existe en INVIMA                2
                                  Diferencia de estado o campos 30.849
```

## Reglas heredadas que siguen vigentes

- **Nunca fusionar filas con `CODIGO_INTERNO` duplicado**: suelen ser
  medicamentos combinados y fusionarlas pierde un principio activo.
- **Degradación explícita**: si falta un archivo auxiliar se reporta; no se
  asume un valor por defecto.
- **La cascada de resolución es 100 % determinística** y nunca depende del
  modelo de IA. Son 200.000 filas.
- **La IA solo traduce**, no decide.
- **`cum_con_sufijo_atc` se excluye** del universo auditable: verificado contra
  producción, es la capa legada donde viven los suplementos e insumos que el
  negocio no quiere auditar (ENSURE, PEDIASURE, REPLENA), con `EXPEDIENTE = -999`
  y sin fechas.
