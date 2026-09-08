// Vocabulario compartido para pintar valores de estado como pildora --
// reusado por las vistas de candidatos (accion) y auditoria (ESTADO_COHERENCIA).

const TIPO_POR_ACCION: Record<string, string> = { candidato: "acento", ya_existe: "ok", cuarentena: "danger" };

const ETIQUETA_ESTADO_COHERENCIA: Record<string, string> = {
  correcto: "Correcto",
  con_diferencias: "Con diferencias",
  vencido_en_invima: "Vencido en INVIMA",
  encontrado_en_otro_estado_invima: "En otro estado en INVIMA",
  en_tramite_renovacion_invima: "En trámite de renovación",
  vigente_no_comercializado_invima: "Vigente, no comercializado",
  sin_correspondencia_invima: "Sin correspondencia con INVIMA",
};

const TIPO_POR_ESTADO_COHERENCIA: Record<string, string> = {
  correcto: "ok",
  con_diferencias: "warn",
  vencido_en_invima: "danger",
  sin_correspondencia_invima: "neutro",
  en_tramite_renovacion_invima: "acento",
  encontrado_en_otro_estado_invima: "neutro",
  vigente_no_comercializado_invima: "neutro",
};

function esc(valor: unknown): string {
  return String(valor).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}

export function pildora(tipo: string, texto: string): string {
  return `<span class="pildora pildora--${tipo}">${esc(texto)}</span>`;
}

export function pildoraAccion(valor: unknown): string {
  const v = String(valor);
  return pildora(TIPO_POR_ACCION[v] ?? "neutro", v);
}

export function pildoraEstadoCoherencia(valor: unknown): string {
  const v = String(valor);
  return pildora(TIPO_POR_ESTADO_COHERENCIA[v] ?? "neutro", ETIQUETA_ESTADO_COHERENCIA[v] ?? v);
}

export function etiquetaEstadoCoherencia(valor: string): string {
  return ETIQUETA_ESTADO_COHERENCIA[valor] ?? valor;
}

export const ESTADOS_COHERENCIA = Object.keys(ETIQUETA_ESTADO_COHERENCIA);

// PRIORIDAD_ACCION: los 5 niveles de `clasificar_prioridad_accion` en
// coherencia_invima.py. El valor crudo lleva prefijo numerico ("1_critico")
// para que ordenar la columna por texto deje los criticos arriba; la etiqueta
// que se ve conserva el numero porque "nivel 1" es como se habla de esto.
const ETIQUETA_PRIORIDAD: Record<string, string> = {
  "1_critico": "1 · Crítico",
  "2_alto": "2 · Alto",
  "3_medio": "3 · Medio",
  "4_bajo": "4 · Bajo",
  "5_informativo": "5 · Informativo",
};

// Que significa cada nivel, para el tooltip de la tarjeta y del selector --
// el numero solo no dice por que un critico es critico.
export const AYUDA_PRIORIDAD: Record<string, string> = {
  "1_critico": "INVIMA marca el CUM como Inactivo y en Gemma Net sigue activo: se puede autorizar sin respaldo sanitario vigente.",
  "2_alto": "No aparece en ninguno de los 4 listados de INVIMA: no hay contra qué contrastarlo.",
  "3_medio": "Está en Vencidos u Otros Estados pero el CUM sigue Activo: vigencia temporal mientras se agotan lotes, va a caer.",
  "4_bajo": "Renovación en curso en INVIMA. Hoy sigue vigente; solo hay que esperar.",
  "5_informativo": "Vigente en INVIMA y en Gemma Net. Si hay diferencias son de campos, sin riesgo de vigencia.",
};

const TIPO_POR_PRIORIDAD: Record<string, string> = {
  "1_critico": "danger",
  "2_alto": "warn",
  "3_medio": "acento",
  "4_bajo": "neutro",
  "5_informativo": "ok",
};

export function pildoraPrioridad(valor: unknown): string {
  const v = String(valor);
  return pildora(TIPO_POR_PRIORIDAD[v] ?? "neutro", ETIQUETA_PRIORIDAD[v] ?? v);
}

