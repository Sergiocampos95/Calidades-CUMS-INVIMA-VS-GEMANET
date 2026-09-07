import type { ClavePagina } from "./cache_tablas";
import { guardarEstado, guardarPagina, leerEstado, leerPagina, snapshotVigente } from "./cache_tablas";
import type { PaginaTabla } from "./tipos";

/**
 * El equivalente de `_tabla_filtrable`/`_mostrar_tabla_estandar` de la UI de
 * Streamlit: UN solo componente para dibujar cualquier tabla grande, con
 * busqueda libre siempre visible y el recorte de previsualizacion, que ahora
 * se navega por paginas (regla de CLAUDE.md, seccion UI). Ninguna tabla de
 * esta app se dibuja fuera de este componente.
 *
 * Ancho de columna FIJO + texto truncado (con tooltip nativo del valor
 * completo) + arrastrar el borde del encabezado para redimensionar, como en
 * Excel. Antes las columnas crecian al ancho del contenido mas largo (una
 * celda de COMO_VERIFICAR con un parrafo entero estiraba la tabla entera) --
 * eso es lo que reportó el usuario como "los campos se extienden
 * innecesariamente" Y como el scroll lento (~5 fps): con `table-layout:
 * fixed` el navegador no tiene que medir el contenido de cada celda para
 * decidir el ancho de cada columna, que es justo el trabajo caro que se
 * repetia en cada frame de scroll.
 *
 * Filtro por columna estilo Excel (pedido del usuario, 2026-08-28): cada
 * encabezado con `obtenerValoresColumna` en las opciones gana un boton "▾"
 * que abre un popover con ordenar A-Z/Z-A + buscar dentro de los valores +
 * checkbox-list de los valores distintos de esa columna (con conteo). Es
 * opcional (`obtenerValoresColumna` sin definir = sin boton) porque no toda
 * tabla tiene un endpoint /valores detras.
 */

const LIMITE_PREVISUALIZACION = 1000;
const DEMORA_BUSQUEDA_MS = 300;
const ANCHO_COLUMNA_DEFECTO_PX = 150;
const ANCHO_COLUMNA_ANCHA_PX = 280; // columnas de texto largo conocidas -- ver ES_COLUMNA_ANCHA
const ANCHO_COLUMNA_MINIMO_PX = 60;

const ES_COLUMNA_ANCHA = /DESCRIPCION|MOTIVO|COMO_VERIFICAR|DETALLE|CAMPOS_CON|CONSEJO|CONSULTA_VERIFICACION_SQL/i;

export interface ValorColumnaTabla {
  valor: string;
  conteo: number;
}

export type FormatoDescarga = "xlsx" | "csv" | "txt";

/** Etiqueta y titulo de cada boton de descarga. En un solo sitio para que el
 * orden y los textos no se dupliquen por vista. */
const FORMATOS_DESCARGA: { formato: FormatoDescarga; etiqueta: string; titulo: string }[] = [
  { formato: "xlsx", etiqueta: "⤓ Excel", titulo: "Descargar en Excel (.xlsx)" },
  { formato: "csv", etiqueta: "⤓ CSV", titulo: "Descargar en CSV (separado por comas)" },
  { formato: "txt", etiqueta: "⤓ TXT", titulo: "Descargar en texto separado por tabulaciones" },
];

