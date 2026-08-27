import {
  ErrorAPI,
  obtenerAdvertenciasMalla,
  obtenerCargueFinal,
  obtenerEstructuraCargue,
  obtenerResumenCargue,
} from "../api";
import { renderTarjetas } from "../tarjetas";
import { TablaFiltrable } from "../tabla";

function avisoSinMalla(mensaje: string): string {
  return `<div class="placeholder"><strong>Sin Estructura Cargue Medicamentos</strong><span>${mensaje}</span></div>`;
}

export async function montarCargueEstructura(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = `<p class="vista__intro">TODOS los candidatos de la corrida (listos y pendientes), con el campo puntual que falta y cómo verificarlo.</p>`;

  const tarjetas = document.createElement("div");
  contenedor.appendChild(tarjetas);
  let listo = true;
  try {
    const resumen = await obtenerResumenCargue();
    renderTarjetas(
      tarjetas,
      [
        { clave: "listos", etiqueta: "Listos para cargue", ayuda: "Marca y unidad resueltas, POS y Modelo de Servicio confirmados por expediente." },
        { clave: "pendientes", etiqueta: "Pendientes de clasificación manual" },
      ],
      resumen,
    );
  } catch (error) {
    if (error instanceof ErrorAPI && error.status === 503) {
      contenedor.innerHTML += avisoSinMalla(error.message);
      return;
    }
    tarjetas.innerHTML = `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
    listo = false;
  }
  if (!listo) return;

  const advertenciasEl = document.createElement("div");
  contenedor.appendChild(advertenciasEl);
  try {
    const advertencias = await obtenerAdvertenciasMalla();
    if (advertencias.length) {
      advertenciasEl.className = "panel";
      advertenciasEl.innerHTML = `<div class="panel__cab"><div class="panel__titulo">⚠ ${advertencias.length} campo(s) con inconsistencias en la malla de referencia</div></div><div class="panel__cuerpo">${advertencias
        .map((a) => `<p style="font-size:0.82rem;margin:4px 0"><strong>${a.campo}</strong>: ${a.advertencia}</p>`)
        .join("")}</div>`;
    }
  } catch {
    /* no bloquea el resto de la vista */
  }

  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: ["CODIGO_INTERNO", "DESCRIPCION", "EXPEDIENTE", "ESTADO", "CAMPOS_CON_ERROR", "PORCENTAJE_COMPLETITUD", "COMO_VERIFICAR"],
    cargarPagina: (p) => obtenerEstructuraCargue(p),
  });
}

export async function montarCargueExcel(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = `<p class="vista__intro">Solo lo listo para subir: marca y unidad resueltas contra catálogo, POS y Modelo de Servicio confirmados. Ningún campo adivinado.</p>`;

  try {
    const resumen = await obtenerResumenCargue();
    const listos = resumen.listos ?? 0;
    if (listos === 0) {
      contenedor.innerHTML += `<div class="banner banner--desactualizado" style="margin:0 0 16px">🟡 0 filas listas todavía. No es un error — revisá "Auditoría de estructura" para ver qué falta.</div>`;
      return;
    }
  } catch (error) {
    if (error instanceof ErrorAPI && error.status === 503) {
      contenedor.innerHTML += avisoSinMalla(error.message);
      return;
    }
    contenedor.innerHTML += `<p class="aviso aviso--error">${error instanceof Error ? error.message : String(error)}</p>`;
    return;
  }

  const seccionTabla = document.createElement("div");
  contenedor.appendChild(seccionTabla);
  new TablaFiltrable(seccionTabla, {
    columnas: ["CODIGO_INTERNO", "DESCRIPCION", "POS", "FORMA_FARMACEUTICA", "CLASIFICADO", "CODIGO_NIVEL_SERVICIO"],
    cargarPagina: (p) => obtenerCargueFinal(p),
  });
}
