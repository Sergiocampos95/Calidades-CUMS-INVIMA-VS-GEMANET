import { obtenerAuditoria, obtenerCadena, obtenerEslabon, obtenerResumenAuditoria } from "../api";
import { cabeceraConDescarga } from "../descargas";
import { ESTADOS_COHERENCIA, etiquetaEstadoCoherencia, pildoraEstadoCoherencia } from "../pildoras";
import { renderTarjetas } from "../tarjetas";
import { TablaFiltrable } from "../tabla";
import type { EslabonResumen } from "../tipos";

const FORMATEADOR_ESTADO = (columna: string, valor: unknown) =>
  columna === "ESTADO_COHERENCIA" ? pildoraEstadoCoherencia(valor) : null;

function selectorEstado(): HTMLSelectElement {
  const select = document.createElement("select");
  for (const [valor, etiqueta] of [["", "Todos los estados"], ...ESTADOS_COHERENCIA.map((e) => [e, etiquetaEstadoCoherencia(e)])]) {
    const opcion = document.createElement("option");
    opcion.value = valor;
    opcion.textContent = etiqueta;
    select.appendChild(opcion);
  }
  return select;
}

export async function montarAuditPriorizar(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = `<p class="vista__intro">Priorizá una acción: cada tarjeta es un estado de coherencia con Gemma Net, de mayor a menor riesgo.</p>`;
  const tarjetas = document.createElement("div");
  contenedor.appendChild(tarjetas);
  try {
    const resumen = await obtenerResumenAuditoria();
    renderTarjetas(
      tarjetas,
      [
        { clave: "vencido_en_invima", etiqueta: "Vencido en INVIMA" },
        { clave: "encontrado_en_otro_estado_invima", etiqueta: "En otro estado en INVIMA" },
        { clave: "en_tramite_renovacion_invima", etiqueta: "En trámite de renovación" },
        { clave: "con_diferencias", etiqueta: "Con algún campo distinto al de INVIMA" },
      ],
      resumen,
    );
  } catch (error) {
    tarjetas.innerHTML = `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
  }

  const select = selectorEstado();
  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: ["CODIGO_INTERNO", "PRODUCTO", "ESTADO_COHERENCIA"],
    controlesExtra: select,
    formatearCelda: FORMATEADOR_ESTADO,
    cargarPagina: (p) => obtenerAuditoria({ ...p, estado_coherencia: select.value || undefined }),
  });
}

export async function montarAuditEntender(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML =
    `<p class="vista__intro">Distribución del catálogo por estado de coherencia frente a INVIMA. ` +
    `Vista simplificada del backend actual (7 estados reales) — la versión de 11 calidades de Streamlit todavía no tiene endpoint propio.</p>`;
  const panel = document.createElement("div");
  panel.className = "panel";
  contenedor.appendChild(panel);
  try {
    const resumen = await obtenerResumenAuditoria();
    const total = Object.values(resumen).reduce((a, b) => a + b, 0) || 1;
    const filas = Object.entries(resumen)
      .sort((a, b) => b[1] - a[1])
      .map(([clave, n]) => `<tr><td>${pildoraEstadoCoherencia(clave)}</td><td class="celda-mono">${n.toLocaleString("es-CO")}</td><td class="celda-mono">${((n / total) * 100).toFixed(1)}%</td></tr>`)
      .join("");
    panel.innerHTML = `<div class="tabla-filtrable__envoltorio" style="max-height:360px"><table><thead><tr><th>Estado</th><th>Medicamentos</th><th>% del catálogo</th></tr></thead><tbody>${filas}</tbody></table></div>`;
  } catch (error) {
    panel.innerHTML = `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
  }
}

export async function montarAuditExplorar(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = cabeceraConDescarga(
    "Todos los hallazgos, filtrables por estado. Buscá por código o producto para llegar directo a un medicamento.",
    "Descargar auditoría completa (.xlsx)",
    "auditoria",
  );
  const tarjetas = document.createElement("div");
  contenedor.appendChild(tarjetas);
  try {
    const resumen = await obtenerResumenAuditoria();
    renderTarjetas(
      tarjetas,
      ESTADOS_COHERENCIA.slice(0, 4).map((e) => ({ clave: e, etiqueta: etiquetaEstadoCoherencia(e) })),
      resumen,
    );
  } catch {
    /* la tabla de abajo ya muestra el error si lo hay */
  }

  const select = selectorEstado();
  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: ["CODIGO_INTERNO", "PRODUCTO", "ESTADO_COHERENCIA", "CAMPOS_CON_DIFERENCIA", "PORCENTAJE_CALIDAD"],
    controlesExtra: select,
    formatearCelda: FORMATEADOR_ESTADO,
    cargarPagina: (p) => obtenerAuditoria({ ...p, estado_coherencia: select.value || undefined }),
  });
}

export async function montarCadenaCalidad(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML =
    `<p class="vista__intro">Cada tabla valida un campo más que la anterior, sobre las mismas filas (pedido de Sergio). ` +
    `H5 (laboratorio) está pendiente de confirmar con negocio, no se muestra todavía.</p>`;

  const grid = document.createElement("div");
  grid.className = "grid-2";
  contenedor.appendChild(grid);
  const columnaPasos = document.createElement("div");
  const columnaTabla = document.createElement("div");
  grid.append(columnaPasos, columnaTabla);

  let cadena: EslabonResumen[];
  try {
    cadena = await obtenerCadena();
  } catch (error) {
    grid.innerHTML = `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
    return;
  }

  function mostrarEslabon(eslabon: EslabonResumen): void {
    columnaPasos.querySelectorAll(".cadena-paso").forEach((el) => el.classList.toggle("activo", el.getAttribute("data-nombre") === eslabon.nombre));
    columnaTabla.innerHTML = "";
    const columnas = ["CODIGO_INTERNO", "PRODUCTO", ...eslabon.campos_acumulados.flatMap((c) => [`${c}_GEMANET`, `${c}_INVIMA`, `${c}_VALIDACION`])];
    new TablaFiltrable(columnaTabla, {
      columnas,
      cargarPagina: (p) => obtenerEslabon(eslabon.nombre, p),
    });
  }

  columnaPasos.innerHTML = cadena
    .map(
      (e) => `<div class="cadena-paso" data-nombre="${e.nombre}">
        <div class="cadena-paso__marca">${e.nombre}</div>
        <div class="cadena-paso__cuerpo">
          <div class="cadena-paso__titulo">${e.campos_acumulados.length ? "+ " + e.campos_acumulados[e.campos_acumulados.length - 1] : "Correspondencia con INVIMA"}</div>
          <div class="cadena-paso__campos">Universo evaluado: ${e.universo.toLocaleString("es-CO")}</div>
        </div>
        <div class="cadena-paso__pct">${e.porcentaje_total === null ? "—" : e.porcentaje_total.toFixed(1) + "%"}</div>
      </div>`,
    )
    .join("");
  columnaPasos.querySelectorAll(".cadena-paso").forEach((el) => {
    el.addEventListener("click", () => {
      const eslabon = cadena.find((e) => e.nombre === el.getAttribute("data-nombre"));
      if (eslabon) mostrarEslabon(eslabon);
    });
  });
  if (cadena.length) mostrarEslabon(cadena[0]);
}
