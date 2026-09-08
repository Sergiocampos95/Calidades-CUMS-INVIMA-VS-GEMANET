import { fechaLegible } from "../fechas";
import { etiquetaEstadoListadoInvima, pildoraValidacion } from "../pildoras";

// Los 7 campos que la auditoria compara lado a lado, en el orden en que se
// leen (lo que identifica el medicamento primero, los codigos despues).
// Mismo conjunto que CAMPOS_COMPARADOS_COHERENCIA en el backend; cada uno
// llega con su trio <CAMPO>_GEMANET / _INVIMA / _VALIDACION ya resuelto.
const CAMPOS_COMPARABLES = [
  { columna: "DESCRIPCION", etiqueta: "Descripción" },
  { columna: "PRINCIPIO_ACTIVO", etiqueta: "Principio activo" },
  // La columna se llama CONCENTRACION pero trae la PRESENTACIÓN COMERCIAL
  // ("CAJA POR 100 TABLETAS EN BLISTER"), y por eso se compara contra
  // DESCRIPCION_COMERCIAL de INVIMA (90,3 % de coincidencias contra 6,1 % de
  // su CONCENTRACION real). Se rotula por lo que es: leerlo como
  // "Concentración" hacía parecer que el cruce traía el campo equivocado.
  { columna: "CONCENTRACION", etiqueta: "Presentación comercial" },
  { columna: "FORMA_FARMACEUTICA", etiqueta: "Forma farmacéutica" },
  { columna: "UNIDAD_MEDIDA", etiqueta: "Unidad de medida" },
  { columna: "CODIGO_ATC", etiqueta: "Código ATC" },
  { columna: "MARCA_MEDICAMENTO", etiqueta: "Marca" },
];

interface RespuestaConsultaDetalle {
  invima: Record<string, unknown>[];
  gemma_net: Record<string, unknown>[] | null;
  codigos_consultados: string[];
  total_encontrados: number;
}

interface Diagnostico {
  nivel: "ok" | "advertencia" | "critico" | "informativo";
  titulo: string;
  mensaje: string;
  pasos: string[];
  icono: string;
}

// Codigo a precargar la proxima vez que se monte esta vista -- pedido del
// usuario: el boton "Ver diferencias" de la tabla de calidades debe llevar
// directo a la consulta de ESE medicamento, no a un formulario vacio.
// Variable de modulo (no un parametro de montarConsultarInvima) porque el
// callback de montaje de cada vista tiene una firma fija
// (contenedor: HTMLElement) => void, la misma para las 15 vistas de la app.
let _codigoPendiente: string | null = null;

export function precargarConsultaInvima(codigo: string): void {
  _codigoPendiente = codigo;
}

// Cualquier tabla de la app puede pedir "andá a consultar este codigo en
// INVIMA" disparando "gemma:consultar-invima" (ver tabla.ts -- boton junto
// a CODIGO_INTERNO en TODAS las tablas, y auditoria.ts -- "Ver diferencias")
// sin importar este modulo directamente: un componente generico (tabla.ts)
// no deberia depender de una vista puntual. Este es el UNICO lugar que sabe
// COMO se hace esa navegacion (precargar + pedirle a main.ts que cambie de
// seccion, evento que main.ts ya escucha desde el fix anterior del boton
// "Ver diferencias" -- 2026-09-01).
window.addEventListener("gemma:consultar-invima", (evento) => {
  const codigo = (evento as CustomEvent<{ codigo: string }>).detail?.codigo;
  if (!codigo) return;
  precargarConsultaInvima(codigo);
  window.dispatchEvent(new CustomEvent("gemma:navegar", { detail: { seccion: "invima", sub: "unica" } }));
});