export interface OpcionesTablaFiltrable {
  columnas: string[];
  /** Identidad de esta tabla para la cache de paginas y para recordar donde
   * estaba parado el usuario al volver a la vista (ver cache_tablas.ts). Sin
   * esto la tabla funciona igual pero no cachea ni recuerda: es opcional a
   * proposito, para no obligar a cada llamador a inventarse un id antes de
   * que la cache le sirva de algo. Ej: "calidad:Diferencia de estado o
   * campos". */
  idTabla?: string;
  /** Seccion abierta, si la tabla las tiene. Entra en la clave de cache
   * porque cambia QUE filas y QUE columnas devuelve el backend. */
  seccion?: string;
  /** Recibe {q, limite, offset, todo, ordenar_por, orden_descendente,
   * filtros_json} + los filtros extra que agregue el llamador (ej.
   * estado_coherencia) y devuelve la pagina correspondiente. */
  cargarPagina: (parametros: {
    q: string;
    limite: number;
    offset: number;
    todo: boolean;
    ordenar_por?: string;
    orden_descendente?: boolean;
    filtros_json?: string;
  }) => Promise<PaginaTabla>;
  /** URL de descarga para cada formato. Si se define, la tabla dibuja los
   * tres botones (Excel/CSV/TXT). Es el llamador quien la arma porque cada
   * vista tiene su endpoint y su contexto (calidad + seccion). */
  urlDescarga?: (formato: FormatoDescarga) => string;
  /** Controles de filtro adicionales (ej. selector de ESTADO_COHERENCIA),
   * ya montados por el llamador -- este componente solo los ubica arriba
   * de la busqueda y escucha su evento "cambio-filtro" para re-consultar. */
  controlesExtra?: HTMLElement;
  /** Formateador de celda por columna, opcional. Devuelve HTML (para
   * pildoras de estado, texto mono, etc) -- SOLO usarlo para columnas de
   * valores controlados (enums como accion/ESTADO_COHERENCIA), nunca para
   * texto libre: el default (sin esto) escapa todo via textContent. */
  formatearCelda?: (columna: string, valor: unknown, fila: Record<string, unknown>) => string | null;
  /** Si se define, cada encabezado gana un boton de "ordenar y filtrar"
   * estilo Excel -- llama a esto para poblar el checkbox-list de valores
   * distintos de esa columna. Sin esto, la tabla se ve igual que antes
   * (solo busqueda libre + orden ninguno). */
  obtenerValoresColumna?: (columna: string) => Promise<ValorColumnaTabla[]>;
  /** Nombre de columna crudo (ej. ESTADO_LISTADO_INVIMA) -> etiqueta en
   * lenguaje de negocio para el encabezado (ej. "Estado INVIMA"). Sin esto
   * (o sin entrada para una columna puntual) se muestra el nombre crudo,
   * igual que antes -- retrocompatible con las vistas que no lo pasan. El
   * nombre real de columna se conserva en el `title` del encabezado para
   * depurar. */
  etiquetasColumna?: Record<string, string>;
}

function esc(valor: unknown): string {
  return String(valor).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}

// Boton compacto junto a CODIGO_INTERNO que lleva directo a "Consultar
// INVIMA" con ese codigo ya cargado -- pedido explicito del usuario
// (2026-09-01): "añadela en todas las filas en las que pueda tener un
// efecto positivo". Vive ACA, no en cada vista: TablaFiltrable es el UNICO
// componente de tabla de la app (regla del proyecto), asi que cualquier
// tabla que muestre CODIGO_INTERNO lo gana gratis, sin que cada una de las
// 9 vistas que la usan tenga que acordarse de conectarlo por separado. El
// click se captura una vez por instancia (delegado en `this.raiz`, ver
// constructor); quien procesa el codigo y navega es
// vistas/consulta_detalle.ts, escuchando el evento "gemma:consultar-invima"
// -- este modulo no importa esa vista para no crear una dependencia de un
// componente generico hacia una pantalla especifica.
function botonConsultarInvima(codigo: unknown): string {
  const cod = String(codigo ?? "").trim();
  if (!cod) return "";
  return `<button type="button" class="btn-consultar-invima" data-codigo="${esc(cod)}" title="Consultar este código en INVIMA">🔍</button>`;
}

function formatearCeldaDefecto(columna: string, valor: unknown): string {
  // null (JSON de NaN/None) nunca se muestra como "0" ni en blanco sin
  // explicacion -- "—" dice explicitamente "no hay dato", igual que hace
  // la UI de Streamlit con PORCENTAJE_CALIDAD vacio.
  if (valor === null || valor === undefined || valor === "") return `<span class="celda-muda">—</span>`;
  if (typeof valor === "number" && (columna.startsWith("PORCENTAJE") || columna.startsWith("SIMILITUD_"))) {
    return `<span class="celda-mono">${valor.toFixed(1)}%</span>`;
  }
  // Solo CODIGO_INTERNO exacto gana el boton -- columnas como
  // CODIGO_INTERNO_MODELO_SERVICIO tambien terminan en "_INTERNO" pero no
  // son un codigo de medicamento consultable en INVIMA.
  if (columna === "CODIGO_INTERNO") {
    return `<span class="celda-codigo"><span class="celda-mono">${esc(valor)}</span>${botonConsultarInvima(valor)}</span>`;
  }
  if (columna.endsWith("_INTERNO")) {
    return `<span class="celda-mono">${esc(valor)}</span>`;
  }
  return esc(valor);
}

// Un solo listener delegado a nivel de documento -- no uno por popover
// abierto, mismo criterio que selector-multiple.ts. Cierra el popover de
// filtro de columna si esta abierto y el clic fue afuera de el (y no fue
// sobre el boton que lo abre, que ya maneja su propio toggle).
if (typeof document !== "undefined") {
  document.addEventListener("click", (evento) => {
    const objetivo = evento.target as HTMLElement;
    document.querySelectorAll<HTMLElement>(".th-popover").forEach((popover) => {
      if (!popover.contains(objetivo) && !objetivo.closest(".th-filtro-boton")) {
        popover.remove();
      }
    });
  });
}

