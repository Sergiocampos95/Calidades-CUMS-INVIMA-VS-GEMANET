import { obtenerIum, obtenerResumenIum, obtenerValoresColumna } from "../api";
import { ETIQUETAS_COLUMNA_COMUNES, ETIQUETAS_IUM, pildoraEstadoCoherencia, pildoraEstadoIum } from "../pildoras";
import { TablaFiltrable } from "../tabla";

const ETIQUETAS: Record<string, string> = { ...ETIQUETAS_COLUMNA_COMUNES, ...ETIQUETAS_IUM };

function formatearCeldaIum(columna: string, valor: unknown): string | null {
  if (columna === "ESTADO_IUM") return pildoraEstadoIum(valor);
  if (columna === "ESTADO_COHERENCIA") return pildoraEstadoCoherencia(valor);
  if (columna === "CUM_INVIMA" && Array.isArray(valor)) {
    return valor.length ? valor.join(", ") : "";
  }
  return null;
}

export async function montarIum(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML =
    `<p class="vista__intro">Medicamentos que Gemma Net identifica por IUM, comparados contra INVIMA -- ` +
    `módulo separado del de CUM, no repite esas cifras. Solo se compara campo a campo cuando INVIMA ` +
    `asocia el IUM a un único CUM; con varios, queda marcado para revisión en vez de elegir uno.</p>`;

  const banner = document.createElement("div");
  contenedor.appendChild(banner);
  try {
    const resumen = await obtenerResumenIum();
    const total = Object.values(resumen).reduce((a, b) => a + b, 0);
    const comparados = resumen["un_cum"] ?? 0;
    banner.className = "banner";
    banner.style.margin = "0 0 16px";
    banner.textContent =
      total === 0
        ? "Todavía no hay IUM cargados en Gemma Net."
        : `${total.toLocaleString("es-CO")} IUM cargados — ${comparados.toLocaleString("es-CO")} se pudieron comparar contra INVIMA.`;
  } catch {
    /* la tabla de abajo ya muestra el error si lo hay */
  }

  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    idTabla: "ium_auditoria",
    columnas: ["CODIGO_INTERNO", "ESTADO_IUM", "CUM_INVIMA", "IDENTIDAD_DUPLICADA", "ESTADO_COHERENCIA"],
    etiquetasColumna: ETIQUETAS,
    formatearCelda: formatearCeldaIum,
    cargarPagina: (p) => obtenerIum(p),
    obtenerValoresColumna: (columna) => obtenerValoresColumna("/ium/valores", columna),
  });
}
