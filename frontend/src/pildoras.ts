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


// Vocabulario de NOVEDAD_VIGENCIA_INVIMA (auditoria/coherencia_invima.py,
// dimension 10) -- mismas etiquetas que _ETIQUETA_VALOR_INTERNO en
// app_streamlit.py, para que decir "vigente o no" no invente un texto nuevo.
const ETIQUETA_NOVEDAD_VIGENCIA: Record<string, string> = {
  riesgo_activo_sin_vigencia: "Activo aquí, sin vigencia en INVIMA",
  registro_vencido_en_invima: "Registro vencido en INVIMA",
  revisar_reactivacion: "Inactivo aquí, con registro vivo en INVIMA",
  actualizar_fecha_fin: "Falta la fecha de fin que INVIMA sí tiene",
  coherente: "Los dos lados coinciden",
  no_verificable: "No se puede verificar contra INVIMA",
};

const TIPO_POR_NOVEDAD_VIGENCIA: Record<string, string> = {
  riesgo_activo_sin_vigencia: "danger",
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
const ETIQUETA_VALIDACION: Record<string, string> = {
  coincide: "Coincide",
  difiere: "Difiere",
  "sin comparar": "Sin comparar",
  "sin dato en Gemma Net": "Sin dato en Gemma Net",
};

const TIPO_POR_VALIDACION: Record<string, string> = {
  coincide: "ok",
  difiere: "danger",
  "sin comparar": "neutro",
  "sin dato en Gemma Net": "warn",
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
