import { obtenerAuditoria, obtenerCandidatos, obtenerValoresColumna } from "../api";
import { TablaFiltrable } from "../tabla";

export function montarPorqueNuevos(contenedor: HTMLElement): void {
  contenedor.innerHTML = `<p class="vista__intro">El o los candidatos nuevos de esta corrida, con el motivo exacto por el que siguen sin estar en Gemma Net.</p>`;
  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: ["CODIGO_INTERNO", "DESCRIPCION", "EXPEDIENTE", "CONSECUTIVO", "motivo"],
    cargarPagina: (p) => obtenerCandidatos({ ...p, accion: "candidato" }),
    obtenerValoresColumna: (columna) => obtenerValoresColumna("/candidatos/valores", columna),
  });
}

export function montarPorqueDiferencias(contenedor: HTMLElement): void {
  contenedor.innerHTML = `<p class="vista__intro">Medicamentos que SÍ existen en Gemma Net pero cuyo dato ya no coincide con el oficial de INVIMA.</p>`;
  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: ["CODIGO_INTERNO", "DESCRIPCION", "CAMPOS_CON_DIFERENCIA", "PORCENTAJE_CALIDAD"],
    cargarPagina: (p) => obtenerAuditoria({ ...p, estado_coherencia: "con_diferencias" }),
    obtenerValoresColumna: (columna) => obtenerValoresColumna("/auditoria/valores", columna),
  });
}

export function montarPorqueVigencia(contenedor: HTMLElement): void {
  contenedor.innerHTML = `<p class="vista__intro">Casos donde el estado local y el de INVIMA no coinciden. Buscá "activo" para ver los de mayor riesgo — activos aquí, vencidos en INVIMA.</p>`;
  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: ["CODIGO_INTERNO", "DESCRIPCION", "ESTADO_COHERENCIA", "NOVEDAD_VIGENCIA_INVIMA", "DETALLE_VIGENCIA_INVIMA"],
    cargarPagina: (p) => obtenerAuditoria(p),
    obtenerValoresColumna: (columna) => obtenerValoresColumna("/auditoria/valores", columna),
  });
}
