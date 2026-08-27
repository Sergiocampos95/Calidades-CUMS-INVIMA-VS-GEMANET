import { obtenerSalud } from "./api";
import type { EstadoSalud } from "./tipos";

// Cada cuanto se vuelve a consultar /salud mientras la pagina esta abierta
// -- no tiene que ser exacto, solo lo bastante seguido para notar un
// refresco fallido sin recargar la pagina a mano.
const INTERVALO_REVISION_MS = 60_000;

const ETIQUETA_POR_ESTADO: Record<EstadoSalud["estado"], string> = {
  ok: "🟢 Datos al día",
  desactualizado: "🟡 Datos desactualizados",
  error: "🔴 El último refresco falló",
  sin_datos: "⚪ Todavía no hay datos (el worker no corrió aún)",
};

function formatearAntiguedad(segundos: number | null): string {
  if (segundos === null) return "";
  const minutos = Math.round(segundos / 60);
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.round(minutos / 60);
  return `hace ${horas} h`;
}

/** El banner que sostiene "degradacion explicita, nunca fallo silencioso"
 * (mismo principio que CLAUDE.md exige en toda la app): siempre visible en
 * la parte de arriba, nunca escondido en un tooltip, cuando el estado no
 * es "ok". */
export function montarBannerSalud(contenedor: HTMLElement): void {
  const revisar = async () => {
    try {
      const salud = await obtenerSalud();
      if (salud.estado === "ok") {
        contenedor.hidden = true;
        return;
      }
      contenedor.hidden = false;
      contenedor.className = `banner-salud banner-salud--${salud.estado}`;
      const antiguedad = formatearAntiguedad(salud.antiguedad_segundos);
      const detalle = salud.detalle_error ? ` — ${salud.detalle_error}` : "";
      contenedor.textContent = `${ETIQUETA_POR_ESTADO[salud.estado]}${antiguedad ? " (" + antiguedad + ")" : ""}${detalle}`;
    } catch (error) {
      contenedor.hidden = false;
      contenedor.className = "banner-salud banner-salud--error";
      contenedor.textContent = `🔴 No se pudo consultar el estado del servicio — ${error instanceof Error ? error.message : String(error)}`;
    }
  };

  void revisar();
  setInterval(() => void revisar(), INTERVALO_REVISION_MS);
}
