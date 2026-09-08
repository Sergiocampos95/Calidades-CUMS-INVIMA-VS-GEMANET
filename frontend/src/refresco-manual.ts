/**
 * "Actualizar ahora": pide al worker que adelante su corrida periodica
 * (POST /refrescar) y sondea GET /refrescar/progreso hasta que termina,
 * mostrando una lista paso a paso -- pedido explicito del usuario
 * (2026-08-27): "un ejemplo como cuando uno descarga varias cosas en
 * Google y podemos ver en que porcentaje va cada una... para sersiorarnos
 * que la informacion es correctamente actualizada y no quedarse en una
 * pantalla cargando sin saber cuanto se va a demorar".
 *
 * No hay un "% real" por paso (leer INVIMA/auditar/etc. son llamadas
 * opacas de varios segundos) -- se muestra el checklist honesto que SI se
 * puede medir: pendiente -> en_curso -> hecho/error por paso.
 */

import { obtenerProgresoRefresco, pedirRefresco } from "./api";
import type { FuenteRefresco } from "./api";
import type { EstadoPaso, PasoProgreso } from "./tipos";

/** Las dos fuentes, tal como se le preguntan al usuario al pulsar el boton.
 *
 * Se PREGUNTA en vez de dejar un selector siempre visible (pedido del
 * usuario, 2026-09-07: "al dar click en el boton de actualizar debe de pedir
 * si mediante listado o JSON") porque las dos fuentes producen cifras muy
 * distintas y el snapshot resultante se ve igual de sano en los dos casos: un
 * selector con memoria hace facil actualizar desde la fuente equivocada sin
 * enterarse. Preguntar cada vez obliga a una decision consciente.
 *
 * `archivos` va primero y es la recomendada: la API todavia no esta
 * soportada de punta a punta -- "Consultar INVIMA" no procesa el JSON de
 * Socrata (ver ingesta/fuente_invima.py::FUENTE_DEFECTO). */
const OPCIONES_FUENTE: { valor: FuenteRefresco; etiqueta: string; ayuda: string }[] = [
  {
    valor: "archivos",
    etiqueta: "📄 Desde los listados",
    ayuda: "Los Excel de INVIMA guardados en data/. Es la fuente con la que funciona toda la aplicación, incluida la consulta puntual de un CUM.",
  },
  {
    valor: "api",
    etiqueta: "🌐 Desde el JSON de INVIMA",
    ayuda: "La API de Socrata, con el catálogo de hoy. Ojo: la vista “Consultar INVIMA” todavía no procesa este formato, así que puede contradecir a las tarjetas.",
  },
];

const INTERVALO_SONDEO_MS = 1500;
// El vigilante del worker revisa la solicitud cada 5s (worker/refresco.py)
// -- si a los 30s todavia no arranco, algo raro pasa (el worker no esta
// corriendo, por ejemplo) y hay que decirlo, no seguir sondeando en silencio.
const ESPERA_MAXIMA_SIN_INICIAR_MS = 30_000;

const ICONO_POR_ESTADO: Record<EstadoPaso, string> = {
  pendiente: "○",
  en_curso: "◐",
  hecho: "✓",
  error: "✕",
};

function esc(valor: unknown): string {
  return String(valor).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}

function renderPasos(pasos: PasoProgreso[]): string {
  return pasos
    .map(
      (p) => `<div class="paso-progreso paso-progreso--${p.estado}">
        <span class="paso-progreso__icono">${ICONO_POR_ESTADO[p.estado]}</span>
        <div>
          <div class="paso-progreso__nombre">${esc(p.nombre)}</div>
          ${p.estado === "error" && p.detalle ? `<div class="paso-progreso__detalle">${esc(p.detalle)}</div>` : ""}
        </div>
      </div>`,
    )
    .join("");
}

/** `alTerminar(exito)` se llama una vez, cuando la corrida termina (o el
 * sondeo se rinde) -- el llamador decide que hacer (ej. re-renderizar la
 * vista actual para que se vean los datos frescos sin recargar la pagina). */
