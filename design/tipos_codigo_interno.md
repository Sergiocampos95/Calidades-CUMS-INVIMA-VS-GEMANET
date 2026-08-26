# Qué hay realmente dentro de CODIGO_INTERNO

Catálogo de los tipos de estructura de `codigo_interno` que existen en
`administrativo.tb_medicamento` (Gemma Net), más allá del binario `cum`/`ium`
que distingue `normaliza/codigos.py` hoy. Investigación pura contra la base
real, sin tocar código de la aplicación — hecha el 2026-08-26 a pedido
explícito del negocio, después de confirmar manualmente que la auditoría de
coherencia evalúa bien un caso real (SALBUTAMOL SULFATO, expediente
`20083667-1`).

## Por qué existe este documento

`clasificar_codigo()` hoy solo sabe decir "es CUM" (patrón estricto
`EXPEDIENTE-CONSECUTIVO`) o "no lo es" — y todo lo que no es CUM cae en un
catch-all llamado `"ium"`. Ese catch-all resultó tener **199.463 filas de
1/3 de la tabla completa** con estructuras muy distintas entre sí: un IUM de
verdad es apenas el 0,04 % de eso. Este documento cataloga qué hay realmente
adentro, con evidencia medida contra producción, para que una futura
extensión de `codigos.py` tenga con qué trabajar en vez de adivinar.

**Nada de esto está implementado todavía.** Es investigación para decisión
de diseño futura.

## Método y alcance

- Base: `muzna`, esquema `administrativo`, vía `gemanet_db.consultar`
  (solo lectura, `statement_timeout`, tope de filas — nunca más de 30 filas
  de salida por consulta; las de barrido devuelven agregados).
- Población medida: `administrativo.tb_medicamento`, **199.611 filas**
  (2026-08-26). `codigo_interno` es único en la tabla base (199.611 valores
  distintos sobre 199.611 filas, 0 con espacios al borde) — la duplicación
  de `CODIGO_INTERNO` que sí existe en el reporte de Gemma Net no nace en
  esta tabla; nace aguas abajo (join o export). No se investigó más a fondo.

### Señales de la base descartadas antes de usar patrones de texto

| Señal | Veredicto | Evidencia |
|---|---|---|
| `grupo_medicamento` | Inútil | `tb_grupo_medicamento` tiene 1 sola fila ("SIN INFORMACIÓN"); las 199.611 filas apuntan a ella |
| `codigo_dci` | Columna muerta | 0 filas con dato en toda la tabla |
| `sw_muestra_magistral` | Casi muerta | 1 fila en `1` |
| `sw_mixto` | Marginal | 398 filas en `1`, no separa ninguna categoría |
| `forma_farmaceutica` | Útil como señal indirecta, no como tipo | Poblada en 99,65 % de la forma CUM; **NULL en el 100 %** de la familia ATC (ver más abajo) |
| `sw_activo` | Muy útil | Parte la tabla en dos mundos, ver tabla siguiente |

| Grupo | Filas | `sw_activo=1` |
|---|---|---|
| Forma CUM `^\d+-\d+$` | 133.367 | 55.572 |
| Familia ATC+expediente+consecutivo | 64.779 | **0** |
| Todo lo demás | 1.465 | 156 |

**Hallazgo de estructura:** Gemma Net sí separa catálogos por naturaleza —
existen `tb_cup` (19.622 filas, procedimientos), `tb_insumo` (175.155 filas)
y `tb_paquete` (vacía). Lo que aparece con esa naturaleza *dentro* de
`tb_medicamento` es contaminación entre catálogos, no diseño intencional.

## Las 8 categorías (6 buscadas + 2 encontradas de más)

| # | Categoría | Filas | % | Confirmación |
|---|---|---:|---:|---|
| 1 | CUM (`EXPEDIENTE-CONSECUTIVO`) | 133.367 | 66,81 % | Ya conocida (`es_cum()`) |
| 1b | CUM con sufijo ATC | 147 | 0,07 % | Nueva — expediente vive solo dentro del código |
| +7 | Familia ATC+expediente+consecutivo | 64.779 | 32,45 % | Nueva — no estaba en la hipótesis original |
| 2 | IUM propiamente dicho | 85 | 0,04 % | Patrón propio confirmado |
| 3 | Códigos propios de Pijao/Gemma Net | ~900 | 0,45 % | 4 sub-familias |
| 4 | Paquetes | 3 (por texto) | — | Sin señal estructural, solo texto |
| 5 | Insumos | 11 duros / ~69 por texto | — | Cruce contra `tb_insumo` |
| 6 | CUPS | 21 duros / ~45 por texto | — | Cruce contra `tb_cup`, contra lo esperado |

