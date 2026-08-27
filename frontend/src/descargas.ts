import { urlDescarga } from "./api";

/** Markup del boton de descarga -- un <a> nativo hacia /descargas/*, sin
 * fetch+blob: el backend ya pone Content-Disposition: attachment, asi que
 * el navegador dispara la descarga solo. Un solo lugar que arma esto para
 * que las 3 vistas que ofrecen descarga (resumen, auditoria, cargue)
 * queden con el mismo boton, mismo criterio que TablaFiltrable siendo el
 * unico lugar que dibuja una tabla. */
export function botonDescarga(etiqueta: string, ruta: Parameters<typeof urlDescarga>[0]): string {
  return `<a class="btn btn--suave btn--descarga" href="${urlDescarga(ruta)}">⬇ ${etiqueta}</a>`;
}

/** Envuelve un texto de intro + el boton de descarga en la cabecera comun
 * de la vista (ver .vista__cabecera en estilo.css). */
export function cabeceraConDescarga(intro: string, etiqueta: string, ruta: Parameters<typeof urlDescarga>[0]): string {
  return `<div class="vista__cabecera"><p class="vista__intro">${intro}</p>${botonDescarga(etiqueta, ruta)}</div>`;
}
