import {
  obtenerAuditoria,
  obtenerCadena,
  obtenerCalidad,
  obtenerCalidades,
  obtenerEslabon,
  obtenerNaturalezaHallazgos,
  obtenerResumenAuditoria,
  obtenerSeccionesCalidad,
  obtenerValoresColumna,
  urlDescargaCalidad,
  urlDescargaEslabon,
} from "../api";
import { cabeceraConDescarga } from "../descargas";
import {
  AYUDA_PRIORIDAD,
  ESTADOS_COHERENCIA,
  ETIQUETAS_COLUMNA_COMUNES,
  ETIQUETAS_TRIO_CAMPOS_COMPARADOS,
  ETIQUETA_CAMPO_COMPARADO,
  PRIORIDADES,
  etiquetaCamposConDiferencia,
  etiquetaEstadoCoherencia,
  etiquetaPrioridad,
  etiquetaResponsable,
  pildoraEstadoCadena,
  pildoraEstadoCoherencia,
  pildoraEstadoInvimaUnificado,
  pildoraEstadoListadoInvima,
  pildoraNovedadVigencia,
  pildoraPrioridad,
  pildoraValidacion,
} from "../pildoras";
import { SelectorMultiple } from "../selector-multiple";
import { renderTarjetas } from "../tarjetas";
import { TablaFiltrable } from "../tabla";
import type { CalidadResumen, EslabonResumen, SeccionCalidad } from "../tipos";

// ACTIVO (Gemma Net) al lado de ESTADO_LISTADO_INVIMA -- comparar los dos
// estados de un vistazo, pedido del usuario: mostrar el estado local junto
// al de INVIMA en la misma fila, no en pantallas separadas.
const ETIQUETAS_ACTIVO_VS_INVIMA: Record<string, string> = {
  // Lo comun a todas las tablas (codigo, descripcion, campos comparados...)
  // y encima lo propio de auditoria.
  ...ETIQUETAS_COLUMNA_COMUNES,
  ACTIVO: "Activo Gemma Net",
  PRIORIDAD_ACCION: "Prioridad",
  // ESTADO_CUM_INVIMA es la vigencia REAL que declara INVIMA; el listado solo
  // dice en cual de los 4 archivos aparece el registro. Rotularlos distinto
  // evita leer la ubicacion como si fuera el veredicto.
  ESTADO_CUM_INVIMA: "Estado CUM INVIMA",
  // Una sola columna en vez de "Estado Registro INVIMA" + "INVIMA Listado",
  // que salian contiguas repitiendo la misma palabra ("Vencido" | "Vencido")
  // en el 91 % de las filas. La compone el backend en calidades.py, para que
  // el filtro y el Excel de descarga vean lo mismo que la pantalla.
  ESTADO_INVIMA: "Estado en INVIMA",
  ESTADO_INVIMA_DETALLE: "Estado del registro (INVIMA)",
  ESTADO_LISTADO_INVIMA: "Listado de INVIMA",
  RESPONSABLE_DISCREPANCIA: "Responsable",
  // Las 4 fechas de la calidad "Fechas con problema" van contiguas y
  // rotuladas por fuente -- sin esto la cabecera decia FECHA_ACTIVO_IN... y
  // no se distinguia cual columna era de que lado.
  FECHA_INICIO: "Fecha inicio (Gemma Net)",
  FECHA_FIN: "Fecha fin (Gemma Net)",
  FECHA_ACTIVO_INVIMA: "Fecha activo (INVIMA)",
  FECHA_INACTIVO_INVIMA: "Fecha inactivo (INVIMA)",
  COHERENCIA_FECHAS_INVIMA: "Diferencia contra INVIMA",
  INCONSISTENCIA_FECHAS_ACTIVO: "Se contradice a sí mismo",
};