export async function montarConsultarInvima(contenedor: HTMLElement): Promise<void> {
  contenedor.innerHTML = `
    <p class="vista__intro">Escribe códigos (CUM) para consultar en INVIMA y Gemma Net. Múltiples códigos separados por coma: 3521-1, 224715-1</p>
    <div class="consulta-invima__form">
      <input
        type="text"
        id="codigo-input"
        class="consulta-invima__input"
        placeholder="Ej: 3521-1 o 3521-1, 224715-1, 42938-5"
      />
      <button id="btn-consultar" class="btn btn--primario">Consultar</button>
      <button id="btn-en-vivo" class="btn" title="Pregunta a los 4 listados de INVIMA ahora mismo, sin pasar por el último refresco">Verificar en INVIMA ahora</button>
    </div>
    <div id="resultado-en-vivo"></div>
    <div id="resultado-consulta"></div>
  `;

  const input = contenedor.querySelector("#codigo-input") as HTMLInputElement;
  const btnConsultar = contenedor.querySelector("#btn-consultar") as HTMLButtonElement;
  const btnEnVivo = contenedor.querySelector("#btn-en-vivo") as HTMLButtonElement;
  const divResultado = contenedor.querySelector("#resultado-consulta") as HTMLDivElement;
  const divEnVivo = contenedor.querySelector("#resultado-en-vivo") as HTMLDivElement;

  // Va bajo accion explicita del usuario y NUNCA automatico al consultar:
  // son 4 llamadas de red por codigo contra Socrata, y la vista tiene que
  // seguir sirviendo sin conexion. Mismo criterio que la regla 4 del
  // proyecto para `explicar_fila`.
  btnEnVivo.addEventListener("click", async () => {
    const codigo = input.value.trim();
    if (!codigo) {
      divEnVivo.innerHTML =
        '<p class="consulta-invima__mensaje consulta-invima__mensaje--advertencia">⚠ Escribe un código para verificar</p>';
      return;
    }
    btnEnVivo.disabled = true;
    btnEnVivo.textContent = "Preguntando a INVIMA...";
    divEnVivo.innerHTML =
      '<p class="consulta-invima__mensaje consulta-invima__mensaje--espera">⏳ Consultando los 4 listados de INVIMA en vivo...</p>';
    try {
      const baseUrl = `${window.location.protocol}//${window.location.hostname}:8000`;
      const resp = await fetch(
        `${baseUrl}/consulta-detalle/invima-en-vivo?codigo=${encodeURIComponent(codigo)}`,
      );
      const datos = await resp.json();
      divEnVivo.innerHTML = renderEnVivo(datos.resultados ?? [], datos.error ?? "");
    } catch (e) {
      divEnVivo.innerHTML = `<p class="consulta-invima__mensaje consulta-invima__mensaje--error">No se pudo consultar INVIMA en vivo: ${escaparHTML(String(e))}</p>`;
    } finally {
      btnEnVivo.disabled = false;
      btnEnVivo.textContent = "Verificar en INVIMA ahora";
    }
  });

  // NO se agrega aca un explorador general del universo de INVIMA con
  // TablaFiltrable: pedido explicito del usuario (2026-09-01), es
  // redundante con esta misma tabla de detalle -- esta vista es para
  // consultar un codigo puntual y comparar sus dos fuentes, no para
  // navegar el catalogo completo.
  const ejecutarConsulta = async () => {
    const codigo = input.value.trim();
    if (!codigo) {
      divResultado.innerHTML =
        '<p class="consulta-invima__mensaje consulta-invima__mensaje--advertencia">⚠ Ingresa al menos un código (ej: 3521-1 o 19905554-16)</p>';
      return;
    }

    btnConsultar.disabled = true;
    btnConsultar.textContent = "Consultando...";
    divResultado.innerHTML = '<p class="consulta-invima__mensaje consulta-invima__mensaje--espera">⏳ Cargando datos...</p>';

    const maxReintentos = 3;
    let intento = 0;
    let ultimoError = "";

    while (intento < maxReintentos) {
      try {
        const baseUrl = `${window.location.protocol}//${window.location.hostname}:8000`;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000); // 10s timeout

        const resp = await fetch(`${baseUrl}/consulta-detalle/medicamento?codigo=${encodeURIComponent(codigo)}`, {
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!resp.ok) {
          let errorMsg = `Error HTTP ${resp.status}`;
          try {
            const error = await resp.json();
            errorMsg = error.detail || errorMsg;
          } catch {}
          throw new Error(errorMsg);
        }

        const datos = await resp.json();

        // Validar respuesta
        if (!datos || typeof datos !== "object") {
          throw new Error("Respuesta inválida del servidor");
        }

        mostrarResultado(divResultado, datos);
        btnConsultar.disabled = false;
        btnConsultar.textContent = "Consultar";
        return; // Éxito
      } catch (err) {
        intento++;
        ultimoError = err instanceof Error ? err.message : "Error desconocido";

        if (intento < maxReintentos) {
          divResultado.innerHTML = `<p class="consulta-invima__mensaje consulta-invima__mensaje--advertencia">⚠ Reintentando (${intento}/${maxReintentos - 1})... ${escaparHTML(ultimoError)}</p>`;
          await new Promise((r) => setTimeout(r, 1000 * intento)); // Backoff
        }
      }
    }

    // Si llegamos aquí, todos los reintentos fallaron
    const errorHtml = `
      <div class="consulta-invima__error">
        <p>❌ Error de conexión</p>
        <p>${escaparHTML(ultimoError)}</p>
        <p>
          Verifica que:
          <ul>
            <li>El backend esté corriendo en puerto 8000</li>
            <li>Tu conexión esté activa</li>
          </ul>
        </p>
      </div>
    `;
    divResultado.innerHTML = errorHtml;
    btnConsultar.disabled = false;
    btnConsultar.textContent = "Consultar";
  };

  btnConsultar.addEventListener("click", ejecutarConsulta);
  input.addEventListener("keypress", (e) => {
    if (e.key === "Enter") ejecutarConsulta();
  });

  if (_codigoPendiente) {
    input.value = _codigoPendiente;
    _codigoPendiente = null;
    void ejecutarConsulta();
  }
}

// Todos los casos reales que puede producir la base de datos, evaluados
// contra datos de produccion (2026-09-01) -- ver bitacora para el detalle.
// Descubrimiento clave: ESTADO_REGISTRO del lado INVIMA (tabla "universo")
// SOLO toma el valor "Vigente" (101.183 filas, 0 con otro valor) porque
// "universo" se arma nada mas con el dataset Vigentes de INVIMA -- por eso
// la version anterior de este diagnostico, que buscaba "vencido"/
// "cancelado"/"trámite" en ESE campo, nunca disparaba: eran ramas muertas.
// La fuente de verdad real es ESTADO_COHERENCIA (columna de
// auditoria/coherencia_invima.py), que YA cruza contra las CUATRO fuentes
// de INVIMA (Vigentes + Vencidos + Otros Estados + Renovacion) y deja listo
// el texto de por que en DETALLE_VIGENCIA_INVIMA / ESTADO_INVIMA_DETALLE /
// TIPO_SIN_CORRESPONDENCIA / CAMPOS_CON_DIFERENCIA -- este diagnostico solo
// tiene que leerlos y traducirlos a "que hacer", no reinventar el analisis.
// De menor a mayor gravedad -- el diagnostico final se queda con el nivel
// MAS alto entre el de vigencia y el de las validaciones de dato.
const ORDEN_NIVEL: Record<Diagnostico["nivel"], number> = { ok: 0, informativo: 1, advertencia: 2, critico: 3 };

