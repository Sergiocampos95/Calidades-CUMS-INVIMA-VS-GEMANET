import type { PaginaTabla } from "./tipos";

/**
 * Store a nivel de MODULO (no de instancia) con las paginas de tabla ya
 * traidas del backend y con el estado de navegacion de cada tabla (pagina,
 * filtros, busqueda, orden, seccion).
 *
 * Por que a nivel de modulo y no adentro de TablaFiltrable: la app corre
 * sobre una sola vista -- `render()` en main.ts llama a
 * `subActual.montar(vista)` y cada vista hace `contenedor.innerHTML = ...`,
 * asi que CADA navegacion destruye la instancia de TablaFiltrable (ver la
 * seccion "Estructura: NO hay que cambiarla" en
 * .ai/planes/tablas-por-seccion-y-exportacion.md). Un estado guardado en
 * `this` de esa clase no sobrevive a salir de la vista y volver. Mismo
 * precedente ya usado en el codebase: `_codigoPendiente` en
 * vistas/consulta_detalle.ts.
 *
 * Este modulo NO llama a la API ni conoce a TablaFiltrable -- eso lo conecta
 * el paso siguiente del plan. Aca solo vive el almacen y su tipado.
 */

/** Cuantas paginas se guardan como maximo antes de empezar a descartar las
 * mas viejas (LRU). De donde sale el numero: una pagina de 1.000 filas ya
 * recortada por seccion pesa ~0,6 MB, y el peor caso medido (sin seccion,
 * 38 columnas) son ~2,0 MB (ver "Estructura" y el paso 2 en el plan de
 * tablas-por-seccion-y-exportacion.md). Con el tope en 30, el peor caso es
 * 30 x 2,0 MB = 60 MB en memoria del navegador -- bastante por debajo de lo
 * que ya tumbaba el equipo con el checkbox "Cargar la tabla completa"
 * (decenas de miles de filas SIN recortar en una sola tabla), y mas que
 * suficiente para el patron que pidio el usuario ("salgo y vuelvo a
 * entrar"): un puñado de tablas visitadas en la misma sesion, no todas las
 * paginas de todas las secciones a la vez. Sin tope, cachear paginas de
 * cada tabla/seccion/filtro/pagina visitada en una sesion larga terminaria
 * comiendose la RAM sin que nadie lo note -- el mismo problema que motivo
 * esta cache, pero corrido al store en vez del DOM.
 */
const LIMITE_PAGINAS_CACHEADAS = 30;

/** Identifica de forma unica una peticion de pagina. Dos consultas que
 * difieran en CUALQUIER campo son datos distintos y no pueden compartir
 * entrada (requisito del paso 6 del plan) -- por eso todos los campos que
 * afectan que filas devuelve el backend estan aca, no solo `idTabla`. */
export interface ClavePagina {
  /** Que tabla/vista pide la pagina, ej. "candidatos", "auditoria",
   * "calidad:Concentracion", "cadena:H3". Cada llamador (vista) decide su
   * propio id -- este modulo no mantiene un catalogo de ids validos. */
  idTabla: string;
  /** Seccion de la tabla, cuando aplica (ej. clave de columnas_de_seccion
   * en auditoria de calidad: "campo:CONCENTRACION"). Sin seccion en tablas
   * que no la tienen (candidatos, universo, etc). */
  seccion?: string;
  busqueda: string;
  ordenarPor?: string;
  ordenDescendente: boolean;
  /** JSON de {columna: [valores]} del filtro estilo Excel -- mismo formato
   * que `filtros_json` en api.ts, ya serializado para que la comparacion de
   * clave sea una comparacion de texto simple. */
  filtrosJson?: string;
  /** Que pagina (en filas, no en numero de pagina) se pidio. */
  offset: number;
  /** Marca del snapshot vigente en el momento de la consulta --
   * `ultima_actualizacion_utc` de GET /salud (ver EstadoSalud en tipos.ts).
   * `null` cuando todavia no hay snapshot (worker sin correr aun).
   *
   * ESTO ES LO QUE INVALIDA LA CACHE CUANDO EL WORKER REFRESCA (requisito
   * "no negociable" del paso 6): al cambiar la marca, la clave de texto que
   * arma `claveComoTexto` cambia entera, asi que una consulta contra el
   * snapshot nuevo JAMAS puede devolver una entrada guardada con el
   * snapshot viejo -- no hace falta un mecanismo aparte de "borrar todo al
   * refrescar" (la misma nota del plan lo dice: "usarlo como parte de la
   * clave evita inventar un mecanismo nuevo"). Es el mismo principio que
   * `_CACHE_TABLAS`/`_CACHE_CALIDADES` en el backend, adaptado a que aca
   * conviene una unica entrada por combinacion en vez de una tupla
   * (marca, valor) por tabla: las entradas de un snapshot viejo quedan
   * simplemente inalcanzables y las va desalojando el LRU con el uso
   * normal. Servir un snapshot viejo sin avisar ya costo una sesion entera
   * de depuracion en este proyecto -- ver CLAUDE.md. */
  snapshot: string | null;
}

