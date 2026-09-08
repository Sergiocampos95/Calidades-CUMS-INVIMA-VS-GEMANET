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
} from "../api";
import { cabeceraConDescarga } from "../descargas";
import {
  AYUDA_PRIORIDAD,
  ESTADOS_COHERENCIA,
  PRIORIDADES,
  etiquetaEstadoCoherencia,
  etiquetaPrioridad,
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
const ETIQUETAS_ACTIVO_VS_INVIMA = {
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
  ESTADO_INVIMA_DETALLE: "Estado Registro INVIMA",
  ESTADO_LISTADO_INVIMA: "INVIMA Listado",
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
function tarjetaSeccion(seccion: SeccionCalidad, activa: boolean): string {
  // "Efecto de X" y no un conteo descontado: la descripcion guardada SI esta
  // mal (es un hecho), pero corregir el principio activo arregla las dos de
  // una vez. Sin esta marca, Descripcion parece el problema mas grande
  // cuando en buena parte es la consecuencia de otro.
  const derivado = seccion.derivado_de.length
    ? `<div class="tarjeta-metrica__veredicto">↳ suele ser efecto de ${esc(seccion.derivado_de.join(" / "))}</div>`
    : "";
  return `<button type="button" class="tarjeta-metrica tarjeta-metrica--abrible${activa ? " activo" : ""}" data-seccion="${esc(seccion.clave)}" title="Ver solo estos medicamentos">
    <div class="tarjeta-metrica__encabezado"><span>${esc(seccion.etiqueta)}</span></div>
    <div class="tarjeta-metrica__numero">${seccion.medicamentos.toLocaleString("es-CO")}</div>
    ${derivado}
  </button>`;
}

export async function montarAuditEntender(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = `<p class="vista__intro">Elegí una calidad arriba para ver los medicamentos que la componen. Si esa calidad mezcla varios tipos de diferencia, la columna de la izquierda los separa — cada cifra se puede <strong>abrir</strong>, no solo mirar.</p>`;

  // Layout (pedido del usuario, 2026-09-01): las calidades -- que son lo que
  // se ELIGE -- van arriba en fila organizada. Antes era al reves: lo
  // clickeable vivia apretado en una columna angosta y las cifras que nadie
  // abre se llevaban todo el ancho superior.
  // La columna lateral la ocupaban las 6 dimensiones de solo lectura; desde
  // 2026-09-02 la ocupan las secciones de la calidad abierta (ver
  // `tarjetaSeccion`), que si son clickeables y acotan la tabla.
  const filaCalidades = document.createElement("div");
  filaCalidades.className = "selector-fila";
  contenedor.appendChild(filaCalidades);

  const grid = document.createElement("div");
  grid.className = "grid-lateral";
  contenedor.appendChild(grid);

  const secciones = document.createElement("div");
  secciones.className = "grid-lateral__aside";
  const columnaTabla = document.createElement("div");
  columnaTabla.className = "grid-lateral__principal";
  grid.append(secciones, columnaTabla);
  habilitarCopiarSQL(columnaTabla);

  let calidades: CalidadResumen[];
  try {
    calidades = await obtenerCalidades();
  } catch (error) {
    grid.innerHTML = `<p class="aviso aviso--error">${esc(error instanceof Error ? error.message : String(error))}</p>`;
    return;
  }

  // Que se esta viendo AHORA. La seccion es un corte DENTRO de la calidad, no
  // algo paralelo: cambiar de calidad la resetea, si no se quedaria filtrando
  // por un tipo de diferencia que la calidad nueva puede no tener.
  let calidadActual: CalidadResumen | null = null;
  let seccionActual: string | null = null;
  let seccionesDeCalidad: SeccionCalidad[] = [];

  function dibujarTabla(calidad: CalidadResumen, seccion: SeccionCalidad | null): void {
    columnaTabla.innerHTML = `<p class="vista__intro" style="margin-bottom:10px">${esc(calidad.explica)}</p>`;
    if (calidad.medicamentos === 0) {
      columnaTabla.innerHTML += `<p class="tabla-filtrable__vacio">Ningún medicamento cae en esta calidad en la corrida actual.</p>`;
      return;
    }
    if (seccion) {
      columnaTabla.innerHTML += `<p class="vista__intro" style="margin-bottom:10px">Viendo solo <strong>${esc(seccion.etiqueta)}</strong> — ${seccion.medicamentos.toLocaleString("es-CO")} de ${calidad.medicamentos.toLocaleString("es-CO")}.</p>`;
    }
    const tablaEl = document.createElement("div");
    columnaTabla.appendChild(tablaEl);
    const clave = seccion?.clave;
    new TablaFiltrable(tablaEl, {
      columnas: calidad.columnas,
      // La identidad incluye la calidad, no solo "calidad": son 6 tablas
      // distintas y compartir id les haria compartir cache y posicion.
      idTabla: `calidad:${calidad.nombre}`,
      seccion: clave,
      formatearCelda: formatearCeldaCalidad,
      etiquetasColumna: ETIQUETAS_ACTIVO_VS_INVIMA,
      cargarPagina: (p) => obtenerCalidad(calidad.nombre, { ...p, seccion: clave }),
      // Sin filtros ni pagina: el archivo trae la seccion completa (ver
      // urlDescargaCalidad).
      urlDescarga: (formato) => urlDescargaCalidad(calidad.nombre, formato, clave),
      obtenerValoresColumna: (columna) =>
        obtenerValoresColumna(`/auditoria/calidades/${encodeURIComponent(calidad.nombre)}/valores`, columna, clave),
    });
  }

  function dibujarSecciones(lista: SeccionCalidad[]): void {
    // Sin secciones se ESCONDE la columna y la tabla toma todo el ancho. No
    // se deja un mensaje: solo la calidad de diferencias se secciona, asi que
    // en las otras cinco el aviso apareceria siempre y seria ruido fijo.
    grid.classList.toggle("grid-lateral--sin-aside", lista.length === 0);
    if (lista.length === 0) {
      secciones.innerHTML = "";
      return;
    }
    const total = calidadActual?.medicamentos ?? 0;
    secciones.innerHTML =
      `<p class="vista__intro" style="margin:0 0 8px">Tipos de diferencia. Un medicamento puede caer en varios, así que los números no suman ${total.toLocaleString("es-CO")}.</p>` +
      lista.map((s) => tarjetaSeccion(s, s.clave === seccionActual)).join("");
  }

  async function mostrarCalidad(calidad: CalidadResumen): Promise<void> {
    calidadActual = calidad;
    seccionActual = null;
    filaCalidades.querySelectorAll(".cadena-paso").forEach((el) => el.classList.toggle("activo", el.getAttribute("data-nombre") === calidad.nombre));
    dibujarTabla(calidad, null);
    // Se arranca con la columna escondida y se abre solo si llegan secciones:
    // al reves, las cinco calidades que no se seccionan mostrarian un
    // "Cargando…" que parpadea y desaparece cada vez que se las abre.
    grid.classList.add("grid-lateral--sin-aside");
    secciones.innerHTML = "";
    try {
      seccionesDeCalidad = await obtenerSeccionesCalidad(calidad.nombre);
      // Otra calidad gano la carrera mientras esta pedia sus secciones: se
      // descarta la respuesta vieja en vez de pintar secciones que no
      // corresponden a lo que se esta viendo.
      if (calidadActual !== calidad) return;
      dibujarSecciones(seccionesDeCalidad);
    } catch (error) {
      // Un fallo si se muestra: no poder cargar las secciones no es lo mismo
      // que esta calidad no tenga, y callarlo dejaria la columna vacia como
      // si fuera lo normal.
      grid.classList.remove("grid-lateral--sin-aside");
      secciones.innerHTML = `<p class="aviso aviso--error">${esc(error instanceof Error ? error.message : String(error))}</p>`;
    }
  }

  // Delegado en el contenedor: el innerHTML se rehace en cada calidad y un
  // listener por tarjeta se perderia.
  secciones.addEventListener("click", (evento) => {
    const tarjeta = (evento.target as HTMLElement).closest<HTMLElement>("[data-seccion]");
    if (!tarjeta || !calidadActual) return;
    // Volver a la tabla completa = click en la seccion ya activa. Reemplaza a
    // la tarjeta "Todos" que encabezaba la lista (el usuario la pidio fuera,
    // 2026-09-02): ocupaba un lugar en la columna repitiendo un numero que ya
    // esta arriba, en la tarjeta de la calidad.
    const clave = tarjeta.dataset.seccion ?? "";
    seccionActual = clave === "" || clave === seccionActual ? null : clave;
    dibujarSecciones(seccionesDeCalidad);
    dibujarTabla(calidadActual, seccionesDeCalidad.find((s) => s.clave === seccionActual) ?? null);
  });

  filaCalidades.innerHTML = calidades
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
  filaCalidades.querySelectorAll(".cadena-paso").forEach((el) => {
    el.addEventListener("click", () => {
      const calidad = calidades.find((c) => c.nombre === el.getAttribute("data-nombre"));
      if (calidad) void mostrarCalidad(calidad);
    });
  });
  if (calidades.length) void mostrarCalidad(calidades[0]);
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
  contenedor.innerHTML =
    `<p class="vista__intro">Cada tabla valida un campo más que la anterior, sobre las mismas filas (pedido de Sergio). ` +
    `H5 (laboratorio) está pendiente de confirmar con negocio, no se muestra todavía.</p>`;

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

  filaPasos.innerHTML = cadena
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
  filaPasos.querySelectorAll(".cadena-paso").forEach((el) => {
    el.addEventListener("click", () => {
      const eslabon = cadena.find((e) => e.nombre === el.getAttribute("data-nombre"));
      if (eslabon) mostrarEslabon(eslabon);
    });
  });
  if (cadena.length) mostrarEslabon(cadena[0]);
}
