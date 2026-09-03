#!/usr/bin/env pwsh
# Reinicia el worker que actualiza los datos -- mata SOLO los procesos
# python de este proyecto (ver reinicia_backend.ps1 para el porque del
# filtro por linea de comando en vez de matar todos los python.exe).

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

Write-Host "Iniciando worker..." -ForegroundColor Green
Set-Location "c:\Users\TECNOLGO TIC\Documents\gemma-cum-loader"
& python -m worker.refresco
