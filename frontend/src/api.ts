import type {
  AdvertenciaMalla,
  CalidadResumen,
  SeccionCalidad,
  DimensionesCalidad,
  EslabonResumen,
  EstadoSalud,
  HallazgoNaturaleza,
  PaginaTabla,
  ProgresoRefresco,
  Resumen,
  ResumenCargue,
  ResumenMetodos,
  UsuarioPermiso,
  UsuarioSesion,
} from "./tipos";

// En produccion la API sirve tambien el frontend compilado (mismo origen,
// puerto 8870), asi que la base es RELATIVA. En desarrollo Vite corre en
// 5173 y `.env.development` apunta al uvicorn local (VITE_API_BASE_URL).
const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

// Todas las llamadas llevan la cookie de sesion y este encabezado: el backend
// exige `X-Requested-With` en cada POST como segunda defensa contra CSRF
// (un formulario de otro sitio no puede ponerlo). Ver backend/app/auth.
export const ENCABEZADOS_FETCH: Record<string, string> = { "X-Requested-With": "fetch" };

export function urlAbsoluta(ruta: string): URL {
  return new URL(`${BASE_URL}${ruta}`, window.location.origin);
}

/** Un 401 en cualquier llamada significa "no hay sesion": se avisa a main.ts
 * (que vuelve a la pantalla de ingreso) y se propaga el error para que la
 * vista no pinte datos vacios como si fueran reales. */
function avisarSesionExpirada(status: number): void {
  if (status === 401) window.dispatchEvent(new CustomEvent("gemanet:sesion-expirada"));
}

/** Error tipado con el mensaje que ya arma el backend (HTTPException.detail)
 * -- nunca un "algo salio mal" generico cuando el backend ya explico que
 * paso (ej. "el worker todavia no genero ningun snapshot"). */
export class ErrorAPI extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ErrorAPI";
  }
}

async function obtenerJSON<T>(
  ruta: string,
  parametros?: Record<string, string | number | boolean | undefined>,
): Promise<T> {
  const url = urlAbsoluta(ruta);
  for (const [clave, valor] of Object.entries(parametros ?? {})) {
    if (valor !== undefined && valor !== "") {
      url.searchParams.set(clave, String(valor));
    }
  }
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000); // 30 segundo timeout
    const respuesta = await fetch(url, { signal: controller.signal, credentials: "include", headers: ENCABEZADOS_FETCH });
    clearTimeout(timeout);
    if (!respuesta.ok) {
      avisarSesionExpirada(respuesta.status);
      const cuerpo = await respuesta.json().catch(() => null);
      const detalle = cuerpo?.detail ?? `Error ${respuesta.status} consultando ${ruta}`;
      throw new ErrorAPI(detalle, respuesta.status);
    }
    return (await respuesta.json()) as T;
  } catch (error) {
    if (error instanceof ErrorAPI) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ErrorAPI(`Timeout: la consulta tardó más de 30 segundos`, 408);
    }
    throw new ErrorAPI(`Failed to fetch: ${error instanceof Error ? error.message : String(error)}`, 0);
  }
}

export function obtenerSalud(): Promise<EstadoSalud> {
  return obtenerJSON<EstadoSalud>("/salud");
}

/** POST /refrescar -- pide al worker que adelante su corrida periodica en
 * vez de esperar hasta 50 min. No corre nada pesado en el backend: solo
 * escribe una senal que el worker revisa cada pocos segundos (ver
 * backend/app/routers/refrescar.py). Vuelve de inmediato (202); el avance
 * real se sigue con obtenerProgresoRefresco(). */
/** De donde lee INVIMA el refresco. Desde el 2026-09-14 solo "archivos"
 * (los Excel de la carpeta del servidor, INVIMA_LISTADOS_DIR) esta
 * habilitada: el backend responde 422 a "api" (ver FUENTES_HABILITADAS en
 * src/gemma_cum_loader/ingesta/fuente_invima.py). El tipo conserva "api"
 * para cuando se reactive. */
export type FuenteRefresco = "api" | "archivos";

export async function pedirRefresco(fuente: FuenteRefresco = "archivos"): Promise<void> {
  const respuesta = await fetch(urlAbsoluta(`/refrescar?fuente=${fuente}`), {
    method: "POST",
    credentials: "include",
    headers: ENCABEZADOS_FETCH,
  });
  if (!respuesta.ok) {
    avisarSesionExpirada(respuesta.status);
    const cuerpo = await respuesta.json().catch(() => null);
    throw new ErrorAPI(cuerpo?.detail ?? `Error ${respuesta.status} pidiendo el refresco`, respuesta.status);
  }
}

export function obtenerProgresoRefresco(): Promise<ProgresoRefresco> {
  return obtenerJSON<ProgresoRefresco>("/refrescar/progreso");
}

export interface ParametrosTabla {
  q?: string;
  limite?: number;
  offset?: number;
  todo?: boolean;
  /** Filtro estilo Excel (pedido del usuario, 2026-08-28): ordenar por
   * cualquier columna + filtrar por un subconjunto de sus valores. */
  ordenar_por?: string;
  orden_descendente?: boolean;
  /** JSON de {columna: [valores]} -- varias columnas filtradas a la vez,
   * igual que se usaria en una tabla real. */
  filtros_json?: string;
  [clave: string]: string | number | boolean | undefined;
}

