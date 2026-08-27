import { obtenerUniverso } from "../api";
import { TablaFiltrable } from "../tabla";

export function montarConsultarInvima(contenedor: HTMLElement): void {
  contenedor.innerHTML = `<p class="vista__intro">Escribí un código, expediente o nombre para ver el estado del registro en INVIMA.</p>`;
  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: ["CODIGO_INTERNO", "PRODUCTO", "TITULAR", "TIPO_ROL", "ESTADO_CUM", "ESTADO_REGISTRO", "CLASIFICACION_CREACION"],
    cargarPagina: (p) => obtenerUniverso(p),
  });
}
