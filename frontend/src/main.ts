import { montarRefrescoManual } from "./refresco-manual";
import { montarSalud } from "./salud";
import { montarAuditEntender, montarAuditExplorar, montarAuditPriorizar, montarCadenaCalidad } from "./vistas/auditoria";
import { montarCargueEstructura, montarCargueExcel } from "./vistas/cargue";
import { montarDecision } from "./vistas/decision";
import { montarConsultarInvima } from "./vistas/consulta_detalle";
import { montarComoSeResolvio, montarDetalleRegistro, montarResumenPrincipal } from "./vistas/resumen";

interface SubVista {
  id: string;
  etiqueta: string;
  montar: (contenedor: HTMLElement) => void | Promise<void>;
}
interface Seccion {
  id: string;
  etiqueta: string;
  icono: string;
  grupo: string;
  sub: SubVista[];
}

// Misma fuente de verdad que SUBVISTAS_POR_SECCION en ui_revision/app_streamlit.py.
const SECCIONES: Seccion[] = [
  {
    id: "resumen", etiqueta: "Resumen de resolución", icono: "▤", grupo: "Candidatos para cargue",
    sub: [
      { id: "principal", etiqueta: "Resumen", montar: montarResumenPrincipal },
      { id: "metodo", etiqueta: "Cómo se resolvió", montar: montarComoSeResolvio },
      { id: "detalle", etiqueta: "Detalle por registro", montar: montarDetalleRegistro },
    ],
  },
  {
    id: "decision", etiqueta: "Casos que requieren decisión", icono: "◆", grupo: "Candidatos para cargue",
    sub: [{ id: "bandeja", etiqueta: "Bandeja de casos", montar: montarDecision }],
  },
  {
    id: "cargue", etiqueta: "Cargue a Gemma Net", icono: "⇪", grupo: "Candidatos para cargue",
    sub: [
      { id: "estructura", etiqueta: "Auditoría de estructura", montar: montarCargueEstructura },
      { id: "excel", etiqueta: "Excel de cargue final", montar: montarCargueExcel },
    ],
  },
  {
    id: "invima", etiqueta: "Consultar INVIMA", icono: "⌕", grupo: "Medicamentos ya cargados",
    sub: [{ id: "unica", etiqueta: "Consulta", montar: montarConsultarInvima }],
  },
  {
    id: "auditoria", etiqueta: "Auditoría de coherencia", icono: "✓", grupo: "Medicamentos ya cargados",
    sub: [
      { id: "priorizar", etiqueta: "Priorizar lo que requiere acción", montar: montarAuditPriorizar },
      { id: "entender", etiqueta: "Entender la calidad del catálogo", montar: montarAuditEntender },
      { id: "explorar", etiqueta: "Explorar todos los hallazgos", montar: montarAuditExplorar },
      { id: "cadena", etiqueta: "Trazabilidad de calidad (H1-H6)", montar: montarCadenaCalidad },
    ],
  },
];

let seccionActual = SECCIONES[0];
let subActual = seccionActual.sub[0];

// Pila de pestañas visitadas, para el boton "← Volver" de la topbar. Se
// guarda la posicion ANTES de cada salto, asi que volver siempre deshace el
// ultimo movimiento. Importa sobre todo con "Ver diferencias" y el buscador
// de INVIMA, que sacan al usuario de su pestaña de un salto: sin esto habia
// que reconstruir a mano por donde se venia.
const historial: { seccion: string; sub: string }[] = [];
const LIMITE_HISTORIAL = 50;

function recordarPosicion(): void {
  historial.push({ seccion: seccionActual.id, sub: subActual.id });
  if (historial.length > LIMITE_HISTORIAL) historial.shift();
}

/** Navegacion programatica -- para que una vista (ej. "Ver diferencias" en
 * la calidad de auditoria) pueda llevar al usuario a otra seccion sin pasar
 * por el clic del rail. `subId` opcional cae a la primera sub-vista. */
function navegarA(seccionId: string, subId?: string, recordar = true): void {
  const seccion = SECCIONES.find((s) => s.id === seccionId);
  if (!seccion) return;
  const destinoSub = (subId && seccion.sub.find((s) => s.id === subId)) || seccion.sub[0];
  // Ir a donde ya estas no es un movimiento: apilarlo obligaria a pulsar
  // "Volver" dos veces para retroceder una.
  if (seccion.id === seccionActual.id && destinoSub.id === subActual.id) return;
  if (recordar) recordarPosicion();
  seccionActual = seccion;
  subActual = destinoSub;
  render();
}

function volver(): void {
  const previa = historial.pop();
  if (!previa) return;
  navegarA(previa.seccion, previa.sub, false);
}

