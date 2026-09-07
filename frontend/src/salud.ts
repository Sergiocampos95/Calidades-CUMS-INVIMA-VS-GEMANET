import { obtenerSalud } from "./api";
import { fijarSnapshot } from "./cache_tablas";
import type { EstadoSalud } from "./tipos";

// Cada cuanto se vuelve a consultar /salud mientras la pagina esta abierta.
const INTERVALO_REVISION_MS = 60_000;
// El worker refresca cada ~50 min (ver worker/refresco.py) -- el anillo se
// llena en funcion de que tan cerca esta la antiguedad del snapshot de ese
// umbral. Es dato REAL (antiguedad_segundos de /salud), no una cuenta
// regresiva decorativa: no sabemos el momento exacto del proximo refresco,
// solo que tan fresco es lo que estamos mostrando ahora mismo.
const INTERVALO_WORKER_SEGUNDOS = 50 * 60;

const ETIQUETA_POR_ESTADO: Record<EstadoSalud["estado"], string> = {
  ok: "🟢 Datos al día",
  desactualizado: "🟡 Datos desactualizados",
  error: "🔴 El último refresco falló",
  sin_datos: "⚪ Todavía no hay datos (el worker no corrió aún)",
};

function formatearAntiguedad(segundos: number | null): string {
  if (segundos === null) return "sin datos";
  const minutos = Math.round(segundos / 60);
  if (minutos < 1) return "hace instantes";
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.round(minutos / 60);
  return `hace ${horas} h`;
}

/** Pinta el banner (solo si algo no esta "ok") y el anillo de frescura de
 * la barra superior -- ambos alimentados por el mismo /salud, mismo
 * principio de "degradacion explicita, nunca fallo silencioso" que rige
 * toda la app real. */
export function montarSalud(elementos: {
  banner: HTMLElement;
  anillo: HTMLElement;
  textoRefresco: HTMLElement;
  subtextoRefresco: HTMLElement;
  contenedorRefresco: HTMLElement;
}): void {
  const revisar = async () => {
    try {
      const salud = await obtenerSalud();
      // La cache de tablas versiona sus entradas por snapshot. Se alimenta
      // desde aca en vez de que cada tabla pregunte a /salud por su cuenta:
      // este sondeo ya corre igual para el anillo de "hace N min", y asi hay
      // UN solo sitio que sabe cual es el snapshot vigente.
      fijarSnapshot(salud.ultima_actualizacion_utc ?? null);
      pintarBanner(elementos.banner, salud);
      pintarRefresco(elementos, salud);
    } catch (error) {
      elementos.banner.hidden = false;
      elementos.banner.className = "banner banner--error";
      elementos.banner.textContent = `🔴 No se pudo consultar el estado del servicio — ${error instanceof Error ? error.message : String(error)}`;
      elementos.textoRefresco.textContent = "—";
      elementos.subtextoRefresco.textContent = "sin conexión";
    }
  };

  void revisar();
  setInterval(() => void revisar(), INTERVALO_REVISION_MS);
}

function pintarBanner(banner: HTMLElement, salud: EstadoSalud): void {
  if (salud.estado === "ok") {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  banner.className = `banner banner--${salud.estado}`;
  const antiguedad = formatearAntiguedad(salud.antiguedad_segundos);
  const detalle = salud.detalle_error ? ` — ${salud.detalle_error}` : "";
  banner.textContent = `${ETIQUETA_POR_ESTADO[salud.estado]} (${antiguedad})${detalle}`;
}

function pintarRefresco(
  elementos: { anillo: HTMLElement; textoRefresco: HTMLElement; subtextoRefresco: HTMLElement; contenedorRefresco: HTMLElement },
  salud: EstadoSalud,
): void {
  const { anillo, textoRefresco, subtextoRefresco, contenedorRefresco } = elementos;
  if (salud.antiguedad_segundos === null) {
    textoRefresco.textContent = "Sin datos";
    subtextoRefresco.textContent = "el worker no corrió aún";
    contenedorRefresco.className = "refresco refresco--warn";
    anillo.style.setProperty("--pct", "0%");
    return;
  }
  const proporcion = Math.min(salud.antiguedad_segundos / INTERVALO_WORKER_SEGUNDOS, 1);
  anillo.style.setProperty("--pct", `${(1 - proporcion) * 100}%`);
  textoRefresco.textContent = formatearAntiguedad(salud.antiguedad_segundos);
  subtextoRefresco.textContent = salud.estado === "error" ? "último refresco falló" : "desde el último refresco";
  contenedorRefresco.className =
    salud.estado === "error" ? "refresco refresco--danger" : proporcion > 0.85 ? "refresco refresco--warn" : "refresco";
}
