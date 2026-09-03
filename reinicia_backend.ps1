#!/usr/bin/env pwsh
# Mata SOLO los procesos python de ESTE proyecto (backend + worker + la
# Streamlit obsoleta, si quedo viva) y reinicia el backend.
#
# Corregido (2026-09-01): la version anterior hacia
# `Get-Process python | Stop-Process -Force` -- mataba TODOS los python.exe
# de la maquina, sin distinguir de cual proceso se trataba. En una sesion de
# trabajo real eso se llevaba por delante cualquier otro proceso Python que
# el usuario tuviera corriendo (otro proyecto, Jupyter, etc.), y si dos
# reinicios se pisaban quedaban procesos huerfanos duplicados (dos backends,
# dos workers escuchando el mismo puerto/senal) -- exactamente el sintoma
# reportado por el usuario: "se pierde la conexion de la aplicacion vite con
# el backend, esto no deberia pasar". El filtro por linea de comando mata
# solo lo que este script mismo va a volver a levantar.

Write-Host "Buscando procesos Python de este proyecto..." -ForegroundColor Yellow
$procesos = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -match 'uvicorn backend\.app\.main' `
        -or $_.CommandLine -match 'worker\.refresco' `
        -or $_.CommandLine -match 'streamlit run'
}
if ($procesos) {
    $procesos | ForEach-Object {
        Write-Host "  Matando PID $($_.ProcessId): $($_.CommandLine)" -ForegroundColor DarkYellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
} else {
    Write-Host "  Ninguno corriendo." -ForegroundColor DarkGray
}

Write-Host "Limpiando cache..." -ForegroundColor Yellow
Get-ChildItem -Path . -Recurse -Directory -Filter __pycache__ -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Iniciando backend en puerto 8000..." -ForegroundColor Green
Set-Location "c:\Users\TECNOLGO TIC\Documents\gemma-cum-loader"
& python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --log-level info
