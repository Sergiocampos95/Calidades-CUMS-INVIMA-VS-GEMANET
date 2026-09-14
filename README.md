# Gemma CUM Loader

Automatiza el cargue y la auditoría de medicamentos **CUM/IUM** entre el catálogo
oficial de **INVIMA** y la plataforma **Gemma Net** (Pijao Salud EPSI).

El programa responde dos preguntas distintas, y es importante no confundirlas:

| Pregunta | Flujo | Pestaña / comando |
|---|---|---|
| ¿Qué medicamentos de INVIMA **me faltan** por cargar? | Candidatos | *Resumen de resolución* / `candidatos` |
| De lo que **ya está cargado**, ¿qué está mal o desactualizado? | Auditoría | *Auditoría de coherencia* / `auditoria` |

---

## 1. Instalación

Requiere **Python 3.12+**.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"
```

Opcional — token de la API de INVIMA (evita el límite de peticiones anónimas):

```bash
set INVIMA_SOCRATA_APP_TOKEN=tu_token   # Windows
```

Se obtiene gratis en <https://www.datos.gov.co> (Sign up → Developer Settings).
**Sin token el programa funciona igual**, solo con un límite de peticiones más bajo.

---

## 2. Archivos que necesitas

### Obligatorio

**Reporte de Gemma Net** (`.xlsx` o `.txt`) — es la foto de lo que ya está cargado.

> Gemma Net → *Mantenimientos › Básicas Atención › Medicamentos › Crear Masivos › Exportar*

### Catálogo INVIMA — por API o por archivo

La aplicación trae el catálogo vigente **en vivo desde la API** de datos.gov.co; no
necesitas descargar nada. Si la API está caída (pasa con cierta frecuencia), usa la vía
de respaldo: descarga el Excel de invima.gov.co → *Consultas, registros y documentos
asociados* y súbelo a mano.

| Dataset | ID Socrata | ¿Para qué sirve? |
|---|---|---|
| Vigentes | `i7cb-raxc` | Base de todo. **Obligatorio.** |
| Vencidos | `vwwf-4ftk` | Detectar registros vencidos — riesgo alto |
| Trámite de Renovación | `vgr4-gemg` | Riesgo medio, informativo |
| Otros Estados | `spzp-dfuc` | Cancelado / Suspendido / Inactivo — riesgo alto |

Los **tres últimos son opcionales e independientes**. Si no los cargas, la auditoría
corre igual: los códigos que no aparezcan en Vigentes simplemente caen todos en
"sin correspondencia" sin poder distinguir *por qué*. Nunca se asume nada en silencio.

### Opcional — Estructura de Cargue

`Estructura Cargue Medicamentos ultimo mixto.xlsx`. Solo se usa como referencia para
completar los campos que **no existen en INVIMA** porque son reglas de negocio propias
de Pijao Salud: edades, copagos, cuota moderadora, modelo y nivel de servicio.

Sin este archivo el resumen y la cuarentena funcionan igual, pero **no se puede generar
el Excel de cargue final**.

---

## 3. Uso con interfaz (recomendado)

```bash
streamlit run ui_revision/app_streamlit.py
```

Sube los archivos, presiona **Procesar**, y trabaja sobre las 6 secciones del menú
lateral (agrupadas en "candidatos para cargue" y "medicamentos ya cargados"):

1. **Resumen de resolución** — cuántos candidatos nuevos salieron y cómo se resolvieron
   marca y unidad de medida contra el catálogo interno. Dos vistas: *Resumen* y
   *Detalle por registro* (la sub-vista *Cómo se resolvió* se retiró el 2026-09-14:
   mostraba el método técnico de traducción y no le daba nada que hacer al auditor).
2. **Casos que requieren decisión** — lo que el sistema **no** se atrevió a decidir
   solo. Cada fila trae el motivo y compara `_texto_invima` (dato oficial) contra
   `_sugerencia` (coincidencia aproximada, nunca confirmada).
3. **Cargue a Gemma Net** — genera el Excel final listo para subir a la plataforma.
   Dos vistas: *Auditoría de estructura* (todos los candidatos, listos y pendientes,
   para repartir el trabajo manual) y *Excel de cargue final* (solo lo listo).
4. **Por qué no se cargó** — vista por CAMPO, no por flujo: elige un campo puntual
   (marca, unidad, POS...) y ve exactamente qué medicamentos fallan en él, separando
   candidatos nuevos de los ya cargados con diferencias frente a INVIMA.
5. **Consultar INVIMA** — consulta puntual de un EXPEDIENTE-CONSECUTIVO contra la API,
   sin pasar por el proceso masivo.
6. **Auditoría de coherencia** — el informe de calidad de lo ya cargado (sección 5).
   Tres vistas: *Priorizar lo que requiere acción*, *Entender la calidad del catálogo*,
   *Explorar todos los hallazgos*.

Todas las tablas tienen búsqueda libre y filtros; ninguna se muestra en crudo. Las
descargas de listas completas son de dos pasos (**Preparar** → **Descargar**): generar
el Excel es lo más lento de cada vista, así que solo se paga ese costo si de verdad
vas a bajarlo.

### Casos de uso frecuentes

| Necesito... | Uso |
|---|---|
| Saber qué medicamentos de INVIMA todavía no están en Gemma Net | *Resumen de resolución* → *Resumen* (métrica "Candidatos a crear") |
| Ver, uno por uno, por qué INVIMA sí/no dio candidato | *Resumen de resolución* → *Detalle por registro* |
| Entender por qué un candidato puntual quedó pendiente de decisión humana | *Casos que requieren decisión* → busca el `CODIGO_INTERNO` o filtra por `motivo` |
| Saber si un medicamento activo aquí perdió vigencia en INVIMA (riesgo real de autorización) | *Auditoría de coherencia* → tarjeta "activo(s) aquí sin vigencia en INVIMA" — el ícono **❓** trae el dato exacto de ambos lados, no hace falta salir a verificar a mano |
| La lista exacta de qué campo (marca, unidad, POS...) le falta a cada medicamento, para repartir el trabajo | *Por qué no se cargó* → elige el campo, filtra, descarga |
| Verificar un EXPEDIENTE-CONSECUTIVO puntual sin correr todo el proceso | *Consultar INVIMA* |
| Preparar el archivo para que Autorizaciones confirme y complete a mano | *Cargue a Gemma Net* → *Auditoría de estructura* → Preparar/Descargar |
| El Excel final ya confirmado, listo para subir a Gemma Net | *Cargue a Gemma Net* → *Excel de cargue final* → Preparar/Descargar |
| Cambiar de archivo/fuente sin perder la corrida actual en pantalla | Botón **"Cambiar fuente de datos"** (arriba, junto a la fuente usada) → *Procesar* de nuevo |
| Repetir la misma corrida sin esperar minutos otra vez | No hace falta nada: si los archivos de origen no cambiaron, la corrida se lee de una caché en disco en vez de recalcularse |

---

## 4. Uso por línea de comandos

Útil para lotes programados o servidores sin navegador.

```bash
# ¿Qué me falta por cargar?
gemma-cum-loader candidatos --api \
    --gemma-net data/LISTADO_MEDICAMENTOS.xlsx \
    --salida candidatos.xlsx

