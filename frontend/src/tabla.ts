import type { PaginaTabla } from "./tipos";

/**
 * El equivalente de `_tabla_filtrable`/`_mostrar_tabla_estandar` de la UI de
 * Streamlit: UN solo componente para dibujar cualquier tabla grande, con
 * busqueda libre siempre visible y el recorte de previsualizacion + opcion
 * explicita de "Cargar la tabla completa" (regla de CLAUDE.md, seccion UI).
 * Ninguna tabla de esta app se dibuja fuera de este componente.
 */

const LIMITE_PREVISUALIZACION = 1000;
const DEMORA_BUSQUEDA_MS = 300;

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
  if (typeof valor === "number" && columna.startsWith("PORCENTAJE")) {
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

  constructor(
    contenedor: HTMLElement,
    private opciones: OpcionesTablaFiltrable,
  ) {
    this.raiz = document.createElement("div");
    this.raiz.className = "tabla-filtrable";
    contenedor.appendChild(this.raiz);
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

  private render(pagina?: PaginaTabla, error?: string): void {
    this.raiz.innerHTML = "";

    const filaBusqueda = document.createElement("div");
    filaBusqueda.className = "tabla-filtrable__busqueda";
    const input = document.createElement("input");
    input.type = "search";
    input.placeholder = "🔎 Buscar (cualquier columna)";
    input.value = this.busqueda;
    input.addEventListener("input", (e) => this.onBuscar((e.target as HTMLInputElement).value));
    filaBusqueda.appendChild(input);
    if (this.opciones.controlesExtra) filaBusqueda.appendChild(this.opciones.controlesExtra);
    this.raiz.appendChild(filaBusqueda);

    if (error) {
      const aviso = document.createElement("p");
      aviso.className = "aviso aviso--error";
      aviso.textContent = error;
      this.raiz.appendChild(aviso);
      return;
    }

    if (this.cargando && !pagina) {
      const cargandoEl = document.createElement("p");
      cargandoEl.className = "tabla-filtrable__cargando";
      cargandoEl.textContent = "Cargando…";
      this.raiz.appendChild(cargandoEl);
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
    this.raiz.appendChild(leyenda);

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
      this.raiz.appendChild(etiquetaCheckbox);
    }

    const envoltorio = document.createElement("div");
    envoltorio.className = "tabla-filtrable__envoltorio"; // overflow-x: auto -- nunca scroll horizontal de toda la pagina
    const tabla = document.createElement("table");

    const encabezado = document.createElement("thead");
    const filaEncabezado = document.createElement("tr");
    for (const columna of this.opciones.columnas) {
      const th = document.createElement("th");
      th.textContent = columna;
      filaEncabezado.appendChild(th);
    }
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
      for (const fila of pagina.filas) {
        const tr = document.createElement("tr");
        for (const columna of this.opciones.columnas) {
          const td = document.createElement("td");
          const html = this.opciones.formatearCelda?.(columna, fila[columna], fila);
          td.innerHTML = html ?? formatearCeldaDefecto(columna, fila[columna]);
          tr.appendChild(td);
        }
        cuerpo.appendChild(tr);
      }
    }
    tabla.appendChild(cuerpo);
    envoltorio.appendChild(tabla);
    this.raiz.appendChild(envoltorio);
  }
}
