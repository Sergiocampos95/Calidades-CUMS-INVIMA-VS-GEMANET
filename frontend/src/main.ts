import { montarRefrescoManual } from "./refresco-manual";
import { montarSalud } from "./salud";
import { montarAuditEntender, montarAuditExplorar, montarAuditPriorizar, montarCadenaCalidad } from "./vistas/auditoria";
import { montarCargueEstructura, montarCargueExcel } from "./vistas/cargue";
import { montarDecision } from "./vistas/decision";
import { montarConsultarInvima } from "./vistas/invima";
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
      const seccion = SECCIONES.find((s) => s.id === b.dataset.seccion);
      if (!seccion) return;
      seccionActual = seccion;
      subActual = seccion.sub[0];
      render();
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
      const sub = seccionActual.sub.find((s) => s.id === b.dataset.sub);
      if (sub) {
        subActual = sub;
        render();
      }
    }),
  );
}

function render(): void {
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

document.getElementById("toggle-tema")?.addEventListener("click", () => {
  const raiz = document.documentElement;
  raiz.setAttribute("data-theme", raiz.getAttribute("data-theme") === "dark" ? "light" : "dark");
});

inicializarSalud();
inicializarRefrescoManual();
render();