// Las validaciones que la auditoria YA calculo por fila y que el diagnostico
// tiene que mirar ADEMAS de ESTADO_COHERENCIA.
//
// Bug real reportado por el usuario (2026-09-01): la consulta de 20081076-36
// decia "✓ Correcto — Todos los campos comparables coinciden" mientras en la
// misma pantalla se veia FECHA_FIN 2999-12-31 contra una fecha de INVIMA
// distinta. El diagnostico hacia `switch (ESTADO_COHERENCIA)` y ese campo
// solo resume la VIGENCIA (en que listado de INVIMA esta), no si el dato
// coincide -- las diferencias de fecha y de campo vivian en otras columnas
// que nadie leia aca. Afirmar "correcto" sin mirarlas es exactamente la
// decision a ciegas que el proyecto prohibe.
const VALIDACIONES_DE_DATO: { columna: string; titulo: string; paso: (valor: string) => string; fragmentosRedundantes?: string[] }[] = [
  {
    columna: "COHERENCIA_FECHAS_INVIMA",
    titulo: "las fechas no coinciden con INVIMA",
    paso: (v) => `Corregir las fechas en Gemma Net con el dato oficial de INVIMA — ${v}`,
  },
  {
    columna: "CAMPOS_CON_DIFERENCIA",
    titulo: "hay campos distintos a INVIMA",
    paso: (v) => `Actualizar con el dato oficial de INVIMA los campos: ${v}`,
  },
  {
    columna: "INCONSISTENCIA_FECHAS_ACTIVO",
    titulo: "las fechas se contradicen dentro de Gemma Net",
    paso: (v) => `Revisar la vigencia interna del registro — ${v}`,
    // Esta columna mezcla DOS cosas: contradicciones internas de fecha y el
    // aviso de "ACTIVO=SI pero VENCIDO en INVIMA", que es informacion de
    // vigencia y ya la dice el diagnostico principal. Sin filtrarlo, la
    // consulta de 00028983-02-0N01BB02 repetia el mismo hallazgo dos veces y
    // encima lo rotulaba mal ("se contradicen dentro de Gemma Net" para algo
    // que es un contraste CONTRA INVIMA) -- bug reportado por el usuario,
    // 2026-09-01.
    fragmentosRedundantes: ["VENCIDO en INVIMA"],
  },
  {
    columna: "FILA_LEGADA_DUPLICADA",
    titulo: "hay otra fila del mismo medicamento en Gemma Net",
    paso: (v) => `Revisar la convivencia de códigos — ${v}`,
  },
  {
    columna: "INTEGRIDAD_REFERENCIAL_CATALOGO",
    titulo: "hay un código de catálogo que no existe",
    paso: (v) => `Crear o corregir el código en el catálogo interno — ${v}`,
  },
  {
    columna: "VALORES_FUERA_DE_DOMINIO",
    titulo: "hay un valor fuera de lo permitido",
    paso: (v) => `Corregir el valor en Gemma Net — ${v}`,
  },
  {
    columna: "INCONSISTENCIA_NUMERICA",
    titulo: "hay un número que no tiene sentido",
    paso: (v) => `Revisar edades y topes de uso — ${v}`,
  },
  {
    columna: "FORMATO_CODIGO_INTERNO_INVALIDO",
    titulo: "el código interno tiene un formato inválido",
    paso: (v) => `Corregir el CODIGO_INTERNO en Gemma Net — ${v}`,
  },
];

/** Suma al diagnostico de vigencia todo lo que digan las demas validaciones.
 * Nunca BAJA el nivel (un crítico de vigencia sigue siendo crítico); si el
 * diagnóstico venía en "ok" o "informativo" y hay hallazgos de dato, sube a
 * "advertencia" -- no se puede decir "correcto" y mostrar una diferencia. */
function refinarConValidaciones(base: Diagnostico, fila: Record<string, unknown>): Diagnostico {
  const hallazgos = VALIDACIONES_DE_DATO.map((v) => {
    // Los hallazgos vienen separados por "; " -- se descartan uno por uno los
    // fragmentos que ya dice el diagnostico de vigencia, en vez de tirar la
    // columna entera: una fila puede tener a la vez una contradiccion REAL de
    // fechas y el aviso redundante de vencido.
    const partes = String(fila[v.columna] ?? "")
      .split(";")
      .map((t) => t.trim())
      .filter((t) => t !== "" && !(v.fragmentosRedundantes ?? []).some((f) => t.includes(f)));
    return { v, valor: partes.join("; ") };
  }).filter((h) => h.valor !== "");
  if (hallazgos.length === 0) return base;

  const nivel: Diagnostico["nivel"] = ORDEN_NIVEL[base.nivel] >= ORDEN_NIVEL.advertencia ? base.nivel : "advertencia";
  const resumen = hallazgos.map((h) => h.v.titulo).join("; ");
  // Un "correcto" que en realidad tiene hallazgos no se matiza: se reemplaza,
  // porque el titulo es lo unico que mucha gente lee.
  const titulo = base.nivel === "ok" ? "⚠ Con diferencias frente a INVIMA" : base.titulo;
  const mensaje = base.nivel === "ok" ? `El registro está en INVIMA, pero ${resumen}.` : `${base.mensaje} Además, ${resumen}.`;
  return {
    ...base,
    nivel,
    titulo,
    icono: base.nivel === "ok" ? "🔀" : base.icono,
    mensaje,
    pasos: [...hallazgos.map((h) => h.v.paso(h.valor)), ...base.pasos.filter((p) => p !== "Sin acciones requeridas")],
  };
}

function generarDiagnostico(invima: Record<string, unknown>[], gemmaNet: Record<string, unknown>[] | null): Diagnostico {
  const base = diagnosticoDeVigencia(invima, gemmaNet);
  // Las validaciones de dato solo aplican si hay fila de Gemma Net: son
  // columnas de la auditoria, que audita lo YA cargado.
  return gemmaNet && gemmaNet.length > 0 ? refinarConValidaciones(base, gemmaNet[0]) : base;
}

