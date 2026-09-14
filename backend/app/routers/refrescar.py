"""POST /refrescar -- solicita al worker que adelante su ciclo periodico.
GET /refrescar/progreso -- sondea el estado del refresco actual.

No hay concurrencia: si uno ya esta en curso, pedir otro devuelve 409.
El progreso se persiste en el DB de estado (worker/estado.py) para que
sobreviva a reinicios del backend.

Los dos endpoints deciden "hay un refresco en curso" con la MISMA funcion
(`_hay_refresco_en_curso`). Antes no: POST miraba `hay_solicitud_pendiente()`
y GET miraba los pasos, asi que podian contradecirse -- y se contradecian.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.auth.dependencias import exigir_admin
from backend.app.dependencies import ruta_estado
from gemma_cum_loader.ingesta.fuente_invima import (
    FUENTE_DEFECTO,
    FUENTES_HABILITADAS,
    FUENTES_VALIDAS,
)
from worker.estado import (
    ESTADO_PASO_ERROR,
    ESTADO_PASO_HECHO,
    PasoProgreso,
    guardar_fuente_refresco,
    progreso_actual,
    solicitar_refresco_manual,
    worker_vivo,
)

router = APIRouter(prefix="/refrescar", tags=["refresco"])


def _hay_refresco_en_curso(pasos: list[PasoProgreso], *, worker_activo: bool = True) -> bool:
    """Un refresco esta en curso si algun paso quedo sin terminar Y la corrida
    sigue viva de verdad.

    Las dos condiciones extra existen porque `progreso_pasos` NO sabe expresar
    "esta corrida abortó": solo guarda el estado de cada paso, y una corrida
    muerta en el paso 3 se ve identica a una que justo va por el paso 3.
    Sin ellas el boton se vuelve a bloquear para siempre, que es el mismo
    sintoma que el usuario ya reporto dos veces (2026-09-07):

    1. ALGUN PASO EN ERROR => termino. `_paso` (worker/tareas.py) marca el paso
       como error y RE-LANZA, asi que `ejecutar_refresco` corta ahi mismo: es
       imposible que un paso falle y la corrida siga. Los pasos que quedan en
       "pendiente" detras del error no van a moverse nunca. Fue exactamente lo
       que paso al caerse la VPN a Gemma Net: "Leyendo reporte de Gemma Net" en
       error, los otros 9 en pendiente, y el boton devolviendo 409 sobre una
       corrida que habia muerto una hora antes.

    2. SIN WORKER VIVO => tampoco hay nada corriendo. Cubre el caso que el
       punto 1 no puede ver: si el PROCESO muere de golpe (kill, reinicio,
       corte de luz) no hay excepcion que capturar, el paso queda "en_curso"
       para siempre y nadie lo va a cerrar.

    NO se mira `hay_solicitud_pendiente()`, que es lo que hacia POST antes y
    es una pregunta DISTINTA: esa bandera significa "hay una solicitud que el
    worker todavia no recogio", no "hay un refresco corriendo". Usarla como
    guard fallaba en las dos direcciones (defecto reportado por el usuario el
    2026-09-07, con el boton bloqueado y los 10 pasos en "hecho"):

    - Sin worker vivo nadie la borra nunca, asi que el boton devolvia 409
      "ya hay un refresco en curso" PARA SIEMPRE, sobre una corrida que habia
      terminado hacia rato.
    - Con worker vivo la borra a los pocos segundos de escribirse, muchisimo
      antes de que el refresco (~2 min) termine, asi que durante la corrida
      real el guard no protegia nada.

    La proteccion de verdad contra solapamiento no es este 409: es
    `max_instances=1` en el job de apscheduler (ver worker/refresco.py). Este
    guard es para no confundir al usuario, y por eso tiene que responder a lo
    que el usuario ve en la barra de progreso -- los pasos.
    """
    if not worker_activo:
        return False
    if any(p.estado == ESTADO_PASO_ERROR for p in pasos):
        return False
    return any(p.estado != ESTADO_PASO_HECHO for p in pasos)


# Solo administradores (pedido del usuario, 2026-09-14): un refresco es una
# corrida de ~3 min que cambia las cifras de todos; quien consulta no la dispara.
@router.post("", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(exigir_admin)])
def pedir_refresco(
    fuente: str = FUENTE_DEFECTO,
    ruta_sqlite: Path = Depends(ruta_estado),
) -> dict[str, str]:
    """Pide al worker que ejecute un ciclo de refresco ahora, sin esperar su
    intervalo periodico. Devuelve 202 Accepted inmediatamente; el cliente
    sondea el progreso via GET /refrescar/progreso. El worker detecta la
    solicitud en su siguiente ciclo de vigilancia y la ejecuta.

    `fuente` elige de donde sale el catalogo de INVIMA: "api" (Socrata, el
    catalogo de hoy) o "archivos" (los Excel de listados de `data/`). Pedido
    del usuario (2026-09-07): las dos fuentes dan cifras muy distintas y las
    explicaciones ya dadas al negocio estan hechas sobre los archivos, asi que
    la eleccion tiene que ser explicita. Ver `ingesta/fuente_invima.py`.
    """
    if fuente not in FUENTES_VALIDAS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Fuente '{fuente}' desconocida. Validas: {', '.join(FUENTES_VALIDAS)}.",
        )
    # Deshabilitada != desconocida: la API existe pero no se ofrece (decision
    # del usuario, 2026-09-14). Ver FUENTES_HABILITADAS.
    if fuente not in FUENTES_HABILITADAS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"La fuente '{fuente}' esta deshabilitada. Los listados de INVIMA se leen "
                "de la carpeta del servidor (INVIMA_LISTADOS_DIR)."
            ),
        )
    # Un solo `worker_vivo`, compartido por los dos chequeos de abajo: si se
    # consultara dos veces podrian dar distinto (el latido vence entre una y
    # otra) y saldria un 409 "hay un refresco en curso" seguido de un 503 "no
    # hay worker" -- dos respuestas que se contradicen para el mismo clic.
    activo = worker_vivo(ruta=ruta_sqlite)
    if _hay_refresco_en_curso(progreso_actual(ruta=ruta_sqlite), worker_activo=activo):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay un refresco en curso. Espera a que termine.",
        )

    # El backend NO ejecuta el refresco: solo deja la solicitud. Si no hay
    # worker que la recoja, aceptarla seria mentir -- el usuario veria "listo"
    # y esperaria un refresco que nunca va a arrancar. Se dice explicitamente
    # en vez de fallar en silencio.
    if not activo:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "El worker de refresco no esta corriendo, asi que nadie ejecutaria "
                "la actualizacion. Arrancalo con .\\reinicia_worker.ps1 y volve a intentar."
            ),
        )

    # La fuente ANTES de la solicitud: el worker vigila cada 5 s y arranca en
    # cuanto ve la bandera, asi que escribirla despues abre una ventana en la
    # que el refresco ya empezo leyendo la fuente anterior.
    guardar_fuente_refresco(fuente, ruta=ruta_sqlite)
    solicitar_refresco_manual(ruta=ruta_sqlite)

    return {"solicitud": "aceptada", "fuente": fuente}


@router.get("/progreso")
def obtener_progreso_refresco(
    ruta_sqlite: Path = Depends(ruta_estado),
) -> dict[str, object]:
    """Sondea el estado actual del refresco (si hay uno en curso o si termino).
    Lee el DB de estado para obtener el progreso real."""
    pasos = progreso_actual(ruta=ruta_sqlite)

    # Si no hay pasos registrados, aun no se pidio ninguno.
    if not pasos:
        return {"en_curso": False, "pasos": []}

    # Mismo criterio y mismo `worker_vivo` que POST: si los dos endpoints
    # respondieran distinto, la barra de progreso diria "terminado" mientras el
    # boton contesta "hay uno en curso" (o al reves), que es el defecto que se
    # arreglo aca el 2026-09-07.
    return {
        "en_curso": _hay_refresco_en_curso(pasos, worker_activo=worker_vivo(ruta=ruta_sqlite)),
        "pasos": [{"nombre": p.nombre, "estado": p.estado, "detalle": p.detalle} for p in pasos],
    }
