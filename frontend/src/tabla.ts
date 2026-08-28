import type { PaginaTabla } from "./tipos";

/**
 * El equivalente de `_tabla_filtrable`/`_mostrar_tabla_estandar` de la UI de
 * Streamlit: UN solo componente para dibujar cualquier tabla grande, con
 * busqueda libre siempre visible y el recorte de previsualizacion + opcion
 * explicita de "Cargar la tabla completa" (regla de CLAUDE.md, seccion UI).
 * Ninguna tabla de esta app se dibuja fuera de este componente.
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
 */

const LIMITE_PREVISUALIZACION = 1000;
const DEMORA_BUSQUEDA_MS = 300;
const ANCHO_COLUMNA_DEFECTO_PX = 150;
const ANCHO_COLUMNA_ANCHA_PX = 280; // columnas de texto largo conocidas -- ver ES_COLUMNA_ANCHA
const ANCHO_COLUMNA_MINIMO_PX = 60;

const ES_COLUMNA_ANCHA = /DESCRIPCION|MOTIVO|COMO_VERIFICAR|DETALLE|CAMPOS_CON|CONSEJO|CONSULTA_VERIFICACION_SQL/i;

export interface OpcionesTablaFiltrable {
  columnas: string[];
  /** Recibe {q, limite, offset, todo} + los filtros extra que agregue el
   * llamador (ej. estado_coherencia) y devuelve la pagina correspondiente. */
  cargarPagina: (parametros: { q: string; limite: number; offset: number; todo: boolean }) => Promise<PaginaTabla>;
  /** Controles de filtro adicionales (ej. selector de ESTADO_COHERENCIA),
   * ya montados por el llamador -- este componente solo los ubica arriba
   * de la busqueda y escucha su evento "cambio-filtro" para re-consultar. */
  controlesExtra?: HTMLElement;
  /** Formateador de celda por columna, opcional. Devuelve HTML (para
   * pildoras de estado, texto mono, etc) -- SOLO usarlo para columnas de
   * valores controlados (enums como accion/ESTADO_COHERENCIA), nunca para
   * texto libre: el default (sin esto) escapa todo via textContent. */
  formatearCelda?: (columna: string, valor: unknown, fila: Record<string, unknown>) => string | null;
}

function esc(valor: unknown): string {
  return String(valor).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}

function formatearCeldaDefecto(columna: string, valor: unknown): string {
  // null (JSON de NaN/None) nunca se muestra como "0" ni en blanco sin
  // explicacion -- "—" dice explicitamente "no hay dato", igual que hace
  // la UI de Streamlit con PORCENTAJE_CALIDAD vacio.
  if (valor === null || valor === undefined || valor === "") return `<span class="celda-muda">—</span>`;
  if (typeof valor === "number" && (columna.startsWith("PORCENTAJE") || columna.startsWith("SIMILITUD_"))) {
    return `<span class="celda-mono">${valor.toFixed(1)}%</span>`;
  }
  if (columna === "CODIGO_INTERNO" || columna.endsWith("_INTERNO")) {
    return `<span class="celda-mono">${esc(valor)}</span>`;
  }
  return esc(valor);
}

export class TablaFiltrable {
  private busqueda = "";
  private mostrarTodo = false;
  private cargando = false;
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

  constructor(
    contenedor: HTMLElement,
    private opciones: OpcionesTablaFiltrable,
  ) {
    this.raiz = document.createElement("div");
    this.raiz.className = "tabla-filtrable";
    contenedor.appendChild(this.raiz);

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

    this.opciones.controlesExtra?.addEventListener("cambio-filtro", () => this.recargar());
    this.recargar();
  }

  private async recargar(): Promise<void> {
    this.cargando = true;
    this.render();
    try {
      const pagina = await this.opciones.cargarPagina({
        q: this.busqueda,
        limite: LIMITE_PREVISUALIZACION,
        offset: 0,
        todo: this.mostrarTodo,
      });
      this.cargando = false;
      this.render(pagina);
    } catch (error) {
      this.cargando = false;
      this.render(undefined, error instanceof Error ? error.message : String(error));
    }
  }

