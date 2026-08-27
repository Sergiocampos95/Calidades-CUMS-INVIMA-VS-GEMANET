import type { EstadoSalud, PaginaTabla, Resumen } from "./tipos";

// Configurable via .env (VITE_API_BASE_URL) para cuando el backend viva en
// otro host -- ver frontend/.env.example. Por defecto, el puerto local de
// `uvicorn backend.app.main:app`.
const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://127.0.0.1:8000";

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
  const url = new URL(`${BASE_URL}${ruta}`);
  for (const [clave, valor] of Object.entries(parametros ?? {})) {
    if (valor !== undefined && valor !== "") {
      url.searchParams.set(clave, String(valor));
    }
  }
  const respuesta = await fetch(url);
  if (!respuesta.ok) {
    const cuerpo = await respuesta.json().catch(() => null);
    const detalle = cuerpo?.detail ?? `Error ${respuesta.status} consultando ${ruta}`;
    throw new ErrorAPI(detalle, respuesta.status);
  }
  return (await respuesta.json()) as T;
}

export function obtenerSalud(): Promise<EstadoSalud> {
  return obtenerJSON<EstadoSalud>("/salud");
}

export interface ParametrosTabla {
  q?: string;
  limite?: number;
  offset?: number;
  todo?: boolean;
  [clave: string]: string | number | boolean | undefined;
}

export function obtenerCandidatos(parametros: ParametrosTabla = {}): Promise<PaginaTabla> {
  return obtenerJSON<PaginaTabla>("/candidatos", parametros);
}

export function obtenerResumenCandidatos(): Promise<Resumen> {
  return obtenerJSON<Resumen>("/candidatos/resumen");
}

export interface ParametrosAuditoria extends ParametrosTabla {
  estado_coherencia?: string;
}

export function obtenerAuditoria(parametros: ParametrosAuditoria = {}): Promise<PaginaTabla> {
  return obtenerJSON<PaginaTabla>("/auditoria", parametros);
}

export function obtenerResumenAuditoria(): Promise<Resumen> {
  return obtenerJSON<Resumen>("/auditoria/resumen");
}
