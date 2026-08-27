# Cómo se llega a la cifra de "Registros evaluados" y sus vecinas

> Documento de trazabilidad, escrito a pedido explícito del usuario
> (2026-08-27) porque Sergio exige poder verificar de qué forma se llega a
> cada cifra que la aplicación reporta, no solo el número final. Pensado para
> anexarse a la conciliación. Cubre únicamente la sub-vista **Resumen** de
> "Resumen de resolución" y la sub-vista **Detalle por registro** que la
> respalda — las cifras que el usuario señaló primero. El mismo nivel de
> detalle se puede escribir para las demás secciones si se pide.

## De dónde sale el 101.183

Es el número de filas del archivo que se está usando como fuente de INVIMA
(`ListadoCodigoUnicoVigentes2022.xlsx`, o su equivalente por API) **sin
ningún filtro aplicado todavía**. No es un cálculo: es `len(df_invima)` tal
cual se leyó del Excel/API, después de normalizar encabezados
(`ingesta/invima_reader.py` / `ingesta/invima_socrata.py`).

Ese número varía con cada corte de INVIMA — no es una constante del código,
es el tamaño real del archivo que se cargó esa vez.

## Cómo se reparte ese universo en 5 categorías (suma exacta = 101.183)

La función `universo_invima_clasificado()` en
[`armado/malla.py:41-78`](../src/gemma_cum_loader/armado/malla.py#L41-L78)
recorre las 101.183 filas y le asigna a **cada una, sin excepción**, una y
solo una de estas 5 etiquetas (columna `CLASIFICACION_CREACION`). Se evalúan
en este orden de prioridad — la primera condición que se cumple es la que
queda, aunque una fila incumpla varias a la vez:

| Orden | Etiqueta | Condición (sobre la fila de INVIMA) | Columna(s) fuente |
|---|---|---|---|
| 1 | `rol_no_fabricante` | `TIPO_ROL` normalizado ≠ `FABRICANTE` (ej. `IMPORTADOR`) | `TIPO_ROL` |
| 2 | `cum_inactivo` | `ESTADO_CUM` normalizado ≠ `ACTIVO` | `ESTADO_CUM` |
| 3 | `registro_no_vigente` | `ESTADO_REGISTRO` normalizado ≠ `VIGENTE` | `ESTADO_REGISTRO` |
| 4 | `muestra_medica` | `MUESTRA_MEDICA` = `SI`, **o** `DESCRIPCION_COMERCIAL` menciona "muestra medica" aunque la columna diga `No` | `MUESTRA_MEDICA`, `DESCRIPCION_COMERCIAL` |
| 5 | `candidato` | Pasó las 4 condiciones anteriores | — (residual) |

En código (`np.select`, vectorizado, no un bucle por fila) — literal:

```python
condiciones = [
    tipo_rol.ne("FABRICANTE"),
    estado_cum.ne("ACTIVO"),
    estado_registro.ne("VIGENTE"),
    es_muestra_medica | menciona_muestra,
]
df["CLASIFICACION_CREACION"] = np.select(
    condiciones, CLASIFICACIONES_CREACION[:-1], default="candidato"
)
```

Por construcción de `np.select` (evalúa en orden y se queda con la primera
verdadera), las 5 categorías son **mutuamente excluyentes** y cubren el
100 % de las filas — por eso, y solo por eso, las 5 cifras de la sub-vista
"Detalle por registro" suman exactamente 101.183. No es una coincidencia que
haya que recalcular: es una propiedad garantizada por cómo se construye la
columna.

Nota sobre "Registro no vigente": si la fuente cargada es el listado de
**Vigentes**, esta categoría da 0 por definición — todas las filas de ese
archivo ya vienen con registro vigente. No es un error del filtro; el mismo
criterio sí encuentra casos cuando la fuente es Vencidos/Renovación/Otros
Estados.

## Cómo se llega a los 47.767 "Registros evaluados" (o el número que aplique)

De las 101.183, solo el bucket `candidato` continúa al siguiente paso: es el
insumo de `candidatos_creacion()`
([`armado/malla.py:81-90`](../src/gemma_cum_loader/armado/malla.py#L81)),
que además arma `DESCRIPCION` (`PRINCIPIO_ACTIVO` + `UNIDAD_REFERENCIA`) y
`MARCA_MEDICAMENTO` (= `TITULAR`) para cada fila que queda. Ese subconjunto
es el que la sub-vista "Resumen" llama **"Registros evaluados"** — el texto
de ayuda ya lo dice: *"Los registros de INVIMA que pasaron los cuatro
filtros... y llegaron a cruzarse contra Gemma Net"*.

Importante: "Registros evaluados" **no** es 101.183. Es el tamaño del bucket
`candidato` (en la corrida de referencia, 47.767). El 101.183 completo solo
se ve en "Detalle por registro"; mezclarlos fue justamente el motivo por el
que la tarjeta se renombró de "Total filas vigentes" a "Registros evaluados"
(ver el comentario en `app_streamlit.py` junto a esa métrica).

## Cómo se cruza ese subconjunto contra Gemma Net

Cada una de esas filas ya "candidato" se compara, una por una, contra el
archivo/consulta exportada de Gemma Net
([`pipeline.py:190-260`](../src/gemma_cum_loader/pipeline.py#L190)):

1. **La llave de comparación es `CODIGO_INTERNO`** en ambos lados. Del lado
   de INVIMA se arma en `ingesta/invima_reader.py:121-124`: si el corte trae
   `COD_MEDICAMENTO_INVIMA` se usa tal cual; si no, se arma como
   `EXPEDIENTE-CONSECUTIVO` (INVIMA no tiene un "código interno" nativo, por
   eso el equivalente construido). Del lado de Gemma Net, `CODIGO_INTERNO`
   ya viene como columna propia en el export
   (`armado/cruce_gemanet.py:leer_codigos_gemanet`).
2. Antes de comparar, cada fila pasa dos validaciones de forma (no de
   negocio): que `CODIGO_INTERNO` sea válido/no vacío
   (`filtro_codigo_interno_valido`) y que la fila no venga con columnas
   corridas (`filtro_integridad_estructural`). Lo que falla acá va directo a
   `cuarentena`, sin llegar a compararse contra Gemma Net.
3. Con la llave válida, se pregunta: **¿ese `CODIGO_INTERNO` ya está en el
   conjunto de códigos leídos de Gemma Net?**
   - Si sí → **`ya_existe`** ("Ya en Gemma Net"): no hay nada que crear.
   - Si el código coincide con una línea del export de Gemma Net que vino
     rota/no verificable → **`cuarentena`**: no se puede confirmar con
     certeza, se aparta para revisión manual.
   - Si no aparece en ningún lado → **`candidato`** ("Candidatos a crear").

Las tres son excluyentes y suman exactamente el total de "Registros
evaluados" — la misma garantía que arriba, ahora aplicada al segundo cruce:
`ya_existe + candidatos + cuarentena = registros_evaluados`.

## Resumen de la cadena completa

```
101.183 (archivo INVIMA completo, sin filtrar)
   │
   ├─ rol_no_fabricante ─┐
   ├─ cum_inactivo       │  se quedan clasificados así, no siguen
   ├─ registro_no_vigente│  a la siguiente etapa
   ├─ muestra_medica ────┘
   │
   └─ candidato = 47.767 ("Registros evaluados")
          │
          ├─ CODIGO_INTERNO ya existe en Gemma Net  → "Ya en Gemma Net"
          ├─ CODIGO_INTERNO no se pudo verificar     → "En cuarentena"
          └─ CODIGO_INTERNO no existe en ningún lado → "Candidatos a crear"
```

Cada número de esta cadena es verificable abriendo la tabla correspondiente
en la UI (búsqueda + filtros, sin cifras que no se puedan abrir a la lista
de medicamentos que las componen — el mismo principio que se le pidió
aplicar a las calidades de la auditoría de coherencia).
