# Publicar el proyecto en un repositorio nuevo de GitHub

- **Estado:** en curso
- **Creado:** 2026-08-25 por Copilot CLI
- **Objetivo:** publicar únicamente el código, documentación y configuración aprobados en un repositorio nuevo de GitHub, sin exponer datos de producción, credenciales ni artefactos locales.

## Contexto

El repositorio local está en `master`, no tiene remoto configurado y contiene un cambio de trabajo amplio sin commit (4.164 inserciones y 471 eliminaciones en archivos ya rastreados, más módulos y configuración nuevos). `data/` contiene producción y debe permanecer fuera de Git; la base de Gemma Net y las claves de Socrata/Anthropic se administran por variables de entorno. El archivo no rastreado `ui_revision/app_streamlit.py.bak` requiere una decisión explícita: no se debe publicar como código por defecto.

La publicación no cambia lógica de negocio, pero sí convierte el estado local actual en un artefacto compartido. Por eso se revisa y valida antes de crear el primer commit o remoto.

## Pasos

Un paso, un dueño, los archivos que toca. `[ ]` libre · `[~]` tomado · `[x]` hecho.

- [x] 1. (claude/revisor) — revisar el diff y los archivos no rastreados para detectar secretos, datos de producción, artefactos locales o cambios de correctitud que impidan publicar. Debe cubrir en especial `.gitignore`, `ui_revision/app_streamlit.py.bak`, `.streamlit/`, `consultas/`, `src/gemma_cum_loader/integraciones/gemanet_db.py` y `src/gemma_cum_loader/catalogos/ia_client.py`; entregar hallazgos accionables sin editar.
- [x] 2. (claude/pruebas) `tests/`, `src/`, `ui_revision/` — ejecutar `pytest` y `ruff check src/ tests/ ui_revision/` sobre el estado que se pretende publicar; reportar el resultado y no modificar archivos. **Puede correr en paralelo con el paso 1.**
- [x] 3. (copilot) `.gitignore`, `ui_revision/app_streamlit.py.bak` — preparar el conjunto publicable a partir de los hallazgos: asegurar exclusión explícita de datos, secretos y artefactos; decidir con el usuario si el `.bak` se elimina o se ignora, sin incluirlo por accidente. Depende de los pasos 1 y 2.
- [~] 4. (claude) — crear el repositorio de GitHub con el propietario, nombre y visibilidad confirmados; añadir `origin` al repositorio local sin reemplazar ningún remoto existente. Depende del paso 3.
- [~] 5. (claude) — inspeccionar el índice final, crear el commit inicial sólo con los archivos aprobados y subir `master` al remoto. El mensaje debe describir la primera publicación e incluir el trailer `Agente: Copilot CLI`. Depende del paso 4.
- [ ] 6. (claude/revisor) — verificar después del push que el commit remoto coincide con el commit local aprobado, que no entraron archivos excluidos y que la rama predeterminada apunta al historial esperado. Depende del paso 5.

## Decisiones

- La visibilidad debe ser **privada** por defecto: el proyecto procesa información de producción de Pijao Salud, aunque `data/` esté ignorado.
- No se fuerza, reemplaza ni elimina ningún remoto; hoy no hay uno configurado.
- No se publican datos de `data/`, archivos `.env`, DSN, tokens, copias de respaldo ni salidas generadas.
- `ui_revision/app_streamlit.py.bak` y `consultas/verificar_auditoria.sql` se excluyeron en `.gitignore`: el primero es un respaldo local y el segundo contiene métricas operativas.
- `pytest -q` pasó con 342 pruebas; tras los cambios concurrentes, `ruff check --select E9,F src/ tests/ ui_revision/` también quedó limpio.

## Abierto

- El repositorio de GitHub se llamará **GEMMACUM** y será **privado**; el propietario será la cuenta autenticada al crearlo.
- Falta decidir si `ui_revision/app_streamlit.py.bak` debe conservarse localmente e ignorarse o eliminarse antes de publicar.
- Los cambios locales pertenecen a trabajo concurrente; el primer commit sólo se crea tras aprobar el inventario y la revisión.
- La autenticación de GitHub CLI no está configurada; `gh auth status` requiere ejecutar `gh auth login`.
- Falta volver a ejecutar `pytest` tras los cambios concurrentes antes del commit inicial.

## Verificacion

- [x] `pytest` en verde (342 passed)
- [ ] `ruff check src/ tests/ ui_revision/` limpio
- [ ] Revisión de secretos, datos y artefactos aprobada
- [ ] El remoto contiene exactamente el commit aprobado y ningún archivo excluido
- [ ] Linea agregada a `.ai/bitacora.jsonl`
