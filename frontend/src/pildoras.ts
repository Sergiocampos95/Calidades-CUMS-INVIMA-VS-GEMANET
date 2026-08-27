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
