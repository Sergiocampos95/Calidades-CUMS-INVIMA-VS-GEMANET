import {
  obtenerAuditoria,
  obtenerCadena,
  obtenerCalidad,
  obtenerCalidades,
  obtenerDimensionesCalidad,
  obtenerEslabon,
  obtenerNaturalezaHallazgos,
  obtenerResumenAuditoria,
  obtenerValoresColumna,
} from "../api";
import { cabeceraConDescarga } from "../descargas";
import {
  ESTADOS_COHERENCIA,
  etiquetaEstadoCoherencia,
  pildoraEstadoCadena,
  pildoraEstadoCoherencia,
  pildoraNovedadVigencia,
  pildoraValidacion,
} from "../pildoras";
import { SelectorMultiple } from "../selector-multiple";
import { renderTarjetas } from "../tarjetas";
import { TablaFiltrable } from "../tabla";
import type { CalidadResumen, EslabonResumen } from "../tipos";

const FORMATEADOR_ESTADO = (columna: string, valor: unknown) =>
  columna === "ESTADO_COHERENCIA" ? pildoraEstadoCoherencia(valor) : null;

function esc(valor: unknown): string {
  return String(valor).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}

// CONSULTA_VERIFICACION_SQL + CONSEJO -- pedido explicito del usuario
// (2026-08-28): "campos con diferencia... imprimes la desc de invima la
// desc de gema y el resultado" + "un consejo... con logica segun su caso"
// + "incluir la consulta sql en un campo para corroborar un dato". El
// boton de copiar usa un delegado en el contenedor de la tabla (ver
// montarAuditEntender) porque TablaFiltrable rehace el <tbody> en cada
// busqueda/pagina -- un listener por celda se perderia.
function formatearCeldaCalidad(columna: string, valor: unknown): string | null {
  if (valor === null || valor === undefined || valor === "") return null;
  if (columna === "ESTADO_COHERENCIA") return pildoraEstadoCoherencia(valor);
  if (columna === "NOVEDAD_VIGENCIA_INVIMA") return pildoraNovedadVigencia(valor);
  if (columna.endsWith("_VALIDACION")) return pildoraValidacion(valor);
  if (columna === "CONSULTA_VERIFICACION_SQL") {
    const texto = String(valor);
    return `<span class="celda-sql"><button type="button" class="btn-copiar-sql" data-sql="${encodeURIComponent(texto)}" title="Copiar la consulta">📋</button><code>${esc(texto)}</code></span>`;
  }
  return null;
}

function habilitarCopiarSQL(contenedor: HTMLElement): void {
  contenedor.addEventListener("click", (evento) => {
    const boton = (evento.target as HTMLElement).closest<HTMLButtonElement>(".btn-copiar-sql");
    if (!boton?.dataset.sql) return;
    const sql = decodeURIComponent(boton.dataset.sql);
    navigator.clipboard?.writeText(sql).then(
      () => {
        const original = boton.textContent;
        boton.textContent = "✓";
        setTimeout(() => {
          boton.textContent = original;
        }, 1200);
      },
      () => {
        /* portapapeles no disponible (ej. sin HTTPS) -- la consulta sigue visible para copiar a mano */
      },
    );
  });
}

function selectorEstado(): SelectorMultiple {
  return new SelectorMultiple(
    ESTADOS_COHERENCIA.map((e) => ({ valor: e, etiqueta: etiquetaEstadoCoherencia(e) })),
    "Todos los estados",
  );
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
    columnas: ["CODIGO_INTERNO", "DESCRIPCION", "ESTADO_COHERENCIA"],
    controlesExtra: select.elemento,
    formatearCelda: FORMATEADOR_ESTADO,
    cargarPagina: (p) => obtenerAuditoria({ ...p, estado_coherencia: select.valores().join(",") || undefined }),
    obtenerValoresColumna: (columna) => obtenerValoresColumna("/auditoria/valores", columna),
  });
}

function tarjetaDimension(etiqueta: string, valorTexto: string, ayuda: string): string {
  return `<div class="tarjeta-metrica"><div class="tarjeta-metrica__encabezado"><span>${etiqueta}</span><span class="tarjeta-metrica__ayuda" title="${esc(ayuda)}">?</span></div><div class="tarjeta-metrica__numero">${valorTexto}</div></div>`;
}

