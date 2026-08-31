#!/usr/bin/env pwsh
# Mata todos los procesos python que usen puerto 8000 y reinicia el backend

Write-Host "Matando procesos Python..." -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "Limpiando cache..." -ForegroundColor Yellow
Get-ChildItem -Path . -Recurse -Directory -Filter __pycache__ -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Iniciando backend en puerto 8000..." -ForegroundColor Green
Set-Location "c:\Users\TECNOLGO TIC\Documents\gemma-cum-loader"
& python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --log-level info