export function etiquetaPrioridad(valor: string): string {
  return ETIQUETA_PRIORIDAD[valor] ?? valor;
}

/** Los 5 niveles en orden de urgencia -- el orden de declaracion del objeto,
 * que es el que hay que respetar en tarjetas y selector. Alfabeticamente
 * "2_alto" iria antes que "1_critico", que es exactamente al reves. */
export const PRIORIDADES = Object.keys(ETIQUETA_PRIORIDAD);

// Proyeccion de ESTADO_COHERENCIA a "en cual de los 4 listados de INVIMA
// aparece este medicamento" (coherencia_invima.py::_estado_listado_invima) --
// vocabulario chico y cerrado, se muestra al lado de ACTIVO (Gemma Net) para
// comparar los dos estados de un vistazo.
const ETIQUETA_ESTADO_LISTADO_INVIMA: Record<string, string> = {
  vigente: "Vigente",
  vencido: "Vencido",
  renovacion: "En trámite de renovación",
  otros_estados: "Otro estado",
  // Pedido explicito del usuario (2026-09-01): "sin correspondencia" sonaba
  // ambiguo (parecia un error de cruce, no un hecho del dato) -- el
  // medicamento sencillamente no existe en ninguno de los 4 listados.
  ninguno: "No existe en INVIMA",
};

const TIPO_POR_ESTADO_LISTADO_INVIMA: Record<string, string> = {
  vigente: "ok",
  vencido: "danger",
  renovacion: "acento",
  otros_estados: "warn",
  ninguno: "neutro",
};

export function pildoraEstadoListadoInvima(valor: unknown): string {
  const v = String(valor);
  return pildora(TIPO_POR_ESTADO_LISTADO_INVIMA[v] ?? "neutro", ETIQUETA_ESTADO_LISTADO_INVIMA[v] ?? v);
}

export function etiquetaEstadoListadoInvima(valor: string): string {
  return ETIQUETA_ESTADO_LISTADO_INVIMA[valor] ?? valor;
}

/** Pildora para ESTADO_INVIMA, la columna que fusiona listado + detalle
 * (`calidades.py::_con_columnas_derivadas`). El backend ya manda el texto
 * legible y compuesto -- "Vencido", "Otro estado (Cancelado)" -- asi que el
 * color se decide por el PREFIJO, que es la parte que corresponde al listado.
 *
 * Se busca por prefijo y no por igualdad exacta justamente por el parentesis:
 * los 8 valores distintos de "otros_estados" comparten el mismo color de
 * riesgo, que es lo que interesa de un vistazo. */
export function pildoraEstadoInvimaUnificado(valor: unknown): string {
  const texto = String(valor ?? "").trim();
  if (!texto) return pildora("neutro", "—");
  const entrada = Object.entries(ETIQUETA_ESTADO_LISTADO_INVIMA).find(([, etiqueta]) =>
    texto.startsWith(etiqueta),
  );
  const clave = entrada ? entrada[0] : "";
  return pildora(TIPO_POR_ESTADO_LISTADO_INVIMA[clave] ?? "neutro", texto);
}


// Vocabulario de NOVEDAD_VIGENCIA_INVIMA (auditoria/coherencia_invima.py,
// dimension 10) -- mismas etiquetas que _ETIQUETA_VALOR_INTERNO en
// app_streamlit.py, para que decir "vigente o no" no invente un texto nuevo.
const ETIQUETA_NOVEDAD_VIGENCIA: Record<string, string> = {
  riesgo_activo_sin_vigencia: "Activo aquí, sin vigencia en INVIMA",
  // No es riesgo: el CUM sigue Activo en INVIMA aunque el registro este en
  // Vencidos/Otros Estados -- gracia de lotes (ver NOVEDAD_VIGENCIA_TEMPORAL
  // en coherencia_invima.py).
  vigencia_temporal_gracia_lotes: "Vigencia temporal — agotando lotes",
  registro_vencido_en_invima: "Registro vencido en INVIMA",
  revisar_reactivacion: "Inactivo aquí, con registro vivo en INVIMA",
  actualizar_fecha_fin: "Falta la fecha de fin que INVIMA sí tiene",
  coherente: "Los dos lados coinciden",
  no_verificable: "No se puede verificar contra INVIMA",
};

