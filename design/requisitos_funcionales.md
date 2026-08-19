# Requisitos funcionales — dictados por el usuario (2026-08-13)

Notas tal como las explico el usuario en conversacion, para no perder el
contexto de negocio mientras se continua el desarrollo (incluye trabajo en
otra sesion de Claude Code en paralelo sobre `ui_revision/app_streamlit.py`
y `exportacion/cargue_txt.py`).

## 1. Seleccion de archivos en la UI (pendiente)

Hoy `ui_revision/app_streamlit.py` pide las rutas de los 3 archivos de
entrada con `st.text_input` (rutas de texto escritas a mano, ver
`main()` en ese archivo, campos `ruta_malla` / `ruta_invima` / `ruta_alias`).

Requisito: agregar seleccion de archivo que permita **buscar en el
almacenamiento de la PC** (un file picker real), no solo escribir la ruta.
Streamlit no tiene un file picker nativo de sistema operativo — evaluar
`st.file_uploader` (sube el archivo al proceso, funciona en local y en
servidor) como reemplazo de los `text_input` actuales.

## 2. Flujo de negocio completo

La plataforma exporta y carga archivos en formato TXT. En orden:

1. **Analizar validez del archivo descargado** (la malla de cargue): debe
   verificar que la informacion no tenga errores antes de seguir.
2. **Homologar inconsistencias** encontradas en los documentos Excel
   (ej. unidades de medida o marcas escritas distinto entre archivos —
   esto ya lo cubre en parte `catalogos/resolver.py` + `config/catalogos/alias_unidades.csv`,
   pero hay que revisar si cubre todos los casos que el usuario tiene en mente).
3. **Cruzar esa informacion contra el archivo oficial de INVIMA**
   (`ListadoCodigoUnicoVigentes*.xlsx`) y comparar.
4. **Validar todos los campos** segun los requerimientos (no solo el cruce
   INVIMA) — ver `validacion/reglas.py`, confirmar que cubre "todos los
   parametros" que el usuario espera.
5. **Cruzar y eliminar informacion repetida** (deduplicar) — **no se
   encontro este paso en el pipeline actual** (`pipeline.py` /
   `procesar_malla`). Falta confirmar si ya se cubre en otro punto o si
   hay que agregarlo.
6. **Generar el archivo de cargue** con el resultado, para subir los
   medicamentos nuevos a Gemma Net (`exportacion/cargue_txt.py`).

## 3. Volumen y rendimiento

El archivo de la malla puede superar las **100.000 filas**. La plataforma
debe ser **exacta y agil** con ese volumen — pendiente probar el pipeline
actual (`procesar_malla`) contra un archivo de ese tamano y medir tiempos;
hoy los tests usan fixtures pequenos, no hay benchmark de escala real.

## 4. Guia de referencia (pendiente de recibir)

El usuario menciono que iba a compartir **una guia en imagen** para
interpretar el formato/reglas de estos archivos ("te la doy en imagen,
interpretala"), pero la imagen no llego adjunta en el mensaje donde se
dictaron estos requisitos. **Falta pedirsela de nuevo** — es clave para
confirmar el formato real del TXT de cargue, hoy marcado como "asumido,
no confirmado" en `exportacion/cargue_txt.py` y en la pestana "Cargue a
Gemma Net" de `ui_revision/app_streamlit.py`.

## Resumen: que ya cubre el codigo actual vs que falta

| Requisito | Estado |
|---|---|
| Validar que el archivo descargado no tenga errores | Parcial — `validacion/reglas.py` (`filtro_integridad_estructural`) |
| Homologar inconsistencias (unidad/marca) | Si — `catalogos/resolver.py` + alias CSV |
| Cruce contra INVIMA oficial | Si — `validacion/reglas.py` (`filtro_cruce_invima`) |
| Validacion de todos los campos/parametros | Revisar alcance — confirmar con el usuario que reglas.py cubre todo lo esperado |
| Eliminar filas repetidas (dedup) | **No encontrado** — pendiente confirmar/implementar |
| Generar archivo de cargue TXT | Si, pero formato **no confirmado** contra Gemma Net real |
| Selector de archivo (no solo ruta de texto) | **No implementado** — usa `st.text_input` |
| Rendimiento probado con 100k+ filas | **No probado** — sin benchmark todavia |
