# Módulo IUM separado del módulo CUM: plan de implementación

> 2026-09-28. Es un plan de diseño y no trae código. Rama sugerida: `feature/modulo-ium`, sacada de `main` actualizado y no de `feature/lector-invima-formato-portal-nuevo`, que es donde está parado el checkout hoy.

## Antes del plan: choca con una regla documentada

`design/reglas_negocio.md` §1 dice: "El software audita CUMs. Nada más. […] (IUM, …) Se ignoran". En el código eso es `coherencia_invima.py:3013`, `_TIPOS_CODIGO_AUDITABLES = ["cum"]`. El módulo IUM abre un segundo alcance. Hay dos formas de no romper §1:

- **(a)** El módulo CUM sigue ignorando los IUM. Sus cifras no se mueven, y eso se fija con una prueba.
- **(b)** El IUM vive aparte: su propia tabla de snapshot, su propio router y su propia vista.

Igual hay que reescribir §1 para que diga esto. Si no se reescribe, la próxima sesión va a "arreglar" el módulo IUM porque contradice §1.

---

## Objetivo

Replicar para IUM los dos flujos que ya existen para CUM, como módulo aparte dentro de la misma app:

1. **IUM ya cargados (auditoría):** comparar lo que Gemma Net tiene identificado por IUM contra INVIMA.
2. **Candidatos IUM:** IUM de INVIMA que todavía no están en Gemma Net.

La clasificación `TIPO_CODIGO_INTERNO == "ium"` (`normaliza/codigos.py:88`, `clasificar_codigos()` en `:156`) se reutiliza y no se toca.

## Lo que dice el dato (medido el 2026-09-28)

