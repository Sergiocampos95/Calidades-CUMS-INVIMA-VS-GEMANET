/**
 * Filtro de seleccion multiple (checkbox-dropdown) -- pedido explicito del
 * usuario (2026-08-28), reemplaza el <select> de un solo valor de
 * ESTADO_COHERENCIA: "si me gusta pero mas bien seleccion multiple es lo
 * mejor para el caso" (poder ver, por ejemplo, "vencido en INVIMA" y "en
 * otro estado" a la vez, no uno por uno).
 *
 * Generico (no atado a ESTADO_COHERENCIA) para poder reusarlo en cualquier
 * otro filtro de columna que lo necesite mas adelante -- mismo criterio que
 * TablaFiltrable siendo el unico componente de tabla.
 */

export interface OpcionSelectorMultiple {
  valor: string;
  etiqueta: string;
}

// UN solo listener delegado a nivel de documento, registrado una vez al
// cargar el modulo -- no uno por instancia. Cada vista que se visita crea
// una instancia nueva de SelectorMultiple (las vistas no tienen un ciclo de
// "destruir" explicito); un listener por instancia se iria acumulando sin
// limite cada vez que se navega de un lado a otro. Delegar a documento
// cierra cualquier panel abierto sin importar cuantas instancias existan.
if (typeof document !== "undefined") {
  document.addEventListener("click", (evento) => {
    document.querySelectorAll<HTMLElement>(".selector-multiple__panel:not(.oculto)").forEach((panel) => {
      if (!panel.parentElement?.contains(evento.target as Node)) {
        panel.classList.add("oculto");
      }
    });
  });
}

export class SelectorMultiple {
  readonly elemento: HTMLElement;
  private readonly boton: HTMLButtonElement;
  private readonly panel: HTMLElement;
  private readonly seleccionados = new Set<string>();

  constructor(
    opciones: OpcionSelectorMultiple[],
    private readonly etiquetaVacio: string = "Todos",
  ) {
    this.elemento = document.createElement("div");
    this.elemento.className = "selector-multiple";

    this.boton = document.createElement("button");
    this.boton.type = "button";
    this.boton.className = "selector-multiple__boton";
    this.elemento.appendChild(this.boton);

    this.panel = document.createElement("div");
    this.panel.className = "selector-multiple__panel oculto";
    this.elemento.appendChild(this.panel);

    for (const { valor, etiqueta } of opciones) {
      const fila = document.createElement("label");
      fila.className = "selector-multiple__opcion";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = valor;
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) this.seleccionados.add(valor);
        else this.seleccionados.delete(valor);
        this.actualizarBoton();
        this.elemento.dispatchEvent(new CustomEvent("cambio-filtro"));
      });
      fila.append(checkbox, document.createTextNode(` ${etiqueta}`));
      this.panel.appendChild(fila);
    }

    this.boton.addEventListener("click", (evento) => {
      evento.stopPropagation();
      this.panel.classList.toggle("oculto");
    });

    this.actualizarBoton();
  }

  private actualizarBoton(): void {
    const n = this.seleccionados.size;
    this.boton.textContent = n === 0 ? `${this.etiquetaVacio} ▾` : `${n} seleccionado${n === 1 ? "" : "s"} ▾`;
  }

  /** Los valores marcados, en el orden en que se seleccionaron -- vacio
   * significa "sin filtro" (el llamador lo traduce a `undefined`). */
  valores(): string[] {
    return [...this.seleccionados];
  }
}
