# Planes compartidos — como trabajan Claude Code y Copilot sobre el mismo repo

Un plan es **un archivo markdown por tarea** en esta carpeta. Es el unico
lugar donde las dos herramientas se ponen de acuerdo: quien hace que, en que
orden, y que archivo esta tomado ahora mismo.

Se versiona en git a proposito. Es barato, se lee en 20 segundos y sobrevive a
que cualquiera de las dos ventanas se cierre.

## El reparto

**Claude Code decide y verifica. Copilot acelera dentro de una decision ya
tomada.**

| Trabajo | Dueno | Por que |
|---|---|---|
| Disenar un cambio que toca varios modulos | **Claude Code** (`arquitecto`) | Ve el repo completo y no edita mientras piensa |
| Reglas de negocio nuevas, cascada del resolver, auditoria | **Claude Code** (`implementador`) | El hook de pytest no lo deja terminar en rojo |
| Suite de pruebas de codigo nuevo | **Claude Code** (`pruebas`) | Escribe el test del bug antes del arreglo |
| Cazar bugs y violaciones de reglas antes de un commit | **Claude Code** (`revisor`) | Solo lee: sus hallazgos se discuten, no se tapan |
| Preguntas sobre los datos, INVIMA, Socrata | **Claude Code** (`dominio-invima`) | Puede consultar los datasets y citar evidencia |
| Iterar la UI de Streamlit con la app corriendo | **Copilot** | El usuario ve el efecto de cada cambio al instante |
| Explicar codigo seleccionado, dudas puntuales | **Copilot** | Ya tiene el contexto del editor abierto |
| Completado inline, docstrings, renombres, boilerplate | **Copilot** | Volumen alto, riesgo bajo, cero decisiones |
| Un caso mas en una parametrizacion de test existente | **Copilot** | El contrato ya esta fijado |
| Leer un traceback de la terminal y proponer el arreglo | **Copilot** | Ve la terminal integrada |
| Mensaje de commit | **Copilot** | Ve el diff staged sin pedir nada |

Casos de frontera, resueltos de una vez:

- **UI que necesita una regla nueva:** la regla la escribe Claude Code en
  `src/`; Copilot solo la muestra. Nunca al reves.
- **Bug reportado:** Claude Code escribe el test que lo reproduce; despues
  cualquiera de los dos puede arreglarlo, pero el arreglo tiene que poner ese
  test en verde.
- **Copilot recibe algo del lado de Claude Code:** lo dice y propone el plan;
  no improvisa la implementacion.

## En paralelo, sin pisarse

Se puede trabajar a la vez cuando los archivos no se solapan. Las dos
combinaciones que rinden:

- Claude Code en `src/` + Copilot en `ui_revision/` sobre la misma feature.
- Claude Code disenando o investigando datos + Copilot cerrando docstrings y
  tests de relleno en modulos ya estables.

**Nunca a la vez:** los dos sobre el mismo archivo, ni `implementador` y una
sesion de Copilot sobre el mismo modulo mientras la firma todavia cambia.

## El protocolo anticolision — tres marcas

Cada paso del plan lleva un estado y un dueno:

| Marca | Significa |
|---|---|
| `[ ]` | Pendiente, libre |
| `[~]` | **Tomado ahora mismo.** No lo toques ni abras sus archivos para editarlos |
| `[x]` | Terminado |

Reglas:

1. **Antes de escribir la primera linea**, marca tu paso `[~]` con tu nombre y
   guarda el archivo del plan. Esa marca es el candado.
2. Si un paso esta `[~]` a nombre de la otra herramienta, **no toques sus
   archivos**. Toma otro paso libre o espera.
3. Al terminar, marca `[x]` y anota en `## Decisiones` cualquier cosa que el
   siguiente necesite saber.
4. Si te bloqueas, deja el paso en `[~]` y escribe la razon en `## Abierto`.
   Un paso abandonado en `[~]` sin nota es lo unico que rompe este sistema.

## Ciclo de vida

```
   crear el plan            tomar un paso          cerrar
        |                        |                    |
   Claude Code /            cualquiera de los     el que hizo
   Copilot escribe    ->    dos, marcando [~]  -> el ultimo paso:
   .ai/planes/<slug>.md     y luego [x]           Estado: terminado
                                                  + linea en bitacora.jsonl
```

Un plan terminado se queda aqui. Es el registro de por que el codigo quedo
como quedo, con mas detalle que la bitacora y menos ruido que el diff.

## Como se crea uno

- En Claude Code: `/plan-equipo <descripcion de la tarea>`
- En Copilot Chat: `/plan` (prompt file en `.github/prompts/`)
- A mano: copia `PLANTILLA.md` a `<slug>.md`

## Cuando NO hace falta un plan

Un archivo, un cambio obvio, sin decision de diseno. Ahi el plan cuesta mas de
lo que ahorra: hazlo y, si fue no trivial, deja la linea en
`.ai/bitacora.jsonl`.
