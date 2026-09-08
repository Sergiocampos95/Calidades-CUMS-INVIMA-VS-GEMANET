# Operación — arrancar, reiniciar, versionar y mitigar fallos

El cuarto documento de `design/`, junto a
[`reglas_negocio.md`](reglas_negocio.md) (qué/por qué),
[`mapa_del_proyecto.md`](mapa_del_proyecto.md) (dónde) y
[`mecanismos/`](mecanismos/) (cómo calcula el código). Este es el **cómo se
opera y se recupera** el sistema: cuándo commitear, cómo levantar cada pieza,
y qué hacer cuando algo se rompe.

Nace de una auditoría de estructura (2026-09-09) que encontró dos scripts de
reinicio con un bug real (`python` sin calificar tomaba el intérprete del
sistema en vez del venv) que llevaba desde el 2026-09-07 sin corregirse en
uno de ellos porque no había un solo lugar que listara los tres juntos.

---

## 1. Cuándo commitear

El detalle completo vive en `CLAUDE.md` §"Flujo de trabajo y control de
versiones" — esto es el resumen accionable:

- **Una sesión = un problema = una rama = un cierre.** Si el nombre de la
  rama ya no describe lo que hay dentro, la sesión cubrió más de un problema.
- **Commit por sub-tema, no uno gigante al final.** Cada arreglo, con su
  porqué en el mensaje — son los commits los que le dan trazabilidad real al
  proyecto, más que cualquier documento.
- **`/bitacora` al cerrar una sesión que tocó código.** Verifica alineación
  de `design/`, deja la entrada en `.ai/bitacora.jsonl`, propone el mensaje
  de commit, y recuerda el push.
- **Push seguido, no al final del día.** El hook `pre-push` corre pytest +
  ruff + tsc y aborta si algo falla — es la última red antes de que el
  código salga de la máquina.
- **Nunca commitear directo a `master`.** Rama por tarea, merge solo cuando
  está verde **y verificado en pantalla** (`scripts/ver_app.py`).

## 2. Arrancar y reiniciar

Tabla completa de scripts en `mapa_del_proyecto.md` §Scripts. Acá, cuándo
usar cada uno:

| Situación | Comando |
|---|---|
| Empezar el día, o tras tocar `src/`/`backend/` | `.\reinicia_todo.ps1` |
| Lo mismo pero el snapshot ya sirve (no cambió lógica de datos) | `.\reinicia_todo.ps1 -SinRefresco` |
| Solo cambió Python, el frontend ya está bien | `.\reinicia_backend.ps1` |
| Necesito que el botón "Actualizar ahora" funcione | `.\reinicia_worker.ps1` (aparte — `reinicia_todo.ps1` no lo arranca) |
| Verificar en pantalla, no solo contra la API | `python scripts\ver_app.py <seccion> <sub>` |

**Los tres scripts de reinicio usan el python del venv por ruta
(`.venv\Scripts\python.exe`), no el del PATH.** Si algún día se agrega un
cuarto script que arranque un proceso Python, seguir el mismo patrón — un
`python` pelado revienta con `No module named 'X'` en cualquier consola donde
el venv no esté activo, y es un bug que ya costó pasar desapercibido varios
días en `reinicia_todo.ps1` mismo.

## 3. Fallos conocidos y cómo mitigarlos

Cada uno es un incidente real, no una hipótesis. Buscá el síntoma.

### "El puerto 8000/5173 sigue ocupado" tras matar el proceso

**Causa real (medido 2026-09-07, dos veces en la misma sesión):** un proceso
`python.exe` de `multiprocessing.spawn` queda **huérfano** sosteniendo el
socket después de que su padre (el uvicorn que se mató) ya no existe.
`Stop-Process` sobre el uvicorn no lo mata porque nunca lo tenía como target.

**Diagnóstico:**
```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Select-Object ProcessId, ParentProcessId, CommandLine
```
Buscar el PID que escucha el puerto (primer comando) y, si no aparece con un
`CommandLine` reconocible de uvicorn/worker, es el huérfano — su
`CommandLine` va a decir `multiprocessing.spawn`. Matarlo por PID directo:
`Stop-Process -Id <pid> -Force`.

### El backend responde pero sirve código viejo

