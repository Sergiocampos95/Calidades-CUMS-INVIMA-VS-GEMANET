# Guía de estilo — Gemma Net (aproximada)

Derivada de capturas de pantalla del formulario **"Mantenimiento Medicamentos"** de Gemma Net, recibidas el 2026-08-13. No hay acceso a CSS en vivo ni a un manual de marca oficial todavía, así que todo valor de color/tipografía aquí es una lectura visual, no un valor exacto extraído de código. Cuando llegue una fuente de mayor fidelidad (manual de marca o CSS exportado), este documento y `design_tokens.json` se actualizan sin tocar el resto de la arquitectura.

## Nivel de confianza por elemento

| Elemento | Confianza | Origen | Nota |
|---|---|---|---|
| Barra superior azul + logo circular verde "g" | Aproximada | Captura de la pantalla completa del formulario | Color leído visualmente, no medido con cuentagotas de imagen |
| Layout de formulario (label izquierda, input derecha) | Alta | Confirmado en dos capturas distintas del mismo formulario | Patrón estructural, no depende de color |
| Estilo de inputs (fondo gris claro, borde fino, esquinas ligeramente redondeadas) | Aproximada | Capturas del formulario | — |
| Estilo de botones (píldora azul claro, icono + texto) | Aproximada | Captura de la fila de botones Agregar/Remover/Anterior/Actualizar | — |
| Colores de badge de estado (Vigente/Vencido, Activo/Inactivo) | **Estimada, no observada** | No aparece ningún badge de color en las capturas recibidas | Se usó una convención genérica verde/rojo hasta ver el componente real en Gemma Net |
| Tipografía exacta (nombre de fuente) | Estimada | No identificable de forma confiable en una captura | Se usa una pila sans-serif genérica (`Segoe UI`, `Arial`) como aproximación |

## Campos de formulario confirmados por las capturas

Las capturas del formulario "Mantenimiento Medicamentos" confirmaron nombres de campo que no estaban documentados antes en la malla de cargue: `Código DCI`, `Mixto (Seguimiento MIPRES)`, `Muestra Magistral`, y `Nivel de Servicio` / `Modelo del Servicio` como selector de tipo checkbox con una sola opción seleccionable (ej. "Nivel 4 - EPS - SUMINISTRO DE MEDICAMENTOS"), no como texto libre.

## Cómo refinar esto más adelante

1. **Manual de marca oficial de Pijao Salud**, si existe — reemplaza directamente los valores de `color` y `tipografia` en `design_tokens.json`.
2. **CSS real de Gemma Net** (F12 → Elements → copiar variables `:root` o el CSS computado de un botón) — da valores hex y nombres de fuente exactos.
3. **Más capturas** — en particular de un badge de estado real (Vigente/Vencido) y de un mensaje de error/validación, que no llegaron en esta primera tanda.

Ninguna actualización futura de fidelidad requiere rediseñar `ui_revision/`: solo se editan los valores de este archivo y de `design_tokens.json`.
