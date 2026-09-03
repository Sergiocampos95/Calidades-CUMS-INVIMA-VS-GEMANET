# Reinicio completo del entorno de desarrollo.
#   .\reinicia_todo.ps1            backend + refresco + frontend
#   .\reinicia_todo.ps1 -SinRefresco   omite el refresco (~2 min) si el snapshot ya sirve
#
# Por que existe: tras tocar src/ o backend/ hacen falta CUATRO cosas, y
# olvidar una sola hace que la pantalla siga mostrando lo viejo sin avisar
# (pedido del usuario 2026-09-02: "ya es molesto desarrollar asi"):
#   1. matar el python viejo            -- si no, el puerto sigue tomado
#   2. borrar __pycache__               -- si no, se sirve el .pyc anterior
#   3. refrescar el snapshot            -- si no, faltan las COLUMNAS nuevas
#   4. tener el frontend vivo en 5173   -- si no, se ve una pagina rancia
param([switch]$SinRefresco)

$ErrorActionPreference = "Stop"
$raiz = $PSScriptRoot
Set-Location $raiz

# La consola de Windows es cp1252: un emoji en un print de Python revienta el
# proceso con UnicodeEncodeError (fallo real, 2026-09-02). Se fuerza UTF-8 y
# todo lo que imprime este script es ASCII.
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

function Paso($texto) { Write-Host "[*] $texto" -ForegroundColor Cyan }

# Se mira quien ESCUCHA el puerto, no se intenta conectar: vite se enlaza a
# ::1 (IPv6) y un TcpClient sobre "localhost" resuelve a 127.0.0.1 primero,
# asi que daba "libre" con vite corriendo -- y el script levantaba un segundo
# vite en 5174 mientras el navegador seguia en 5173 (medido, 2026-09-02).
function Test-Puerto($puerto) {
  return $null -ne (Get-NetTCPConnection -State Listen -LocalPort $puerto -ErrorAction SilentlyContinue)
}

# --- 1. Procesos ---------------------------------------------------------
Paso "Deteniendo backend anterior"
# Se mata por DUEÑO DEL PUERTO, no por linea de comando: un uvicorn arrancado
# de otra forma (otra shell, otra sesion, un reloader huerfano) no matchea el
# filtro de CommandLine, sobrevive, y el uvicorn nuevo muere con
# "[Errno 10048] solo se permite un uso de cada direccion de socket" -- pero
# el puerto SIGUE respondiendo, asi que parece que arranco bien y en realidad
# se esta sirviendo el codigo viejo (pasado de verdad, 2026-09-02: la ruta
# nueva daba 404 contra un backend "arriba").
foreach ($conexion in Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) {
  Stop-Process -Id $conexion.OwningProcess -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
if (Test-Puerto 8000) {
  Write-Host "[X] El puerto 8000 sigue ocupado. Cerra el proceso a mano antes de seguir." -ForegroundColor Red
  exit 1
}

# --- 2. Cache ------------------------------------------------------------
Paso "Limpiando __pycache__ y .pyc"
Get-ChildItem -Path $raiz -Filter "__pycache__" -Recurse -Directory -Force -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $raiz -Filter "*.pyc" -Recurse -File -Force -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue

# --- 3. Refresco ---------------------------------------------------------
# OJO: ejecutar_refresco() NO lanza excepcion cuando falla -- registra
# ESTADO_ERROR y devuelve el estado. Mirar $LASTEXITCODE daria "todo bien"
# sobre un refresco roto, que es justo el fallo silencioso que el proyecto
# prohibe. Por eso se inspecciona el estado devuelto y se sale con codigo 1.
if (-not $SinRefresco) {
  Paso "Refrescando snapshot (~2 min)"
  python -c @"
from pathlib import Path
import sys
from worker.tareas import ejecutar_refresco
from worker.estado import ESTADO_OK
from worker.almacen_snapshots import desfases_de_esquema

estado = ejecutar_refresco(ruta_estado=Path('data_runtime/estado.sqlite3'))
if estado.estado != ESTADO_OK:
    print('[ERROR] Refresco fallido: ' + (estado.detalle_error or 'sin detalle'))
    sys.exit(1)
desfases = desfases_de_esquema(carpeta=Path('data_runtime/snapshots'))
if desfases:
    print('[ERROR] El snapshot quedo con columnas desfasadas: ' + repr(desfases))
    sys.exit(1)
print('[OK] Snapshot al dia (%.0f s)' % estado.duracion_segundos)
"@
  if ($LASTEXITCODE -ne 0) {
    Write-Host "[X] El refresco fallo. No se levanta el backend sobre datos malos." -ForegroundColor Red
    exit 1
  }
}

# --- 4. Frontend ---------------------------------------------------------
# Si 5173 ya responde se REUSA. Arrancar otro vite no falla: se va a 5174 en
# silencio, y entonces el navegador del usuario sigue en 5173 mirando otra
# instancia (paso de verdad, 2026-09-02).
if (Test-Puerto 5173) {
  Paso "Frontend ya vivo en 5173 (se reusa)"
} else {
  Paso "Levantando frontend en 5173"
  Start-Process -FilePath "npm" -ArgumentList "run", "dev" -WorkingDirectory (Join-Path $raiz "frontend") -WindowStyle Minimized
}

# --- 5. Backend ----------------------------------------------------------
Write-Host ""
Write-Host "Backend  -> http://localhost:8000" -ForegroundColor Green
Write-Host "Frontend -> http://localhost:5173  (recarga con Ctrl+F5)" -ForegroundColor Green
Write-Host ""
python -m uvicorn backend.app.main:app --reload --port 8000