# Auditoría completa, con los 3 datasets auxiliares
gemma-cum-loader auditoria \
    --invima data/ListadoCodigoUnicoVigentes2022.xlsx \
    --gemma-net data/LISTADO_MEDICAMENTOS.xlsx \
    --vencidos data/ListadoCodigoUnicoVencidos.xlsx \
    --renovacion data/ListadoCodigoUnicoRenovacion.xlsx \
    --otros-estados data/ListadoCodigoUnicoOtrosEstado.xlsx \
    --salida auditoria.xlsx
```

`--api` y `--invima` son intercambiables en ambos comandos. La salida es un `.xlsx`
con **una hoja por estado**, para repartir el trabajo por tipo de hallazgo.

---

## 5. Cómo leer la auditoría

### Estado de vigencia (de mayor a menor riesgo)

Cada código se evalúa en cascada; solo se pasa al siguiente si el anterior no aplicó:

| Estado | Qué significa | Acción |
|---|---|---|
| `vencido_en_invima` | El registro sanitario **expiró** | 🔴 Riesgo directo de autorización |
| `encontrado_en_otro_estado_invima` | Cancelado / Suspendido / Inactivo | 🔴 Ver `ESTADO_INVIMA_DETALLE` |
| `en_tramite_renovacion_invima` | Renovación en curso | 🟡 Seguimiento, no bloqueante |
| `con_diferencias` | Existe y coincide, pero algún campo difiere | 🟡 Actualizar el dato |
| `correcto` | Todo coincide con INVIMA | ✅ |
| `sin_correspondencia_invima` | No aparece en ningún dataset | Ver abajo |

**"Sin correspondencia" no es un solo problema.** La columna `TIPO_SIN_CORRESPONDENCIA`
separa dos poblaciones muy distintas:

- **Con formato EXPEDIENTE-CONSECUTIVO pero no encontrado** → posible error de digitación
  o registro anulado. *Vale la pena revisarlos uno por uno.*
- **Código legado** (texto libre, sin formato INVIMA) → nunca tuvo expediente asociado.
  *No hay nada que verificar contra INVIMA.*

### Las 9 dimensiones de calidad

Cada una es un mensaje accionable, no solo un indicador:

| # | Dimensión | Columna | Qué detecta |
|---|---|---|---|
| 1 | Exactitud | `CAMPOS_CON_DIFERENCIA`, `PORCENTAJE_CALIDAD` | Campos que no coinciden con INVIMA |
| 2 | Vigencia | `ESTADO_COHERENCIA`, `ESTADO_INVIMA_DETALLE` | Registro sanitario vencido o irregular |
| 3 | Consistencia | `INCONSISTENCIA_FECHAS_ACTIVO` | ACTIVO vs FECHA_INICIO/FECHA_FIN no cuadran |
| 4 | Completitud | `PORCENTAJE_COMPLETITUD_REPORTE` | Cuántos de los 37 campos están diligenciados |
| 5 | Unicidad | `CODIGO_DUPLICADO_EN_REPORTE` | CODIGO_INTERNO repetido |
| 6 | Validez de dominio | `VALORES_FUERA_DE_DOMINIO` | CLASIFICADO / POS / ACTIVO con valores inválidos |
| 7 | Razonabilidad | `INCONSISTENCIA_NUMERICA` | Edades y topes fuera de orden lógico |
| 8 | Formato | `FORMATO_CODIGO_INTERNO_INVALIDO` | Código vacío o error de fórmula de Excel |
| 9 | Integridad referencial | `INTEGRIDAD_REFERENCIAL_CATALOGO` | Código de marca/unidad que no existe en el catálogo interno |

`PORCENTAJE_CALIDAD` queda **vacío** (no en 0%) cuando no hay correspondencia con
INVIMA: no hay nada que comparar, y eso no es lo mismo que "0% de calidad".

**La descripción de INVIMA se arma, no se publica.** Para compararla, la auditoría
la construye con `PRINCIPIO_ACTIVO + CANTIDAD+UNIDAD_MEDIDA + FORMA_FARMACEUTICA`
(como la guarda la plataforma) y acepta también `PRINCIPIO_ACTIVO + UNIDAD_REFERENCIA`
(como dicta la guía de actualización de CUMS); coincide si la de Gemma Net iguala
cualquiera de las dos, sin distinguir mayúsculas, tildes, puntos ni espacios. La
columna `DESCRIPCION_INVIMA` muestra la forma con la que se comparó. Detalle y
cifras en `design/reglas_negocio.md` §4.

### `-999` significa "sin dato"

Gemma Net usa `-999` como centinela de campo vacío. Medido sobre el reporte real de
producción (199.689 filas):

| Campo | % con `-999` |
|---|---|
| `POSOLOGIA` | 99,9 % |
| `EXPEDIENTE` | 0,8 % |
| `CONSECUTIVO` | 0,8 % |
| `CODIGO_ATC` | 0,5 % |
| `CONCENTRACION` | 0,2 % |

Cuando un campo entero supera el **90 % sin dato**, el programa lo reporta como
**problema de proceso**, no como miles de hallazgos sueltos:

> ⚠ El campo POSOLOGIA no trae dato real en el 99,9 % de las filas de este reporte —
> parece no estarse diligenciando en el proceso de origen.

---

## 6. Cómo se decide cargar o no un medicamento

Un candidato pasa por dos etapas independientes.

**Etapa 1 — clasificación del universo INVIMA** (`armado/malla.py`). Solo llegan a
candidato las filas que superan todos los filtros:

`rol_no_fabricante` · `cum_inactivo` · `registro_no_vigente` · `muestra_medica` → descartadas.

**Etapa 2 — validación por fila** (`validacion/reglas.py`). La columna `accion` del
reporte toma tres valores:

| Acción | Significado |
|---|---|
| `candidato` | Nuevo y listo para cargar |
| `ya_existe` | Su CODIGO_INTERNO ya está en Gemma Net — no hay nada que hacer |
| `cuarentena` | **El sistema no decide solo** — requiere criterio humano |

La cuarentena es deliberada. Tres casos reales la disparan:

- **CODIGO_INTERNO inválido** — cuando EXPEDIENTE o CONSECUTIVO traen un error de
  digitación, pandas los vuelve `NaN` y la llave de la fila se rompe *en silencio*.
- **Error de fórmula de Excel** (`#N/A`, `#NAME?`) guardado como texto: pasa cualquier
  chequeo de "campo no vacío" pero no es un dato usable.