export async function montarAuditEntender(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = `<p class="vista__intro">Las 10 dimensiones de calidad de dato de esta auditoría (Exactitud, Vigencia, Consistencia y Correspondencia ya se ven como estado/pildora en las demás vistas). Elegí una fila de la tabla de calidades para ver los medicamentos que la componen — cada cifra se puede <strong>abrir</strong>, no solo mirar.</p>`;

  const dimensiones = document.createElement("div");
  dimensiones.className = "fila-tarjetas";
  contenedor.appendChild(dimensiones);
  try {
    const d = await obtenerDimensionesCalidad();
    dimensiones.innerHTML = [
      tarjetaDimension(
        "Completitud",
        d.completitud_promedio === null ? "—" : `${d.completitud_promedio.toFixed(1)}%`,
        "Promedio de cuántos de los 37 campos del cargue están diligenciados por medicamento.",
      ),
      tarjetaDimension("Unicidad", d.duplicados.toLocaleString("es-CO"), "CODIGO_INTERNO repetido dentro del propio reporte de Gemma Net."),
      tarjetaDimension(
        "Validez de dominio",
        d.fuera_de_dominio.toLocaleString("es-CO"),
        "CLASIFICADO / CODIGO_NIVEL_SERVICIO / POS / ACTIVO con un valor fuera de lo permitido.",
      ),
      tarjetaDimension("Razonabilidad numérica", d.inconsistencia_numerica.toLocaleString("es-CO"), "Edades o topes de uso fuera de orden lógico, o negativos."),
      tarjetaDimension("Conformidad de formato", d.formato_invalido.toLocaleString("es-CO"), "CODIGO_INTERNO vacío o guardado como error de fórmula de Excel."),
      tarjetaDimension(
        "Integridad referencial",
        d.integridad_referencial.toLocaleString("es-CO"),
        "MARCA_MEDICAMENTO / UNIDAD_MEDIDA con un código que NO existe en el catálogo interno.",
      ),
    ].join("");
  } catch (error) {
    dimensiones.innerHTML = `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
  }

  const grid = document.createElement("div");
  grid.className = "grid-2";
  grid.style.marginTop = "18px";
  contenedor.appendChild(grid);
  const columnaLista = document.createElement("div");
  const columnaTabla = document.createElement("div");
  grid.append(columnaLista, columnaTabla);
  habilitarCopiarSQL(columnaTabla);

  let calidades: CalidadResumen[];
  try {
    calidades = await obtenerCalidades();
  } catch (error) {
    grid.innerHTML = `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
    return;
  }

  function mostrarCalidad(calidad: CalidadResumen): void {
    columnaLista.querySelectorAll(".cadena-paso").forEach((el) => el.classList.toggle("activo", el.getAttribute("data-nombre") === calidad.nombre));
    columnaTabla.innerHTML = `<p class="vista__intro" style="margin-bottom:10px">${esc(calidad.explica)}</p>`;
    if (calidad.medicamentos === 0) {
      columnaTabla.innerHTML += `<p class="tabla-filtrable__vacio">Ningún medicamento cae en esta calidad en la corrida actual.</p>`;
      return;
    }
    const tablaEl = document.createElement("div");
    columnaTabla.appendChild(tablaEl);
    new TablaFiltrable(tablaEl, {
      columnas: calidad.columnas,
      formatearCelda: formatearCeldaCalidad,
      cargarPagina: (p) => obtenerCalidad(calidad.nombre, p),
      obtenerValoresColumna: (columna) =>
        obtenerValoresColumna(`/auditoria/calidades/${encodeURIComponent(calidad.nombre)}/valores`, columna),
    });
  }

  columnaLista.innerHTML = calidades
    .map(
      (c) => `<div class="cadena-paso" data-nombre="${esc(c.nombre)}">
        <div class="cadena-paso__marca">${c.porcentaje_del_catalogo.toFixed(0)}%</div>
        <div class="cadena-paso__cuerpo">
          <div class="cadena-paso__titulo">${esc(c.nombre)}</div>
          <div class="cadena-paso__campos">${c.medicamentos.toLocaleString("es-CO")} medicamentos</div>
        </div>
      </div>`,
    )
    .join("");
  columnaLista.querySelectorAll(".cadena-paso").forEach((el) => {
    el.addEventListener("click", () => {
      const calidad = calidades.find((c) => c.nombre === el.getAttribute("data-nombre"));
      if (calidad) mostrarCalidad(calidad);
    });
  });
  if (calidades.length) mostrarCalidad(calidades[0]);
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

  // "Que hacer con cada hallazgo" -- recuperado de Streamlit (el usuario lo
  // recordaba: "un filtro que nos daba recomendaciones de como tratar x
  // datos"). Agrupa por NATURALEZA_HALLAZGO (una etiqueta por medicamento,
  // la de la accion mas urgente que pide) en vez de por ESTADO_COHERENCIA
  // -- no se suma con las tarjetas de arriba, contestan preguntas distintas.
  const naturaleza = document.createElement("div");
  contenedor.appendChild(naturaleza);
  try {
    const hallazgos = await obtenerNaturalezaHallazgos();
    if (hallazgos.length) {
      naturaleza.className = "panel";
      naturaleza.style.marginTop = "18px";
      const filas = hallazgos
        .map(
          (h) =>
            `<tr><td>${esc(h.naturaleza)}</td><td class="celda-mono">${h.medicamentos.toLocaleString("es-CO")}</td><td>${esc(h.que_hacer)}</td></tr>`,
        )
        .join("");
      naturaleza.innerHTML = `<div class="panel__cab"><div class="panel__titulo">Qué hacer con cada hallazgo — acción sugerida por clase</div></div><div class="panel__cuerpo"><div class="tabla-filtrable__envoltorio"><table><thead><tr><th>Clase de hallazgo</th><th>Medicamentos</th><th>Qué hacer</th></tr></thead><tbody>${filas}</tbody></table></div></div>`;
    }
  } catch {
    /* no bloquea el resto de la vista */
  }

  const select = selectorEstado();
  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: ["CODIGO_INTERNO", "DESCRIPCION", "ESTADO_COHERENCIA", "CAMPOS_CON_DIFERENCIA", "PORCENTAJE_CALIDAD"],
    controlesExtra: select.elemento,
    formatearCelda: FORMATEADOR_ESTADO,
    cargarPagina: (p) => obtenerAuditoria({ ...p, estado_coherencia: select.valores().join(",") || undefined }),
    obtenerValoresColumna: (columna) => obtenerValoresColumna("/auditoria/valores", columna),
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
    // Columnas REALES que trae esa tabla (ver EslabonResumen.columnas_trio
    // en el backend) -- no se re-derivan a mano a partir de
    // campos_acumulados: para H1 esa lista viene vacia (no agrega un campo
    // del trio, valida la correspondencia misma) y dejaba a H1 sin
    // ESTADO_COHERENCIA ni NOVEDAD_VIGENCIA_INVIMA/DETALLE_VIGENCIA_INVIMA
    // -- justo la vigencia que se necesita ver (bug real reportado por el
    // usuario, 2026-08-27).
    const columnas = ["CODIGO_INTERNO", "DESCRIPCION", ...eslabon.columnas_trio, eslabon.columna_estado];
    new TablaFiltrable(columnaTabla, {
      columnas,
      formatearCelda: (columna, valor) => {
        if (valor === null || valor === undefined || valor === "") return null; // deja el "—" del default
        if (columna === "ESTADO_COHERENCIA") return pildoraEstadoCoherencia(valor);
        if (columna === "NOVEDAD_VIGENCIA_INVIMA") return pildoraNovedadVigencia(valor);
        if (columna === eslabon.columna_estado) return pildoraEstadoCadena(valor);
        if (columna.endsWith("_VALIDACION")) return pildoraValidacion(valor);
        return null;
      },
      cargarPagina: (p) => obtenerEslabon(eslabon.nombre, p),
      obtenerValoresColumna: (columna) =>
        obtenerValoresColumna(`/auditoria/cadena/${encodeURIComponent(eslabon.nombre)}/valores`, columna),
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