function diagnosticoDeVigencia(invima: Record<string, unknown>[], gemmaNet: Record<string, unknown>[] | null): Diagnostico {
  const hayInvima = invima && invima.length > 0;
  const hayGemma = gemmaNet && gemmaNet.length > 0;

  // Caso 1: no existe en ningun lado -- no hay ningun campo del que sacar
  // una explicacion mas especifica.
  if (!hayInvima && !hayGemma) {
    return {
      nivel: "informativo",
      titulo: "ℹ Sin correspondencia",
      icono: "❓",
      mensaje: "El código no aparece en INVIMA ni está cargado en Gemma Net",
      pasos: [
        "Verifica que el código sea correcto (ej: 3521-1)",
        "Si es un código especial (ancestral, planta, IUM), consulta el catálogo de INVIMA directamente",
        "Si es un error de digitación, intenta nuevamente",
      ],
    };
  }

  // Caso 2: esta en Gemma Net (con o sin fila de "universo" -- da igual,
  // ESTADO_COHERENCIA ya resume la relacion completa contra INVIMA).
  if (hayGemma) {
    const fila = gemmaNet![0];
    const estado = String(fila["ESTADO_COHERENCIA"] || "");
    const activo = String(fila["ACTIVO"] || "").toUpperCase() === "SI";
    const activoStr = activo ? "activo" : "inactivo";
    const detalleVigencia = String(fila["DETALLE_VIGENCIA_INVIMA"] || "");
    const estadoInvimaDetalle = String(fila["ESTADO_INVIMA_DETALLE"] || "");
    const camposConDiferencia = String(fila["CAMPOS_CON_DIFERENCIA"] || "");
    // El CUM sigue Activo en INVIMA aunque el registro este en el listado de
    // Vencidos u Otros Estados: es la "gracia de lotes" (agotar lo fabricado),
    // no una autorizacion sin respaldo. Sin mirar esto la pantalla anunciaba
    // "CRÍTICO — se puede autorizar un medicamento sin registro vigente" tres
    // líneas encima de su propia fila "Estado del registro: Activo / Activo /
    // coincide" -- reportado por el usuario (2026-09-07) sobre 20055681-1, y
    // contradiciendo al nivel 3 que la auditoría ya le había asignado.
    const cumActivoEnInvima = String(fila["ESTADO_CUM_INVIMA"] || "").trim().toLowerCase() === "activo";
    // Riesgo real de vigencia = activo aquí Y sin respaldo en INVIMA. Es el
    // MISMO par (ACTIVO, ESTADO_CUM_INVIMA) con el que
    // `clasificar_prioridad_accion` decide el nivel 1, para que esta pantalla
    // y las tarjetas no puedan volver a decir cosas distintas del mismo CUM.
    const sinRespaldoVigente = activo && !cumActivoEnInvima;

    // Un "correcto" solo puede anunciarse como tal si NADA lo contradice.
    // Bug real que corrige (20055212-21, reportado por el usuario el
    // 2026-09-03): la tarjeta salia verde con "✓ Correcto" y, dentro, su
    // propio mensaje decia "INVIMA tiene el CUM como Inactivo. Riesgo alto:
    // se puede autorizar un medicamento que INVIMA ya desactivo". El mensaje
    // se tomaba de DETALLE_VIGENCIA_INVIMA pero el nivel y el titulo
    // ignoraban su gravedad.
    const novedadVigencia = String(fila["NOVEDAD_VIGENCIA_INVIMA"] || "");
    const vigenciaCoherente = novedadVigencia === "" || novedadVigencia === "coherente";
    // ESTADO_COHERENCIA se queda en "correcto" cuando un campo esta vacio en
    // Gemma Net: no "difiere" de INVIMA porque no hay nada que comparar (ver
    // VALIDACION_SIN_DATO_LOCAL). Pero si INVIMA SI lo trae, hay algo que
    // hacer -- caso de la marca "SIN INFORMACION" contra "LABORATORIOS MK
    // S.A.S.": "sin marca en gemma net, pero invima si tiene, entonces
    // correcto no esta" (usuario, 2026-09-03).
    const camposSinDatoLocal = CAMPOS_COMPARABLES.filter(
      (c) => String(fila[`${c.columna}_VALIDACION`] || "") === "sin dato en Gemma Net",
    ).map((c) => c.etiqueta);

    switch (estado) {
      case "correcto": {
        if (vigenciaCoherente && camposSinDatoLocal.length === 0) {
          return {
            nivel: "ok",
            titulo: "✓ Correcto",
            icono: "✅",
            mensaje: "Todos los campos comparables coinciden con el registro vigente de INVIMA.",
            pasos: ["Sin acciones requeridas", "Monitorear cambios en INVIMA regularmente"],
          };
        }
        const critico = novedadVigencia === "riesgo_activo_sin_vigencia" && activo;
        const faltantes = camposSinDatoLocal.length
          ? `Falta diligenciar en Gemma Net: ${camposSinDatoLocal.join(", ")} (INVIMA sí lo reporta).`
          : "";
        return {
          nivel: critico ? "critico" : "advertencia",
          titulo: critico ? "🔴 CRÍTICO — Activo sin vigencia en INVIMA" : "⚠ Requiere revisión",
          icono: critico ? "🔴" : "⚠",
          mensaje: [detalleVigencia, faltantes].filter(Boolean).join(" ") ||
            "Los campos coinciden, pero hay algo que revisar frente a INVIMA.",
          pasos: [
            ...(vigenciaCoherente ? [] : ["Verificar la vigencia en INVIMA antes de autorizar"]),
            ...(camposSinDatoLocal.length
              ? [`Diligenciar en Gemma Net con el dato oficial: ${camposSinDatoLocal.join(", ")}`]
              : []),
          ],
        };
      }

      case "con_diferencias":
        return {
          nivel: "advertencia",
          titulo: "⚠ Con diferencias frente a INVIMA",
          icono: "🔀",
          mensaje: detalleVigencia || `Coincide con un registro de INVIMA, pero difiere en: ${camposConDiferencia || "uno o más campos"}.`,
          pasos: [
            camposConDiferencia ? `Revisar y corregir en Gemma Net: ${camposConDiferencia}` : "Revisar los campos marcados como diferentes",
            "Actualizar con el dato oficial de INVIMA (ver la tabla de INVIMA más abajo)",
          ],
        };

      case "vencido_en_invima": {
        // Tres casos distintos, no dos: inactivo aquí (coherente), activo con
        // el CUM aún Activo en INVIMA (gracia de lotes) y activo sin respaldo
        // (el único crítico de verdad).
        if (!activo) {
          return {
            nivel: "advertencia",
            titulo: "⚠ Vencido en INVIMA",
            icono: "⏰",
            mensaje: detalleVigencia || "INVIMA tiene este registro en su listado de VENCIDOS. En Gemma Net está inactivo.",
            pasos: ["Ya está inactivo en Gemma Net — estado coherente", "Confirmar que la fecha de inactivación es consistente con el vencimiento"],
          };
        }
        if (!sinRespaldoVigente) {
          return {
            nivel: "advertencia",
            titulo: "⚠ Vigencia temporal — agotando lotes",
            icono: "⏳",
            mensaje:
              detalleVigencia ||
              "Está en el listado de VENCIDOS de INVIMA, pero el CUM sigue Activo: vigencia temporal mientras se agotan los lotes fabricados.",
            pasos: [
              "Se puede seguir dispensando mientras el CUM siga Activo en INVIMA",
              "Vigilar: deja de estar vigente en cuanto INVIMA cambie el estado del CUM",
              "Solicitar la renovación del registro si se requiere seguir usándolo",
            ],
          };
        }
        return {
          nivel: "critico",
          titulo: "🔴 CRÍTICO — Vencido y activo",
          icono: "🔴",
          mensaje: detalleVigencia || "INVIMA tiene este registro en su listado de VENCIDOS. En Gemma Net está activo.",
          pasos: [
            "INMEDIATAMENTE: desactivar en Gemma Net",
            "Notificar al área clínica",
            "No dispensar con un registro vencido",
            "Solicitar renovación del registro a INVIMA si se requiere seguir usándolo",
          ],
        };
      }

      case "encontrado_en_otro_estado_invima": {
        const detalleEstado = estadoInvimaDetalle || "un estado especial (Cancelado, Suspendido, Negado, Desistido, Abandono o con pérdida de fuerza ejecutoria)";
        // Mismo criterio que el listado de Vencidos: lo que decide el riesgo
        // es ESTADO_CUM_INVIMA, no en que archivo aparece el registro.
        if (activo && !sinRespaldoVigente) {
          return {
            nivel: "advertencia",
            titulo: `⏳ ${estadoInvimaDetalle || "Otro estado"} — CUM aún vigente`,
            icono: "⏳",
            mensaje: `INVIMA reporta este registro como "${detalleEstado}", pero el CUM sigue Activo: todavía hay respaldo sanitario.`,
            pasos: [
              "Se puede seguir dispensando mientras el CUM siga Activo en INVIMA",
              "Vigilar: el estado del registro ya cambió, el del CUM puede seguirlo",
              "Confirmar con INVIMA si el cambio de estado afecta la comercialización",
            ],
          };
        }
        return {
          nivel: activo ? "critico" : "ok",
          titulo: activo ? `🔴 CRÍTICO — ${estadoInvimaDetalle || "Otro estado"} y activo` : `✓ ${estadoInvimaDetalle || "Otro estado"} e inactivo`,
          icono: activo ? "🔴" : "✓",
          mensaje: `INVIMA reporta este registro como "${detalleEstado}". En Gemma Net está ${activoStr}.`,
          pasos: activo
            ? [
                "INMEDIATAMENTE: desactivar en Gemma Net",
                "Notificar al área clínica del estado real en INVIMA",
                "No dispensar mientras el registro no esté vigente",
              ]
            : ["Ya está inactivo en Gemma Net — estado coherente con INVIMA"],
        };
      }

      case "en_tramite_renovacion_invima":
        return {
          nivel: "informativo",
          titulo: "ⓘ En trámite de renovación",
          icono: "⏳",
          mensaje: detalleVigencia || `La renovación del registro está en trámite en INVIMA. En Gemma Net está ${activoStr}.`,
          pasos: [
            "El registro sigue siendo válido mientras dura el trámite — se puede seguir dispensando",
            estadoInvimaDetalle ? `Detalle de INVIMA: ${estadoInvimaDetalle}` : "Monitorear la resolución del trámite en INVIMA",
          ],
        };

      case "vigente_no_comercializado_invima":
        return {
          nivel: "informativo",
          titulo: "ⓘ Vigente, no comercializado",
          icono: "🏭",
          mensaje: detalleVigencia || `El registro está vigente en INVIMA, pero reportado como no comercializado actualmente. En Gemma Net está ${activoStr}.`,
          pasos: ["No requiere acción sobre el registro en sí", "Si un paciente lo necesita, verificar disponibilidad real antes de formular"],
        };

      case "sin_correspondencia_invima": {
        // TIPO_SIN_CORRESPONDENCIA ya distingue "SI tiene formato de CUM
        // pero INVIMA no tiene el registro" de "no tiene forma de CUM" --
        // ver TIPO_CODIGO_INTERNO=="cum" como criterio (no el texto).
        const tipoSinCorrespondencia = String(fila["TIPO_SIN_CORRESPONDENCIA"] || "");
        const esFormatoCumValido = String(fila["TIPO_CODIGO_INTERNO"] || "") === "cum";
        return {
          nivel: esFormatoCumValido ? "advertencia" : "informativo",
          titulo: esFormatoCumValido ? "⚠ No encontrado en INVIMA" : "ℹ Código interno, no es un CUM",
          icono: esFormatoCumValido ? "🔍" : "🏷️",
          mensaje: tipoSinCorrespondencia || "El código no tiene correspondencia con ninguno de los cuatro listados de INVIMA.",
          pasos: esFormatoCumValido
            ? [
                "El código SÍ tiene formato EXPEDIENTE-CONSECUTIVO válido, pero INVIMA no tiene ningún registro con ese código en sus cuatro listados (Vigentes, Vencidos, Otros Estados, Renovación)",
                "Verificar si el registro fue anulado o si hay un error de digitación en Gemma Net",
                "Si el código es correcto y sigue sin aparecer, puede ser un registro muy antiguo fuera de los datasets vigentes de INVIMA",
              ]
            : [
                "El código no sigue el formato EXPEDIENTE-CONSECUTIVO de INVIMA — es un código interno propio de Gemma Net",
                "No se puede verificar contra INVIMA por este medio; no es un error, simplemente no aplica",
              ],
        };
      }

      case "no_valida_contra_invima": {
        const clasificado = String(fila["CLASIFICADO"] || "");
        return {
          nivel: "ok",
          titulo: "✓ No aplica contra INVIMA",
          icono: "🌿",
          mensaje: `Cargado en Gemma Net como "${clasificado || "medicamento ancestral/planta medicinal"}" — este tipo de registro no tiene equivalente en el catálogo de INVIMA, es normal que no aparezca del otro lado.`,
          pasos: ["Sin acciones requeridas: INVIMA no regula este tipo de producto"],
        };
      }

      default:
        // Defensivo: ESTADOS_COHERENCIA es un vocabulario cerrado (ver
        // pildoras.ts), esto no deberia alcanzarse con datos reales.
        return {
          nivel: "informativo",
          titulo: "ℹ Revisar estado",
          icono: "ℹ️",
          mensaje: `Estado de coherencia sin clasificar: "${estado}". Activo en Gemma Net: ${activoStr}.`,
          pasos: ["Revisar la fila de Gemma Net más abajo para más detalle"],
        };
    }
  }

  // Caso 3: solo INVIMA (candidato a cargar). "universo" solo trae
  // Vigentes, asi que esto siempre es "vigente en INVIMA, sin cargar" --
  // ESTADO_CUM (Activo/Inactivo, distinto de ESTADO_REGISTRO) es el unico
  // matiz real disponible: una presentacion puntual descontinuada dentro
  // de un registro que en conjunto sigue vigente.
  const estadoCum = String(invima[0]["ESTADO_CUM"] || "").toLowerCase();
  return {
    nivel: "advertencia",
    titulo: "⚠ Candidato a cargar",
    icono: "📋",
    mensaje:
      estadoCum === "inactivo"
        ? "Medicamento vigente en INVIMA pero NO cargado en Gemma Net. Ojo: este CUM específico está marcado como Inactivo dentro de su propio registro (puede ser una presentación descontinuada)."
        : "Medicamento vigente en INVIMA pero NO cargado en Gemma Net.",
    pasos:
      estadoCum === "inactivo"
        ? [
            "Verificar si esta presentación puntual sigue siendo relevante antes de incluirla en el cargue",
            "Revisar en 'Resumen de resolución' por qué no se cargó",
          ]
        : [
            "Revisar en 'Resumen de resolución' por qué no se cargó",
            "Completar datos faltantes (marca, unidad, etc) si es necesario",
            "Incluir en próximo cargue a Gemma Net",
          ],
  };
}

