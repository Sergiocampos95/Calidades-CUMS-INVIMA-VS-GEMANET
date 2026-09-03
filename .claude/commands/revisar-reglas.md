---
description: Revisar los cambios pendientes contra las reglas de negocio del proyecto
allowed-tools: Read, Grep, Glob, Bash(git diff*), Bash(git status*), Bash(git log*)
---

Revisa los cambios pendientes (`git diff` y `git diff --staged`) contra las
reglas duras del proyecto. Solo reporta: **no edites nada**.

Busca especificamente:

1. Filas fusionadas por `CODIGO_INTERNO` duplicado (pierde un principio activo
   de un medicamento combinado).
2. Cualquier llamada de red o de IA dentro de la cascada de
   `catalogos/resolver.py`, o cualquier cosa que corra una vez por fila en una
   ruta que ve el universo completo (`iterrows`, `apply` fila a fila, un
   `merge` sin indice, una consulta dentro de un bucle). Son 200.000 filas.
3. Ambiguedad resuelta adivinando en vez de mandada a `cuarentena`.
4. Valores por defecto asumidos en silencio cuando falta un archivo auxiliar.
5. `-999` tratado como numero, o `PORCENTAJE_CALIDAD` puesto en 0 % donde
   deberia quedar vacio.
6. `data/` leido desde un test, o contenido de produccion pegado en el codigo.
7. Tildes en identificadores, docstrings o comentarios de `.py`.
8. Comentarios existentes borrados que documentaban un hallazgo contra datos
   reales.
9. Tablas de medicamentos en la UI sin filtros ni busqueda.

Para cada hallazgo: archivo y linea, que regla rompe, y que pasaria en
produccion si se queda. Ordena por gravedad. Si no hay nada, dilo en una linea.

Si encuentras algo que requiere rediseno y no solo un parche, dilo y propon
llevarlo al agente `arquitecto` (`.claude/agents/arquitecto.md`) en vez de
parchearlo aca.