Suma exacta de la clasificación por regex: 199.611 filas.

### 1. CUM — confirmada

133.367 filas. Ejemplos: `20083667-1`, `19950313-8`, `20015009-18`,
`222200-1`. Expediente de 8 dígitos en el 78,6 % de los casos (5, 6, 7, 4, 9
y 10 dígitos cubren el resto).

**Sospecha sin confirmar:** expedientes que parecen inventados
(`222200-1..6`, `33333-1..2`, `55550-1..4`, `55553-5..24`), todos con
`valor = 1.0000` y descripción genérica. Pasan `es_cum()` pero difícilmente
crucen contra INVIMA real. Requiere cruzar contra el catálogo INVIMA para
confirmar — una heurística de "dígito repetido" da falsos positivos
(`20015555` puede ser un expediente legítimo).

### 1b. CUM con sufijo ATC — nueva, corrige una clasificación real

147 filas, **48 activas**. Patrón:
`EXPEDIENTE(8, cero-relleno)-CONSECUTIVO(2, cero-relleno)-0ATC(7)`.

```
00009811-01-0M01AE01  ::  IBUPROFENO 200 MG                    (activo)
00017702-01-0A11AA03  ::  PEDIASURE X 400GR                    (activo)
00046068-04-0D04AX98  ::  CALADRYL LOCION
00206777-01-0H03AA01  ::  EUTIROX 125 MCG
```

143 de las 147 tienen `expediente = '-999'` en la columna dedicada — el
expediente solo existe parseando el código. Hoy `clasificar_codigo()` las
manda a `"ium"` y el cruce contra INVIMA no las ve, aunque son CUM
perfectamente reconstruibles. **Es la corrección con más valor por línea.**

### +7. Familia ATC+expediente+consecutivo — el hallazgo grande

64.779 filas, **un tercio de la tabla completa**. Fórmula medida:
`codigo_interno = codigo_atc || RIGHT(expediente, 6) || consecutivo`
(cumple en 99,8 % de los casos con expediente/consecutivo numéricos).

```
V10XX029556981   ::  ZEVAMAB®                    (ATC V10XX02, exp 19955698, cons 1)
V10XA022291221   ::  MIBG- 131- T                 (ATC V10XA02, exp 229122, cons 1)
B02BD072267491   ::  TISSUCOL® KIT ADHESIVO BIOLOGICO DE DOS COMPONENTES
```

Tres señales independientes confirman que es una capa legada apagada, no
199.463 hallazgos sueltos:
1. **0 de 64.779 activas.**
2. `forma_farmaceutica` NULL en el 100 %.
3. **90,2 %** ya existe en la misma tabla como fila CUM `EXPEDIENTE-CONSECUTIVO`
   independiente (gemelo duplicado, apagado).

### 2. IUM propiamente dicho — confirmada, con patrón propio

85 filas, **74 activas**. Patrón medido sobre las 85: exactamente 15
caracteres, `^[0-9][A-Za-z][0-9]{13}$`. La letra en posición 2 coincide con
la inicial del principio activo en 79/85 (92,9 %). Descripción normalizada:
`PRINCIPIO ACTIVO + CONCENTRACIÓN + FORMA FARMACÉUTICA + VÍA + (MARCA) + PRESENTACIÓN`.

```
1C1016781003102  ::  CEFAZOLINA 1000mg/1 U POLVOS PARA RECONSTITUIR INTRAMUSCULAR INTRAVENOSA (NORSTRAY NUART) VIAL 1 U/CAJA X 50
1V1019601002100  ::  VASOPRESINA 20UI/1 ml OTRAS SOLUCIONES INTRAMUSCULAR INTRAVENOSA SUBCUTANEA (NEXT PHARMA) AMPOLLA 1 ml/CAJA X 5
1H1011461000100  ::  HALOPERIDOL 5mg/1 ml OTRAS SOLUCIONES INTRAMUSCULAR INTRAVENOSA (SALUSPHARMA) AMPOLLA 1 ml/CAJA X 5
```

**Sin confirmar:** que la descomposición interna corresponda a los niveles
1/2/3 de la norma INVIMA para IUM. El patrón de 15 caracteres y el estilo de
descripción sí están medidos; la semántica normativa de cada segmento no se
pudo verificar desde la base.

Hoy `"ium"` es el nombre del catch-all completo (199.463 filas) cuando en
realidad describe apenas estas 85. El nombre es literalmente incorrecto
para el 99,96 % de lo que agrupa.

### 3. Códigos propios de Pijao Salud / Gemma Net — confirmada, 4 sub-familias

