/**
 * Tarjetas de metrica compactas -- equivalente de `st.metric(...help=...)`
 * en Streamlit. Un icono "?" con `title` nativo (tooltip del navegador) en
 * vez de un parrafo largo: mismo pedido explicito del usuario documentado
 * en CLAUDE.md ("un desplegable solo desperdicia espacio").
 */

export interface DefinicionTarjeta {
  clave: string;
  etiqueta: string;
  ayuda?: string;
}

export function renderTarjetas(
  contenedor: HTMLElement,
  definiciones: DefinicionTarjeta[],
  valores: Record<string, number>,
): void {
  contenedor.innerHTML = "";
  contenedor.className = "fila-tarjetas";
  for (const def of definiciones) {
    const valor = valores[def.clave] ?? 0;
    const tarjeta = document.createElement("div");
    tarjeta.className = "tarjeta-metrica";

    const encabezado = document.createElement("div");
    encabezado.className = "tarjeta-metrica__encabezado";
    const etiqueta = document.createElement("span");
    etiqueta.textContent = def.etiqueta;
    encabezado.appendChild(etiqueta);
    if (def.ayuda) {
      const ayuda = document.createElement("span");
      ayuda.className = "tarjeta-metrica__ayuda";
      ayuda.textContent = "?";
      ayuda.title = def.ayuda;
      encabezado.appendChild(ayuda);
    }
    tarjeta.appendChild(encabezado);

    const numero = document.createElement("div");
    numero.className = "tarjeta-metrica__numero";
    numero.textContent = valor.toLocaleString("es-CO");
    tarjeta.appendChild(numero);

    contenedor.appendChild(tarjeta);
  }
}