/** Columnas que la auditoria calcula para PODER verificar un hallazgo a mano,
 * no para leerlas de corrido. Ocupan un ancho enorme (una consulta SQL entera)
 * y empujan a la derecha justo las columnas de estado que el usuario si mira
 * -- pedido explicito del usuario (2026-09-02): "el campo que facilita la
 * consulta de verificacion puede permanecer oculto hasta que se requiera".
 * Se ocultan de la VISTA, nunca del dato: siguen viajando en la respuesta y en
 * las descargas, y la casilla de abajo las revela cuando hacen falta -- nunca
 * se asume en silencio que al usuario no le hacen falta. */
const COLUMNAS_TECNICAS = new Set(["CONSULTA_VERIFICACION_SQL"]);

export class TablaFiltrable {
  private busqueda = "";
  /** Primera fila de la pagina que se esta viendo. Reemplaza al viejo
   * `mostrarTodo`: antes la unica alternativa a "las primeras 1.000" era
   * traerse la tabla ENTERA de un golpe, y eso trababa el equipo -- reporte
   * del usuario (2026-09-04): "si el usuario daba click al lado de la casilla
   * de cargar todos los datos hasta se trababa el computador". Ahora se
   * navega de 1.000 en 1.000 y el que quiere el conjunto completo lo
   * descarga, que es para lo que sirve un reporte. */
  private offset = 0;
  private mostrarTecnicas = false;
  private cargando = false;
  /** La ultima pagina servida, para poder repintar sin volver a pedirla
   * cuando lo unico que cambia es que columnas se muestran. */
  private ultimaPagina?: PaginaTabla;
  private raiz: HTMLElement;
  /** El contenedor de la fila de busqueda se arma UNA vez en el constructor
   * y nunca se destruye -- bug real reportado por el usuario (2026-08-28):
   * "voy a escribir algo y no me deja terminar de escribir". Antes
   * render() reconstruia TODO el HTML de raiz, input de busqueda incluido,
   * en cada tecla (debounce de por medio) -- el navegador creaba un <input>
   * nuevo y el que tenia el foco lo perdia. Ahora solo `contenedorDatos`
   * (leyenda/checkbox/tabla) se reconstruye; la fila de busqueda es
   * DOM estable, el foco y la posicion del cursor nunca se pierden. */
  private contenedorDatos: HTMLElement;
  /** Ancho por columna en pixeles, sobrevive a los re-render (busqueda,
   * cargar todo) mientras esta instancia siga viva -- redimensionar una vez
   * no se pierde con cada tecla que se escribe en el buscador. */
  private anchosColumna = new Map<string, number>();
  /** Orden y filtro por columna estilo Excel -- ver OpcionesTablaFiltrable. */
  private ordenarPor: string | undefined;
  private ordenDescendente = false;
  private filtrosColumna = new Map<string, Set<string>>();
  /** Cache de valores distintos por columna, para no volver a pedirlos
   * cada vez que se reabre el mismo popover dentro de la misma instancia. */
  private cacheValoresColumna = new Map<string, ValorColumnaTabla[]>();

  constructor(
    contenedor: HTMLElement,
    private opciones: OpcionesTablaFiltrable,
  ) {
    this.raiz = document.createElement("div");
    this.raiz.className = "tabla-filtrable";
    contenedor.appendChild(this.raiz);

    // Delegado UNA vez por instancia (this.raiz nunca se destruye, igual
    // que el resto de listeners de esta clase) -- atrapa tanto el boton de
    // CODIGO_INTERNO (formatearCeldaDefecto, arriba) como cualquier boton
    // "Ver diferencias"/similar que una vista arme con la misma clase (ver
    // auditoria.ts -- un solo mecanismo para "andá a consultar este codigo
    // en INVIMA", sin importar de que columna salio el clic).
    this.raiz.addEventListener("click", (evento) => {
      const boton = (evento.target as HTMLElement).closest<HTMLElement>(
        ".btn-consultar-invima, .btn-ver-diferencias",
      );
      if (!boton?.dataset.codigo) return;
      window.dispatchEvent(new CustomEvent("gemma:consultar-invima", { detail: { codigo: boton.dataset.codigo } }));
    });

    const filaBusqueda = document.createElement("div");
    filaBusqueda.className = "tabla-filtrable__busqueda";
    const input = document.createElement("input");
    input.type = "search";
    input.placeholder = "🔎 Buscar (cualquier columna)";
    input.addEventListener("input", (e) => this.onBuscar((e.target as HTMLInputElement).value));
    filaBusqueda.appendChild(input);
    if (this.opciones.controlesExtra) filaBusqueda.appendChild(this.opciones.controlesExtra);
    this.raiz.appendChild(filaBusqueda);

    this.contenedorDatos = document.createElement("div");
    this.raiz.appendChild(this.contenedorDatos);

    this.opciones.controlesExtra?.addEventListener("cambio-filtro", () => this.onCambioDeFiltro());
    this.restaurarEstado();
    this.recargar();
  }

