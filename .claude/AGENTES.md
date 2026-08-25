# Equipo de agentes — gemma-cum-loader

Cada archivo `.md` de esta carpeta define un agente especializado. Todos heredan
`CLAUDE.md` de la raiz del proyecto, pero **no heredan la conversacion**: cada
uno arranca en frio y solo sabe lo que dice su definicion, lo que dice
`CLAUDE.md` y lo que se le pasa en la tarea.

## El equipo

| Agente | Modelo | Escribe en | Para que |
|---|---|---|---|
| `arquitecto` | Opus | — (solo lee) | Disenar el plan antes de codificar |
| `implementador` | Sonnet | `src/` | Escribir el codigo del paquete |
| `pruebas` | Sonnet | `tests/` | Escribir y arreglar la suite de pytest |
| `revisor` | Opus | — (solo lee) | Cazar bugs y violaciones de reglas |
| `ui-streamlit` | Sonnet | `ui_revision/`, `design/` | La interfaz del equipo de negocio |
| `dominio-invima` | Sonnet | `config/catalogos/` | Datos, INVIMA, Socrata, catalogos |
| `rastreador` | Haiku | — (solo lee) | Busquedas e inventarios baratos |

**Opus para juzgar, Sonnet para producir, Haiku para localizar.** Los dos
agentes de criterio (`arquitecto`, `revisor`) no pueden editar a proposito: eso
obliga a que sus hallazgos se discutan en vez de desaparecer en un parche.

Los permisos de escritura no se solapan: dos agentes nunca compiten por el mismo
archivo, asi se pueden correr en paralelo sin pisarse.

## Como se encadenan

**Funcionalidad nueva que toca varios modulos**

```
arquitecto  ->  implementador  ->  pruebas  ->  revisor
  (plan)         (src/)           (tests/)     (hallazgos)
```

**Bug reportado**

```
rastreador       ->  pruebas            ->  implementador  ->  revisor
 (donde vive)        (test que lo repro)     (arreglo)          (verificacion)
```

Escribir primero el test que reproduce el bug es lo que evita el arreglo que
"funciona" sin demostrar nada.

**Cambio de interfaz**

```
ui-streamlit  ->  revisor
```

**Pregunta sobre los datos**

```
dominio-invima   (solo; responde con evidencia, no implementa)
```

## En paralelo

Se pueden lanzar a la vez cuando no comparten archivos. Ejemplos utiles:

- `implementador` (src/) + `ui-streamlit` (ui_revision/) sobre la misma feature.
- `dominio-invima` investigando un dataset mientras `arquitecto` disena.
- Varios `revisor` sobre modulos distintos.

**No** en paralelo: `implementador` y `pruebas` sobre el mismo modulo si el
contrato todavia esta cambiando — el segundo escribiria contra una firma que ya
no existe.

## Uso

Basta con pedir el trabajo en lenguaje natural; la delegacion se decide con el
campo `description` de cada agente. Para forzar uno concreto, nombralo:

> "Usa el arquitecto para planear como agregar la dimension de calidad 10, y
> despues el implementador."

## Autonomia — que corre sin preguntarte

Configurado en `.claude/settings.json`. Modo `acceptEdits`: las ediciones de
archivos se aplican solas, los comandos siguen las listas.

| | |
|---|---|
| **Corre solo** | `pytest`, `ruff`, `git status/diff/log/show/branch`, lecturas |
| **Siempre pregunta** | `git commit`, `git push`, `pip install` |
| **Bloqueado** | `rm -rf`, `git push --force`, `git reset --hard`, `git clean -fd`, escribir en `data/`, leer `data/` y `.env` |

Leer `data/` esta bloqueado a proposito: son 34 MB de datos reales de
produccion y volcarlos al transcript no ayuda a nadie. Para investigarlos se
usa Python y se citan **conteos y porcentajes, no filas** — que es justo lo que
pide la regla del proyecto.

### Los dos hooks

**`hooks/ruff_post_edit.py`** (PostToolUse) — despues de cada edicion de un
`.py` pasa `ruff check --select E9,F --fix`. Lo autocorregible se arregla solo;
lo que queda vuelve al agente para que lo corrija en el mismo turno.

Usa `E9,F` (errores reales) y **no** las reglas por defecto de ruff. Medido el
2026-08-19 con ruff 0.16.3: el proyecto esta limpio en `E9,F` pero arrastra 26
hallazgos de estilo por defecto, 13 de orden de imports. Con las reglas por
defecto el hook reordenaria imports de cualquier archivo que se toque de paso,
metiendo en el diff ruido que nadie pidio.

**`hooks/pytest_al_terminar.py`** (Stop) — corre la suite cuando el modelo va a
detenerse. Si esta roja, no lo deja terminar: le devuelve el fallo para que lo
arregle. Dos topes deliberados:

- **No corre si no cambio codigo.** Guarda una huella de los `.py` de `src/` y
  `tests/`; si es identica a la de la ultima corrida verde, sale en 0,2 s en vez
  de pagar los ~5 s de la suite.
- **Se rinde tras 3 bloqueos seguidos** y avisa al usuario. Un hook Stop sin
  tope se convierte en un bucle.

Ambos fallan hacia el lado seguro: si ruff o pytest no pueden correr, el hook
sale en silencio y no tumba el trabajo del agente.

Para revisarlos o desactivarlos: `/hooks`.

## Reglas que valen para todos

Estan en `CLAUDE.md`, pero las tres que mas se rompen:

1. La cascada de `catalogos/resolver.py` es deterministica y **nunca** usa IA.
2. Lo ambiguo va a `cuarentena`; nada se adivina en silencio.
3. `data/` no se versiona, no se lee en tests y no se pega en reportes.