function mostrarResultado(contenedor: HTMLElement, datos: RespuestaConsultaDetalle): void {
  try {
    if (!datos) throw new Error("Datos vacíos");

    const invima = Array.isArray(datos.invima) ? datos.invima : [];
    const gemma_net = Array.isArray(datos.gemma_net) ? datos.gemma_net : null;
    const codigos_consultados = Array.isArray(datos.codigos_consultados) ? datos.codigos_consultados : [];

    const diagnostico = generarDiagnostico(invima, gemma_net);
    // codigos_consultados viene del backend, pero ORIGINA en lo que el
    // usuario escribio en el input -- nunca insertar sin escapar (mismo
    // criterio que esc() en auditoria.ts/tabla.ts).
    const codigosTexto = escaparHTML(codigos_consultados.join(", ") || "—");

    let html = `
      <div class="consulta-invima__diagnostico consulta-invima__diagnostico--${diagnostico.nivel}">
        <h3>${diagnostico.icono} ${escaparHTML(diagnostico.titulo)}</h3>
        <p>${escaparHTML(diagnostico.mensaje)}</p>
        <p>Código(s): <strong>${codigosTexto}</strong></p>
      </div>

      <div class="consulta-invima__pasos">
        <h4>📋 Pasos a seguir:</h4>
        <ol>
          ${diagnostico.pasos.map((paso) => `<li>${escaparHTML(paso)}</li>`).join("")}
        </ol>
      </div>
      ${crearComparacionEstadosHTML(gemma_net)}
    `;

    // Ya NO se dibujan las dos tablas horizontales (una por fuente) que iban
    // debajo -- pedido del usuario (2026-09-02): "esas dos tablas las vamos a
    // remover y vamos a tomar los datos que ya llama y los vamos a enlistar
    // en la tabla superior que tiene formato vertical". Repetian, en dos
    // tablas anchas con scroll horizontal, los mismos campos que la tabla de
    // arriba ya enfrenta uno contra otro; para comparar un campo habia que
    // buscarlo en una tabla y despues en la otra.
    contenedor.innerHTML = html;
  } catch (err) {
    contenedor.innerHTML = `
      <div class="consulta-invima__error">
        <p>❌ Error al procesar resultado</p>
        <p>${escaparHTML(err instanceof Error ? err.message : "Desconocido")}</p>
      </div>
    `;
  }
}