  /** Vuelve a donde estaba el usuario la ultima vez que miro esta tabla.
   * Existe porque cada navegacion destruye esta instancia (`innerHTML = ...`
   * al montar la vista), asi que sin esto volver a una tabla siempre
   * significaba empezar de cero: pagina 1, sin filtros, sin orden. */
  private restaurarEstado(): void {
    if (!this.opciones.idTabla) return;
    const guardado = leerEstado(this.opciones.idTabla);
    // El estado se guarda por tabla, pero la seccion abierta la decide la
    // vista al construirla: si no coincide, ese estado es de otra cosa.
    if (!guardado || guardado.seccion !== this.opciones.seccion) return;
    this.busqueda = guardado.busqueda;
    this.offset = guardado.offset;
    this.ordenarPor = guardado.ordenarPor;
    this.ordenDescendente = guardado.ordenDescendente;
    if (guardado.filtrosJson) {
      try {
        const filtros = JSON.parse(guardado.filtrosJson) as Record<string, string[]>;
        this.filtrosColumna = new Map(Object.entries(filtros).map(([c, v]) => [c, new Set(v)]));
      } catch {
        // Un estado corrupto no puede impedir abrir la tabla: se empieza
        // limpio, que es exactamente lo que pasaba antes de tener cache.
      }
    }
    const input = this.raiz.querySelector<HTMLInputElement>(".tabla-filtrable__busqueda input");
    if (input) input.value = this.busqueda;
  }

  private get filtrosJson(): string | undefined {
    return this.filtrosColumna.size
      ? JSON.stringify(Object.fromEntries([...this.filtrosColumna].map(([c, v]) => [c, [...v]])))
      : undefined;
  }

  /** La clave con la que esta consulta exacta entra y sale de la cache.
   * `undefined` cuando la tabla no declaro `idTabla`: sin identidad no se
   * puede cachear sin arriesgar servirle a una tabla los datos de otra. */
  private claveCache(): ClavePagina | undefined {
    if (!this.opciones.idTabla) return undefined;
    return {
      idTabla: this.opciones.idTabla,
      seccion: this.opciones.seccion,
      busqueda: this.busqueda,
      ordenarPor: this.ordenarPor,
      ordenDescendente: this.ordenDescendente,
      filtrosJson: this.filtrosJson,
      offset: this.offset,
      snapshot: snapshotVigente(),
    };
  }

  private persistirEstado(): void {
    if (!this.opciones.idTabla) return;
    guardarEstado(this.opciones.idTabla, {
      seccion: this.opciones.seccion,
      busqueda: this.busqueda,
      ordenarPor: this.ordenarPor,
      ordenDescendente: this.ordenDescendente,
      filtrosJson: this.filtrosJson,
      offset: this.offset,
    });
  }

  private async recargar(): Promise<void> {
    this.persistirEstado();
    const clave = this.claveCache();

    // Un acierto de cache se pinta SIN pasar por "Cargando…": ese parpadeo
    // en una pagina que ya se tiene es justo lo que hace sentir lenta la app.
    const cacheada = clave ? leerPagina(clave) : undefined;
    if (cacheada) {
      this.cargando = false;
      this.ultimaPagina = cacheada;
      this.render(cacheada);
      return;
    }

    this.cargando = true;
    this.render();
    try {
      const pagina = await this.opciones.cargarPagina({
        q: this.busqueda,
        limite: LIMITE_PREVISUALIZACION,
        offset: this.offset,
        // Se manda siempre false: la tabla ya no ofrece traerse el conjunto
        // completo de un golpe. El parametro sigue en la firma porque otros
        // llamadores del backend lo usan.
        todo: false,
        ordenar_por: this.ordenarPor,
        orden_descendente: this.ordenDescendente,
        filtros_json: this.filtrosJson,
      });
      this.cargando = false;

      // Una pagina vacia con offset > 0 no es "no hay hallazgos": es que el
      // conjunto encogio debajo de donde estaba parado el usuario (un
      // refresco con menos filas, un estado restaurado de la sesion
      // anterior). Se vuelve a la primera en vez de mostrar una tabla en
      // blanco, que aca se leeria como un error o como "esto no tiene datos".
      if (pagina.visibles === 0 && pagina.total > 0 && this.offset > 0) {
        this.offset = 0;
        void this.recargar();
        return;
      }

      this.ultimaPagina = pagina;
      if (clave) guardarPagina(clave, pagina);
      this.render(pagina);
    } catch (error) {
      this.cargando = false;
      this.render(undefined, error instanceof Error ? error.message : String(error));
    }
  }

