import { obtenerResumenCandidatos, obtenerResumenUniverso, obtenerUniverso, obtenerValoresColumna } from "../api";
import { cabeceraConDescarga } from "../descargas";
import { ETIQUETAS_COLUMNA_COMUNES, pildora } from "../pildoras";
import { renderTarjetas } from "../tarjetas";
import { TablaFiltrable } from "../tabla";

export async function montarResumenPrincipal(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = cabeceraConDescarga(
    "Lo que INVIMA da por válido, cruzado contra lo que ya existe en Gemma Net.",
    "Descargar reporte de cruce (.xlsx)",
    "candidatos",
  );
  const tarjetas = document.createElement("div");
  contenedor.appendChild(tarjetas);
  try {
    const resumen = await obtenerResumenCandidatos();
    const evaluados = Object.values(resumen).reduce((a, b) => a + b, 0);
    renderTarjetas(
      tarjetas,
      [
        { clave: "__evaluados", etiqueta: "Registros evaluados", ayuda: "Los registros de INVIMA que pasaron los cuatro filtros y llegaron a cruzarse contra Gemma Net." },
        { clave: "candidato", etiqueta: "Candidatos a crear", ayuda: "Están en INVIMA, cumplen todo, y su código no existe todavía en Gemma Net." },
        { clave: "ya_existe", etiqueta: "Ya en Gemma Net", ayuda: "Su código ya está cargado en la plataforma: no hay nada que crear." },
        // "En cuarentena" es como lo llama el proceso; la pantalla que los
        // atiende se llama "Casos que requieren decisión", y las dos tienen
        // que decir lo mismo.
        { clave: "cuarentena", etiqueta: "Requieren decisión", ayuda: "No se pudo decidir con certeza (por ejemplo, un código repetido entre candidatos): una persona lo resuelve en «Casos que requieren decisión». Cero es el mejor resultado posible." },
      ],
      { ...resumen, __evaluados: evaluados },
    );
  } catch (error) {
    tarjetas.innerHTML = `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
  }
}

// La sub-vista "Cómo se resolvió" (con qué método se tradujo la marca y la
// unidad de INVIMA a los códigos de Gemma Net: exacto_sigla / alias / fuzzy /
// sin_resolver) se retiró el 2026-09-14, pedido del usuario: era telemetría
// del proceso en vocabulario técnico ("fuzzy") y no le daba nada que hacer al
// auditor. Lo accionable ya está en "Casos que requieren decisión" y en
// "Auditoría de estructura" (pendientes de clasificación manual). El endpoint
// GET /candidatos/resumen-metodos sigue existiendo por si se necesita.

const ETIQUETA_CLASIFICACION: Record<string, string> = {
  candidato: "Candidato",
  rol_no_fabricante: "Titular no es fabricante",
  cum_inactivo: "CUM inactivo",
  registro_no_vigente: "Registro no vigente",
  muestra_medica: "Muestra médica",
};
const AYUDA_CLASIFICACION: Record<string, string> = {
  candidato: "Pasó los cuatro filtros: es un medicamento que la EPS debería tener cargado.",
  rol_no_fabricante: "El titular no figura como fabricante (ej. importador).",
  cum_inactivo: "La presentación está descontinuada en INVIMA.",
  registro_no_vigente: "Cero es lo esperado si la fuente es el listado de Vigentes.",
  muestra_medica: "Marcado como muestra médica, no se dispensa.",
};

// La tabla traía el valor crudo ("rol_no_fabricante") mientras la tarjeta de
// arriba decía "Titular no es fabricante": misma etiqueta en los dos sitios.
function pildoraClasificacion(valor: unknown): string {
  const v = String(valor ?? "");
  return pildora(v === "candidato" ? "ok" : "neutro", ETIQUETA_CLASIFICACION[v] ?? v);
}

export async function montarDetalleRegistro(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = `<p class="vista__intro">Cada registro de INVIMA recibe la etiqueta del <strong>primer</strong> filtro que incumple — por eso las categorías suman el archivo completo.</p>`;
  const tarjetas = document.createElement("div");
  contenedor.appendChild(tarjetas);
  try {
    const resumen = await obtenerResumenUniverso();
    renderTarjetas(
      tarjetas,
      Object.keys(ETIQUETA_CLASIFICACION).map((clave) => ({ clave, etiqueta: ETIQUETA_CLASIFICACION[clave], ayuda: AYUDA_CLASIFICACION[clave] })),
      resumen,
    );
  } catch (error) {
    tarjetas.innerHTML = `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
    return;
  }

  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: ["CODIGO_INTERNO", "PRODUCTO", "EXPEDIENTE", "CONSECUTIVO", "TIPO_ROL", "ESTADO_CUM", "ESTADO_REGISTRO", "CLASIFICACION_CREACION"],
    etiquetasColumna: ETIQUETAS_COLUMNA_COMUNES,
    formatearCelda: (columna, valor) => (columna === "CLASIFICACION_CREACION" && valor ? pildoraClasificacion(valor) : null),
    cargarPagina: (p) => obtenerUniverso(p),
    obtenerValoresColumna: (columna) => obtenerValoresColumna("/universo/valores", columna),
  });
}