// Las dos tablas horizontales (una por fuente) y su armador se quitaron el
// 2026-09-02: la comparacion vive ahora en una sola tabla vertical, campo
// contra campo (ver crearComparacionEstadosHTML). La regla que motivo la
// separacion original -- que el panel de Gemma Net no mezclara columnas
// *_INVIMA -- sigue respetada: en la tabla vertical cada valor esta en la
// columna de la fuente de la que sale, que era el fondo del pedido.

// Lado a lado, sin desplegable -- las 4 fechas y los 2 estados son cortos,
// esconderlos detras de un expander "solo desperdicia espacio" (regla del
// proyecto). Solo se arma si hay fila de Gemma Net: es la unica que trae
// ESTADO_LISTADO_INVIMA/FECHA_ACTIVO_INVIMA/etc pegados (ver backend,
// consulta_detalle.py) -- si el codigo solo existe en INVIMA ya lo cubre el
// diagnostico de arriba ("candidato a cargar").
// Ya no recibe las filas de INVIMA: la unica que usaba era el TITULAR, que se
// quito por redundante (Gemma Net no lo guarda y la fila "Marca" ya compara
// contra el mismo dato). Todo lo demas sale de la fila de auditoria, que trae
// los dos lados en su trio <CAMPO>_GEMANET / _INVIMA / _VALIDACION.
function crearComparacionEstadosHTML(
  gemmaNet: Record<string, unknown>[] | null,
): string {
  if (!gemmaNet || gemmaNet.length === 0) return "";
  const fila = gemmaNet[0];

  // Fechas comodin de Gemma Net: NO son fechas, son "sin dato" (residuo de la
  // migracion a la nube). Mostrarlas como "2999-12-31" al lado de una fecha
  // real de INVIMA hacia parecer que el dato estaba mal cuando en realidad
  // esta ausente -- dos problemas distintos, que se atienden distinto.
  // Las de fechas PASADAS son una lista corta y cerrada (FECHAS_CENTINELA en
  // coherencia_invima.py). 1899-12-30 es el cero del calendario serial de Excel.
  const COMODINES = new Set(["2999-12-31", "1900-01-01", "1899-12-30"]);
  // Las de "no vence" NO son una lista: son decenas de variantes repartidas
  // (3000-01-01, 3000-12-31, 3001-01-01, 2199-01-01, 2900-01-01...), asi que
  // se cortan por ANO igual que ANIO_CENTINELA_SIN_VENCIMIENTO en
  // coherencia_invima.py -- ESE es el numero de referencia, este es su espejo.
  //
  // Sin este corte la tabla decia "falta actualizar" sobre un vencimiento de
  // INVIMA del ano 3000, o sea: copia a Gemma Net una fecha imposible. Lo
  // reporto el usuario (2026-09-07, "ano 3000 imposible") sobre 19998786-12, y
  // la auditoria YA lo tenia bien (COHERENCIA_FECHAS_INVIMA vacio, sin
  // hallazgo): la pantalla lo contradecia por recalcular con lista incompleta.
  const ANIO_SIN_VENCIMIENTO = 2100;
  const soloFecha = (valor: unknown): string => String(valor ?? "").trim().slice(0, 10);
  const esComodin = (valor: unknown) => {
    const texto = soloFecha(valor);
    if (COMODINES.has(texto)) return true;
    const anio = Number(texto.slice(0, 4));
    return Number.isFinite(anio) && anio >= ANIO_SIN_VENCIMIENTO;
  };

  const celda = (valor: unknown): string => {
    const texto = soloFecha(valor);
    if (!texto) return `<span class="celda-muda">—</span>`;
    // El texto ya no dice "de Gemma Net": desde que el corte por año entró,
    // esto también tapa los comodines de INVIMA (vencimientos del año 3000).
    if (esComodin(valor)) return `<span class="celda-muda" title="Fecha comodín (${escaparHTML(soloFecha(valor))}): significa «sin dato», no una fecha real">sin dato</span>`;
    // Mes con letras para que no se pueda confundir con el dia (INVIMA es
    // MM/DD/YYYY en origen y Gemma Net YYYY-MM-DD). El ISO exacto queda en el
    // title, que es el dato con el que alguien buscaria en la fuente.
    const legible = fechaLegible(texto);
    return legible
      ? `<span title="${escaparHTML(texto)}">${escaparHTML(legible)}</span>`
      : escaparHTML(texto);
  };
  const texto = (valor: unknown): string => {
    const t = String(valor ?? "").trim();
    return t ? escaparHTML(t) : `<span class="celda-muda">—</span>`;
  };

  const estadoInvima = fila["ESTADO_LISTADO_INVIMA"] ? etiquetaEstadoListadoInvima(String(fila["ESTADO_LISTADO_INVIMA"])) : null;
  const estadoInvimaDetalle = fila["ESTADO_INVIMA_DETALLE"] ? String(fila["ESTADO_INVIMA_DETALLE"]) : "";

  // La TABLA solo lleva pares que de verdad se comparan. El listado y el
  // estado de registro no lo son -- Gemma Net no guarda ninguno de los dos --
  // y ademas dicen lo mismo entre si (listado "vencido" <-> registro
  // "Vencido"), asi que ocupaban dos filas con veredicto "ubicación" y "sin
  // comparar" que no aportaban nada. Salen a una linea informativa ENCIMA de
  // la tabla (pedido del usuario, 2026-09-04: "eliminar la redundancia... y
  // fuera de la tabla debe decir en que listado buscarlo").
  const dondeBuscarlo = estadoInvima
    ? `<p class="consulta-invima__ubicacion">
        📋 En INVIMA búscalo en el listado de <strong>${escaparHTML(estadoInvima)}</strong>${
          estadoInvimaDetalle && estadoInvimaDetalle !== estadoInvima
            ? ` — estado del registro: ${escaparHTML(estadoInvimaDetalle)}`
            : ""
        }.
      </p>`
    : "";

  // ESTADO_CUM es el veredicto de VIGENCIA REAL de INVIMA ("Activo"/
  // "Inactivo"), independiente del listado donde este el registro. Es la
  // UNICA fila de estado que queda en la tabla porque es la unica que se
  // puede contrastar: Gemma Net si tiene su equivalente (ACTIVO). Su
  // veredicto es el que responde "¿la vigencia es correcta?" y destapa el
  // caso de mayor riesgo -- activo aqui, ya desactivado en INVIMA.
  const estadoCumInvima = String(fila["ESTADO_CUM_INVIMA"] ?? "").trim();
  const activoGemma = String(fila["ACTIVO"] ?? "").trim().toUpperCase() === "SI";
  const equivalenteGemma = activoGemma ? "Activo" : "Inactivo";
  const filaEstadoCum = estadoCumInvima
    ? `<tr>
        <th scope="row">Estado del registro (cruce de vigencia)</th>
        <td>${escaparHTML(equivalenteGemma)}</td>
        <td>${escaparHTML(estadoCumInvima)}</td>
        <td>${
          estadoCumInvima === equivalenteGemma
            ? '<span class="pildora pildora--ok">coincide</span>'
            : '<span class="pildora pildora--danger">diferente</span>'
        }</td>
      </tr>`
    : "";

  // Filas EMPAREJADAS, no dos columnas sueltas -- pedido del usuario
  // (2026-09-01): con dos listas independientes no se veia que campo de un
  // lado corresponde a cual del otro, y "Fecha fin" quedaba visualmente
  // enfrentada a "Fecha vencimiento", que NO es su par. El par real, ya
  // fijado como regla de negocio y verificado contra el caso 20102710-2, es
  // FECHA_INICIO ↔ FECHA ACTIVO y FECHA_FIN ↔ FECHA INACTIVO.
  //
  // FECHA_VENCIMIENTO va aparte, sin par y rotulada como tal: es la vigencia
  // del registro sanitario, otra cosa. Enfrentarla a FECHA_FIN era justo lo
  // que hacia leer "todo correcto" con dos fechas visiblemente distintas.
  // Fin ANTES que Inicio: la fecha de expiración es lo más importante para
  // vigencia. Formatos aclarados porque INVIMA y Gemma Net usan distintos:
  // INVIMA es MM/DD/YYYY (04/03/2017 = 4 de marzo), Gemma es YYYY-MM-DD
  // (2017-03-04 = 4 de marzo). Esto causa confusión si no se aclara, porque
  // 04/03 vs 03/04 parecen fechas distintas. Pedido del usuario (2026-09-03).
  // Inicio ARRIBA de fin -- pedido del usuario (2026-09-03), es el orden
  // natural de lectura de un periodo de vigencia.
  const pares: { etiqueta: string; gemma: unknown; invima: unknown }[] = [
    {
      etiqueta: "Fecha de inicio / activo",
      gemma: fila["FECHA_INICIO"],
      invima: fila["FECHA_ACTIVO_INVIMA"],
    },
    {
      etiqueta: "Fecha de fin / vencimiento",
      gemma: fila["FECHA_FIN"],
      invima: fila["FECHA_VENCIMIENTO_INVIMA"],
    },
  ];

  /** Por que una fila quedo "sin comparar": sin esto el veredicto no se
   * podia interpretar -- caso real 00028983-02-0N01BB02, donde Gemma Net
   * simplemente no tiene fecha registrada (fila legada con expediente -999)
   * y parecia que la comparacion habia fallado. */
  const motivoSinComparar = (gemma: unknown, invima: unknown): string => {
    const g = soloFecha(gemma);
    const i = soloFecha(invima);
    if (!g && !i) return "Ninguna de las dos fuentes tiene esta fecha.";
    if (!g) return "Gemma Net no tiene esta fecha registrada.";
    if (!i) return "INVIMA no reporta esta fecha para este código.";
    if (esComodin(gemma)) return "Gemma Net tiene una fecha comodín, que significa «sin dato» — no es una fecha distinta.";
    if (esComodin(invima)) return "INVIMA tiene una fecha comodín, que significa «sin dato».";
    return "No hay con qué comparar.";
  };

  const filasPares = pares
    .map((par) => {
      const g = soloFecha(par.gemma);
      const i = soloFecha(par.invima);
      // Solo se marca diferencia cuando AMBOS lados traen una fecha real:
      // un comodin es "sin dato", no una fecha distinta (misma regla que
      // COHERENCIA_FECHAS_INVIMA en coherencia_invima.py).
      const comparable = g && i && !esComodin(par.gemma) && !esComodin(par.invima);
      const difiere = comparable && g !== i;
      // Gemma sin dato (vacio o comodin) e INVIMA con fecha real: no esta
      // "mal", FALTA -- y hay de donde copiarla.
      const falta = (!g || esComodin(par.gemma)) && i && !esComodin(par.invima);
      return `<tr class="${difiere || falta ? "consulta-invima__par--difiere" : ""}">
        <th scope="row">${escaparHTML(par.etiqueta)}</th>
        <td>${celda(par.gemma)}</td>
        <td>${celda(par.invima)}</td>
        <td>${difiere ? '<span class="pildora pildora--warn">No coincide / Actualizar campo</span>' : falta ? '<span class="pildora pildora--warn">Falta / Actualizar campo</span>' : comparable ? '<span class="pildora pildora--ok">Coincide</span>' : `<span class="celda-muda" title="${escaparHTML(motivoSinComparar(par.gemma, par.invima))}">Sin comparar</span>`}</td>
      </tr>`;
    })
    .join("");

  // Los 7 campos comparables, con el veredicto que la auditoria YA calculo
  // por campo (columnas <CAMPO>_GEMANET / _INVIMA / _VALIDACION, ver
  // COLUMNAS_TRIO_CAMPOS_COMPARADOS en calidades.py). No se recalcula la
  // comparacion aca: reimplementarla en el frontend es como se llega a que
  // esta pantalla diga una cosa y las tarjetas de calidades otra para el
  // mismo CUM.
  const filasCampos = CAMPOS_COMPARABLES.map(({ columna, etiqueta }) => {
    const g = fila[`${columna}_GEMANET`];
    const i = fila[`${columna}_INVIMA`];
    const veredicto = String(fila[`${columna}_VALIDACION`] ?? "").trim();
    // Una fila sin NINGUN dato de los dos lados no aporta: se omite en vez de
    // alargar la tabla con guiones.
    if (!String(g ?? "").trim() && !String(i ?? "").trim()) return "";
    return `<tr class="${veredicto === "difiere" ? "consulta-invima__par--difiere" : ""}">
      <th scope="row">${escaparHTML(etiqueta)}</th>
      <td>${texto(g)}</td>
      <td>${texto(i)}</td>
      <td>${veredicto ? pildoraValidacion(veredicto) : `<span class="celda-muda">—</span>`}</td>
    </tr>`;
  }).join("");

  // La fila TITULAR se quito (2026-09-03, pedido del usuario: "mira si en
  // gemma net hay un equivalente de titular, si no eliminar ese campo porque
  // no se puede comparar"). Verificado: Gemma Net NO guarda titular -- su
  // consulta solo trae `m.marca_medicamento` (ver ingesta/gemanet_sql.py) --
  // y del lado de INVIMA el TITULAR es justamente lo que la auditoria ya
  // compara como MARCA_MEDICAMENTO (`crudos_invima["MARCA_MEDICAMENTO"] =
  // TITULAR_INVIMA` en coherencia_invima.py). Asi que la fila repetia el
  // mismo dato que "Marca" con un "no aplica" al lado, sin aportar nada.

  return `
    ${dondeBuscarlo}
    <div class="consulta-invima__envoltorio">
      <table class="consulta-invima__tabla consulta-invima__pares">
        <thead>
          <tr><th>Campo</th><th>🔧 Gemma Net</th><th>📋 INVIMA</th><th>Veredicto</th></tr>
        </thead>
        <tbody>
          ${filaEstadoCum}
          ${filasCampos}
          ${filasPares}
        </tbody>
      </table>
    </div>
  `;
}