  /** Cualquier cambio de busqueda, orden o filtro devuelve a la primera
   * pagina: quedarse en la pagina 7 de un resultado que ahora tiene 3 es
   * como se llega a una tabla vacia que parece un error. */
  private onCambioDeFiltro(): void {
    this.offset = 0;
    this.recargar();
  }

  private irAPagina(nuevoOffset: number): void {
    this.offset = Math.max(0, nuevoOffset);
    this.recargar();
  }

  private temporizadorBusqueda: ReturnType<typeof setTimeout> | undefined;

  private onBuscar(valor: string): void {
    this.busqueda = valor;
    clearTimeout(this.temporizadorBusqueda);
    this.temporizadorBusqueda = setTimeout(() => this.recargar(), DEMORA_BUSQUEDA_MS);
  }

  /** Barra de paginacion + descargas. Sustituye al checkbox "Cargar la tabla
   * completa", que para ver la fila 1.001 obligaba a traerse las 59.000 de
   * una vez y trababa el equipo. */
  private construirPie(pagina: PaginaTabla): HTMLElement {
    const pie = document.createElement("div");
    pie.className = "tabla-filtrable__pie";

    const totalPaginas = Math.max(1, Math.ceil(pagina.total / LIMITE_PREVISUALIZACION));
    const paginaActual = Math.floor(this.offset / LIMITE_PREVISUALIZACION) + 1;

    if (totalPaginas > 1) {
      const navegacion = document.createElement("div");
      navegacion.className = "tabla-filtrable__paginacion";

      const anterior = document.createElement("button");
      anterior.type = "button";
      anterior.className = "btn btn--suave";
      anterior.textContent = "‹ Anterior";
      anterior.disabled = this.offset <= 0 || this.cargando;
      anterior.addEventListener("click", () => this.irAPagina(this.offset - LIMITE_PREVISUALIZACION));

      const indicador = document.createElement("span");
      indicador.className = "tabla-filtrable__pagina-actual";
      const desde = pagina.total === 0 ? 0 : this.offset + 1;
      const hasta = this.offset + pagina.visibles;
      indicador.textContent = `Página ${paginaActual.toLocaleString("es-CO")} de ${totalPaginas.toLocaleString("es-CO")} · filas ${desde.toLocaleString("es-CO")}–${hasta.toLocaleString("es-CO")}`;

      const siguiente = document.createElement("button");
      siguiente.type = "button";
      siguiente.className = "btn btn--suave";
      siguiente.textContent = "Siguiente ›";
      siguiente.disabled = paginaActual >= totalPaginas || this.cargando;
      siguiente.addEventListener("click", () => this.irAPagina(this.offset + LIMITE_PREVISUALIZACION));

      navegacion.append(anterior, indicador, siguiente);
      pie.appendChild(navegacion);
    }

    if (this.opciones.urlDescarga) {
      const descargas = document.createElement("div");
      descargas.className = "tabla-filtrable__descargas";
      const rotulo = document.createElement("span");
      rotulo.className = "tabla-filtrable__descargas-rotulo";
      // Se dice CUANTAS filas trae el archivo porque no son las que se ven:
      // la pantalla pagina, la descarga no. Sin esta linea el usuario no
      // tiene forma de saber si bajo 1.000 o 59.000.
      rotulo.textContent = `Descargar las ${pagina.total.toLocaleString("es-CO")} filas:`;
      descargas.appendChild(rotulo);
      for (const { formato, etiqueta, titulo } of FORMATOS_DESCARGA) {
        const enlace = document.createElement("a");
        enlace.className = "btn btn--suave";
        enlace.href = this.opciones.urlDescarga(formato);
        enlace.title = titulo;
        enlace.textContent = etiqueta;
        // El navegador dispara la descarga solo: son GET con
        // Content-Disposition: attachment, sin fetch+blob de por medio.
        enlace.setAttribute("download", "");
        descargas.appendChild(enlace);
      }
      pie.appendChild(descargas);
    }

    return pie;
  }

  /** Las columnas que se DIBUJAN. Unico lugar que decide eso: el resto del
   * render itera esto y nunca `opciones.columnas` directo, para que encabezado,
   * colgroup y celdas no se puedan desalinear entre si. */
  private get columnasVisibles(): string[] {
    if (this.mostrarTecnicas) return this.opciones.columnas;
    return this.opciones.columnas.filter((c) => !COLUMNAS_TECNICAS.has(c));
  }

