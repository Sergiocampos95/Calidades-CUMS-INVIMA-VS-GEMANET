#!/usr/bin/env pwsh
# Reinicia el worker que actualiza los datos

Write-Host "Matando procesos Python..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "Limpiando cache..." -ForegroundColor Yellow
Get-ChildItem -Path . -Recurse -Directory -Filter __pycache__ -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Iniciando worker..." -ForegroundColor Green
Set-Location "c:\Users\TECNOLGO TIC\Documents\gemma-cum-loader"
& python -m worker.refresco
