"""Lee el reporte de medicamentos directamente de la base de Gemma Net.

Reemplaza el archivo que hoy alguien exporta a mano desde la plataforma
(Mantenimientos > Basicas Atencion > Medicamentos > Crear Masivos > Exportar)
por una consulta a `administrativo.tb_medicamento`.

POR QUE IMPORTA MAS QUE AHORRAR UN PASO -- el Excel exportado introduce
defectos que la base no tiene, todos medidos el 2026-08-20:

  - **131 filas con las columnas corridas** (POS trae presentaciones,
    EDAD_MINIMA trae expedientes). Imposible en SQL: cada columna tiene tipo.
  - **`CLASIFICADO` como "Si"/"No"** en vez del `sw_resolucion` smallint, lo
    que provocaba 199.590 falsos positivos de "fuera de dominio".
  - **87 filas sin CODIGO_INTERNO** que se contaban entre si como duplicadas.

Lo que el archivo y la base SI comparten son las fechas comodin
(`1900-01-01`, `2999-12-31`): son dato real de Gemma Net, residuo de su
migracion a la nube, no un artefacto del export.

El mapeo de columnas se verifico fila por fila contra el export del
2026-08-12, incluido el modelo de servicio, que no vive en `tb_medicamento`
sino en `tb_medicamento_nota_tecnica` -> `tb_concepto_nota_tecnica`.
"""

from __future__ import annotations

import pandas as pd

from gemma_cum_loader.armado.cruce_gemanet import ReporteGemaNet
from gemma_cum_loader.integraciones import gemanet_db