  private onMostrarTecnicas(marcado: boolean): void {
    this.mostrarTecnicas = marcado;
    // Solo cambia QUE se pinta: la pagina ya esta en memoria, no se vuelve a
    // pedir al backend (a diferencia de buscar/filtrar/cargar-todo, que si
    // cambian el conjunto de filas).
    this.render(this.ultimaPagina);
  }

  private anchoColumna(columna: string): number {
    const guardado = this.anchosColumna.get(columna);
    if (guardado !== undefined) return guardado;
    return ES_COLUMNA_ANCHA.test(columna) ? ANCHO_COLUMNA_ANCHA_PX : ANCHO_COLUMNA_DEFECTO_PX;
  }

  /** Arrastrar el borde derecho de un <th> para redimensionar su columna --
   * mismo gesto que Excel/Streamlit dataframe. Ajusta el <col> del
   * colgroup, no el <th> directo: con table-layout:fixed eso alcanza para
   * redimensionar TODA la columna sin recalcular el resto. */
  private habilitarRedimension(manija: HTMLElement, columna: string, col: HTMLTableColElement): void {
    manija.addEventListener("pointerdown", (evento) => {
      evento.preventDefault();
      const inicioX = evento.clientX;
      const anchoInicial = this.anchoColumna(columna);
      manija.setPointerCapture(evento.pointerId);
      manija.classList.add("redimensionando");

      const mover = (e: PointerEvent) => {
        const nuevoAncho = Math.max(ANCHO_COLUMNA_MINIMO_PX, anchoInicial + (e.clientX - inicioX));
        this.anchosColumna.set(columna, nuevoAncho);
        col.style.width = `${nuevoAncho}px`;
      };
      const soltar = () => {
        manija.classList.remove("redimensionando");
        manija.removeEventListener("pointermove", mover);
        manija.removeEventListener("pointerup", soltar);
      };
      manija.addEventListener("pointermove", mover);
      manija.addEventListener("pointerup", soltar);
    });
    // Doble clic: volver al ancho por defecto de esa columna, escape rapido
    // si alguien la angosto/ensancho demasiado.
    manija.addEventListener("dblclick", () => {
      this.anchosColumna.delete(columna);
      col.style.width = `${this.anchoColumna(columna)}px`;
    });
  }

  private cerrarPopover(): void {
    document.querySelectorAll(".th-popover").forEach((el) => el.remove());
  }

  private posicionarPopover(popover: HTMLElement, boton: HTMLElement): void {
    const rect = boton.getBoundingClientRect();
    popover.style.top = `${rect.bottom + 4}px`;
    popover.style.left = `${rect.left}px`;
    requestAnimationFrame(() => {
      const anchoVentana = window.innerWidth;
      const anchoPopover = popover.offsetWidth;
      if (rect.left + anchoPopover > anchoVentana - 8) {
        popover.style.left = `${Math.max(8, anchoVentana - anchoPopover - 8)}px`;
      }
    });
  }

  private ordenarYRecargar(columna: string, descendente: boolean): void {
    this.ordenarPor = columna;
    this.ordenDescendente = descendente;
    this.cerrarPopover();
    this.recargar();
  }

