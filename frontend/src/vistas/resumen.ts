import { obtenerResumenCandidatos, obtenerResumenMetodos, obtenerResumenUniverso, obtenerUniverso } from "../api";
import { cabeceraConDescarga } from "../descargas";
import { renderTarjetas } from "../tarjetas";
import { TablaFiltrable } from "../tabla";

function panel(titulo: string): { panel: HTMLElement; cuerpo: HTMLElement } {
  const panel = document.createElement("div");
  panel.className = "panel";
  const cab = document.createElement("div");
  cab.className = "panel__cab";
  cab.innerHTML = `<div class="panel__titulo">${titulo}</div>`;
  const cuerpo = document.createElement("div");
  cuerpo.className = "panel__cuerpo";
  panel.append(cab, cuerpo);
  return { panel, cuerpo };
}

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
        { clave: "cuarentena", etiqueta: "En cuarentena", ayuda: "No se pudo decidir con certeza; cero es el mejor resultado posible." },
      ],
      { ...resumen, __evaluados: evaluados },
    );
  } catch (error) {
    tarjetas.innerHTML = `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
  }
}

export async function montarComoSeResolvio(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = `<p class="vista__intro">INVIMA escribe marca y unidad como texto; Gemma Net las guarda como código. Esto dice cómo se logró cada traducción — no es un dato de negocio, es el nivel de confianza del proceso.</p>`;
  const grid = document.createElement("div");
  grid.className = "grid-2";
  contenedor.appendChild(grid);
  try {
    const metodos = await obtenerResumenMetodos();
    for (const [clave, titulo] of [["unidad", "Cómo se resolvió la UNIDAD DE MEDIDA"], ["marca", "Cómo se resolvió la MARCA"]] as const) {
      const { panel: p, cuerpo } = panel(titulo);
      const datos = metodos[clave] ?? {};
      const total = Object.values(datos).reduce((a, b) => a + b, 0) || 1;
      cuerpo.innerHTML = Object.entries(datos)
        .sort((a, b) => b[1] - a[1])
        .map(([metodo, n]) => {
          const pct = (n / total) * 100;
          return `<div class="fila-metodo"><div class="fila-metodo__nombre">${metodo}<div class="mini-barra"><span style="width:${pct}%"></span></div></div><span class="fila-metodo__num">${n.toLocaleString("es-CO")} · ${pct.toFixed(1)}%</span></div>`;
        })
        .join("");
      grid.appendChild(p);
    }
  } catch (error) {
    grid.innerHTML = `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
  }
}

const ETIQUETA_CLASIFICACION: Record<string, string> = {
  candidato: "Candidato",
  rol_no_fabricante: "Rol ≠ FABRICANTE",
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
    cargarPagina: (p) => obtenerUniverso(p),
  });
}
