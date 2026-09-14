/**
 * Administracion > Permisos: quien puede entrar a esta app. Calca
 * /admin/permisos del dashboard de Auditoria de Calidades, acotado al modulo
 * CUMS (pedido del usuario, 2026-09-14: "as admin, where do I manage the
 * permission of the users"). Los administradores del ERP entran sin modulo y
 * se muestran marcados, sin casilla.
 *
 * No usa TablaFiltrable a proposito: no es una tabla de medicamentos
 * paginada desde la API sino un formulario de ~250 filas con una casilla por
 * usuario, que cabe entero y se filtra en el navegador. El unico "componente
 * de tabla" de la app sigue siendo TablaFiltrable para los datos.
 */

import { cambiarModuloUsuario, obtenerUsuariosPermisos } from "../api";
import type { UsuarioPermiso } from "../tipos";

function esc(valor: unknown): string {
  return String(valor).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}

function fila(u: UsuarioPermiso): string {
  const casilla = u.admin
    ? `<span class="pildora pildora--ok">ADMIN · ve todo</span>`
    : `<label class="permiso"><input type="checkbox" data-usuario="${esc(u.usuario)}" ${u.tiene_modulo ? "checked" : ""}> <span>${u.tiene_modulo ? "Tiene acceso" : "Sin acceso"}</span></label>`;
  const asignado = u.asignado_por ? `${esc(u.asignado_por)} · ${esc(u.fecha_asignacion ?? "")}` : `<span class="celda-muda">—</span>`;
  return `<tr data-fila="${esc(u.usuario)}" data-texto="${esc((u.usuario + " " + u.nombre).toLowerCase())}">
    <td class="celda-mono">${esc(u.usuario)}</td>
    <td>${esc(u.nombre)}</td>
    <td>${casilla}</td>
    <td>${asignado}</td>
  </tr>`;
}

export async function montarAdminPermisos(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = `<p class="vista__intro">Quién puede entrar a Calidades CUMS. Los administradores de GemaNet entran siempre; a los demás usuarios activos se les da o quita el acceso aquí y aplica en menos de 5 minutos, sin que tengan que volver a ingresar. Es el mismo permiso que se ve en Auditoría de Calidades › Permisos, módulo <strong>CUMS</strong>.</p>`;
  const panel = document.createElement("div");
  panel.className = "panel";
  contenedor.appendChild(panel);
  panel.innerHTML = `<div class="panel__cab"><div class="panel__titulo">Usuarios activos de GemaNet</div></div><div class="panel__cuerpo"><p class="vista__intro">Cargando…</p></div></div>`;
  const cuerpo = panel.querySelector<HTMLElement>(".panel__cuerpo")!;

  let usuarios: UsuarioPermiso[];
  try {
    usuarios = await obtenerUsuariosPermisos();
  } catch (error) {
    cuerpo.innerHTML = `<p class="aviso aviso--error">${esc(error instanceof Error ? error.message : String(error))}</p>`;
    return;
  }

  const conAcceso = usuarios.filter((u) => u.tiene_modulo && !u.admin).length;
  const admins = usuarios.filter((u) => u.admin).length;
  cuerpo.innerHTML = `
    <div class="permisos__barra">
      <input type="search" class="permisos__buscar" id="permisos-buscar" placeholder="Buscar por usuario o nombre…" autocomplete="off">
      <span class="permisos__resumen">${usuarios.length} usuarios · ${admins} administradores · <strong id="permisos-con-acceso">${conAcceso}</strong> con acceso asignado</span>
    </div>
    <p class="aviso aviso--error oculto" id="permisos-error"></p>
    <div class="tabla-filtrable__envoltorio"><table>
      <thead><tr><th>Usuario</th><th>Nombre</th><th>Acceso a CUMS</th><th>Asignado por</th></tr></thead>
      <tbody>${usuarios.map(fila).join("")}</tbody>
    </table></div>`;

  const buscar = cuerpo.querySelector<HTMLInputElement>("#permisos-buscar")!;
  buscar.addEventListener("input", () => {
    const q = buscar.value.trim().toLowerCase();
    cuerpo.querySelectorAll<HTMLTableRowElement>("tbody tr").forEach((tr) => {
      tr.classList.toggle("oculto", q !== "" && !(tr.dataset.texto ?? "").includes(q));
    });
  });

  // Delegado en el cuerpo: una casilla por usuario, guardado inmediato.
  const error = cuerpo.querySelector<HTMLElement>("#permisos-error")!;
  cuerpo.addEventListener("change", (evento) => {
    const casilla = evento.target as HTMLInputElement;
    if (casilla.type !== "checkbox" || !casilla.dataset.usuario) return;
    const usuario = casilla.dataset.usuario;
    const deseado = casilla.checked;
    casilla.disabled = true;
    error.classList.add("oculto");
    cambiarModuloUsuario(usuario, deseado)
      .then((actualizado) => {
        casilla.checked = actualizado.tiene_modulo;
        const tr = cuerpo.querySelector<HTMLTableRowElement>(`tr[data-fila="${CSS.escape(usuario)}"]`);
        if (tr) tr.outerHTML = fila(actualizado);
        const n = cuerpo.querySelectorAll<HTMLInputElement>("tbody input[type=checkbox]:checked").length;
        const contador = cuerpo.querySelector("#permisos-con-acceso");
        if (contador) contador.textContent = String(n);
      })
      .catch((e) => {
        casilla.checked = !deseado; // se revierte: lo que se ve es lo que hay en la base
        error.textContent = e instanceof Error ? e.message : String(e);
        error.classList.remove("oculto");
      })
      .finally(() => {
        casilla.disabled = false;
      });
  });
}
