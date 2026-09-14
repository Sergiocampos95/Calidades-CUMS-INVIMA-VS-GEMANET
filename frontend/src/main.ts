import { invalidarTodo } from "./cache_tablas";
import { montarRefrescoManual } from "./refresco-manual";
import { montarSalud } from "./salud";
import { mostrarIngreso, pintarUsuario, sesionActual } from "./sesion";
import type { UsuarioSesion } from "./tipos";
import { montarAdminPermisos } from "./vistas/admin";
import { montarAuditEntender, montarAuditExplorar, montarAuditPriorizar, montarBandeja, montarCadenaCalidad } from "./vistas/auditoria";
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
  // Rediseño 2026-09-14 (sistema de diseño de Auditoría de Calidades): la
  // BANDEJA de calidades es la portada, y la navegación es una barra
  // superior con pocas entradas cortas, como en ese dashboard.
  {
    id: "auditoria", etiqueta: "Bandeja", icono: "✓", grupo: "Medicamentos ya cargados",
    sub: [
      { id: "bandeja", etiqueta: "Bandeja de calidades", montar: montarBandeja },
      { id: "entender", etiqueta: "Casos por calidad", montar: montarAuditEntender },
      { id: "priorizar", etiqueta: "Priorizar por riesgo", montar: montarAuditPriorizar },
      { id: "explorar", etiqueta: "Explorar todos los hallazgos", montar: montarAuditExplorar },
      { id: "cadena", etiqueta: "Trazabilidad H1-H6", montar: montarCadenaCalidad },
    ],
  },
  {
    id: "invima", etiqueta: "Consultar INVIMA", icono: "⌕", grupo: "Medicamentos ya cargados",
    sub: [{ id: "unica", etiqueta: "Consulta de un CUM", montar: montarConsultarInvima }],
  },
  {
    id: "resumen", etiqueta: "Candidatos", icono: "▤", grupo: "Candidatos para cargue",
    sub: [
      { id: "principal", etiqueta: "Resumen de resolución", montar: montarResumenPrincipal },
      { id: "metodo", etiqueta: "Cómo se resolvió", montar: montarComoSeResolvio },
      { id: "detalle", etiqueta: "Detalle por registro", montar: montarDetalleRegistro },
    ],
  },
  {
    id: "decision", etiqueta: "Decisiones", icono: "◆", grupo: "Candidatos para cargue",
    sub: [{ id: "bandeja", etiqueta: "Casos que requieren decisión", montar: montarDecision }],
  },
  {
    id: "cargue", etiqueta: "Cargue", icono: "⇪", grupo: "Candidatos para cargue",
    sub: [
      { id: "estructura", etiqueta: "Auditoría de estructura", montar: montarCargueEstructura },
      { id: "excel", etiqueta: "Excel de cargue final", montar: montarCargueExcel },
    ],
  },
];

// Solo para administradores del ERP: se agrega a SECCIONES al iniciar la app
// con una sesion admin (ver iniciarApp). Un usuario normal ni la ve en el
// riel ni puede llegar a ella: el backend responde 403 de todas formas.
const SECCION_ADMIN: Seccion = {
  id: "admin", etiqueta: "Permisos", icono: "⚙", grupo: "Administración",
  sub: [{ id: "permisos", etiqueta: "Usuarios con acceso", montar: montarAdminPermisos }],
};

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
  // Barra superior con enlaces planos (sistema de diseño de Auditoría de
  // Calidades), sin grupos: los grupos siguen viviendo en las migas.
  const nav = document.getElementById("nav-principal");
  if (!nav) return;
  nav.innerHTML = SECCIONES.map(
    (s) => `<a role="button" tabindex="0" class="${s.id === seccionActual.id ? "activo" : ""}" data-seccion="${s.id}">${s.etiqueta}</a>`,
  ).join("");
  nav.querySelectorAll<HTMLElement>("[data-seccion]").forEach((b) => {
    const ir = () => {
      if (b.dataset.seccion) navegarA(b.dataset.seccion);
    };
    b.addEventListener("click", ir);
    b.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        ir();
      }
    });
  });
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

/** El rastro completo "grupo › sección › sub-vista" al lado de "← Volver".
 *
 * Antes esta linea mostraba SOLO el grupo ("Candidatos para cargue"), asi que
 * desde una vista de tercer nivel no se veia por donde se habia entrado ni se
 * podia subir un escalon sin buscar la sección en el riel. "Volver" deshace el
 * ultimo salto; las migajas dicen DONDE estás -- son cosas distintas y por eso
 * conviven (pedido del usuario, 2026-09-08).
 *
 * El grupo no es navegable a proposito: es una etiqueta de agrupación del
 * riel, no una pantalla. La sección sí, y solo cuando lleva a otro sitio.
 */
function pintarMigajas(): void {
  const contenedor = document.getElementById("miga-ruta");
  if (!contenedor) return;
  const esc = (t: string) => t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
  const separador = `<span class="miga__sep" aria-hidden="true">›</span>`;

  const partes = [`<span class="miga__grupo">${esc(seccionActual.grupo)}</span>`];
  // Con una sola sub-vista, sección y título son lo mismo: repetirlo seria
  // ruido ("Consultar INVIMA › Consultar INVIMA").
  if (seccionActual.sub.length > 1) {
    const enLaPrimera = subActual.id === seccionActual.sub[0].id;
    partes.push(
      enLaPrimera
        ? `<span class="miga__actual">${esc(seccionActual.etiqueta)}</span>`
        : `<button type="button" class="miga__enlace" data-ir-seccion="${esc(seccionActual.id)}">${esc(seccionActual.etiqueta)}</button>`,
    );
  }
  contenedor.innerHTML = partes.join(separador);
}