Fuente: snapshot `20260928T155543895270Z` del checkout viejo (`Documents\gemma-cum-loader\data_runtime\snapshots\`). Ese snapshot sale de la base de Gemma Net en vivo más los listados de julio 2026. El repo nuevo todavía no tiene snapshot propio. Solo se reportan agregados.

**Gemma Net, filas con `TIPO_CODIGO_INTERNO == "ium"`**

| | |
|---|---|
| Filas | **90** (eran 85 el 2026-08-26), **79 activas** |
| `EXPEDIENTE` / `CONSECUTIVO` vacíos | 79 de 90 |
| `CODIGO_ATC` vacío | 66 de 90 |
| Cómo salen hoy en el snapshot CUM | 90/90 `sin_correspondencia_invima`, con el texto "Código legado…" y `PRIORIDAD_ACCION = 2_alto`. Quedan fuera del universo auditable, así que no se ven |

**INVIMA, columna `IUM` de los 4 listados apilados (423.445 filas)**

| | |
|---|---|
| Filas con IUM | 41.250 (9,7 %). En Vigentes son 33.052 de 157.799, es decir **20,9 %**. Otros Estados 7.956, Vencidos 180, Renovación 62 |
| Cumplen la forma `^[0-9][A-Za-z][0-9]{13}$` | 99,1 %. Hay 324 filas mal formadas (`"99"`, 12 caracteres, texto) |
| IUM distintos / CUM distintos que tienen IUM | 16.075 / 17.552 |
| Relación CUM → IUM | **siempre 1** |
| Relación IUM → CUM | 1 en 14.935 casos; **2 o más en 1.140** (hasta 6) |

**Cruce literal entre los IUM de Gemma Net e `INVIMA.IUM`**

| | |
|---|---|
| Aparecen en INVIMA | **52 de 90** (47 de los 79 activos). 51 en Vigentes y 1 en Otros Estados; los 52 con `ESTADO_CUM = Activo` |
| De esos 52, cuántos CUM les asocia INVIMA | 49 tienen un solo CUM; 3 tienen varios (2, 2 y 4) |
| Esos CUM ya cargados en Gemma Net como fila CUM propia | **56 de 57 (55 activos)** |
| No aparecen en INVIMA | 38 (32 activos) |
| Acuerdo de campos en los 49 casos de un solo CUM (texto normalizado) | `PRINCIPIO_ACTIVO` igual en 14 (lo contiene en 28); `FORMA_FARMACEUTICA` 7; `CODIGO_ATC` 20 (27 vacíos en Gemma Net) |

**Posibles candidatos** (Vigentes, activo + fabricante, con IUM): 11.852 IUM / 12.776 CUM. De esos, 11.801 IUM no están cargados como IUM en Gemma Net:

- **10.135:** todos sus CUM ya están cargados en Gemma Net como CUM.
- **1.628:** ninguno de sus CUM está cargado. Esos CUM ya los cubre el flujo CUM: 424 salen allá como `candidato` (287) o `cuarentena` (137), y 1.344 son muestra médica, que el SOP excluye.

**Qué se concluye**

1. **IUM de INVIMA e IUM de Gemma Net son la misma noción.** Tienen la misma forma y el cruce literal funciona en 52 de 90. La clave de cruce es el IUM literal, sin espacios y en mayúsculas. **Pero no es una llave 1:1:** un IUM agrupa varios CUM. Traducir IUM → CUM solo es seguro cuando INVIMA le asocia exactamente un CUM.
2. **En Gemma Net, una fila IUM es casi siempre una segunda identidad** de un medicamento que ya está cargado como CUM (55 de 57 activos). Es el hallazgo más fuerte de la auditoría IUM, más que la comparación de campos.
3. **Un "candidato IUM" no agrega ningún medicamento** que el flujo CUM no muestre ya. Lo único nuevo son unos 10.100 IUM que no tienen fila propia en Gemma Net. Eso solo es un hallazgo si el negocio decide que Gemma Net debe llevar una fila por IUM además de la del CUM.
4. **El acuerdo de campos es bajo** (principio activo 14 de 49). Antes de publicar veredictos hay que validar el instrumento: puede ser un defecto real o que las filas IUM usen otra convención de texto (ver `design/tipos_codigo_interno.md` §2: "PA + concentración + forma + vía + (marca) + presentación").
5. El "~9,3 %" del docstring de `invima_reader.py:22` es del corte 2022.

## Qué se reutiliza y qué hay que implementar, pieza por pieza

### Flujo de candidatos

| Pieza | Veredicto | Evidencia |
|---|---|---|
| `ingesta/*` (lectura de INVIMA y de Gemma Net) | Se reutiliza tal cual | La columna `IUM` ya llega (`invima_socrata.py` `CAMPOS_API["ium"]`, lector de Excel) |
| `invima_reader.mapa_ium()` (`:286`) | Se reutiliza como primer filtro | Hoy no lo llama nadie en `src/`, y su docstring cita un `flujo_ium` que no existe |
| `clasificar_codigos()` | Se reutiliza para validar la forma del IUM de INVIMA (`== "ium"`) | Evita duplicar la regex, que es privada en `_PATRONES_TIPO` |
| `malla.universo_invima_clasificado()` (`:41`) | Se reutiliza tal cual | La fase 2 del SOP es por fila de INVIMA, y una fila con IUM es una fila de INVIMA |
| `malla.candidatos_creacion()`: `DESCRIPCION = PA + UNIDAD_REFERENCIA` (`:85`) | **No aplica** | Las filas IUM de Gemma Net siguen otra convención. Requiere definición de negocio (D4) |
| `cruce_gemanet.leer_codigos_gemanet()` (`:175`) | Se reutiliza, comparando en mayúsculas | El patrón IUM acepta la letra en minúscula |
| `catalogos/resolver` + `pipeline._resolver_serie()` (`:86`) | Se reutiliza tal cual | La marca es el `TITULAR` y la unidad sale de `UNIDAD_MEDIDA`; los 52 cruzados tienen un solo titular |
| `filtro_integridad_estructural()` (`:41`), `es_error_excel()` | Se reutiliza tal cual | Son genéricos |
| `filtro_codigo_interno_valido()` (`validacion/reglas.py:83`) | Con cambios | Su motivo habla de EXPEDIENTE/CONSECUTIVO. Hace falta un `filtro_ium_valido` nuevo en el mismo archivo, con los mismos `Accion`/`ResultadoFiltro` |
| `filtro_cruce_invima()` (`:110`) | No aplica | Ni el flujo CUM lo usa hoy |
| `pipeline._reclasificar_duplicados()` (`:350`) | El concepto aplica y se amplía | Un IUM con 2 o más CUM, o con 2 o más principios activos, va a cuarentena. Nunca se fusiona ni se elige uno |
| Bucle `for fila in malla.to_dict("records")` (`pipeline.py:211`) | **No se copia** | El IUM se decide con máscaras (`np.select`) |
| `reglas_negocio`: las 22 constantes (`:74`) | Se reutiliza tal cual | |
| `reglas_negocio`: POS y MODELO_SERVICIO por EXPEDIENTE (`:100`, `:195`) | Con cambios | El EXPEDIENTE sale del CUM traducido. Un IUM con varios CUM de distinto expediente queda con `cierta=False` |
| `exportacion/cargue.py`, `estructura_cargue.py` | **No aplica hasta D5** | 79 de las 90 filas IUM existentes tienen EXPEDIENTE/CONSECUTIVO vacíos. No hay plantilla definida para una fila IUM |

### Auditoría: las dimensiones de `coherencia_invima.py:134-171`

| Dimensión | Veredicto |
|---|---|
| 1. Exactitud (los 7 campos) | Aplica solo a los IUM de un solo CUM, y **con la misma función** (la clave de cruce es el CUM traducido). `DESCRIPCION` va con cambios (D4): hasta definirla queda "sin comparar" y sale del denominador. `CONCENTRACION` sigue la decisión homónima de §4 |
| 2. Vigencia (cascada de listados) | Aplica sin cambios, vía el CUM traducido |
| 3. Consistencia de fechas ACTIVO | Tal cual. Ya se calcula hoy para estas 90 filas |
| 4. Completitud | Aplica, pero con 79 de 90 sin EXPEDIENTE: ¿es obligatorio en una fila IUM? (D5) |
| 5. Unicidad | Aplica, y aparece una nueva: **identidad duplicada IUM↔CUM** (55 de 57). `_detectar_fila_legada_duplicada()` (`:3016`) no sirve tal cual, porque busca la fila hermana dentro del mismo DataFrame y la auditoría IUM corre sobre un subconjunto |
| 6. Dominio, 7. Numérica, 9. Integridad referencial | Tal cual (son de auto-consistencia) |
| 8. Formato del código | Tal cual. La forma IUM está garantizada por cómo se arma el subconjunto |
| 10. Contraste de vigencia, 11. Fechas entre fuentes | Vía el CUM traducido |
| Prioridad en 5 niveles (`:1967`) | Con cambios. En un IUM con varios CUM diría "2_alto: no aparece en ningún listado", y es falso. Se blanquea y se reemplaza por el veredicto IUM |
| `TIPO_SIN_CORRESPONDENCIA` (`:2647-2657`) | No aplica: le diría "Código legado" a un IUM |
| Combinados → Garantía y Calidad (mecanismo §3.5) | Aplica vía el CUM traducido (17 de los 52 tienen 2 o más principios activos) |
| Las 7 calidades (`calidades.py`) y la cadena H1-H6 | **No se replican.** Con unas 80 filas darían 7 tarjetas casi en cero. Basta una tabla y un conteo por veredicto IUM |

## Volumen: ¿módulo completo o algo más liviano? (lo decide el usuario)

| Opción | Qué entrega | Filas reales | Costo |
|---|---|---|---|
| **A. Completo** | Auditoría IUM + candidatos IUM + Excel de cargue IUM, cada uno con backend, frontend y descarga | 90 filas auditables; 11.801 "candidatos" de los que 0 son medicamentos nuevos | Unos 12 archivos nuevos. El Excel de cargue no se puede terminar sin D2, D4 y D5 |
| **B. Por fases** (recomendada) | Fase 1: auditoría IUM completa. Fase 2: una tabla de **diagnóstico** de IUM de INVIMA contra Gemma Net, sin Excel de cargue, que se convierte en flujo de cargue solo si D2 dice que sí | Igual | Unos 8 archivos en la fase 1; la fase 2 es chica |
| C. Mínima | Solo buscar por IUM en "Consultar INVIMA" | — | Mínimo, pero no cumple "módulos distintos" |

Hay que tener en cuenta el plazo: el jueves 2026-10-01 a las 4pm, compartido con el problema del formato nuevo de INVIMA. La fase 1 de B entra; A completa no.

## Dónde vive cada pieza

Los archivos nuevos se quedan en sus capas y llevan el sufijo `_ium`. No se crea un paquete `ium/` aparte: eso rompería la separación `armado/` / `validacion/` / `auditoria/` / `exportacion/`.

| Archivo | Responsabilidad |
|---|---|
| `src/gemma_cum_loader/armado/indice_ium.py` (**nuevo**) | `indice_ium(listados) -> DataFrame`: una fila por IUM con `IUM`, `CUM_INVIMA` (lista), `N_CUM_INVIMA`, `N_PRINCIPIOS_ACTIVOS`, `LISTADOS`, `ESTADO_IUM` (`un_cum` / `varios_cum` / `mal_formado`). Lo usan los dos flujos. Va en `armado/` porque arma un universo, y `coherencia_invima` ya importa de `armado/` |
| `src/gemma_cum_loader/auditoria/coherencia_ium.py` (**nuevo**) | `auditar_coherencia_ium(reporte, listados, ...)`: filtra `ium`, traduce, llama a `auditar_coherencia()` con la clave alterna, sobrescribe los veredictos que no aplican y agrega la identidad duplicada |
| `src/gemma_cum_loader/auditoria/coherencia_invima.py` (**cambio chico**) | Nuevo parámetro `claves_cruce_alternas: Mapping[str, str] \| None = None`, aplicado justo después de `:2253-2260`. Es un **dict por `CODIGO_INTERNO`** y no una Series, porque `:2223` hace `reset_index` y una Series se desalinearía. Con `None`, el comportamiento es idéntico |
| `src/gemma_cum_loader/armado/candidatos_ium.py` (**nuevo**, fase 2) | Diagnóstico por IUM con `np.select` |
| `src/gemma_cum_loader/validacion/reglas.py` (**se agrega**) | `filtro_ium_valido()` |
| `src/gemma_cum_loader/pipeline_ium.py` (**nuevo**) | Orquesta los dos flujos IUM. Importa `_fuente`, `_resolver_serie`, `_resolver_marca` y `_resolver_unidad` de `pipeline.py`; no los copia |
| `worker/tareas.py`, `worker/almacen_snapshots.py` | Pasos nuevos y tablas `auditoria_ium` / `candidatos_ium` en `COLUMNAS_ESPERADAS` |
| `backend/app/routers/ium.py` (**nuevo**) + `descargas.py` | Lector delgado sobre `leer_tabla` |
| `frontend/src/vistas/ium.ts` (**nuevo**), `main.ts`, `api.ts`, `tipos.ts`, `pildoras.ts` | La vista |

## Pasos

### Fase 0: sin código (bloquea la fase 1)

- Respuestas de D1 a D7 (ver "Qué falta decidir").
- **Validar el instrumento:** revisar a mano 10 de los 49 IUM de un solo CUM con `PRINCIPIO_ACTIVO` distinto. Hay que saber si la diferencia es real o de convención antes de publicar veredictos.
- **Listo cuando:** las decisiones están anotadas en `design/reglas_negocio.md`, en una §16 IUM nueva y con §1 reescrita.

### Fase 1: auditoría IUM

**1. `armado/indice_ium.py`**

- Parte de `mapa_ium()`. Normaliza con `str.strip().str.upper()` y valida la forma con `clasificar_codigos(serie) == "ium"`.
- Agrega con `groupby`: `nunique` de CUM y de principio activo, y los listados. La lista de CUM se arma solo para `varios_cum` (1.140 grupos); no se hace un join por grupo sobre los 16.075.
- **Degradación explícita:** si ningún listado trae la columna `IUM`, o viene toda vacía, devuelve el índice vacío con `attrs["sin_fuente_ium"] = True`. Nunca un "no encontrado" masivo.
- **Listo cuando:** las pruebas del índice pasan. Medido sobre el snapshot real debe dar 16.075 IUM y 1.140 `varios_cum`.

**2. `coherencia_invima.py`: parámetro `claves_cruce_alternas`**

- `clave = clave.where(~codigo.isin(mapa.keys()), codigo.map(mapa))`, vectorizado.
- Se actualiza `design/mecanismos/auditoria_coherencia.md` con una §0 "clave de cruce".
- **Listo cuando:** la suite existente queda intacta y la prueba de equivalencia con `None` pasa.

**3. `auditoria/coherencia_ium.py`**

- El subconjunto `TIPO_CODIGO_INTERNO == "ium"` se calcula con `clasificar_codigos` sobre el reporte.
- El mapa se arma solo para `un_cum`. Los `varios_cum` y los no encontrados conservan **su propio IUM como clave**, que nunca calza con un CUM. Así quedan "sin correspondencia", con el trío en "sin comparar" y `PORCENTAJE_CALIDAD` en NaN, sin elegir nada.
- Se llama a `auditar_coherencia()` con **los listados completos, sin prefiltrar** (ver riesgos).
- Después de la llamada:
  - `CODIGO_INTERNO` queda con el IUM original.
  - Se agregan `ESTADO_IUM`, `CUM_INVIMA`, `N_CUM_INVIMA` e `IDENTIDAD_DUPLICADA`. Esta última se calcula con un `map` hash sobre las filas CUM del reporte completo, con `ACTIVO` de la hermana. Si el CUM aparece en más de una fila, se informa cuántas y no se elige una.
  - Se sacan `TIPO_SIN_CORRESPONDENCIA`, `CUM_RECONSTRUIDO`, `FILA_LEGADA_DUPLICADA` y `TIPO_CODIGO_INTERNO`.
  - Se blanquean `PRIORIDAD_ACCION`, `NATURALEZA_HALLAZGO` y `ACCION_SUGERIDA` cuando `ESTADO_IUM != "un_cum"`.
  - Se ignoran los `attrs["advertencias_calidad"]` orientados a CUM (`:2971-2980`).
- El orden importa: primero la traducción, luego la auditoría, luego las sobrescrituras, **al final**. Documentarlo en `design/mecanismos/modulo_ium.md` (**nuevo**).
- **Listo cuando:** las pruebas pasan. Sobre el snapshot real debe dar 49 `un_cum`, 3 `varios_cum` y 38 no encontrados.

**4. `pipeline_ium.py`**

- `auditar_coherencia_ium_gemanet(listados, reporte_gemanet, fuente_catalogos=...)`.
- **Listo cuando:** sin red y con el cliente inyectado.

**5. Worker (`worker/tareas.py`)**

- Paso "Revisando los IUM ya cargados" en `NOMBRES_PASOS_REFRESCO` (`:66`). Corre después de `_listados_invima_unificados` (`:383`), que hoy se calcula fuera de `_paso`: hay que moverlo antes.
- Nueva tabla `auditoria_ium` en `escribir_snapshot`.
- `auditor_ium` inyectable.
- Según D7: un `_paso_opcional` que registra el error en el progreso y escribe el snapshot CUM sin la tabla IUM.
- Se agrega `COLUMNAS_ESPERADAS["auditoria_ium"] = ("ESTADO_IUM", "CUM_INVIMA", "ESTADO_CUM_INVIMA", "ESTADO_LISTADO_INVIMA")`.
- **Listo cuando:** `.\reinicia_todo.ps1` termina y `desfases_de_esquema()` queda vacío.

**6. Backend**

- `routers/ium.py` con `prefix="/ium"`:
  - `GET /ium/auditoria` usando `paginar`, con los mismos parámetros que `candidatos.py:33-57`.
  - `/ium/auditoria/valores`.
  - `/ium/auditoria/resumen` (conteo por `ESTADO_IUM` y por `IDENTIDAD_DUPLICADA`).
  - Un 503 con texto de auditor si la tabla no existe. Si la falta es porque la fuente no trae IUM, el `detail` lo dice.
- Registrarlo en `backend/app/main.py:86-97` dentro de `protegido`.
- `descargas.py`: `/descargas/ium-auditoria` reutilizando `_tabla_o_503` y `_serializar_tabla_plana`.
- **Listo cuando:** las pruebas del backend pasan.

**7. Frontend**

- `vistas/ium.ts`, con `montarIumCargados`.
- `TablaFiltrable` con `idTabla: "ium_auditoria"` (la clave de caché usa `idTabla`, `cache_tablas.ts:104`).
- `etiquetasColumna = {...ETIQUETAS_COLUMNA_COMUNES, ...ETIQUETAS_IUM}`, con las etiquetas IUM en `pildoras.ts`.
- La píldora de `ESTADO_IUM` se lee del backend y no se recalcula.
- Tarjeta corta con el resumen y botón de descarga.
- `SECCIONES` según D6.
- Vocabulario: nada de "traducción", "clave", "snapshot" ni "índice". Ejemplos: "INVIMA lo asocia a un CUM", "INVIMA lo asocia a varios CUM, requiere decisión", "INVIMA no publica este IUM", "Duplica al CUM 20012345-1, activo".
- **Listo cuando:** `npx tsc --noEmit` pasa y `python scripts\ver_app.py ium cargados` se ve bien sin errores de consola. Si `ver_app.py` tiene una lista fija de vistas, se agrega ahí.

**8. Documentación**

- `reglas_negocio.md`: §1 y §16 nueva.
- `mapa_del_proyecto.md`: filas de los archivos nuevos y una fila "quiero cambiar la auditoría IUM → `coherencia_ium.py`".
- `mecanismos/modulo_ium.md` (nuevo) y `mecanismos/auditoria_coherencia.md` (§0).
- Docstrings de `invima_reader.py:22` y `:287`.
- `/bitacora` al cierre.

### Fase 2: candidatos IUM (solo si D2 lo pide)

**9. `armado/candidatos_ium.py`**

- `universo_invima_clasificado(df_invima)` y luego `indice_ium`.
- Una fila por IUM de Vigentes, con la acción decidida por `np.select` en este orden:
  1. `no_aplica`: ninguna de sus filas pasa la fase 2; se lleva la clasificación.
  2. `ya_existe`: el IUM está en los códigos de Gemma Net.
  3. `cuarentena`: mal formado, varios CUM, combinado, clasificación mixta o línea de Gemma Net no verificable.
  4. `candidato`.
- Columna `CUM_EN_GEMANET` (todos / algunos / ninguno) y `YA_ES_CANDIDATO_CUM`, para que nadie trabaje dos veces los 424.
- Marca y unidad con `_resolver_serie`, solo sobre los candidatos.

**10. Resto de la fase 2**

- Worker: paso "Revisando IUM por cargar" y tabla `candidatos_ium`.
- Router `/ium/candidatos` y descarga.
- Sub-vista `montarIumCandidatos`.
- **Sin Excel de cargue hasta D4 y D5.**

## Pruebas que deben existir

**`tests/test_indice_ium.py`**

- `test_indice_ium_un_ium_con_un_cum_queda_un_cum`
- `test_indice_ium_un_ium_con_varios_cum_queda_varios_cum_y_lista_todos`
- `test_indice_ium_combinado_cuenta_principios_sin_fusionar_filas`
- `test_indice_ium_normaliza_mayusculas_y_espacios`
- `test_indice_ium_valor_mal_formado_queda_marcado_no_descartado`
- `test_indice_ium_conserva_los_listados_donde_aparece`
- `test_indice_ium_sin_columna_ium_lo_dice_en_vez_de_devolver_vacio`

**`tests/test_coherencia_invima.py`** (se agregan)

- `test_claves_cruce_alternas_none_da_el_mismo_resultado`
- `test_claves_cruce_alternas_cruza_por_la_clave_dada`
- `test_claves_cruce_alternas_no_altera_codigo_interno_ni_tipo`
- `test_claves_cruce_alternas_con_indice_no_contiguo`

**`tests/test_coherencia_ium.py`**

- `test_auditar_ium_solo_toma_filas_tipo_ium`
- `test_auditar_ium_un_cum_compara_contra_la_fila_de_invima_de_ese_cum`
- `test_auditar_ium_varios_cum_no_elige_ninguno_y_queda_sin_comparar`
- `test_auditar_ium_no_encontrado_deja_porcentaje_vacio_no_cero`
- `test_auditar_ium_no_dice_codigo_legado`
- `test_auditar_ium_prioridad_vacia_si_no_es_un_cum`
- `test_auditar_ium_detecta_cum_hermano_activo_en_gemma_net`
- `test_auditar_ium_cum_hermano_repetido_informa_cuantas_filas`
- `test_auditar_ium_la_salida_lleva_el_ium_como_codigo_interno`
- `test_auditar_ium_usa_listados_completos_para_el_corte`

**`tests/test_pipeline_ium.py`**

- `test_auditar_coherencia_ium_gemanet_sin_red`

**`tests/test_worker_tareas.py`** (se agregan)

- `test_refresco_escribe_auditoria_ium_en_el_snapshot`
- `test_refresco_falla_ium_no_tumba_snapshot_cum` (si D7 = degradar)
- `test_tabla_auditoria_cum_identica_con_y_sin_modulo_ium`: es el invariante de §1

**`tests/test_backend_ium.py`**

- `test_ium_auditoria_503_sin_tabla`
- `test_ium_auditoria_503_dice_si_falta_la_fuente_ium`
- `test_ium_auditoria_pagina_filtra_y_busca`
- `test_ium_resumen_cuenta_por_estado`

**`tests/test_backend_descargas.py`**

- `test_descarga_ium_auditoria_trae_todas_las_filas`

**`tests/test_reglas.py`**

- `test_filtro_ium_valido_acepta_quince_caracteres`
- `test_filtro_ium_valido_manda_a_cuarentena_mal_formado`

**Fase 2, `tests/test_candidatos_ium.py`**

- `test_candidatos_ium_ya_cargado_es_ya_existe`
- `test_candidatos_ium_varios_cum_va_a_cuarentena`
- `test_candidatos_ium_combinado_va_a_cuarentena_sin_fusionar`
- `test_candidatos_ium_marca_si_su_cum_ya_es_candidato_cum`
- `test_candidatos_ium_no_pasa_fase_2_lleva_la_clasificacion`
- `test_candidatos_ium_orden_ya_existe_antes_que_cuarentena`

## Riesgos y trampas

- **No prefiltrar INVIMA a los CUM traducidos.** `_corte_catalogo_invima()` (`:1234`) toma el máximo de `FECHA_ACTIVO` del catálogo completo. Recortar el catálogo mueve la fecha de corte y cambia en silencio los veredictos de vigencia. Hay que pasar los listados completos, aunque el reporte sea de 90 filas.
- **Costo de ese llamado:** está dominado por el lado INVIMA (el `drop_duplicates` sobre 157 mil filas, las descripciones esperadas y los combinados sobre los 4 listados). Hay que medirlo en el refresco. Si pasa de unos 15 s, discutirlo antes de optimizar.
- **Ningún `apply` ni bucle por fila:**
  - La traducción es `Series.map` con un dict.
  - La hermana CUM es un `map` hash, como en `:3052`.
  - La decisión de candidatos va con `np.select`.
  - `clasificar_codigos` corre sobre las 423 mil filas de IUM de INVIMA y ya está vectorizado.
  - El único trabajo en Python por grupo es la lista de CUM de los 1.140 IUM ambiguos.
  - No se copia el bucle de `pipeline.py:211`.
- **Vigentes sin columna IUM.** El export nuevo del portal para Vigentes trae 10 columnas y no incluye `IUM` (ver `.ai/planes/2026-09-28-modulo-ium-y-fuentes-invima.md`). En ese caso `mapa_ium()` devuelve vacío (`:288-289`) y los 90 IUM saldrían "no encontrados". Por eso el paso 1 tiene que decir "sin fuente IUM" y el router responder un 503 que lo explique.
- **La `Series` de clave se desalinea.** `auditar_coherencia` hace `reset_index` (`:2223`); por eso la clave va como dict por `CODIGO_INTERNO`.
- **Las advertencias sobre el subconjunto cambian.** `_campos_sistemicamente_no_diligenciados` sobre 90 filas puede declarar sistemático un campo que en el universo CUM no lo es, y eso cambia `NATURALEZA_HALLAZGO`. Es correcto dentro del universo IUM, pero hay que documentarlo en `mecanismos/modulo_ium.md`.
- **Veredictos pensados para CUM que mienten sobre un IUM:** `TIPO_SIN_CORRESPONDENCIA` ("Código legado") y `PRIORIDAD 2_alto` en los ambiguos. Se sobrescriben al final, no en medio de la cascada.
- **El acuerdo de campos es bajo.** Publicar 49 "difiere" sin validar el instrumento repite el error ya documentado de medir con una fórmula que falla en casi el 100 % de las filas.
- **Un paso nuevo del worker que revienta** hoy tumba todo el refresco, snapshot CUM incluido (`tareas.py:314-414`). Se resuelve con D7.
- **Vite y el reinicio:** el frontend nuevo no se ve sin `.\reinicia_todo.ps1`. La tabla nueva falta hasta el primer refresco; como `desfases_de_esquema()` no marca tablas ausentes, el aviso lo tiene que dar el 503 del router.
- **Push:** según la nota de continuidad, todavía no hay acceso de escritura a `Sergiocampos95/Calidades-CUMS-INVIMA-VS-GEMANET`. El cierre (commit → fusión → push) puede quedar bloqueado; se resuelve por PR contra el fork, como el resto de esta sesión.

## Qué falta decidir

- **D1 Alcance.** A (completo), B (por fases) o C (mínima).
- **D2 ¿Gemma Net debe llevar una fila por IUM además de la del CUM?** De esto depende si los ~10.100 "IUM sin fila" son candidatos o no, y si las 55 filas IUM duplicadas son lo esperado o un hallazgo.
- **D3 IUM con varios CUM** (3 en Gemma Net, 1.140 en INVIMA): ¿cuarentena sin comparar, o comparar solo los campos iguales en todos sus CUM?
- **D4 `DESCRIPCION` de una fila IUM:** qué fórmula usar para crear y para auditar.
- **D5 `EXPEDIENTE` / `CONSECUTIVO` en una fila IUM:** ¿obligatorios? Afecta la completitud y la plantilla de cargue.
- **D6 Pantalla:** una sección "IUM" con dos sub-vistas y grupo propio, o repartir en los dos grupos existentes.
- **D7 Si el paso IUM falla:** ¿tumba el refresco o se degrada y el módulo CUM sigue?
- **D8 Riesgo de la identidad duplicada.** El caso IUM activo + CUM inactivo, ¿es riesgo como el legado ATC o solo informativo?

## Resumen para el usuario (del agente arquitecto)

Medí los datos: Gemma Net tiene 90 IUM (79 activos) e INVIMA publica IUM en el 20,9 % de Vigentes.

- **Sí son el mismo código en las dos fuentes.** 52 de los 90 IUM de Gemma Net aparecen tal cual en INVIMA. Pero un IUM puede agrupar varios CUM (1.140 casos en INVIMA, 3 de los de Gemma Net), así que no siempre se puede ubicar un único registro contra el cual comparar.
- **Casi todo IUM cargado duplica un CUM.** De los CUM que corresponden a esos IUM, 56 de 57 ya están cargados en Gemma Net como CUM, 55 activos. Ese es el hallazgo más fuerte que tendría el módulo.
- **"Candidatos IUM" no trae medicamentos nuevos.** Todo medicamento con IUM que falta ya lo muestra el flujo de CUM, o es muestra médica. Solo quedarían unos 10.100 IUM "sin fila propia", y eso importa únicamente si el negocio quiere que Gemma Net tenga una fila por IUM además de la del CUM.
- **Parte de lo del CUM se reutiliza, parte no.** La lectura de fuentes, la resolución de marca y unidad, los filtros de estructura y la comparación campo a campo sirven, ubicando el IUM a través de su CUM. No sirven la fórmula de descripción, el Excel de cargue, las 7 tarjetas de calidad ni la cadena H1-H6.
- **El acuerdo de campos es bajo** (el principio activo coincide en 14 de 49), así que conviene revisar casos a mano antes de publicar veredictos.
- **La aplicación hoy dice por escrito que solo audita CUMs.** Habría que actualizar esa regla, dejando claro que las cifras de CUM no cambian.

Recomendación del arquitecto en cada decisión:

1. **Alcance:** por fases (B) — primero auditoría IUM, que alcanza para el jueves; candidatos IUM después.
2. **¿Fila IUM propia en Gemma Net?** preguntarlo a Garantía y Calidad o a Hugo antes de construir candidatos IUM.
3. **IUM con varios CUM:** dejarlos "requiere decisión" sin comparar — son 3 casos, elegir uno sería adivinar.
4. **Descripción de una fila IUM:** no compararla hasta que el negocio la defina.
5. **Expediente/consecutivo obligatorios:** informar la ausencia sin tratarla como falla, por ahora.
6. **Pantalla:** una sola entrada "IUM" con dos sub-vistas.
7. **Si el cálculo IUM falla:** que el módulo CUM siga funcionando igual.
8. **IUM activo con CUM inactivo:** tratarlo como riesgo, igual que los códigos legados.