export function montarRefrescoManual(
  boton: HTMLButtonElement,
  panel: HTMLElement,
  alTerminar: (exito: boolean) => void,
): void {
  let sondeo: ReturnType<typeof setInterval> | undefined;
  let vistoEnCurso = false;
  let inicioSolicitud = 0;

  function detener(): void {
    if (sondeo) clearInterval(sondeo);
    sondeo = undefined;
    boton.disabled = false;
  }

  async function sondear(): Promise<void> {
    let progreso;
    try {
      progreso = await obtenerProgresoRefresco();
    } catch {
      return; // un fallo de red puntual no corta el sondeo, se reintenta solo
    }

    if (progreso.en_curso) {
      vistoEnCurso = true;
      panel.innerHTML = `<div class="panel-progreso__titulo">⟳ Actualizando datos…</div><div class="panel-progreso__lista">${renderPasos(progreso.pasos)}</div>`;
      return;
    }

    if (vistoEnCurso) {
      // Ya vimos que arranco (en_curso=true en un sondeo anterior) y ahora
      // ya no lo esta -- termino, para bien o para mal.
      const huboError = progreso.pasos.some((p) => p.estado === "error");
      panel.innerHTML = `<div class="panel-progreso__titulo">${
        huboError ? "✕ La actualización terminó con un error" : "✓ Actualización completa"
      }</div><div class="panel-progreso__lista">${renderPasos(progreso.pasos)}</div>`;
      detener();
      alTerminar(!huboError);
      return;
    }

    if (Date.now() - inicioSolicitud > ESPERA_MAXIMA_SIN_INICIAR_MS) {
      panel.innerHTML =
        `<div class="panel-progreso__titulo">El worker no tomó la solicitud a tiempo</div>` +
        `<p style="font-size:0.8rem;color:var(--text-muted);margin:0">Puede que el proceso del worker no esté corriendo ahora mismo.</p>`;
      detener();
      alTerminar(false);
      return;
    }
    panel.innerHTML = `<div class="panel-progreso__titulo">Esperando a que el worker tome la solicitud…</div>`;
  }

  /** Pinta la pregunta de fuente dentro del mismo panel de progreso -- no
   * hace falta un modal nuevo, y ademas queda en el sitio exacto donde
   * despues van a salir los pasos. */
  function preguntarFuente(): void {
    panel.classList.remove("oculto");
    panel.innerHTML =
      `<div class="panel-progreso__titulo">¿Con qué fuente querés actualizar?</div>` +
      `<div class="eleccion-fuente">${OPCIONES_FUENTE.map(
        (o) =>
          `<button type="button" class="btn btn--suave eleccion-fuente__opcion" data-fuente="${o.valor}" title="${esc(o.ayuda)}">
             <strong>${esc(o.etiqueta)}</strong><span>${esc(o.ayuda)}</span>
           </button>`,
      ).join("")}</div>` +
      `<button type="button" class="eleccion-fuente__cancelar" data-fuente="">Cancelar</button>`;
  }

  function lanzar(fuente: FuenteRefresco): void {
    boton.disabled = true;
    vistoEnCurso = false;
    inicioSolicitud = Date.now();
    panel.innerHTML = `<div class="panel-progreso__titulo">Enviando la solicitud… (${
      fuente === "archivos" ? "listados en archivo" : "JSON de INVIMA"
    })</div>`;

    pedirRefresco(fuente)
      .then(() => {
        sondeo = setInterval(() => void sondear(), INTERVALO_SONDEO_MS);
        void sondear();
      })
      .catch((error) => {
        panel.innerHTML =
          `<div class="panel-progreso__titulo">✕ No se pudo pedir la actualización</div>` +
          `<p style="font-size:0.8rem;color:var(--danger);margin:0">${esc(error instanceof Error ? error.message : String(error))}</p>`;
        boton.disabled = false;
      });
  }

  // Delegado en el panel: `preguntarFuente` rehace su innerHTML en cada
  // apertura, asi que un listener por boton se perderia.
  panel.addEventListener("click", (evento) => {
    const opcion = (evento.target as HTMLElement).closest<HTMLElement>("[data-fuente]");
    if (!opcion || sondeo) return;
    const fuente = opcion.dataset.fuente;
    if (fuente === "archivos" || fuente === "api") {
      lanzar(fuente);
    } else {
      panel.classList.add("oculto");
      panel.innerHTML = "";
    }
  });

  boton.addEventListener("click", () => {
    if (sondeo) return; // ya hay una corrida siendo seguida
    preguntarFuente();
  });
}