export interface ValorColumna {
  valor: string;
  conteo: number;
}

/** Los valores distintos de una columna (con conteo), para el checkbox-list
 * del filtro estilo Excel -- `ruta` es la ruta COMPLETA del endpoint
 * /valores de esa tabla (cada router tiene el suyo: /candidatos/valores,
 * /auditoria/valores, /auditoria/cadena/{nombre}/valores...). Lista vacia
 * si el backend decide que la columna tiene demasiados valores distintos
 * para este filtro (ver LIMITE_VALORES_DISTINTOS en paginacion.py) -- la
 * busqueda libre de la tabla sigue siendo la herramienta correcta ahi. */
export function obtenerValoresColumna(
  ruta: string,
  columna: string,
  seccion?: string,
): Promise<ValorColumna[]> {
  // `seccion` acota los valores ofrecidos como filtro a la seccion abierta:
  // ofrecer un valor que no existe en lo que se ve deja la tabla vacia sin
  // explicar por que.
  return obtenerJSON<ValorColumna[]>(ruta, { columna, seccion });
}

export interface ParametrosCandidatos extends ParametrosTabla {
  accion?: string;
}

export function obtenerCandidatos(parametros: ParametrosCandidatos = {}): Promise<PaginaTabla> {
  return obtenerJSON<PaginaTabla>("/candidatos", parametros);
}

export function obtenerResumenCandidatos(): Promise<Resumen> {
  return obtenerJSON<Resumen>("/candidatos/resumen");
}

export function obtenerResumenMetodos(): Promise<ResumenMetodos> {
  return obtenerJSON<ResumenMetodos>("/candidatos/resumen-metodos");
}

export interface ParametrosAuditoria extends ParametrosTabla {
  estado_coherencia?: string;
  /** Uno o varios niveles de PRIORIDAD_ACCION separados por coma
   * ("1_critico,2_alto"). */
  prioridad?: string;
  /** Que columnas serializar, separadas por coma. Recorta solo lo que viaja:
   * la busqueda y los filtros siguen viendo la tabla entera. */
  columnas?: string;
}

export function obtenerAuditoria(parametros: ParametrosAuditoria = {}): Promise<PaginaTabla> {
  return obtenerJSON<PaginaTabla>("/auditoria", parametros);
}

export function obtenerResumenAuditoria(): Promise<Resumen> {
  return obtenerJSON<Resumen>("/auditoria/resumen");
}

export interface ParametrosUniverso extends ParametrosTabla {
  clasificacion?: string;
}

export function obtenerUniverso(parametros: ParametrosUniverso = {}): Promise<PaginaTabla> {
  return obtenerJSON<PaginaTabla>("/universo", parametros);
}

export function obtenerResumenUniverso(): Promise<Resumen> {
  return obtenerJSON<Resumen>("/universo/resumen");
}

export function obtenerCadena(): Promise<EslabonResumen[]> {
  return obtenerJSON<EslabonResumen[]>("/auditoria/cadena");
}

export function obtenerCalidades(): Promise<CalidadResumen[]> {
  return obtenerJSON<CalidadResumen[]>("/auditoria/calidades");
}

export function obtenerCalidad(nombre: string, parametros: ParametrosTabla = {}): Promise<PaginaTabla> {
  return obtenerJSON<PaginaTabla>(`/auditoria/calidades/${encodeURIComponent(nombre)}`, parametros);
}

export function obtenerSeccionesCalidad(nombre: string): Promise<SeccionCalidad[]> {
  return obtenerJSON<SeccionCalidad[]>(
    `/auditoria/calidades/${encodeURIComponent(nombre)}/secciones`,
  );
}

export function obtenerDimensionesCalidad(): Promise<DimensionesCalidad> {
  return obtenerJSON<DimensionesCalidad>("/auditoria/dimensiones");
}

/** Los medicamentos que caen en una dimension -- "cada cifra se puede abrir,
 * no solo mirar" (pedido del usuario, 2026-09-01). `clave` es una de las de
 * DIMENSIONES_ABRIBLES en backend/app/routers/calidades.py. */
export function obtenerDimension(clave: string, parametros: ParametrosTabla = {}): Promise<PaginaTabla> {
  return obtenerJSON<PaginaTabla>(`/auditoria/dimensiones/${encodeURIComponent(clave)}`, parametros);
}

export function obtenerNaturalezaHallazgos(): Promise<HallazgoNaturaleza[]> {
  return obtenerJSON<HallazgoNaturaleza[]>("/auditoria/naturaleza");
}

export interface ParametrosEslabon extends ParametrosTabla {
  solo_pasa?: boolean;
}

export function obtenerEslabon(nombre: string, parametros: ParametrosEslabon = {}): Promise<PaginaTabla> {
  return obtenerJSON<PaginaTabla>(`/auditoria/cadena/${nombre}`, parametros);
}