function escaparHTML(texto: string): string {
  const map: Record<string, string> = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  };
  return texto.replace(/[&<>"']/g, (char) => map[char]);
}

interface AparicionEnVivo {
  listado: string;
  estado_cum: string;
  estado_registro: string;
  producto: string;
  filas: number;
}

interface ResultadoEnVivo {
  codigo: string;
  encontrado: boolean;
  apariciones: AparicionEnVivo[];
  listados_no_consultados: string[];
  error: string;
  consultado_utc: string;
}

/** Lo que INVIMA responde AHORA, para contrastarlo con lo que muestra el
 * resto de la vista (que sale del último refresco). Cuando los dos no
 * coinciden, el snapshot está viejo -- normalmente porque el refresco cayó
 * al respaldo local con Socrata caído. */
function renderEnVivo(resultados: ResultadoEnVivo[], errorGeneral: string): string {
  if (errorGeneral) {
    return `<p class="consulta-invima__mensaje consulta-invima__mensaje--error">${escaparHTML(errorGeneral)}</p>`;
  }
  if (!resultados.length) return "";
  const bloques = resultados.map((r) => {
    if (r.error) {
      return `<li><strong>${escaparHTML(r.codigo)}</strong> — <span class="consulta-invima__mensaje--advertencia">${escaparHTML(r.error)}</span></li>`;
    }
    if (!r.encontrado) {
      return `<li><strong>${escaparHTML(r.codigo)}</strong> — no aparece en ninguno de los 4 listados de INVIMA</li>`;
    }
    const donde = r.apariciones
      .map(
        (a) =>
          `${etiquetaEstadoListadoInvima(a.listado)} · estado CUM <strong>${escaparHTML(a.estado_cum)}</strong> · ${escaparHTML(a.estado_registro)} (${a.filas} fila${a.filas === 1 ? "" : "s"})`,
      )
      .join("<br/>");
    const producto = r.apariciones[0]?.producto ?? "";
    const aviso = r.listados_no_consultados.length
      ? `<br/><span class="consulta-invima__mensaje--advertencia">No se pudo consultar: ${escaparHTML(r.listados_no_consultados.join("; "))}</span>`
      : "";
    return `<li><strong>${escaparHTML(r.codigo)}</strong> — ${escaparHTML(producto)}<br/>${donde}${aviso}</li>`;
  });
  return `
    <div class="tarjeta-alerta tarjeta-alerta--info">
      <p><strong>Respuesta de INVIMA en vivo</strong> — consultado ahora, sin pasar por el último refresco.</p>
      <ul>${bloques.join("")}</ul>
    </div>
  `;
}