  private temporizadorBusqueda: ReturnType<typeof setTimeout> | undefined;

  private onBuscar(valor: string): void {
    this.busqueda = valor;
    clearTimeout(this.temporizadorBusqueda);
    this.temporizadorBusqueda = setTimeout(() => this.recargar(), DEMORA_BUSQUEDA_MS);
  }

  private onCargarTodo(marcado: boolean): void {
    this.mostrarTodo = marcado;
    this.recargar();
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
    if (pagina.limite_aplicado) {
      leyenda.textContent = `Total: ${pagina.total.toLocaleString("es-CO")} · visibles: ${pagina.visibles.toLocaleString("es-CO")}. Para que la pantalla siga ágil, se muestran las primeras ${LIMITE_PREVISUALIZACION.toLocaleString("es-CO")}.`;
    } else {
      leyenda.textContent = `Total: ${pagina.total.toLocaleString("es-CO")} · todos caben en esta vista.`;
    }
    this.contenedorDatos.appendChild(leyenda);

    if (pagina.limite_aplicado || this.mostrarTodo) {
      const etiquetaCheckbox = document.createElement("label");
      etiquetaCheckbox.className = "tabla-filtrable__cargar-todo";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = this.mostrarTodo;
      checkbox.addEventListener("change", (e) => this.onCargarTodo((e.target as HTMLInputElement).checked));
      etiquetaCheckbox.appendChild(checkbox);
      etiquetaCheckbox.appendChild(
        document.createTextNode(` Cargar la tabla completa (${pagina.total.toLocaleString("es-CO")} filas, puede tardar más)`),
      );
      this.contenedorDatos.appendChild(etiquetaCheckbox);
    }

    const envoltorio = document.createElement("div");
    envoltorio.className = "tabla-filtrable__envoltorio"; // overflow-x: auto -- nunca scroll horizontal de toda la pagina
    const tabla = document.createElement("table");
    tabla.className = "tabla-ancho-fijo";

    const colgroup = document.createElement("colgroup");
    const columnasEl: HTMLTableColElement[] = [];
    for (const columna of this.opciones.columnas) {
      const col = document.createElement("col");
      col.style.width = `${this.anchoColumna(columna)}px`;
      colgroup.appendChild(col);
      columnasEl.push(col);
    }
    tabla.appendChild(colgroup);

    const encabezado = document.createElement("thead");
    const filaEncabezado = document.createElement("tr");
    this.opciones.columnas.forEach((columna, i) => {
      const th = document.createElement("th");
      const etiqueta = document.createElement("span");
      etiqueta.className = "th-etiqueta";
      etiqueta.textContent = columna;
      etiqueta.title = columna;
      const manija = document.createElement("span");
      manija.className = "th-manija";
      manija.title = "Arrastrar para cambiar el ancho · doble clic para restablecer";
      th.append(etiqueta, manija);
      this.habilitarRedimension(manija, columna, columnasEl[i]);
      filaEncabezado.appendChild(th);
    });
    encabezado.appendChild(filaEncabezado);
    tabla.appendChild(encabezado);

    const cuerpo = document.createElement("tbody");
    if (pagina.filas.length === 0) {
      const fila = document.createElement("tr");
      const celda = document.createElement("td");
      celda.colSpan = this.opciones.columnas.length;
      celda.className = "tabla-filtrable__vacio";
      celda.textContent = "No hay medicamentos con esos criterios.";
      fila.appendChild(celda);
      cuerpo.appendChild(fila);
    } else {
      const fragmento = document.createDocumentFragment();
      for (const fila of pagina.filas) {
        const tr = document.createElement("tr");
        for (const columna of this.opciones.columnas) {
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
  }
}
