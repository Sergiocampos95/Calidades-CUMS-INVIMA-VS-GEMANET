# Gemma CUM Loader — contexto para agentes

Automatiza el cargue y la auditoria de medicamentos CUM/IUM entre el catalogo
oficial de INVIMA y la plataforma Gemma Net (Pijao Salud EPSI).

El `README.md` es la documentacion funcional completa y esta al dia: leelo antes
de tocar logica de negocio. Este archivo solo recoge lo que un agente necesita
para no romper convenciones.

## Los dos flujos (no confundirlos)

| Pregunta | Flujo | Modulos |
|---|---|---|
| Que medicamentos de INVIMA **faltan** por cargar | Candidatos | `armado/`, `validacion/`, `exportacion/` |
| De lo **ya cargado**, que esta mal o desactualizado | Auditoria | `auditoria/coherencia_invima.py` |

## Comandos

```bash
pytest                                    # suite completa (261 pruebas)
pytest tests/test_reglas.py -q            # un modulo
ruff check src/ tests/ ui_revision/       # lint
streamlit run ui_revision/app_streamlit.py
```

Entorno: Python 3.12+, venv en `.venv/`, Windows. Instalacion: `pip install -e ".[dev]"`.

## Arquitectura

```
src/gemma_cum_loader/
├── ingesta/        Lectura INVIMA: invima_reader.py (Excel), invima_socrata.py (API)
├── integraciones/  socrata.py — cliente HTTP crudo de datos.gov.co
├── armado/         malla.py (universo), cruce_gemanet.py, reglas_negocio.py
├── catalogos/      resolver.py (cascada deterministica) + ia_client.py
├── validacion/     reglas.py — acepta / rechaza / descarta / cuarentena
├── auditoria/      coherencia_invima.py — 9 dimensiones de calidad
├── exportacion/    cargue.py, estructura_cargue.py — Excel final
├── normaliza/      texto.py, codigos.py
└── pipeline.py     orquestacion end-to-end
```

Datasets Socrata: Vigentes `i7cb-raxc` (obligatorio), Vencidos `vwwf-4ftk`,
Renovacion `vgr4-gemg`, Otros Estados `spzp-dfuc` (los tres opcionales e
independientes).

## Reglas de diseno — no negociables

1. **Sin decisiones a ciegas.** Lo ambiguo va a `cuarentena`, no se resuelve
   adivinando. Nunca fusionar filas con `CODIGO_INTERNO` duplicado: suelen ser
   medicamentos combinados y fusionarlas pierde un principio activo.
2. **Degradacion explicita, nunca suposicion silenciosa.** Si falta un archivo
   auxiliar se reporta; no se asume un valor por defecto.
3. **La cascada de resolucion es 100 % deterministica** (`exacto -> alias ->
   fuzzy -> sin_resolver`) y **nunca depende del modelo de IA**. Son 200.000
   filas: tiene que ser exacta y rapida, sin llamadas de red.
4. **La IA solo traduce**, no decide. `ia_client.py` convierte un `motivo`
   tecnico en lenguaje de negocio. `explicar_motivo()` se llama una vez por
   motivo distinto (vocabulario fijo y chico), nunca una vez por fila.
   `explicar_fila()` solo bajo accion explicita del usuario en la UI.
5. **`-999` es el centinela de "sin dato"** de Gemma Net, no un valor numerico.
   Si un campo supera el 90 % en `-999` se reporta como problema de proceso, no
   como miles de hallazgos sueltos.
6. **`PORCENTAJE_CALIDAD` queda vacio, no en 0 %,** cuando no hay
   correspondencia con INVIMA: no hay nada que comparar y no es lo mismo.

## Convenciones de codigo

- **Espanol sin tildes en el codigo fuente** (identificadores, docstrings y
  comentarios son ASCII: `codigos`, `deterministica`, `espanol`). El `README.md`
  y los `.md` de `design/` si llevan tildes.
- **Los comentarios explican el *porque*, no el *que*.** Varios documentan
  hallazgos reales contra datos de produccion (`-999`, hojas de Excel mal
  nombradas, medicamentos combinados). Son la memoria del proyecto: no los
  borres ni los "limpies".
- `from __future__ import annotations` al inicio de cada modulo.
- Dataclasses (a menudo `frozen=True`) para los valores de retorno.
- Type hints en todas las firmas publicas.
- Sin dependencias nuevas sin justificarlas: el `pyproject.toml` es corto a
  proposito.

## Pruebas

- **Nunca golpear APIs reales desde pytest.** El cliente se inyecta
  (`ClienteExplicacionIA(client=...)`); lo mismo para Socrata/HTTP.
- Cada modulo de `src/` tiene su `tests/test_<modulo>.py`.
- Los tests se construyen con DataFrames pequenos in-line, no con archivos de
  produccion.
- Nombres de test descriptivos en espanol, coherentes con los existentes.

## Datos

`data/` esta en `.gitignore` y contiene archivos reales de produccion (decenas
de MB). **Nunca subirlos al repositorio ni pegar su contenido en un reporte.**
Los archivos reales son la fuente para medir rendimiento, no para versionar.

## UI (Streamlit)

- **Toda tabla de medicamentos lleva filtros y busqueda libre.** Ninguna se
  muestra en crudo.
- Las advertencias van como **tarjeta corta + detalle en un expander**, nunca
  como parrafos largos dentro de un banner.
- 5 pestanas: Resumen de resolucion · Bandeja de cuarentena · Cargue a Gemma Net
  · Consultar INVIMA · Auditoria de coherencia.

## Equipo de agentes

Este proyecto define agentes especializados en `.claude/agents/`. Ver
`.claude/AGENTES.md` para el reparto de responsabilidades y como encadenarlos.

## Contexto compartido entre herramientas (Copilot CLI, Claude Code, Copilot Chat)

- `AGENTS.md` en la raiz es el puente para Copilot CLI (lo lee
  automaticamente). Copilot Chat en VS Code lee `.github/copilot-instructions.md`
  y las reglas por carpeta de `.github/instructions/*.instructions.md`. Los tres
  apuntan a este archivo sin duplicar reglas.
- **El reparto de trabajo con Copilot esta en `.ai/planes/README.md`**: Claude
  Code decide y verifica, Copilot acelera dentro de una decision ya tomada.
  Cada tarea no trivial lleva un plan en `.ai/planes/<slug>.md` con un dueno
  por paso y tres marcas (`[ ]` libre, `[~]` tomado, `[x]` hecho). Comandos:
  `/plan-equipo`, `/tomar-paso`, `/bitacora`.
- `.ai/bitacora.jsonl` es un registro append-only de cambios no triviales
  (agente, fecha, resumen, archivos). Formato en `.ai/README.md`.
- Convencion de commits: si propones un mensaje, agrega un trailer
  `Agente: <nombre>` (ej. `Agente: Copilot CLI`) para poder filtrar
  `git log --grep="^Agente:"` por herramienta.
