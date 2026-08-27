import { obtenerCandidatos, obtenerResumenCandidatos } from "./api";
import { renderTarjetas } from "./tarjetas";
import { TablaFiltrable } from "./tabla";

const COLUMNAS = ["CODIGO_INTERNO", "DESCRIPCION", "EXPEDIENTE", "CONSECUTIVO", "accion", "motivo"];

const TARJETAS = [
  {
    clave: "candidato",
    etiqueta: "Candidatos a crear",
    ayuda: "Están en INVIMA, cumplen todo, y su código no existe todavía en Gemma Net.",
  },
  {
    clave: "ya_existe",
    etiqueta: "Ya en Gemma Net",
    ayuda: "Su código ya está cargado en la plataforma: no hay nada que crear.",
  },
  {
    clave: "cuarentena",
    etiqueta: "Casos que requieren decisión",
    ayuda: "No se pudo decidir con certeza y se aparta para que una persona resuelva.",
  },
];

export async function montarVistaCandidatos(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = "";

  const seccionTarjetas = document.createElement("div");
  contenedor.appendChild(seccionTarjetas);
  seccionTarjetas.textContent = "Cargando resumen…";
  try {
    const resumen = await obtenerResumenCandidatos();
    renderTarjetas(seccionTarjetas, TARJETAS, resumen);
  } catch (error) {
    seccionTarjetas.textContent = error instanceof Error ? error.message : String(error);
  }

  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: COLUMNAS,
    cargarPagina: (parametros) => obtenerCandidatos(parametros),
  });
}