const TIPO_POR_NOVEDAD_VIGENCIA: Record<string, string> = {
  riesgo_activo_sin_vigencia: "danger",
  vigencia_temporal_gracia_lotes: "warn",
  registro_vencido_en_invima: "danger",
  revisar_reactivacion: "warn",
  actualizar_fecha_fin: "warn",
  coherente: "ok",
  no_verificable: "neutro",
};

export function pildoraNovedadVigencia(valor: unknown): string {
  const v = String(valor);
  return pildora(TIPO_POR_NOVEDAD_VIGENCIA[v] ?? "neutro", ETIQUETA_NOVEDAD_VIGENCIA[v] ?? v);
}

// Veredicto de un campo comparado ({CAMPO}_VALIDACION) -- mismo vocabulario
// que VALIDACION_COINCIDE/DIFIERE/... en coherencia_invima.py, generico para
// cualquier columna que termine en _VALIDACION (DESCRIPCION_VALIDACION,
// PRINCIPIO_ACTIVO_VALIDACION, etc.).
// La CLAVE es el valor que emite el backend (VALIDACION_DIFIERE = "difiere")
// y no se toca: viaja en las columnas <CAMPO>_VALIDACION del snapshot y en las
// descargas. Lo que cambia es solo la ETIQUETA que se lee en pantalla
// ("Diferente" en vez de "Difiere", pedido del usuario 2026-09-04: se entiende
// de un vistazo sin conjugar un verbo). Traducir aca y no en el backend es lo
// que permite renombrar sin invalidar los snapshots ya escritos.
const ETIQUETA_VALIDACION: Record<string, string> = {
  coincide: "Coincide",
  // "No coincide / Actualizar campo": el veredicto Y la accion en la misma
  // pildora (pedido del usuario, 2026-09-08). Saber que un campo difiere no
  // dice que hacer con el, y quien revisa esta tabla lo que necesita es
  // exactamente eso: copiar el dato oficial de INVIMA a Gemma Net.
  // Ademas iguala el vocabulario con la tabla de FECHAS de la misma pantalla,
  // que decia "no coincide" para este mismo concepto mientras esta decia
  // "Diferente" -- dos palabras para lo mismo, una encima de la otra.
  difiere: "No coincide / Actualizar campo",
  "sin comparar": "Sin comparar",
  "sin dato en Gemma Net": "Sin dato en Gemma Net",
  // Medicamento combinado: Gemma Net guardo en una fila lo que INVIMA
  // publica como varias (una por principio activo). No se corrige campo a
  // campo -- lo revisa Garantia y Calidad. Ver VALIDACION_PENDIENTE_GYC en
  // coherencia_invima.py.
  "pendiente de decision - Garantia y Calidad": "Pendiente de decisión — Garantía y Calidad",
};

const TIPO_POR_VALIDACION: Record<string, string> = {
  coincide: "ok",
  difiere: "danger",
  "sin comparar": "neutro",
  "sin dato en Gemma Net": "warn",
  "pendiente de decision - Garantia y Calidad": "warn",
};

export function pildoraValidacion(valor: unknown): string {
  const v = String(valor);
  return pildora(TIPO_POR_VALIDACION[v] ?? "neutro", ETIQUETA_VALIDACION[v] ?? v);
}

// Resultado acumulado de un eslabon H1..H6 (cadena_calidad.py) -- "pasa"
// quiere decir que la fila supero esta condicion Y todas las anteriores de
// la cadena (interseccion, no solo la de este paso).
export function pildoraEstadoCadena(valor: unknown): string {
  const v = String(valor);
  return pildora(v === "pasa" ? "ok" : "danger", v === "pasa" ? "Pasa" : "No pasa");
}
