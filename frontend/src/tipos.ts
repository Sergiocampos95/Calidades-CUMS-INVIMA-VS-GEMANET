// Espejo de backend/app/schemas.py -- si el contrato de la API cambia, este
// archivo es el primero que hay que actualizar.

export interface PaginaTabla {
  total: number;
  visibles: number;
  limite_aplicado: boolean;
  filas: Record<string, unknown>[];
}

export type EstadoSaludNombre = "ok" | "desactualizado" | "error" | "sin_datos";

export interface EstadoSalud {
  estado: EstadoSaludNombre;
  ultima_actualizacion_utc: string | null;
  antiguedad_segundos: number | null;
  duracion_ultimo_refresco_segundos: number | null;
  detalle_error: string;
}

export type Resumen = Record<string, number>;

export interface ResumenMetodos {
  unidad?: Resumen;
  marca?: Resumen;
}

export interface EslabonResumen {
  nombre: string;
  campos_acumulados: string[];
  universo: number;
  porcentaje_total: number | null;
  columnas_trio: string[];
  columna_estado: string;
}

export interface CalidadResumen {
  nombre: string;
  explica: string;
  medicamentos: number;
  porcentaje_del_catalogo: number;
  columnas: string[];
  /** Condiciones que definen la calidad, en lenguaje de negocio, una por
   * entrada -- la UI las pinta como lista en el panel "Cómo se calcula". */
  criterios: string[];
  /** Qué hacer con lo que sale en esta calidad. */
  que_hacer: string;
}

/** Un TIPO de diferencia dentro de una calidad. Las secciones NO son
 * excluyentes: sus conteos no suman el total de la calidad, porque una misma
 * fila puede tener dos campos distintos. `derivado_de` viene con los campos
 * de los que ESTE es consecuencia (ej. Descripcion <- Principio activo). */
export interface SeccionCalidad {
  clave: string;
  etiqueta: string;
  medicamentos: number;
  derivado_de: string[];
  /** Qué se compara en esta sección (qué campo de Gemma Net contra qué de
   * INVIMA y cómo), para quien no es técnico. */
  explica: string;
}

export interface DimensionesCalidad {
  n_total_auditado: number;
  completitud_promedio: number | null;
  duplicados: number;
  fuera_de_dominio: number;
  inconsistencia_numerica: number;
  formato_invalido: number;
  integridad_referencial: number;
}

export interface HallazgoNaturaleza {
  naturaleza: string;
  medicamentos: number;
  que_hacer: string;
}

export interface ResumenCargue {
  listos?: number;
  pendientes?: number;
  [clave: string]: number | undefined;
}

export interface AdvertenciaMalla {
  campo: string;
  advertencia: string;
}

export type EstadoPaso = "pendiente" | "en_curso" | "hecho" | "error";

export interface PasoProgreso {
  nombre: string;
  estado: EstadoPaso;
  detalle: string;
}

export interface ProgresoRefresco {
  en_curso: boolean;
  pasos: PasoProgreso[];
}
