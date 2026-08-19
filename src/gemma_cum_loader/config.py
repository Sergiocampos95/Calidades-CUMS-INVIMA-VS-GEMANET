"""Constantes de configuracion compartidas entre modulos."""

# Campos del catalogo INVIMA con corrupcion de origen conocida (literal "SIN DATO"
# incrustado en el texto). No usar en cruces, deduplicacion ni descripciones.
CAMPOS_NO_CONFIABLES_INVIMA = ("CONCENTRACION", "DESCRIPCION_COMERCIAL")