  /** Arma y abre el popover de "ordenar y filtrar" de una columna --
   * pedido del usuario (2026-08-28): "un filtro como los de excel que
   * permite buscar especificamente aprox y ordenar". */
  private async abrirPopoverColumna(columna: string, boton: HTMLElement): Promise<void> {
    this.cerrarPopover();
    if (!this.opciones.obtenerValoresColumna) return;

    const popover = document.createElement("div");
    popover.className = "th-popover";
    popover.innerHTML = `<div class="th-popover__mensaje">Cargando valores…</div>`;
    document.body.appendChild(popover);
    this.posicionarPopover(popover, boton);

    let valores = this.cacheValoresColumna.get(columna);
    if (!valores) {
      try {
        valores = await this.opciones.obtenerValoresColumna(columna);
        this.cacheValoresColumna.set(columna, valores);
      } catch {
        if (document.body.contains(popover)) {
          popover.innerHTML = `<div class="th-popover__mensaje">No se pudo cargar la lista de valores.</div>`;
        }
        return;
      }
    }
    if (!document.body.contains(popover)) return; // se cerro mientras cargaba

    popover.innerHTML = "";

    const filaOrden = document.createElement("div");
    filaOrden.className = "th-popover__orden";
    const botonAsc = document.createElement("button");
    botonAsc.type = "button";
    botonAsc.textContent = "↑ Ordenar A-Z";
    botonAsc.addEventListener("click", () => this.ordenarYRecargar(columna, false));
    const botonDesc = document.createElement("button");
    botonDesc.type = "button";
    botonDesc.textContent = "↓ Ordenar Z-A";
    botonDesc.addEventListener("click", () => this.ordenarYRecargar(columna, true));
    filaOrden.append(botonAsc, botonDesc);
    popover.appendChild(filaOrden);

    if (valores.length === 0) {
      const mensaje = document.createElement("div");
      mensaje.className = "th-popover__mensaje";
      mensaje.textContent = "Esta columna tiene demasiados valores distintos para filtrar por lista — usá la búsqueda de la tabla.";
      popover.appendChild(mensaje);
      return;
    }

    const buscar = document.createElement("input");
    buscar.type = "search";
    buscar.placeholder = "🔎 Buscar un valor…";
    buscar.className = "th-popover__buscar";
    popover.appendChild(buscar);

    const listaEl = document.createElement("div");
    listaEl.className = "th-popover__lista";
    popover.appendChild(listaEl);

    const seleccionPrevia = this.filtrosColumna.get(columna);
    const seleccionLocal = new Set(seleccionPrevia ?? valores.map((v) => v.valor));
    const todosLosValores = valores;

    const renderLista = (filtroTexto: string) => {
      listaEl.innerHTML = "";
      const filtroBajo = filtroTexto.trim().toLowerCase();
      const visibles = filtroBajo ? todosLosValores.filter((v) => v.valor.toLowerCase().includes(filtroBajo)) : todosLosValores;
      for (const { valor, conteo } of visibles) {
        const fila = document.createElement("label");
        fila.className = "th-popover__opcion";
        const casilla = document.createElement("input");
        casilla.type = "checkbox";
        casilla.checked = seleccionLocal.has(valor);
        casilla.addEventListener("change", () => {
          if (casilla.checked) seleccionLocal.add(valor);
          else seleccionLocal.delete(valor);
        });
        const etiquetaValor = document.createElement("span");
        etiquetaValor.className = "th-popover__valor";
        etiquetaValor.textContent = valor;
        etiquetaValor.title = valor;
        const etiquetaConteo = document.createElement("span");
        etiquetaConteo.className = "th-popover__conteo";
        etiquetaConteo.textContent = conteo.toLocaleString("es-CO");
        fila.append(casilla, etiquetaValor, etiquetaConteo);
        listaEl.appendChild(fila);
      }
      if (visibles.length === 0) {
        listaEl.innerHTML = `<p class="th-popover__mensaje">Sin coincidencias.</p>`;
      }
    };
    renderLista("");
    buscar.addEventListener("input", () => renderLista(buscar.value));

    const filaBotones = document.createElement("div");
    filaBotones.className = "th-popover__botones";
    const botonCancelar = document.createElement("button");
    botonCancelar.type = "button";
    botonCancelar.className = "btn btn--suave";
    botonCancelar.textContent = "Cancelar";
    botonCancelar.addEventListener("click", () => this.cerrarPopover());
    const botonAplicar = document.createElement("button");
    botonAplicar.type = "button";
    botonAplicar.className = "btn btn--primario";
    botonAplicar.textContent = "Aplicar";
    botonAplicar.addEventListener("click", () => {
      // Todos seleccionados == sin filtro (mismo criterio que Excel: tildar
      // "Seleccionar todo" quita el embudo de la columna).
      if (seleccionLocal.size === todosLosValores.length) {
        this.filtrosColumna.delete(columna);
      } else {
        this.filtrosColumna.set(columna, new Set(seleccionLocal));
      }
      this.cerrarPopover();
      this.recargar();
    });
    filaBotones.append(botonCancelar, botonAplicar);
    popover.appendChild(filaBotones);
  }