/** Recuerda EN QUE estaba parada una tabla (pagina, filtros, busqueda,
 * orden, seccion) para repintar igual al volver a la vista, sin que el
 * usuario tenga que rehacer sus filtros. Una entrada por `idTabla`: es
 * "donde estaba el usuario", no un cache de datos, asi que no necesita LRU
 * (como mucho una entrada por tabla distinta que exista en la app). */
export interface EstadoTabla {
  seccion?: string;
  busqueda: string;
  ordenarPor?: string;
  ordenDescendente: boolean;
  filtrosJson?: string;
  offset: number;
}

// Separador que no puede aparecer en un valor real de estos campos (texto de
// busqueda, JSON de filtros, nombre de columna): un caracter de control, no
// un simple "-" o ":" que si podria colarse en filtrosJson o en la marca de
// snapshot. Nunca delegar en JSON.stringify(clave) para esto -- el orden de
// llaves de un objeto literal puede variar entre dos llamadores que arman la
// misma clave con distinto orden de propiedades, y eso partiria en dos la
// cache de una consulta identica.
const SEPARADOR_CLAVE = "";

function claveComoTexto(clave: ClavePagina): string {
  return [
    clave.idTabla,
    clave.seccion ?? "",
    clave.busqueda,
    clave.ordenarPor ?? "",
    clave.ordenDescendente ? "1" : "0",
    clave.filtrosJson ?? "",
    String(clave.offset),
    clave.snapshot ?? "",
  ].join(SEPARADOR_CLAVE);
}

// Map, no un objeto plano: preserva el orden de insercion, que es lo que
// hace posible el LRU de abajo con solo borrar-y-reinsertar (sin llevar un
// contador de "ultimo uso" aparte).
const _paginas = new Map<string, PaginaTabla>();
const _estados = new Map<string, EstadoTabla>();

/** La pagina ya cacheada para esta clave exacta, o `undefined` si hay que
 * pedirla al backend. Un acierto la marca como la mas recientemente usada
 * (la manda al final del Map), para que el LRU descarte primero lo que hace
 * mas tiempo que nadie mira. */
export function leerPagina(clave: ClavePagina): PaginaTabla | undefined {
  const llave = claveComoTexto(clave);
  const pagina = _paginas.get(llave);
  if (pagina === undefined) return undefined;
  _paginas.delete(llave);
  _paginas.set(llave, pagina);
  return pagina;
}

export function guardarPagina(clave: ClavePagina, pagina: PaginaTabla): void {
  const llave = claveComoTexto(clave);
  _paginas.delete(llave); // si ya existia, que el set de abajo la deje al final (mas reciente)
  _paginas.set(llave, pagina);
  while (_paginas.size > LIMITE_PAGINAS_CACHEADAS) {
    // Map.keys() itera en orden de insercion -- la primera clave es la
    // menos recientemente usada, justo la que hay que desalojar.
    const llaveMasVieja = _paginas.keys().next().value;
    if (llaveMasVieja === undefined) break;
    _paginas.delete(llaveMasVieja);
  }
}

export function leerEstado(idTabla: string): EstadoTabla | undefined {
  return _estados.get(idTabla);
}

export function guardarEstado(idTabla: string, estado: EstadoTabla): void {
  _estados.set(idTabla, estado);
}

/** Vacia todo el store -- paginas y estados de navegacion. La invalidacion
 * por snapshot ya ocurre sola via `ClavePagina.snapshot` (ver comentario en
 * ese campo); esta funcion es para los casos que SI necesitan un reinicio
 * duro y explicito (ej. una futura accion "olvidar cache" en la UI, o
 * pruebas), no un paso obligatorio del flujo de refresco. */
export function invalidarTodo(): void {
  _paginas.clear();
  _estados.clear();
}

// El snapshot vigente, para que `ClavePagina.snapshot` no obligue a cada
// tabla a preguntarle a /salud por su cuenta. Lo escribe el sondeo de salud
// que main.ts ya hace para el anillo de "hace N min"; las tablas solo leen.
//
// Vale `null` mientras ese sondeo no haya respondido todavia. Con null la
// clave sigue siendo consistente (una tabla cargada antes de saber el
// snapshot no reusa entradas de una cargada despues), que es justo el
// comportamiento seguro: ante la duda se vuelve a pedir, nunca se sirve algo
// que podria ser viejo.
let _snapshot: string | null = null;

export function fijarSnapshot(valor: string | null): void {
  _snapshot = valor;
}

export function snapshotVigente(): string | null {
  return _snapshot;
}