**Causa real (2026-09-02, documentado también en `ui-vite.md`):** `--reload`
de uvicorn en Windows no es confiable — puede loguear "Reloading..." y seguir
sirviendo el proceso anterior, o un hijo de multiprocessing sobrevive
sosteniendo el puerto tras el cambio de código.

**Mitigación:** tras un cambio en `src/`/`backend/`, no confiar en
`--reload`. Matar el proceso por dueño de puerto (no por línea de comando,
ver más abajo) y arrancar de nuevo. Verificar con `curl` contra el endpoint
real, nunca asumir "debería funcionar" por el código.

### `reinicia_todo.ps1`/`reinicia_worker.ps1` explota con `No module named 'X'`

**Causa:** se corrió desde una consola donde el venv no estaba activo, y el
script usaba `python` sin calificar. Corregido el 2026-09-09 en los tres
scripts de reinicio (usan `.venv\Scripts\python.exe` por ruta) — si aparece
en un script nuevo, es el mismo bug, mismo arreglo.

### Un `Stop-Process` mata más de lo que debía

**Causa (corregida el 2026-09-01, ver comentario en `reinicia_backend.ps1`):**
`Get-Process python | Stop-Process -Force` mata **todos** los `python.exe`
de la máquina, sin distinguir cuál es de este proyecto — se lleva por delante
Jupyter, otro proyecto, cualquier cosa.

**Regla:** siempre filtrar por `CommandLine` via
`Get-CimInstance Win32_Process -Filter "Name='python.exe'"` y matchear contra
`uvicorn backend\.app\.main`, `worker\.refresco`, etc. — nunca `Get-Process`
a secas sobre el nombre del ejecutable.

### Un segundo Vite aparece en el puerto 5174

**Causa (medido 2026-09-02):** Vite se enlaza a `::1` (IPv6). Un chequeo de
puerto libre que prueba `127.0.0.1` (via `TcpClient`) da "libre" con Vite ya
corriendo, así que el script levanta una segunda instancia en 5174 mientras
el navegador sigue apuntando a la primera en 5173.

**Mitigación:** comprobar con `Get-NetTCPConnection -State Listen -LocalPort
5173`, nunca con un intento de conexión TCP a `127.0.0.1`.

### Las cifras salen en cero, o una columna nueva no aparece

**Causa:** el snapshot que sirve el backend es de antes de que esa columna
existiera. `worker/almacen_snapshots.py::desfases_de_esquema()` existe
justo para detectar esto — `reinicia_todo.ps1` ya lo revisa después de
refrescar y aborta si hay desfase, en vez de levantar el backend sobre datos
incompletos.

**Regla de lectura:** un `0` en una cifra nueva **no** significa "no hay
hallazgos" — significa "verificá la fecha del último refresco" antes de
confiar en el número.

### `pytest` queda en rojo y no se entiende por qué tras un cambio chico

Revisar primero si el cambio tocó algo que `design/mecanismos/` documenta —
un orden de `.where()`/`.mask()` invertido produce fallos que parecen no
tener relación con lo que se tocó. Los dos hooks de `.claude/hooks/`
(`marcar_lectura_docs.py` + `recordar_docs_negocio.py`) avisan justo de esto
si se editó sin haber leído el mecanismo primero.

### Un hook no dispara, o dispara con un mensaje viejo

Los hooks de `.claude/hooks/` guardan estado por sesión en
`.estado_docs_leidas.json` (fuera de git). Si el comportamiento parece
inconsistente entre turnos de la misma sesión, ese archivo es el primer
lugar para mirar — borrarlo reinicia el estado sin riesgo (los hooks
degradan a "avisar de más", nunca a fallar).

## 4. Verificar antes de dar algo por bueno

**Una cifra no es buena hasta verla contra un proceso reiniciado.** Un
backend vivo sirve el código que cargó al arrancar; un snapshot viejo
degrada a cero en silencio. Antes de reportar un arreglo como terminado:

1. `.\reinicia_todo.ps1` (o `-SinRefresco` si no cambió lógica de datos).
2. `pytest` + `ruff check` en verde.
3. `python scripts\ver_app.py <seccion>` — mirar la pantalla, no solo la
   API. La suite y la API pueden estar en verde con la vista rota (pasó tres
   veces distintas el 2026-09-08, sin que ninguna prueba lo atrapara).