- **CODIGO_INTERNO duplicado entre candidatos** — normalmente un medicamento combinado
  con varios principios activos. **No se fusionan a ciegas**, porque eso perdería un
  principio activo; decide negocio.

### Resolución de marca y unidad

Gemma Net guarda marca y unidad como **códigos**, no como texto. La resolución contra
`config/catalogos/` es una cascada:

**exacto → alias → aproximado (fuzzy) → sin resolver**

Lo que queda en `sin_resolver` no se adivina: la fila llega con sugerencias
(texto, puntaje y código) para que una persona confirme.

Es 100 % determinística y **nunca depende del modelo de IA** — con 200.000 filas tiene
que ser exacta y rápida, sin llamadas de red.

### El SOP manual que esto reemplaza

Antes de esta aplicación el proceso se hacía a mano en Excel, por fases numeradas.
**El documento original del SOP no está en este repositorio**: lo que sigue es todo lo
que quedó registrado, reconstruido desde los docstrings del código.

| Fase | Qué hacía | Dónde está la regla hoy |
|---|---|---|
| 2 | **Depuración**: `ESTADO_CUM=Activo`, `TIPO_ROL=FABRICANTE`, `ESTADO_REGISTRO=Vigente`, y excluir muestra médica | `armado/malla.py` |
| 4 | **Código interno**: `COD_MEDICAMENTO_INVIMA` si el corte la trae; si no, `EXPEDIENTE-CONSECUTIVO` | `ingesta/invima_reader.py` |
| 5 | **Descripción**: `PRINCIPIO_ACTIVO + UNIDAD_REFERENCIA` | `armado/malla.py` |
| 6 | **Cruce contra Gemma Net** — reemplaza el BUSCARV manual contra el archivo exportado | `armado/cruce_gemanet.py` |
| 10 | **Nombre del archivo del período**: `Vigente_MMYYYY` (mes con cero a la izquierda, año de 4 dígitos, sin separador — ej. `Vigente_082026`) | `exportacion/estructura_cargue.py` |