const FORMATEADOR_ESTADO = (columna: string, valor: unknown) => {
  if (columna === "ESTADO_COHERENCIA") return pildoraEstadoCoherencia(valor);
  if (columna === "ESTADO_LISTADO_INVIMA") return pildoraEstadoListadoInvima(valor);
  if (columna === "ESTADO_INVIMA") return pildoraEstadoInvimaUnificado(valor);
  if (columna === "PRIORIDAD_ACCION") return pildoraPrioridad(valor);
  if (columna === "CAMPOS_CON_DIFERENCIA" && valor) return esc(etiquetaCamposConDiferencia(valor));
  return null;
};

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
function formatearCeldaCalidad(columna: string, valor: unknown, fila: Record<string, unknown>): string | null {
  if (valor === null || valor === undefined || valor === "") return null;
  if (columna === "ESTADO_COHERENCIA") return pildoraEstadoCoherencia(valor);
  if (columna === "ESTADO_LISTADO_INVIMA") return pildoraEstadoListadoInvima(valor);
  if (columna === "NOVEDAD_VIGENCIA_INVIMA") return pildoraNovedadVigencia(valor);
  if (columna.endsWith("_VALIDACION")) return pildoraValidacion(valor);
  // Nombres de columna y siglas, traducidos solo para leer: el crudo sigue en
  // el filtro de la columna y en el Excel.
  if (columna === "CAMPOS_CON_DIFERENCIA") return esc(etiquetaCamposConDiferencia(valor));
  if (columna === "RESPONSABLE_DISCREPANCIA") return esc(etiquetaResponsable(valor));
  if (columna === "CONSULTA_VERIFICACION_SQL") {
    const texto = String(valor);
    return `<span class="celda-sql"><button type="button" class="btn-copiar-sql" data-sql="${encodeURIComponent(texto)}" title="Copiar la consulta">📋</button><code>${esc(texto)}</code></span>`;
  }
  // Boton, no texto plano -- pedido del usuario: "quiero que esta columna
  // funcione para que me lleve directamente a consultar en el invima el
  // medicamento especifico". Lleva a "Consultar INVIMA" con el codigo de
  // ESA fila precargado y la busqueda ya ejecutada -- el click lo atrapa
  // TablaFiltrable mismo (delegado en su raiz, ver tabla.ts), no hace falta
  // un handler propio aca: misma clase que el boton generico de
  // CODIGO_INTERNO, mismo evento "gemma:consultar-invima".
  if (columna === "DETALLE_DIFERENCIAS") {
    const codigo = String(fila["CODIGO_INTERNO"] ?? "").trim();
    if (!codigo) return esc(String(valor));
    return `<button type="button" class="btn-ver-diferencias" data-codigo="${esc(codigo)}">${esc(String(valor))} →</button>`;
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

function selectorPrioridad(): SelectorMultiple {
  return new SelectorMultiple(
    PRIORIDADES.map((p) => ({ valor: p, etiqueta: etiquetaPrioridad(p) })),
    "Todos los niveles",
  );
}

export async function montarAuditPriorizar(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = `<p class="vista__intro">Priorizá una acción: cada medicamento activo lleva un nivel de riesgo, del 1 (crítico) al 5 (informativo). Los niveles suman el total de la tabla.</p>`;
  const tarjetas = document.createElement("div");
  contenedor.appendChild(tarjetas);
  try {
    const resumen = await obtenerResumenAuditoria();
    renderTarjetas(
      tarjetas,
      PRIORIDADES.map((p) => ({ clave: p, etiqueta: etiquetaPrioridad(p), ayuda: AYUDA_PRIORIDAD[p] })),
      resumen,
    );
  } catch (error) {
    tarjetas.innerHTML = `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
  }

  const select = selectorPrioridad();
  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  // Seis columnas, no las 92 del snapshot -- pedido del usuario (2026-09-07):
  // "tanta cantidad de informacion por tantos medicamentos te muestra tanto
  // que no ves nada". PRIORIDAD_ACCION reemplaza a ESTADO_COHERENCIA: dice lo
  // mismo pero ordenado por urgencia, y ESTADO_CUM_INVIMA + ESTADO_LISTADO
  // dejan ver de donde sale el nivel (el veredicto y donde se encontro).
  const COLUMNAS_PRIORIZAR = [
    "CODIGO_INTERNO",
    "DESCRIPCION",
    "PRIORIDAD_ACCION",
    "ACTIVO",
    "ESTADO_CUM_INVIMA",
    "ESTADO_LISTADO_INVIMA",
  ];
  new TablaFiltrable(seccionTabla, {
    columnas: COLUMNAS_PRIORIZAR,
    controlesExtra: select.elemento,
    formatearCelda: FORMATEADOR_ESTADO,
    etiquetasColumna: ETIQUETAS_ACTIVO_VS_INVIMA,
    // `columnas` recorta lo que VIAJA: sin el, cada pagina traia las 93
    // columnas del snapshot (2,97 MB) para pintar estas seis.
    cargarPagina: (p) =>
      obtenerAuditoria({
        ...p,
        prioridad: select.valores().join(",") || undefined,
        columnas: COLUMNAS_PRIORIZAR.join(","),
      }),
    obtenerValoresColumna: (columna) => obtenerValoresColumna("/auditoria/valores", columna),
  });
}

// Una seccion = un TIPO de diferencia dentro de la calidad abierta.
//
// Reemplaza a las 6 tarjetas de dimensiones que vivian en esta columna --
// decision del usuario (2026-09-02): "esa informacion [...] no me lo exigen
// aun, mejor dicho no vamos a mostrar eso, mas bien vamos a aprovechar ese
// espacio para hacer algo mejor". El backend las sigue calculando y sirviendo
// (GET /auditoria/dimensiones, con sus pruebas): volver a mostrarlas es un
// cambio de esta vista, no hay que rehacer nada del lado del dato.
//
// El problema que resuelve: la tarjeta "Diferencia de estado o campos" trae
// 59.005 filas de las que 57.255 son un unico problema (FECHA_FIN). En una
// sola tabla, los seis problemas chicos de abajo son invisibles.
function chipSeccion(seccion: SeccionCalidad, activa: boolean): string {
  // Un chip por tipo de diferencia (mismo .chips del dashboard de Auditoría).
  // "suele ser efecto de X" va al tooltip junto con qué se compara: la
  // descripción guardada SÍ está mal (es un hecho), pero corregir el
  // principio activo arregla las dos de una vez.
  const derivado = seccion.derivado_de.length ? ` Suele ser efecto de ${seccion.derivado_de.join(" / ")}.` : "";
  const ayuda = `${seccion.explica || "Ver solo estos medicamentos"}${derivado}`;
  return `<button type="button" class="chip${activa ? " activo" : ""}" data-seccion="${esc(seccion.clave)}" title="${esc(ayuda)}">${esc(seccion.etiqueta)}<span class="chip__num">${seccion.medicamentos.toLocaleString("es-CO")}</span></button>`;
}

// Riesgo con el que se pinta cada calidad en la bandeja (borde superior de la
// tarjeta, como la severidad en el dashboard de Auditoría). Por NOMBRE porque
// la severidad no viaja en la API: es una lectura de negocio fija.
const RIESGO_POR_CALIDAD: Record<string, { sev: "ALTA" | "MEDIA" | "BAJA"; rotulo: string }> = {
  "Vigencia confirmada": { sev: "BAJA", rotulo: "Sin riesgo" },
  "Registro vencido en INVIMA": { sev: "ALTA", rotulo: "Riesgo alto" },
  "En trámite de renovación": { sev: "BAJA", rotulo: "Seguimiento" },
  "En otro estado en INVIMA": { sev: "MEDIA", rotulo: "Revisar" },
  "No existe en INVIMA": { sev: "ALTA", rotulo: "Riesgo alto" },
  Estado: { sev: "ALTA", rotulo: "Riesgo alto" },
  "Diferencia de estado o campos": { sev: "MEDIA", rotulo: "Actualizar datos" },
};

// La calidad con la que debe abrirse "Casos por calidad" la próxima vez
// (una tarjeta de la bandeja la elige). Variable de módulo, mismo patrón que
// precargarConsultaInvima en consulta_detalle.ts.
let _calidadPendiente: string | null = null;

export function abrirCalidad(nombre: string): void {
  _calidadPendiente = nombre;
  window.dispatchEvent(new CustomEvent("gemma:navegar", { detail: { seccion: "auditoria", sub: "entender" } }));
}

/** Portada: una tarjeta por calidad con su cifra, como la bandeja del
 * dashboard de Auditoría de Calidades. Cada cifra se abre a sus casos. */
export async function montarBandeja(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = `<p class="vista__intro">Cada tarjeta es una calidad: qué medicamentos cumplen o incumplen una condición frente a INVIMA. Abrí la cifra para ver los casos uno a uno, con lo que dice Gemma Net, lo que dice INVIMA y qué hacer.</p>`;
  const cuerpo = document.createElement("div");
  contenedor.appendChild(cuerpo);
  let calidades: CalidadResumen[];
  let resumen: Record<string, number> = {};
  try {
    [calidades, resumen] = await Promise.all([obtenerCalidades(), obtenerResumenAuditoria().catch(() => ({}))]);
  } catch (error) {
    cuerpo.innerHTML = `<p class="aviso aviso--error">${esc(error instanceof Error ? error.message : String(error))}</p>`;
    return;
  }
  const tarjetas = calidades
    .map((c) => {
      const riesgo = RIESGO_POR_CALIDAD[c.nombre] ?? { sev: "BAJA", rotulo: "" };
      return `<div class="tarjeta sev-${riesgo.sev}">
        <span class="id">Calidad <span class="badge sev-${riesgo.sev}">${esc(riesgo.rotulo)}</span></span>
        <h3><button type="button" data-calidad="${esc(c.nombre)}">${esc(c.nombre)}</button></h3>
        <p class="explica">${esc(c.explica)}</p>
        <div class="cifras">
          <button type="button" class="cifra ${riesgo.sev === "ALTA" ? "riesgo" : riesgo.sev === "MEDIA" ? "pendientes" : "corregidos"}" data-calidad="${esc(c.nombre)}" title="Ver los medicamentos de esta calidad"><b>${c.medicamentos.toLocaleString("es-CO")}</b><span>Medicamentos</span></button>
          <div class="cifra"><b>${c.porcentaje_del_catalogo.toFixed(1)}%</b><span>del catálogo auditado</span></div>
        </div>
      </div>`;
    })
    .join("");
  const niveles = PRIORIDADES.filter((p) => (resumen[p] ?? 0) > 0)
    .map(
      (p) => `<button type="button" class="cifra ${p === "1_critico" || p === "2_alto" ? "riesgo" : p === "3_medio" ? "pendientes" : ""}" data-prioridad="${esc(p)}" title="${esc(AYUDA_PRIORIDAD[p])}"><b>${(resumen[p] ?? 0).toLocaleString("es-CO")}</b><span>${esc(etiquetaPrioridad(p))}</span></button>`,
    )
    .join("");
  cuerpo.innerHTML = `<h2 class="proceso">Calidades del catálogo</h2><div class="tarjetas">${tarjetas}</div>` +
    (niveles ? `<h2 class="proceso">Priorizar por riesgo</h2><div class="tarjeta sev-ALTA"><span class="id">Cada medicamento activo lleva un nivel, del 1 (crítico) al 5 (informativo). Los niveles suman el total.</span><div class="cifras">${niveles}</div></div>` : "");
  cuerpo.addEventListener("click", (evento) => {
    const objetivo = evento.target as HTMLElement;
    const calidad = objetivo.closest<HTMLElement>("[data-calidad]")?.dataset.calidad;
    if (calidad) {
      abrirCalidad(calidad);
      return;
    }
    if (objetivo.closest<HTMLElement>("[data-prioridad]")) {
      window.dispatchEvent(new CustomEvent("gemma:navegar", { detail: { seccion: "auditoria", sub: "priorizar" } }));
    }
  });
}

export async function montarAuditEntender(contenedor: HTMLElement): Promise<void> {
  // Flujo vertical, como la página de una calidad en el dashboard de
  // Auditoría: (1) elegir la calidad (chips), (2) "qué detecta" (caja azul),
  // (3) tipo de diferencia (chips), (4) la tabla de casos. Antes las
  // calidades eran tarjetas grandes y las secciones una columna lateral:
  // había que mirar en tres sitios para saber qué se estaba viendo.
  contenedor.innerHTML = "";

  const filaCalidades = document.createElement("div");
  filaCalidades.className = "chips";
  contenedor.appendChild(filaCalidades);

  const cabeceraCalidad = document.createElement("div");
  contenedor.appendChild(cabeceraCalidad);

  const secciones = document.createElement("div");
  secciones.className = "chips oculto";
  contenedor.appendChild(secciones);

  const columnaTabla = document.createElement("div");
  contenedor.appendChild(columnaTabla);
  habilitarCopiarSQL(columnaTabla);

  let calidades: CalidadResumen[];
  try {
    calidades = await obtenerCalidades();
  } catch (error) {
    columnaTabla.innerHTML = `<p class="aviso aviso--error">${esc(error instanceof Error ? error.message : String(error))}</p>`;
    return;
  }

  // Que se esta viendo AHORA. La seccion es un corte DENTRO de la calidad, no
  // algo paralelo: cambiar de calidad la resetea.
  let calidadActual: CalidadResumen | null = null;
  let seccionActual: string | null = null;
  let seccionesDeCalidad: SeccionCalidad[] = [];

  // "Que detecta": la frase corta, los criterios y que hacer -- todo viene
  // del backend (CalidadResumen.criterios / que_hacer), la vista no inventa
  // reglas. La seccion abierta agrega su linea de "que se compara".
  function panelCriterios(calidad: CalidadResumen, seccion: SeccionCalidad | null): string {
    const criterios = calidad.criterios.map((c) => `<li>${esc(c)}</li>`).join("");
    const bloqueSeccion = seccion
      ? `<div class="criterios__seccion"><strong>Viendo solo ${esc(seccion.etiqueta)}</strong> — ${seccion.medicamentos.toLocaleString("es-CO")} de ${calidad.medicamentos.toLocaleString("es-CO")}.${seccion.explica ? ` ${esc(seccion.explica)}` : ""}</div>`
      : "";
    const riesgo = RIESGO_POR_CALIDAD[calidad.nombre];
    return `<div class="caso-cabecera"><h1>${esc(calidad.nombre)}</h1>${riesgo ? `<span class="badge sev-${riesgo.sev}">${esc(riesgo.rotulo)}</span>` : ""}<span class="badge pildora--neutro">${calidad.medicamentos.toLocaleString("es-CO")} medicamentos · ${calidad.porcentaje_del_catalogo.toFixed(1)}%</span></div>
    <div class="criterios">
      <div class="criterios__titulo">Qué detecta esta calidad</div>
      <p class="criterios__explica">${esc(calidad.explica)}</p>
      <div class="criterios__cuerpo">
        <div>
          <div class="criterios__titulo">Entra aquí un medicamento cuando</div>
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

  function dibujarTabla(calidad: CalidadResumen, seccion: SeccionCalidad | null): void {
    cabeceraCalidad.innerHTML = panelCriterios(calidad, seccion);
    columnaTabla.innerHTML = "";
    if (calidad.medicamentos === 0) {
      columnaTabla.innerHTML = `<div class="panel"><p class="vista__intro" style="margin:0">Ningún medicamento cae en esta calidad en la corrida actual. ✔</p></div>`;
      return;
    }
    const tablaEl = document.createElement("div");
    columnaTabla.appendChild(tablaEl);
    const clave = seccion?.clave;
    new TablaFiltrable(tablaEl, {
      columnas: calidad.columnas,
      // La identidad incluye la calidad, no solo "calidad": son 7 tablas
      // distintas y compartir id les haria compartir cache y posicion.
      idTabla: `calidad:${calidad.nombre}`,
      seccion: clave,
      formatearCelda: formatearCeldaCalidad,
      // Los trios <CAMPO>_GEMANET/_INVIMA/_VALIDACION se rotulan en lenguaje
      // de negocio (ver ETIQUETAS_TRIO_CAMPOS_COMPARADOS).
      etiquetasColumna: { ...ETIQUETAS_ACTIVO_VS_INVIMA, ...ETIQUETAS_TRIO_CAMPOS_COMPARADOS },
      cargarPagina: (p) => obtenerCalidad(calidad.nombre, { ...p, seccion: clave }),
      urlDescarga: (formato) => urlDescargaCalidad(calidad.nombre, formato, clave),
      obtenerValoresColumna: (columna) =>
        obtenerValoresColumna(`/auditoria/calidades/${encodeURIComponent(calidad.nombre)}/valores`, columna, clave),
    });
  }

  function dibujarSecciones(lista: SeccionCalidad[]): void {
    // Sin secciones se ESCONDE la fila: solo la calidad de diferencias se
    // secciona, y un rotulo fijo en las otras seis seria ruido.
    secciones.classList.toggle("oculto", lista.length === 0);
    if (lista.length === 0) {
      secciones.innerHTML = "";
      return;
    }
    secciones.innerHTML =
      `<span class="chips__rotulo" title="Un medicamento puede caer en varios tipos, así que los números no suman el total de la calidad.">Tipo de diferencia:</span>` +
      `<button type="button" class="chip${seccionActual === null ? " activo" : ""}" data-seccion="">Todos</button>` +
      lista.map((s) => chipSeccion(s, s.clave === seccionActual)).join("");
  }

  async function mostrarCalidad(calidad: CalidadResumen): Promise<void> {
    calidadActual = calidad;
    seccionActual = null;
    filaCalidades.querySelectorAll(".chip").forEach((el) => el.classList.toggle("activo", el.getAttribute("data-nombre") === calidad.nombre));
    dibujarTabla(calidad, null);
    secciones.classList.add("oculto");
    secciones.innerHTML = "";
    try {
      seccionesDeCalidad = await obtenerSeccionesCalidad(calidad.nombre);
      // Otra calidad gano la carrera mientras esta pedia sus secciones.
      if (calidadActual !== calidad) return;
      dibujarSecciones(seccionesDeCalidad);
    } catch (error) {
      secciones.classList.remove("oculto");
      secciones.innerHTML = `<p class="aviso aviso--error">${esc(error instanceof Error ? error.message : String(error))}</p>`;
    }
  }

  // Delegado: el innerHTML se rehace en cada calidad.
  secciones.addEventListener("click", (evento) => {
    const chip = (evento.target as HTMLElement).closest<HTMLElement>("[data-seccion]");
    if (!chip || !calidadActual) return;
    const clave = chip.dataset.seccion ?? "";
    seccionActual = clave === "" || clave === seccionActual ? null : clave;
    dibujarSecciones(seccionesDeCalidad);
    dibujarTabla(calidadActual, seccionesDeCalidad.find((s) => s.clave === seccionActual) ?? null);
  });

  filaCalidades.innerHTML =
    `<span class="chips__rotulo">Calidad:</span>` +
    calidades
      .map((c) => `<button type="button" class="chip" data-nombre="${esc(c.nombre)}" title="${esc(c.explica)}">${esc(c.nombre)}<span class="chip__num">${c.medicamentos.toLocaleString("es-CO")}</span></button>`)
      .join("");
  filaCalidades.querySelectorAll(".chip").forEach((el) => {
    el.addEventListener("click", () => {
      const calidad = calidades.find((c) => c.nombre === el.getAttribute("data-nombre"));
      if (calidad) void mostrarCalidad(calidad);
    });
  });
  // La tarjeta de la bandeja que trajo hasta aqui elige la calidad inicial;
  // si no, la primera.
  const inicial = calidades.find((c) => c.nombre === _calidadPendiente) ?? calidades[0];
  _calidadPendiente = null;
  if (inicial) void mostrarCalidad(inicial);
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
    columnas: ["CODIGO_INTERNO", "DESCRIPCION", "ESTADO_COHERENCIA", "ACTIVO", "ESTADO_LISTADO_INVIMA", "CAMPOS_CON_DIFERENCIA", "PORCENTAJE_CALIDAD"],
    controlesExtra: select.elemento,
    formatearCelda: FORMATEADOR_ESTADO,
    etiquetasColumna: ETIQUETAS_ACTIVO_VS_INVIMA,
    cargarPagina: (p) => obtenerAuditoria({ ...p, estado_coherencia: select.valores().join(",") || undefined }),
    obtenerValoresColumna: (columna) => obtenerValoresColumna("/auditoria/valores", columna),
  });
}

export async function montarCadenaCalidad(contenedor: HTMLElement): Promise<void> {
  // Sin notas internas ("pedido de X", "pendiente de confirmar con negocio")
  // ni jerga ("eslabon", "universo"): esto lo lee el auditor, no el equipo
  // (pedido del usuario, 2026-09-14). El campo que agrega cada tabla va en su
  // tarjeta, asi que la intro no lo repite.
  contenedor.innerHTML =
    `<p class="vista__intro">Cada tabla revisa un campo más que la anterior (el campo está en el título ` +
    `de cada tarjeta) y solo sobre los medicamentos que ya pasaron todas las anteriores. Por eso, si un ` +
    `campo coincide poco, las tablas siguientes se quedan con pocos medicamentos o ninguno. ` +
    `No hay tabla H5: ese campo (laboratorio) todavía no está definido.</p>`;

  // Mismo patron que la vista de calidades: lo que se ELIGE (los eslabones
  // H1..H6) va arriba en fila, y la tabla del eslabon activo se queda con
  // todo el ancho -- que es la que tiene muchas columnas. Normalizado a
  // proposito entre las dos vistas (pedido del usuario, 2026-09-01).
  const filaPasos = document.createElement("div");
  filaPasos.className = "selector-fila";
  contenedor.appendChild(filaPasos);

  const columnaTabla = document.createElement("div");
  contenedor.appendChild(columnaTabla);

  let cadena: EslabonResumen[];
  try {
    cadena = await obtenerCadena();
  } catch (error) {
    columnaTabla.innerHTML = `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
    return;
  }

  function mostrarEslabon(eslabon: EslabonResumen): void {
    filaPasos.querySelectorAll(".cadena-paso").forEach((el) => el.classList.toggle("activo", el.getAttribute("data-nombre") === eslabon.nombre));
    columnaTabla.innerHTML = "";
    // La cadena es acumulativa: un eslabon solo evalua las filas que pasaron
    // TODOS los anteriores. Si un campo intermedio coincide poco (hoy
    // CONCENTRACION, por el cruce homonimo), su universo cae casi a cero y
    // los siguientes se quedan sin filas que evaluar -- eso es correcto, no
    // un dato faltante, pero sin decirlo la tabla vacia se lee como "roto".
    if (eslabon.universo === 0) {
      columnaTabla.innerHTML =
        `<div class="aviso aviso--info">` +
        `<strong>Ningún medicamento llega a la tabla ${esc(eslabon.nombre)}.</strong> ` +
        `Todos se quedaron en una tabla anterior. Mire el porcentaje de la tabla previa ` +
        `para ver dónde se cortan.` +
        `</div>`;
      return;
    }
    // Columnas REALES que trae esa tabla (ver EslabonResumen.columnas_trio
    // en el backend) -- no se re-derivan a mano a partir de
    // campos_acumulados: para H1 esa lista viene vacia (no agrega un campo
    // del trio, valida la correspondencia misma) y dejaba a H1 sin
    // ESTADO_COHERENCIA ni NOVEDAD_VIGENCIA_INVIMA/DETALLE_VIGENCIA_INVIMA
    // -- justo la vigencia que se necesita ver (bug real reportado por el
    // usuario, 2026-08-27).
    // Desde H2 el trio ya trae DESCRIPCION_GEMANET (mismo texto que
    // DESCRIPCION): pedir tambien la DESCRIPCION plana sacaba dos columnas
    // identicas contiguas. El backend deja de mandarla, aca tampoco se pide.
    const identificadoras = eslabon.columnas_trio.includes("DESCRIPCION_GEMANET")
      ? ["CODIGO_INTERNO"]
      : ["CODIGO_INTERNO", "DESCRIPCION"];
    const columnas = [...identificadoras, ...eslabon.columnas_trio, eslabon.columna_estado];
    new TablaFiltrable(columnaTabla, {
      columnas,
      // Mismos rotulos del trio que en las calidades: un campo no puede
      // llamarse distinto segun la pantalla.
      etiquetasColumna: {
        ...ETIQUETAS_ACTIVO_VS_INVIMA,
        ...ETIQUETAS_TRIO_CAMPOS_COMPARADOS,
        // ESTADO_CADENA_H3 es el resultado ACUMULADO: pasa esta tabla y todas
        // las anteriores (ver pildoraEstadoCadena).
        [eslabon.columna_estado]: `Pasa hasta ${eslabon.nombre}`,
      },
      urlDescarga: (formato) => urlDescargaEslabon(eslabon.nombre, formato),
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

  // "+ PRINCIPIO_ACTIVO" era el nombre crudo de la columna; el rotulo de
  // negocio es el mismo que usan las calidades y la consulta puntual.
  const etiquetaCampo = (campo: string) => ETIQUETA_CAMPO_COMPARADO[campo] ?? campo;
  filaPasos.innerHTML = cadena
    .map(
      (e) => `<div class="cadena-paso" data-nombre="${e.nombre}">
        <div class="cadena-paso__marca">${e.nombre}</div>
        <div class="cadena-paso__cuerpo">
          <div class="cadena-paso__titulo">${e.campos_acumulados.length ? "+ " + esc(etiquetaCampo(e.campos_acumulados[e.campos_acumulados.length - 1])) : "Existe en INVIMA"}</div>
          <div class="cadena-paso__campos">Medicamentos evaluados: ${e.universo.toLocaleString("es-CO")}</div>
        </div>
        <div class="cadena-paso__pct" title="Porcentaje de los evaluados que pasa esta tabla">${e.porcentaje_total === null ? "—" : e.porcentaje_total.toFixed(1) + "%"}</div>
      </div>`,
    )
    .join("");
  filaPasos.querySelectorAll(".cadena-paso").forEach((el) => {
    el.addEventListener("click", () => {
      const eslabon = cadena.find((e) => e.nombre === el.getAttribute("data-nombre"));
      if (eslabon) mostrarEslabon(eslabon);
    });
  });
  if (cadena.length) mostrarEslabon(cadena[0]);
}