# Los nombres de salida son EXACTAMENTE los del archivo exportado, para que
# nada aguas abajo (auditoria, cruce, exportacion) note de donde vino el dato.
# sw_* son banderas 0/1 en la base y texto "Si"/"No" en el export: se traducen
# aqui, en SQL, y no en pandas, para no recorrer 200.000 filas dos veces.
SQL_REPORTE_GEMANET = """
WITH nota AS (
    -- DISTINCT ON y no un LATERAL con LIMIT 1 por fila: el LATERAL se
    -- ejecutaba una vez por cada uno de los 199.608 medicamentos y la
    -- consulta moria por statement_timeout. Asi la tabla de enlace se
    -- recorre UNA vez y se queda la primera nota tecnica por secuencia,
    -- que es la que trae el export.
    SELECT DISTINCT ON (mnt.consecutivo_medicamento)
           mnt.consecutivo_medicamento,
           c.codigo_interno
    FROM administrativo.tb_medicamento_nota_tecnica mnt
    JOIN administrativo.tb_concepto_nota_tecnica c
         ON c.consecutivo_concepto = mnt.consecutivo_concepto
    ORDER BY mnt.consecutivo_medicamento, mnt.secuencia
)
SELECT
    m.codigo_interno                                    AS "CODIGO_INTERNO",
    m.descripcion                                       AS "DESCRIPCION",
    m.grupo_medicamento                                 AS "GRUPO_MEDICAMENTO",
    m.concentracion                                     AS "CONCENTRACION",
    CASE WHEN m.sw_pos = 1 THEN 'Si' ELSE 'No' END      AS "POS",
    -- MAPEO INCOMPLETO, a proposito y documentado: el export trae ademas
    -- "Medicamento Ancestral" (12 filas) y "Si" (7), y `sw_resolucion` da
    -- "No" en las 199.608. Esas 19 filas salen de otra parte que aun no
    -- identificamos. Se deja el mapeo parcial en vez de adivinar la columna:
    -- 19 filas mal clasificadas serian un hallazgo falso, no un dato.
    CASE WHEN m.sw_resolucion = 1 THEN 'Si' ELSE 'No' END AS "CLASIFICADO",
    m.marca_medicamento                                 AS "MARCA_MEDICAMENTO",
    m.expediente                                        AS "EXPEDIENTE",
    m.consecutivo                                       AS "CONSECUTIVO",
    m.edad_minima                                       AS "EDAD_MINIMA",
    m.edad_maxima                                       AS "EDAD_MAXIMA",
    m.maximo_veces_dias                                 AS "MAXIMA_VECES_DIA",
    m.maximo_veces_mes                                  AS "MAXIMA_VECES_MESES",
    m.maximo_veces_ano                                  AS "MAXIMA_VECES_ANO",
    m.maximo_veces_vida                                 AS "MAXIMA_VECES_VIDA",
    m.tiempo_limite_dias                                AS "TIEMPO_LIMITE_DIAS",
    CASE WHEN m.sw_cres = 1 THEN 'Si' ELSE 'No' END     AS "CRES",
    CASE WHEN m.sw_copago = 1 THEN 'Si' ELSE 'No' END   AS "GENERA_COPAGO_RS",
    CASE WHEN m.sw_genera_copago_rc = 1 THEN 'Si' ELSE 'No' END AS "GENERA_COPAGO_RC",
    CASE WHEN m.sw_genera_cuota_moderadora = 1 THEN 'Si' ELSE 'No' END AS "GENERA_CUOTA_MODERADORA",
    CASE WHEN m.sw_activo = 1 THEN 'Si' ELSE 'No' END   AS "ACTIVO",
    m.posologia                                         AS "POSOLOGIA",
    m.dia                                               AS "DIAS",
    m.consecutivo_unidad_medida                         AS "UNIDAD_MEDIDA",
    CASE WHEN m.sw_automatico = 1 THEN 'Si' ELSE 'No' END AS "AUTOMATICO",
    CASE WHEN m.sw_cambio_cantidad = 1 THEN 'Si' ELSE 'No' END AS "CAMBIO_CANTIDAD",
    m.valor                                             AS "VALOR",
    CASE WHEN m.sw_regulado = 1 THEN 'Si' ELSE 'No' END AS "REGULADO",
    m.valor_regulado                                    AS "VALOR_REGULADO",
    CASE WHEN m.sw_restringido = 1 THEN 'Si' ELSE 'No' END AS "RESTRINGIDO",
    m.forma_farmaceutica                                AS "FORMA_FARMACEUTICA",
    m.principio_activo                                  AS "PRINCIPIO_ACTIVO",
    m.codigo_atc                                        AS "CODIGO_ATC",
    m.fecha_inicio                                      AS "FECHA_INICIO",
    m.fecha_fin                                         AS "FECHA_FIN",
    nt.codigo_interno                                   AS "CODIGO_INTERNO_MODELO_SERVICIO",
    -- La base guarda 1/2/3/4; el export los renderiza como "Nivel 1"... y el
    -- dominio valido esta declarado con ese texto. Sin traducir, las 4.031
    -- filas con nivel asignado salian como "fuera de dominio".
    CASE
        WHEN m.consecutivo_nivel_servicio IS NULL THEN NULL
        ELSE 'Nivel ' || m.consecutivo_nivel_servicio::text
    END                                                 AS "CODIGO_NIVEL_SERVICIO"
FROM administrativo.tb_medicamento m
LEFT JOIN nota nt ON nt.consecutivo_medicamento = m.medicamento
"""

# 200.000 filas x 37 columnas por red: hay que subir el tope y dar aire al
# servidor. Sigue siendo una consulta acotada, no un barrido libre.
TOPE_FILAS_REPORTE = 500_000
TIMEOUT_REPORTE_MS = 180_000


def leer_reporte_gemanet_db(conexion: gemanet_db.Conexion | None = None) -> ReporteGemaNet:
    """El reporte de Gemma Net, leido de su base en vez de un Excel.

    Devuelve un `ReporteGemaNet` igual que `leer_reporte_gemanet`, para que
    el resto del pipeline no distinga la procedencia. `advertencias` viene
    vacia a proposito: las que produce el lector de archivos son sobre lineas
    mal delimitadas y columnas corridas, problemas que en SQL no existen.
    """
    filas = gemanet_db.consultar(
        SQL_REPORTE_GEMANET,
        conexion=conexion,
        timeout_ms=TIMEOUT_REPORTE_MS,
        tope_filas=TOPE_FILAS_REPORTE,
    )
    columnas = [
        linea.split(' AS "')[1].rstrip('",')
        for linea in SQL_REPORTE_GEMANET.splitlines()
        if ' AS "' in linea
    ]
    df = pd.DataFrame(filas, columns=columnas)
    return ReporteGemaNet(
        df=df,
        advertencias=[],
        lineas_omitidas_tokens=[],
        delimitador="",
    )