> **Fases 1, 3, 7, 8 y 9: sin registrar.** No están ni en el código ni en esta
> documentación. Quien conozca el procedimiento completo debería completarlas aquí —
> hoy solo existen en la memoria de quien lo ejecutaba a mano.

**La fase 5 tiene un problema abierto.** Esa fórmula es la que la auditoría usa para
construir la descripción esperada, y no coincide con lo cargado en Gemma Net en
**ninguno** de los medicamentos que sí tienen correspondencia con INVIMA (43.266 de
43.266 en la corrida del 2026-08-20). Un campo que falla en el 100 % de los casos no
son datos malos: o la fase 5 cambió y el código no se actualizó, o Gemma Net nunca
guardó la descripción así. Sin el SOP escrito no hay contra qué contrastarlo.

---

## 7. El papel de la IA

| | |
|---|---|
| **Modelo** | Claude Haiku 4.5 (`claude-haiku-4-5`) |
| **Qué hace** | Traduce un motivo técnico a lenguaje de negocio |
| **Qué NO hace** | No resuelve códigos, no decide cargues, no toca la cascada |

> **Desactivada en la interfaz desde 2026-08-26** — a pedido explícito ("de momento no
> se requiere"). `ClienteExplicacionIA`, `explicar_motivo()` y `explicar_fila()` siguen
> en el código, solo sin un botón que los llame; reactivarla es agregar de vuelta la
> sub-vista en `ui_revision/app_streamlit.py` (`SUBVISTAS_POR_SECCION`).

El costo se mantiene constante a cualquier volumen porque `explicar_motivo()` se llama
**una vez por motivo distinto**, no una vez por fila — el vocabulario de motivos es fijo
y pequeño. `explicar_fila()` sí manda datos de una fila puntual, pero solo cuando el
usuario presiona *"Explicar este caso"*, nunca en el lote automático.

Si la API de IA falla, se muestra un mensaje de respaldo y **la revisión del resto de la
bandeja sigue funcionando**. Requiere `ANTHROPIC_API_KEY`; sin ella todo lo demás opera
con normalidad.

---

## 8. Estructura del proyecto

```
src/gemma_cum_loader/
├── ingesta/        Lectura de INVIMA (Excel y API Socrata)
├── armado/         Candidatos, cruce con Gemma Net, reglas de negocio
├── catalogos/      Resolución de códigos (cascada) + cliente de IA
├── validacion/     Motor de reglas: acepta/rechaza/descarta/cuarentena
├── auditoria/      Coherencia contra INVIMA + 9 dimensiones de calidad
├── exportacion/    Generación del Excel de cargue
├── normaliza/      Normalización de texto y códigos
└── pipeline.py     Orquestación end-to-end

ui_revision/app_streamlit.py    Interfaz
config/catalogos/               Catálogos internos (CSV)
tests/                          261 pruebas
```

Los catálogos internos son editables a mano: `unidad_medida.csv` (59 entradas),
`marca_medicamento.csv` (894), `modelo_servicio.csv` (60), `alias_unidades.csv`.
Cuando la auditoría reporta un código huérfano (dimensión 9), el arreglo es agregarlo
a estos archivos.

---

## 9. Rendimiento real

Medido contra los archivos reales de producción (INVIMA Vigentes 13 MB + Gemma Net
34 MB) el 2026-08-19:

| Flujo | Filas | Tiempo | Resultado |
|---|---|---|---|
| `auditoria` | 199.689 | ~3 min | 156.423 sin correspondencia · 43.266 con diferencias |
| `candidatos` | 47.767 | ~1 min | 47.766 ya existen · 1 candidato nuevo |

Dos lecturas útiles de esos números:

- **El catálogo ya está prácticamente completo** — de 47.767 filas evaluadas solo 1 era
  un medicamento nuevo por cargar. El valor del programa hoy está más en la auditoría
  que en el cargue masivo.
- **Ninguna fila salió `correcto`**: las 43.266 con correspondencia real en INVIMA
  tenían al menos un campo distinto. Es el hallazgo de fondo que justifica la auditoría.

Casi todo el tiempo es lectura de Excel, no cómputo. Los archivos pesan decenas de MB y
`data/` está en `.gitignore` — nunca subas datos de producción al repositorio.

---

## 10. Desarrollo

```bash
pytest                                    # 261 pruebas
ruff check src/ tests/ ui_revision/       # lint
```

Convenciones del código:

- **Comentarios que explican el *porqué*, no el *qué*.** Varios documentan hallazgos
  reales contra datos de producción (`-999`, hojas de Excel mal nombradas, medicamentos
  combinados) — son la memoria del proyecto, no ruido.
- **Degradación explícita, nunca suposición silenciosa.** Si falta un archivo auxiliar,
  se dice; no se asume un valor.
- **Sin decisiones a ciegas.** Lo ambiguo va a cuarentena, no se resuelve adivinando.


---

## Despliegue en Linux (servicio, red de la oficina)

Desde el 2026-09-14 la aplicación corre como **servicio en el servidor Linux** y la
usan otras áreas desde `http://<host>:8870`. Un solo puerto: la API FastAPI sirve
también el frontend compilado. Diseño completo en
`.ai/planes/2026-09-14-servidor-login-listados.md`.

| Pieza | Qué es | Cómo |
|---|---|---|
| Listados de INVIMA | Los 4 `.xlsx` mensuales, leídos de una **carpeta del servidor** | `INVIMA_LISTADOS_DIR` (defecto `~/gemanet/invima`). Se dejan ahí; la app **no** tiene subida de archivos y la fuente API está deshabilitada (`FUENTES_HABILITADAS`) |
| Login | Usuario y clave de **GemaNet** (`administrativo.usuario` vía Tableros_BI), calcado del dashboard de Auditoría de Calidades | Entra un administrador del ERP o quien tenga el módulo **`CUMS`**, que un administrador asigna en **Administración › Permisos de acceso** de esta misma app (o en Auditoría de Calidades › Permisos: es la misma tabla). 5 intentos fallidos = 15 min de bloqueo. "Actualizar ahora" es solo para administradores |
| Servicios | `gemanet-cums-worker` (refresco cada 50 min) y `gemanet-cums-api` (puerto 8870), `systemd --user` con reinicio automático | `deploy/instalar.sh` una vez; luego `sudo loginctl enable-linger $USER` para que arranquen al reiniciar la máquina |
| Configuración | `~/.config/gemanet_cums/env` (modo 600, fuera del repo) | Variables en `deploy/env.example`: DSN, `SECRET_KEY`, carpeta, límites del login |

**Instalar / actualizar:**

```bash
python3 -m venv --without-pip .venv && pip3 --python .venv/bin/python install -e ".[dev]"
cd frontend && npm install && npm run build && cd ..          # Node 24 (nvm)
export GEMANET_DB_DSN='postgresql://...'                      # una vez, para el instalador
deploy/instalar.sh
# tras cambios de codigo:
git pull && cd frontend && npm run build && cd .. && systemctl --user restart gemanet-cums-api gemanet-cums-worker
journalctl --user -u gemanet-cums-api -f                      # logs
```

`reinicia_*.ps1` siguen siendo los scripts de desarrollo en Windows; en el servidor
no aplican.
