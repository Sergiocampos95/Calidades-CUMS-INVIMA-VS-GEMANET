function placeholder(titulo: string, detalle: string): string {
  return `<div class="placeholder">
    <strong>${titulo}</strong>
    <span>${detalle}</span>
  </div>`;
}

export function montarCargueEstructura(contenedor: HTMLElement): void {
  contenedor.innerHTML =
    `<p class="vista__intro">Verificación de que cada campo del cargue final tiene lo que Gemma Net exige antes de exportar.</p>` +
    placeholder(
      "Todavía sin conectar",
      "El backend no expone hoy un endpoint de estructura de cargue — es lo próximo si se aprueba esta pantalla. La lógica real ya existe en exportacion/estructura_cargue.py.",
    );
}

export function montarCargueExcel(contenedor: HTMLElement): void {
  contenedor.innerHTML =
    `<p class="vista__intro">El archivo final, listo para subir a Gemma Net.</p>` +
    placeholder(
      "Todavía sin conectar",
      "Generar el .xlsx bajo demanda requiere un endpoint nuevo (POST, no GET) que hoy no existe en el backend — el patrón real ya está resuelto en exportacion/cargue.py.",
    );
}
