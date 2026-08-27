import { obtenerCandidatos, obtenerResumenCandidatos } from "../api";
import { TablaFiltrable } from "../tabla";

export async function montarDecision(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = `<p class="vista__intro">Nada se descarta en silencio: lo que no se puede decidir con certeza cae acá para que una persona resuelva.</p>`;
  const banner = document.createElement("div");
  contenedor.appendChild(banner);
  try {
    const resumen = await obtenerResumenCandidatos();
    const n = resumen.cuarentena ?? 0;
    banner.className = `banner ${n === 0 ? "" : "banner--desactualizado"}`;
    banner.style.margin = "0 0 16px";
    banner.textContent =
      n === 0 ? "🟢 0 casos en cuarentena en la corrida actual — es el mejor resultado posible." : `🟡 ${n.toLocaleString("es-CO")} caso(s) requieren decisión.`;
  } catch {
    /* la tabla de abajo ya muestra el error si lo hay */
  }

  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: ["CODIGO_INTERNO", "DESCRIPCION", "EXPEDIENTE", "CONSECUTIVO", "motivo"],
    cargarPagina: (p) => obtenerCandidatos({ ...p, accion: "cuarentena" }),
  });
}