export interface ParametrosEstructuraCargue extends ParametrosTabla {
  listo?: boolean;
}

export function obtenerEstructuraCargue(parametros: ParametrosEstructuraCargue = {}): Promise<PaginaTabla> {
  return obtenerJSON<PaginaTabla>("/cargue/estructura", parametros);
}

export function obtenerCargueFinal(parametros: ParametrosTabla = {}): Promise<PaginaTabla> {
  return obtenerJSON<PaginaTabla>("/cargue/final", parametros);
}

export function obtenerResumenCargue(): Promise<ResumenCargue> {
  return obtenerJSON<ResumenCargue>("/cargue/resumen");
}

export function obtenerAdvertenciasMalla(): Promise<AdvertenciaMalla[]> {
  return obtenerJSON<AdvertenciaMalla[]>("/cargue/advertencias");
}

/** URL completa de un endpoint /descargas/* -- son GET simples con
 * Content-Disposition: attachment, asi que un <a href> nativo alcanza
 * (el navegador dispara la descarga solo, sin fetch+blob de por medio). */
export function urlDescarga(ruta: "candidatos" | "auditoria" | "cargue-estructura" | "cargue-final"): string {
  return `${BASE_URL}/descargas/${ruta}`;
}

/** URL para descargar una calidad de auditoria en xlsx/csv/txt.
 *
 * Trae la SECCION COMPLETA, no la pagina que se ve en pantalla: la
 * paginacion es comodidad de la vista y no debe recortar un reporte
 * (decision del usuario, 2026-09-04 -- "exportar la calidad completa de
 * diferencia en descripcion"). Por eso NO lleva `limite`/`offset` ni los
 * filtros de columna. */
export function urlDescargaCalidad(
  nombre: string,
  formato: "xlsx" | "csv" | "txt",
  seccion?: string,
): string {
  const url = urlAbsoluta(`/descargas/calidad/${encodeURIComponent(nombre)}`);
  url.searchParams.set("formato", formato);
  if (seccion) url.searchParams.set("seccion", seccion);
  return url.toString();
}

/** URL para descargar una tabla de la cadena de calidad H1-H6 completa.
 * Igual que `urlDescargaCalidad`: trae el eslabon entero, sin la paginacion
 * ni los filtros de pantalla. */
export function urlDescargaEslabon(nombre: string, formato: "xlsx" | "csv" | "txt"): string {
  const url = urlAbsoluta(`/descargas/cadena/${encodeURIComponent(nombre)}`);
  url.searchParams.set("formato", formato);
  return url.toString();
}

// ---- Sesion (backend/app/auth) --------------------------------------------

/** GET /auth/sesion -- quien esta adentro, o null si no hay sesion. El 401
 * aqui es la respuesta normal antes de ingresar: NO dispara
 * `gemanet:sesion-expirada`. */
export async function sesionActual(): Promise<UsuarioSesion | null> {
  const respuesta = await fetch(urlAbsoluta("/auth/sesion"), { credentials: "include", headers: ENCABEZADOS_FETCH });
  if (respuesta.status === 401) return null;
  if (!respuesta.ok) throw new ErrorAPI(`Error ${respuesta.status} consultando la sesión`, respuesta.status);
  return (await respuesta.json()) as UsuarioSesion;
}

export async function iniciarSesion(usuario: string, clave: string): Promise<UsuarioSesion> {
  const respuesta = await fetch(urlAbsoluta("/auth/login"), {
    method: "POST",
    credentials: "include",
    headers: { ...ENCABEZADOS_FETCH, "Content-Type": "application/json" },
    body: JSON.stringify({ usuario, clave }),
  });
  if (!respuesta.ok) {
    const cuerpo = await respuesta.json().catch(() => null);
    throw new ErrorAPI(cuerpo?.detail ?? `Error ${respuesta.status} al ingresar`, respuesta.status);
  }
  return (await respuesta.json()) as UsuarioSesion;
}

export async function cerrarSesion(): Promise<void> {
  await fetch(urlAbsoluta("/auth/logout"), { method: "POST", credentials: "include", headers: ENCABEZADOS_FETCH });
}

// ---- Administracion > Permisos (solo admin) --------------------------------

export function obtenerUsuariosPermisos(): Promise<UsuarioPermiso[]> {
  return obtenerJSON<UsuarioPermiso[]>("/admin/usuarios");
}

export async function cambiarModuloUsuario(usuario: string, asignado: boolean): Promise<UsuarioPermiso> {
  const respuesta = await fetch(urlAbsoluta(`/admin/usuarios/${encodeURIComponent(usuario)}/modulo`), {
    method: "POST",
    credentials: "include",
    headers: { ...ENCABEZADOS_FETCH, "Content-Type": "application/json" },
    body: JSON.stringify({ asignado }),
  });
  if (!respuesta.ok) {
    avisarSesionExpirada(respuesta.status);
    const cuerpo = await respuesta.json().catch(() => null);
    throw new ErrorAPI(cuerpo?.detail ?? `Error ${respuesta.status} cambiando el permiso`, respuesta.status);
  }
  return (await respuesta.json()) as UsuarioPermiso;
}