  private render(pagina?: PaginaTabla, error?: string): void {
    this.contenedorDatos.innerHTML = "";

    if (error) {
      const aviso = document.createElement("p");
      aviso.className = "aviso aviso--error";
      aviso.textContent = error;
      this.contenedorDatos.appendChild(aviso);
      return;
    }

    if (this.cargando && !pagina) {
      const cargandoEl = document.createElement("p");
      cargandoEl.className = "tabla-filtrable__cargando";
      cargandoEl.textContent = "Cargando…";
      this.contenedorDatos.appendChild(cargandoEl);
      return;
    }
    if (!pagina) return;

    const leyenda = document.createElement("p");
    leyenda.className = "tabla-filtrable__leyenda";
    const totalPaginas = Math.max(1, Math.ceil(pagina.total / LIMITE_PREVISUALIZACION));
    if (totalPaginas > 1) {
      leyenda.textContent = `Total: ${pagina.total.toLocaleString("es-CO")} filas · se muestran de a ${LIMITE_PREVISUALIZACION.toLocaleString("es-CO")} para que la pantalla siga ágil.`;
    } else {
      leyenda.textContent = `Total: ${pagina.total.toLocaleString("es-CO")} · todos caben en esta vista.`;
    }
    this.contenedorDatos.appendChild(leyenda);

    // Solo se ofrece si ESTA tabla trae alguna columna tecnica: una casilla
    // que no revela nada seria ruido en las tablas que no las tienen.
    const tecnicasEnTabla = this.opciones.columnas.filter((c) => COLUMNAS_TECNICAS.has(c));
    if (tecnicasEnTabla.length > 0) {
      const etiquetaTecnicas = document.createElement("label");
      etiquetaTecnicas.className = "tabla-filtrable__cargar-todo";
      const casilla = document.createElement("input");
      casilla.type = "checkbox";
      casilla.checked = this.mostrarTecnicas;
      casilla.addEventListener("change", (e) =>
        this.onMostrarTecnicas((e.target as HTMLInputElement).checked),
      );
      etiquetaTecnicas.appendChild(casilla);
      etiquetaTecnicas.appendChild(
        document.createTextNode(" Mostrar la consulta SQL de verificación"),
      );
      this.contenedorDatos.appendChild(etiquetaTecnicas);
    }

    const envoltorio = document.createElement("div");
    envoltorio.className = "tabla-filtrable__envoltorio"; // overflow-x: auto -- nunca scroll horizontal de toda la pagina
    const tabla = document.createElement("table");
    tabla.className = "tabla-ancho-fijo";

    const colgroup = document.createElement("colgroup");
    const columnasEl: HTMLTableColElement[] = [];
    for (const columna of this.columnasVisibles) {
      const col = document.createElement("col");
      col.style.width = `${this.anchoColumna(columna)}px`;
      colgroup.appendChild(col);
      columnasEl.push(col);
    }
    tabla.appendChild(colgroup);

    const encabezado = document.createElement("thead");
    const filaEncabezado = document.createElement("tr");
    this.columnasVisibles.forEach((columna, i) => {
      const th = document.createElement("th");
      const filaTh = document.createElement("div");
      filaTh.className = "th-fila";
      const etiqueta = document.createElement("span");
      etiqueta.className = "th-etiqueta";
      etiqueta.textContent = this.opciones.etiquetasColumna?.[columna] ?? columna;
      etiqueta.title = columna;
      filaTh.appendChild(etiqueta);

      if (this.opciones.obtenerValoresColumna) {
        const botonFiltro = document.createElement("button");
        botonFiltro.type = "button";
        botonFiltro.className = "th-filtro-boton";
        if (this.ordenarPor === columna || this.filtrosColumna.has(columna)) {
          botonFiltro.classList.add("activo");
        }
        botonFiltro.textContent = "▾";
        botonFiltro.title = "Ordenar y filtrar esta columna";
        botonFiltro.addEventListener("click", (evento) => {
          evento.stopPropagation();
          void this.abrirPopoverColumna(columna, botonFiltro);
        });
        filaTh.appendChild(botonFiltro);
      }
      th.appendChild(filaTh);

      const manija = document.createElement("span");
      manija.className = "th-manija";
      manija.title = "Arrastrar para cambiar el ancho · doble clic para restablecer";
      th.appendChild(manija);
      this.habilitarRedimension(manija, columna, columnasEl[i]);
      filaEncabezado.appendChild(th);
    });
    encabezado.appendChild(filaEncabezado);
    tabla.appendChild(encabezado);

    const cuerpo = document.createElement("tbody");
    if (pagina.filas.length === 0) {
      const fila = document.createElement("tr");
      const celda = document.createElement("td");
      celda.colSpan = this.columnasVisibles.length;
      celda.className = "tabla-filtrable__vacio";
      celda.textContent = "No hay medicamentos con esos criterios.";
      fila.appendChild(celda);
      cuerpo.appendChild(fila);
    } else {
      const fragmento = document.createDocumentFragment();
      for (const fila of pagina.filas) {
        const tr = document.createElement("tr");
        for (const columna of this.columnasVisibles) {
          const td = document.createElement("td");
          const valor = fila[columna];
          const html = this.opciones.formatearCelda?.(columna, valor, fila);
          td.innerHTML = html ?? formatearCeldaDefecto(columna, valor);
          // Tooltip nativo con el valor completo -- la celda trunca con
          // ellipsis (ver CSS), esto es lo que reemplaza el texto cortado.
          if (valor !== null && valor !== undefined && valor !== "") td.title = String(valor);
          tr.appendChild(td);
        }
        fragmento.appendChild(tr);
      }
      cuerpo.appendChild(fragmento);
    }
    tabla.appendChild(cuerpo);
    envoltorio.appendChild(tabla);
    this.contenedorDatos.appendChild(envoltorio);
    this.contenedorDatos.appendChild(this.construirPie(pagina));
  }
}
