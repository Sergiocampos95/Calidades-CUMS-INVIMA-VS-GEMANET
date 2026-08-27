import { obtenerAuditoria, obtenerResumenAuditoria } from "./api";
import { renderTarjetas } from "./tarjetas";
import { TablaFiltrable } from "./tabla";

const COLUMNAS = ["CODIGO_INTERNO", "PRODUCTO", "ESTADO_COHERENCIA", "CAMPOS_CON_DIFERENCIA", "PORCENTAJE_CALIDAD"];

// Mismo vocabulario que `EstadoCoherencia` en auditoria/coherencia_invima.py
const ESTADOS: Array<{ valor: string; etiqueta: string }> = [
  { valor: "", etiqueta: "Todos los estados" },
  { valor: "correcto", etiqueta: "Correcto" },
  { valor: "con_diferencias", etiqueta: "Con diferencias" },
  { valor: "vencido_en_invima", etiqueta: "Vencido en INVIMA" },
  { valor: "encontrado_en_otro_estado_invima", etiqueta: "En otro estado en INVIMA" },
  { valor: "en_tramite_renovacion_invima", etiqueta: "En trámite de renovación" },
  { valor: "vigente_no_comercializado_invima", etiqueta: "Vigente, no comercializado" },
  { valor: "sin_correspondencia_invima", etiqueta: "Sin correspondencia con INVIMA" },
];

const TARJETAS = ESTADOS.filter((e) => e.valor !== "").map((e) => ({
  clave: e.valor,
  etiqueta: e.etiqueta,
}));

export async function montarVistaAuditoria(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = "";

  const seccionTarjetas = document.createElement("div");
  contenedor.appendChild(seccionTarjetas);
  seccionTarjetas.textContent = "Cargando resumen…";
  try {
    const resumen = await obtenerResumenAuditoria();
    renderTarjetas(seccionTarjetas, TARJETAS, resumen);
  } catch (error) {
    seccionTarjetas.textContent = error instanceof Error ? error.message : String(error);
  }

  const selectorEstado = document.createElement("select");
  selectorEstado.className = "selector-estado";
  for (const estado of ESTADOS) {
    const opcion = document.createElement("option");
    opcion.value = estado.valor;
    opcion.textContent = estado.etiqueta;
    selectorEstado.appendChild(opcion);
  }
  let estadoElegido = "";
  selectorEstado.addEventListener("change", () => {
    estadoElegido = selectorEstado.value;
    selectorEstado.dispatchEvent(new CustomEvent("cambio-filtro"));
  });

  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: COLUMNAS,
    controlesExtra: selectorEstado,
    cargarPagina: (parametros) =>
      obtenerAuditoria({ ...parametros, estado_coherencia: estadoElegido || undefined }),
  });
}