**(a) Prefijo alfabético + secuencia** (56 filas, todas `expediente='-999'`).
El prefijo tiene significado: `CU`=cuidador, `D`=dispositivo, `MED`=medicamento
cargado a mano.
```
CU1155     ::  CUIDADOR TURNO 24 HORAS                      (inactivo)
MED000064  ::  DOMPERIDONA SUSPENSIÓN X 100 MG - HARMETONE  (inactivo)
D00001     ::  STENT DUODENAL                               (activo, valor 1.727.000)
```

**(b) Texto libre** (720 filas sin ningún dígito, todas inactivas). Nombre
comercial usado como código, truncado a 15 caracteres:
```
PEDIAVIT   ::  PEDIAVIT REG INVIMA 20003 M-00000174
ANASTRA    ::  ANASTRAZOL TAB 1MG
```
En `PEDIAVIT` el registro sanitario terminó metido en la *descripción*, no
en el código.

**(c) Relleno de dígito repetido:**
```
99999999-99-00000001  ::  BISTURI ARMONICOSUTURA LINEAL GRAPADORA TLC 75MM DOS RECARGAS  (valor 2.000.000)
66666666666618        ::  APREPITANT (KIT 3 CAPSULAS) CAMPSULA 125MG/80MG
```

**(d) Registro sanitario INVIMA usado como código** (79 filas, todas
inactivas) — no estaba en la hipótesis original. Ni CUM ni IUM ni propio: es
otra identidad de INVIMA metida en el campo equivocado.
```
2007M-0007029   ::  COAPROVEL                     (formato moderno AAAAM-NNNNNNN)
M-14042         ::  DIPIRIDAMOL AMPOLLA X 10 MG    (formato antiguo M-NNNNN)
INVIMA 2003M-00 ::  LEVETIRACETAM KEPPRA® 500 MG   (truncado a 15 caracteres)
```
7 filas adicionales usan el marcador `DM` de INVIMA (dispositivo médico):
`2006DM-0000309` (INHALOCAMARA PEDIATRICO), `2008DM00117382` (GEL HIDROACTIVO
DUODERM).

### 4. Paquetes — confirmada, sin señal estructural

`tb_paquete` está vacía (0 filas) y `tb_medicamento` no tiene columna
`sw_paquete` (`tb_cup` sí la tiene: 1.034 filas marcadas). Dentro de
`tb_medicamento` los paquetes solo se delatan por texto y un `valor`
anómalamente alto:
```
CIRUGIA BARIATR  ::  CIRUGIA BARIATRICA ABIERTA Y LAPAROSCOPICA (PAQUETE Nº 2)  valor 13.300.000
ESTIMULACION CE  ::  ESTIMULACION CEREBRAL PROFUNDA BILATERAL (PAQUETE)         valor 119.900.000
```
Solo 3 filas mencionan "paquete" fuera de la familia CUM. **Buscar "KIT" no
sirve**: arrastra medicamentos legítimos vendidos como kit (`TISSUCOL® KIT
ADHESIVO`, `APREPITANT (KIT 3 CAPSULAS)`), que no son paquetes de servicios.
No hay patrón de código para esta categoría — solo texto.

### 5. Insumos — confirmada por cruce con `tb_insumo`

11 filas de `tb_medicamento` tienen un `codigo_interno` que existe también
en `tb_insumo`, con descripción concordante:
```
D00001  ::  medicamento: STENT DUODENAL            / insumo: ACEITE DE SILICON
D00007  ::  medicamento: KIT DE OSTOMIA (COMPLETO)  / insumo: KIT DE COLOSTOMIA/OSTOMIA #57
170100  ::  medicamento: LENTES                     / insumo: LENTES
```
Por palabra clave (stent, férula, sonda, catéter, bolsa...), ~69 filas
adicionales de las 1.465 no-CUM/no-ATC suenan a insumo — cota inferior, no
conteo exacto. `D00001`, `D00007`, `D00005` (TIRILLAS) están **activas**
dentro del catálogo de medicamentos.

### 6. CUPS — confirmada, y contra la expectativa de que sería inusual

21 filas de `tb_medicamento` tienen `codigo_interno` presente en
`tb_cup.codigo_interno`, con descripción coincidente:
```
881331   ::  medicamento: ULTRASONOGRAFIA DE RIÑONES               / CUPS: ECOGRAFIA DE RIÑONES BAZO AORTA O ADRENALES
903437   ::  medicamento: TROPONINA                                / CUPS: TROPONINA I CUANTITATIVA
992503   ::  medicamento: MONOQUIMIOTERAPIA (CICLO DE TRATAMIENTO)  / CUPS: MONOQUIMIOTERAPIA CICLO DE TRATAMIENTO
```
Dos formatos: 6 dígitos (`881331`, `903437`) y letra+5-6 alfanuméricos de
manuales tarifarios ISS/SOAT (`C40102`, `S500001`). ~45 filas adicionales
suenan a procedimiento por descripción sin código CUPS coincidente.