// Evento global en vez de que las vistas importen navegarA de main.ts
// directamente -- main.ts ya importa las vistas (montarAudit*, etc.), asi
// que un import en sentido contrario cierra un ciclo entre el modulo de
// entrada y un modulo hoja. Un CustomEvent en window desacopla las dos
// puntas por completo: cualquier vista puede pedir navegar sin conocer a
// main.ts, y main.ts no necesita exportar nada para que lo usen.
window.addEventListener("gemma:navegar", (evento) => {
  const detalle = (evento as CustomEvent<{ seccion: string; sub?: string }>).detail;
  if (detalle?.seccion) navegarA(detalle.seccion, detalle.sub);
});

function pintarRail(): void {
  const nav = document.getElementById("rail-nav");
  if (!nav) return;
  const grupos = [...new Set(SECCIONES.map((s) => s.grupo))];
  nav.innerHTML = grupos
    .map(
      (grupo) => `
      <div class="rail__grupo-titulo">${grupo}</div>
      ${SECCIONES.filter((s) => s.grupo === grupo)
        .map((s) => `<button class="rail__item ${s.id === seccionActual.id ? "activo" : ""}" data-seccion="${s.id}"><span class="ic">${s.icono}</span>${s.etiqueta}</button>`)
        .join("")}`,
    )
    .join("");
  nav.querySelectorAll<HTMLButtonElement>("[data-seccion]").forEach((b) =>
    b.addEventListener("click", () => {
      if (b.dataset.seccion) navegarA(b.dataset.seccion);
    }),
  );
}

function pintarSubnav(): void {
  const subnav = document.getElementById("subnav");
  if (!subnav) return;
  if (seccionActual.sub.length <= 1) {
    subnav.innerHTML = "";
    subnav.classList.add("oculto");
    return;
  }
  subnav.classList.remove("oculto");
  subnav.innerHTML = seccionActual.sub
    .map((s) => `<button class="subnav__pill ${s.id === subActual.id ? "activo" : ""}" data-sub="${s.id}">${s.etiqueta}</button>`)
    .join("");
  subnav.querySelectorAll<HTMLButtonElement>("[data-sub]").forEach((b) =>
    b.addEventListener("click", () => {
      if (b.dataset.sub) navegarA(seccionActual.id, b.dataset.sub);
    }),
  );
}

function render(): void {
  const botonVolver = document.getElementById("boton-volver");
  // Se esconde en vez de deshabilitarse: un boton apagado en la topbar de
  // arranque solo agrega ruido, no informa de nada.
  if (botonVolver) botonVolver.classList.toggle("oculto", historial.length === 0);
  document.getElementById("miga-ruta")!.textContent = seccionActual.grupo;
  document.getElementById("miga-titulo")!.textContent = seccionActual.sub.length > 1 ? subActual.etiqueta : seccionActual.etiqueta;
  pintarRail();
  pintarSubnav();
  const vista = document.getElementById("vista");
  if (vista) void subActual.montar(vista);
}

function inicializarSalud(): void {
  const banner = document.getElementById("banner-salud");
  const anillo = document.getElementById("anillo-refresco");
  const textoRefresco = document.getElementById("texto-refresco");
  const subtextoRefresco = document.getElementById("subtexto-refresco");
  const contenedorRefresco = document.getElementById("refresco");
  if (!banner || !anillo || !textoRefresco || !subtextoRefresco || !contenedorRefresco) return;
  montarSalud({ banner, anillo, textoRefresco, subtextoRefresco, contenedorRefresco });
}

function inicializarRefrescoManual(): void {
  const boton = document.getElementById("boton-actualizar-ahora") as HTMLButtonElement | null;
  const panel = document.getElementById("panel-progreso");
  if (!boton || !panel) return;
  montarRefrescoManual(boton, panel, (exito) => {
    if (exito) render(); // re-pinta la vista actual con los datos ya frescos
  });
}

document.getElementById("boton-volver")?.addEventListener("click", volver);

// Alt+← es el atajo que ya usa el navegador para "atras"; aqui la app no
// toca el historial del navegador (es una sola pagina), asi que se replica
// para que el gesto de siempre funcione igual.
window.addEventListener("keydown", (e) => {
  if (e.altKey && e.key === "ArrowLeft") {
    e.preventDefault();
    volver();
  }
});

document.getElementById("toggle-tema")?.addEventListener("click", () => {
  const raiz = document.documentElement;
  raiz.setAttribute("data-theme", raiz.getAttribute("data-theme") === "dark" ? "light" : "dark");
});

inicializarSalud();
inicializarRefrescoManual();
render();
