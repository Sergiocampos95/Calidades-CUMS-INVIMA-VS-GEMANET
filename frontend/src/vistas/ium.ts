import {
  obtenerCalidadesIum,
  obtenerCalidadIum,
  obtenerIum,
  obtenerResumenIum,
  obtenerSeccionesCalidadIum,
  obtenerValoresColumna,
} from "../api";
import { ETIQUETAS_COLUMNA_COMUNES, ETIQUETAS_IUM, pildoraEstadoCoherencia, pildoraEstadoIum } from "../pildoras";
import { TablaFiltrable } from "../tabla";
import type { CalidadResumen, SeccionCalidad } from "../tipos";
import {
  chipSeccion,
  esc,
  ETIQUETAS_ACTIVO_VS_INVIMA,
  formatearCeldaCalidad,
  habilitarCopiarSQL,
} from "./auditoria";

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

const ETIQUETAS_CALIDAD_IUM: Record<string, string> = { ...ETIQUETAS_ACTIVO_VS_INVIMA, ...ETIQUETAS_IUM };

// "Casos por calidad" del modulo IUM -- mismo patron visual que
// montarAuditEntender (CUM) en vistas/auditoria.ts, simplificado porque hoy
// hay una sola calidad ("Diferencia de estado o campos"): no hace falta el
// selector de calidades (los chips de arriba), solo el panel de criterios,
// las secciones (tipo de diferencia) y la tabla. Si en el futuro se agrega
// una segunda calidad IUM, ahi si vale la pena portar el selector completo.
export async function montarIumCalidad(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = "";
  const cabecera = document.createElement("div");
  contenedor.appendChild(cabecera);
  const secciones = document.createElement("div");
  secciones.className = "chips oculto";
  contenedor.appendChild(secciones);
  const columnaTabla = document.createElement("div");
  contenedor.appendChild(columnaTabla);
  habilitarCopiarSQL(columnaTabla);

  let calidad: CalidadResumen;
  try {
    const calidades = await obtenerCalidadesIum();
    if (!calidades.length) {
      columnaTabla.innerHTML = `<p class="aviso aviso--error">No hay ninguna calidad IUM definida.</p>`;
      return;
    }
    calidad = calidades[0];
  } catch (error) {
    columnaTabla.innerHTML = `<p class="aviso aviso--error">${esc(error instanceof Error ? error.message : String(error))}</p>`;
    return;
  }

  let seccionActual: string | null = null;
  let seccionesDeCalidad: SeccionCalidad[] = [];

  function panelCriterios(seccion: SeccionCalidad | null): string {
    const criterios = calidad.criterios.map((c) => `<li>${esc(c)}</li>`).join("");
    const bloqueSeccion = seccion
      ? `<div class="criterios__seccion"><strong>Viendo solo ${esc(seccion.etiqueta)}</strong> — ${seccion.medicamentos.toLocaleString("es-CO")} de ${calidad.medicamentos.toLocaleString("es-CO")}.${seccion.explica ? ` ${esc(seccion.explica)}` : ""}</div>`
      : "";
    return `<div class="caso-cabecera"><h1>${esc(calidad.nombre)}</h1><span class="badge pildora--neutro">${calidad.medicamentos.toLocaleString("es-CO")} medicamentos · ${calidad.porcentaje_del_catalogo.toFixed(1)}%</span></div>
    <div class="criterios">
      <div class="criterios__titulo">Qué detecta esta calidad</div>
      <p class="criterios__explica">${esc(calidad.explica)}</p>
      <div class="criterios__cuerpo">
        <div>
          <div class="criterios__titulo">Entra aquí un IUM cuando</div>
          <ul class="criterios__lista">${criterios}</ul>
        </div>
        <div>
          <div class="criterios__titulo">Qué hacer</div>
          <p class="criterios__texto">${esc(calidad.que_hacer)}</p>
        </div>
      </div>
      ${bloqueSeccion}
    </div>`;
  }

  function dibujarTabla(seccion: SeccionCalidad | null): void {
    cabecera.innerHTML = panelCriterios(seccion);
    columnaTabla.innerHTML = "";
    if (calidad.medicamentos === 0) {
      columnaTabla.innerHTML = `<div class="panel"><p class="vista__intro" style="margin:0">Ningún IUM cae en esta calidad en la corrida actual. ✔</p></div>`;
      return;
    }
    const tablaEl = document.createElement("div");
    columnaTabla.appendChild(tablaEl);
    const clave = seccion?.clave;
    new TablaFiltrable(tablaEl, {
      columnas: calidad.columnas,
      idTabla: `calidad_ium:${calidad.nombre}`,
      seccion: clave,
      formatearCelda: formatearCeldaCalidad,
      etiquetasColumna: ETIQUETAS_CALIDAD_IUM,
      cargarPagina: (p) => obtenerCalidadIum(calidad.nombre, { ...p, seccion: clave }),
      obtenerValoresColumna: (columna) =>
        obtenerValoresColumna(`/ium/calidades/${encodeURIComponent(calidad.nombre)}/valores`, columna, clave),
    });
  }

  function dibujarSecciones(lista: SeccionCalidad[]): void {
    secciones.classList.toggle("oculto", lista.length === 0);
    if (lista.length === 0) {
      secciones.innerHTML = "";
      return;
    }
    secciones.innerHTML =
      `<span class="chips__rotulo" title="Un IUM puede caer en varios tipos, así que los números no suman el total de la calidad.">Tipo de diferencia:</span>` +
      `<button type="button" class="chip${seccionActual === null ? " activo" : ""}" data-seccion="">Todos</button>` +
      lista.map((s) => chipSeccion(s, s.clave === seccionActual)).join("");
  }

  secciones.addEventListener("click", (evento) => {
    const chip = (evento.target as HTMLElement).closest<HTMLElement>("[data-seccion]");
    if (!chip) return;
    const clave = chip.dataset.seccion ?? "";
    seccionActual = clave === "" || clave === seccionActual ? null : clave;
    dibujarSecciones(seccionesDeCalidad);
    dibujarTabla(seccionesDeCalidad.find((s) => s.clave === seccionActual) ?? null);
  });

  dibujarTabla(null);
  try {
    seccionesDeCalidad = await obtenerSeccionesCalidadIum(calidad.nombre);
    dibujarSecciones(seccionesDeCalidad);
  } catch (error) {
    secciones.classList.remove("oculto");
    secciones.innerHTML = `<p class="aviso aviso--error">${esc(error instanceof Error ? error.message : String(error))}</p>`;
  }
}
