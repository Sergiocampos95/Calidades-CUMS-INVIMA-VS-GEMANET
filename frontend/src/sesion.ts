/**
 * Pantalla de ingreso y estado de sesion. Calca el ingreso del dashboard de
 * Auditoria de Calidades (logo, "Ingrese con su usuario de GemaNet"): son las
 * mismas credenciales y el mismo modulo, asi que tiene que verse igual.
 *
 * La app entera (rail, topbar, vistas) no se monta hasta que hay sesion:
 * montarla antes dispararia el sondeo de /salud y cada tabla contra un 401.
 */

import { cerrarSesion, iniciarSesion, sesionActual } from "./api";
import type { UsuarioSesion } from "./tipos";

function esc(valor: unknown): string {
  return String(valor).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}

export { sesionActual };

/** Pinta la pantalla de ingreso en `pantalla` y esconde `shell`. Cuando el
 * usuario entra, invierte la visibilidad y llama `alEntrar`. */
export function mostrarIngreso(
  pantalla: HTMLElement,
  shell: HTMLElement,
  alEntrar: (usuario: UsuarioSesion) => void,
  mensajeInicial = "",
): void {
  shell.classList.add("oculto");
  pantalla.classList.remove("oculto");
  pantalla.innerHTML = `<form class="ingreso" id="form-ingreso" autocomplete="on">
    <img class="ingreso__logo" src="logo-pijaos.jpg" alt="Pijaos Salud EPSI">
    <h1 class="ingreso__titulo">Calidades CUMS</h1>
    <p class="ingreso__sub">Ingrese con su usuario de GemaNet</p>
    <input class="ingreso__campo" name="usuario" type="text" placeholder="Usuario" autocomplete="username" autofocus required>
    <input class="ingreso__campo" name="clave" type="password" placeholder="Clave" autocomplete="current-password" required>
    <p class="ingreso__error${mensajeInicial ? "" : " oculto"}" id="ingreso-error">${esc(mensajeInicial)}</p>
    <button class="btn btn--primario ingreso__boton" type="submit">Ingresar</button>
  </form>`;
  const form = pantalla.querySelector<HTMLFormElement>("#form-ingreso")!;
  const error = pantalla.querySelector<HTMLElement>("#ingreso-error")!;
  const boton = form.querySelector<HTMLButtonElement>("button")!;
  form.addEventListener("submit", (evento) => {
    evento.preventDefault();
    const datos = new FormData(form);
    boton.disabled = true;
    error.classList.add("oculto");
    iniciarSesion(String(datos.get("usuario") ?? ""), String(datos.get("clave") ?? ""))
      .then((usuario) => {
        pantalla.classList.add("oculto");
        pantalla.innerHTML = "";
        shell.classList.remove("oculto");
        alEntrar(usuario);
      })
      .catch((e) => {
        error.textContent = e instanceof Error ? e.message : String(e);
        error.classList.remove("oculto");
        boton.disabled = false;
      });
  });
}

/** Nombre y boton "Salir" en la topbar. */
export function pintarUsuario(contenedor: HTMLElement, usuario: UsuarioSesion, alSalir: () => void): void {
  contenedor.innerHTML = `<span class="usuario__nombre" title="${esc(usuario.usuario)}">${esc(usuario.nombre || usuario.usuario)}</span>
    <button type="button" class="btn btn--suave" id="boton-salir" title="Cerrar la sesión">Salir</button>`;
  contenedor.querySelector("#boton-salir")?.addEventListener("click", () => {
    void cerrarSesion().finally(alSalir);
  });
}