function render(): void {
  const botonVolver = document.getElementById("boton-volver");
  // Se esconde en vez de deshabilitarse: un boton apagado en la topbar de
  // arranque solo agrega ruido, no informa de nada.
  if (botonVolver) botonVolver.classList.toggle("oculto", historial.length === 0);
  pintarMigajas();
  document.getElementById("miga-titulo")!.textContent = seccionActual.sub.length > 1 ? subActual.etiqueta : seccionActual.etiqueta;
  pintarRail();
  pintarSubnav();
  const anterior = document.getElementById("vista");
  if (!anterior) return;
  // Cada render ESTRENA el nodo de la vista en vez de reusarlo. `montar()` es
  // async y `render()` no lo espera: el montar ANTERIOR puede estar detenido
  // en un `await` (la primera pagina de su tabla, un /resumen) y, al resolver,
  // sigue escribiendo en el contenedor que recibio por parametro. Si ese
  // contenedor fuera el mismo nodo de siempre, esa escritura tardia aterriza
  // DEBAJO de la vista nueva, ya montada.
  //
  // Bug real (2026-09-09): cambiando rapido de "Priorizar lo que requiere
  // accion" a "Trazabilidad de calidad", la tabla de Priorizar (55.570 filas,
  // con su columna PRIORIDAD y su selector de niveles) aparecia colgando bajo
  // el eslabon H6 de la cadena. Se veia como si la vista mezclara dos
  // pantallas; en realidad era la anterior llegando tarde.
  //
  // Con un nodo nuevo, lo que llega tarde cae en el nodo VIEJO, ya
  // desconectado del documento: invisible, y recolectado cuando la vista que
  // lo capturo deja de referenciarlo. Se resuelve en UN sitio -- aca --, y no
  // obliga a que cada vista cancele sus propios fetch ni a cambiar la firma
  // `montar(contenedor)` que implementan todas.
  const vista = document.createElement("main");
  vista.className = anterior.className;
  vista.id = "vista";
  anterior.replaceWith(vista);
  void subActual.montar(vista);
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
    if (!exito) return;
    // Vaciar la cache ANTES de repintar, si no la vista se redibuja con las
    // paginas del snapshot viejo. `ClavePagina.snapshot` sale del sondeo de
    // /salud, que corre cada 60 s: justo despues de un refresco manual esa
    // marca todavia es la anterior, asi que la clave calzaria y se serviria
    // dato viejo -- sin pasar siquiera por "Cargando…", porque un acierto de
    // cache se pinta directo. Quedaria el encabezado con las cifras nuevas y
    // la tabla con las viejas, que es el mismo "dos vistas dicen cosas
    // distintas del mismo dato" que ya costo una sesion entera aca.
    invalidarTodo();
    render();
  });
}

document.getElementById("boton-volver")?.addEventListener("click", volver);

// Delegado: `pintarMigajas` rehace su innerHTML en cada render, asi que un
// listener por boton se perderia en el primer salto.
document.getElementById("miga-ruta")?.addEventListener("click", (evento) => {
  const enlace = (evento.target as HTMLElement).closest<HTMLElement>("[data-ir-seccion]");
  if (enlace?.dataset.irSeccion) navegarA(enlace.dataset.irSeccion);
});

// Alt+← es el atajo que ya usa el navegador para "atras"; aqui la app no
// toca el historial del navegador (es una sola pagina), asi que se replica
// para que el gesto de siempre funcione igual.
window.addEventListener("keydown", (e) => {
  if (e.altKey && e.key === "ArrowLeft") {
    e.preventDefault();
    volver();
  }
});

// ---- Arranque con sesion (2026-09-14): nada se monta sin login ----------
//
// La app se sirve a otras areas por la red y exige el usuario de GemaNet
// (ver backend/app/auth y src/sesion.ts). Montar el rail, el sondeo de
// /salud y la primera vista antes de tener sesion solo produciria 401 en
// cadena; por eso el arranque de siempre (salud + refresco + render) queda
// dentro de `iniciarApp` y corre una sola vez, cuando ya hay quien.

let appIniciada = false;

function iniciarApp(usuario: UsuarioSesion): void {
  const contenedorUsuario = document.getElementById("usuario-sesion");
  // Recargar al salir: limpia de un golpe toda memoria de la sesion (caches
  // de tablas, historial, sondeos) en vez de desmontar vista por vista.
  if (contenedorUsuario) pintarUsuario(contenedorUsuario, usuario, () => window.location.reload());
  // "Actualizar ahora" y Administracion son solo para admins (pedido del
  // usuario, 2026-09-14). El backend lo exige tambien (exigir_admin).
  document.getElementById("boton-actualizar-ahora")?.classList.toggle("oculto", !usuario.admin);
  if (usuario.admin && !SECCIONES.includes(SECCION_ADMIN)) SECCIONES.push(SECCION_ADMIN);
  if (appIniciada) {
    render();
    return;
  }
  appIniciada = true;
  inicializarSalud();
  inicializarRefrescoManual();
  render();
}

function pedirIngreso(mensaje = ""): void {
  const pantalla = document.getElementById("pantalla-ingreso");
  const shell = document.querySelector<HTMLElement>(".app-shell");
  if (!pantalla || !shell) return;
  mostrarIngreso(pantalla, shell, iniciarApp, mensaje);
}

// Cualquier 401 posterior (sesion vencida, modulo retirado) vuelve al ingreso.
window.addEventListener("gemanet:sesion-expirada", () => pedirIngreso("La sesión terminó. Vuelva a ingresar."));

void sesionActual().then(
  (usuario) => (usuario ? iniciarApp(usuario) : pedirIngreso()),
  () => pedirIngreso("No se pudo consultar la sesión. Revise que la API esté arriba."),
);
