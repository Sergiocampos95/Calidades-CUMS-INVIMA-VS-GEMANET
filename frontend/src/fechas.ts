/** Formato de fechas para PANTALLA, nunca para el dato.
 *
 * Por que existe (pedido del usuario, 2026-09-04): INVIMA publica en
 * MM/DD/YYYY y Gemma Net en YYYY-MM-DD, asi que "04/03/2017" y "2017-03-04"
 * son la MISMA fecha (4 de marzo) y parecen distintas. El backend ya las
 * normaliza las dos a ISO antes de mandarlas, pero un lector que conoce los
 * dos origenes sigue dudando de cual es el mes y cual el dia. Escribir el mes
 * con letras quita la duda de raiz: "4 de marzo de 2017" no se puede leer de
 * dos maneras.
 *
 * Solo transforma la REPRESENTACION. El dato que viaja en la API y el que sale
 * en las descargas se arma en el backend desde el DataFrame, y no pasa por
 * aqui: un export sigue llevando la fecha como fecha, no como texto -- que es
 * justamente la condicion que puso el usuario.
 */

const MESES_ES = [
  "enero",
  "febrero",
  "marzo",
  "abril",
  "mayo",
  "junio",
  "julio",
  "agosto",
  "septiembre",
  "octubre",
  "noviembre",
  "diciembre",
];

// Acepta ISO con o sin hora, que es como llegan hoy los dos lados: Gemma Net
// manda "2006-11-10" e INVIMA "2006-11-10 00:00:00" (el backend ya tradujo su
// MM/DD/YYYY original). Se ancla al inicio y exige separador despues del dia
// para no aceptar por accidente algo que solo empiece pareciendose.
const ISO_FECHA = /^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$/;

/** "2006-11-10" -> "10 de noviembre de 2006".
 *
 * Devuelve `null` si el valor NO es una fecha ISO reconocible, para que quien
 * llama muestre el valor crudo tal cual. Nunca adivina: si mañana el backend
 * cambiara el formato, se veria el dato original en pantalla en vez de una
 * fecha inventada o un "Invalid Date". */
export function fechaLegible(valor: unknown): string | null {
  const texto = String(valor ?? "").trim();
  if (!texto) return null;
  const partes = ISO_FECHA.exec(texto);
  if (!partes) return null;
  const [, anio, mes, dia] = partes;
  const indiceMes = Number(mes) - 1;
  if (indiceMes < 0 || indiceMes > 11) return null;
  // Number() en el dia quita el cero a la izquierda ("04" -> 4): en español
  // "04 de marzo" se lee raro, "4 de marzo" no.
  return `${Number(dia)} de ${MESES_ES[indiceMes]} de ${anio}`;
}