**Trampa verificada:** cruzar contra `tb_cup.cup` (PK sustituta bigint, NO
el código CUPS) da 12 falsos positivos — medicamentos con código `"1"`..`"12"`
que casualmente igualan un ID interno. El campo correcto es
`tb_cup.codigo_interno`.

## Control negativo

De las 133.367 filas con forma CUM, **0** tienen descripción de
procedimiento (ecografía, tomografía, biopsia, cirugía, paquete...). Un
filtro preliminar marcó 2.081 como "insumo" por contener "lentes" — todas
resultaron ser falso positivo de la palabra "EQUIVALENTES" (ej.
`CLORHIDRATO DE DULOXETINA 67.2 EQUIVALENTE A...`). **La contaminación
(insumos, procedimientos, paquetes) está confinada al catch-all; la forma
CUM está limpia.** Esto valida clasificar por forma del código como el eje
correcto.

## Qué no se pudo confirmar

- Semántica normativa de los segmentos internos del IUM de 15 caracteres.
- Que los expedientes "redondos" dentro de la forma CUM sean inventados
  (requiere cruzar contra INVIMA real).
- Tamaño exacto de insumos/procedimientos sin cruce de tabla — 69 y 45 son
  cotas inferiores por palabra clave.
- Clasificación exhaustiva del bucket residual (240 filas, formas mixtas
  como `2005V 0003063`, `2002M – 0000209` con guion tipográfico) — muestreado,
  parece mayormente registros sanitarios mal digitados, no clasificado fila
  por fila.
- Diferencia entre el total de esta medición (199.611 filas) y el citado en
  `CLAUDE.md` para las estadísticas de `-999` (199.689 filas, 78 de
  diferencia) — no investigada.

## Si se decide extender `clasificar_codigo()` — prioridades para cuando se implemente

**No implementar sin volver a este documento y sin releer
`normaliza/codigos.py`.** `es_cum()` y su comentario sobre las cifras
contradictorias históricas (~66.231 vs 199.463) no deben tocarse — es la
razón por la que el patrón es estricto. La extensión correcta es un
`clasificar_codigo()` con más ramas y un `Literal` más ancho, dejando
`es_cum()` intacto como predicado. **El orden de evaluación importa**:
`cum_con_sufijo_atc` debe probarse antes que cualquier regla laxa con
guion, o vuelve el error de conteo que ya documenta el comentario existente.

**Prioridad alta — corrige clasificación real, no solo la nombra mejor:**
1. `cum_con_sufijo_atc` — 147 filas, 48 activas, recuperables contra INVIMA.
2. `atc_expediente_consecutivo` — 64.779 filas (un tercio de la tabla),
   triple señal de confirmación independiente. Convierte "199.463 códigos
   raros" en "una capa legada apagada de 64.779 duplicados": un hecho de
   proceso, no miles de hallazgos sueltos.
3. `ium` — que el nombre por fin describa las 85 filas que sí lo son.

**Prioridad media — separa poblaciones que no son medicamentos:**
4. `registro_sanitario` (79 filas + 7 con marcador `DM`).
5. `forma_cups` (27 filas, 21 verificables contra `tb_cup`).
6. `codigo_propio` (~780 filas).

**Prioridad baja o descartar de `codigos.py`:** paquetes e insumos no tienen
patrón de código — la única señal fiable es cruzar contra
`tb_cup.codigo_interno`/`tb_insumo.codigo_interno`, que es una consulta, no
una regex. `codigos.py` es puro y sin red por diseño; si se quiere esta
distinción, va como paso de auditoría con acceso a base (ver dimensión 10 de
`auditoria/coherencia_invima.py` como precedente), no como extensión de
`clasificar_codigo()`.

## Archivos relevantes

- `src/gemma_cum_loader/normaliza/codigos.py` — donde vive el catch-all hoy.
- `src/gemma_cum_loader/ingesta/gemanet_sql.py` — no mapea `sw_mixto`,
  `sw_muestra_magistral`, `codigo_dci`; las dos últimas están vacías en toda
  la tabla, la primera es marginal — el mapeo incompleto está bien así.
- `src/gemma_cum_loader/integraciones/gemanet_db.py` — cliente usado para
  esta investigación.
- `src/gemma_cum_loader/armado/malla.py` — revisado, no se solapa: clasifica
  el universo INVIMA por la fase 2 del SOP (rol, estado CUM, estado
  registro, muestra médica), no la forma del `CODIGO_INTERNO` de Gemma Net.
