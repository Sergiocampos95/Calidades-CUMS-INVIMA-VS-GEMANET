# Instala los hooks de git del proyecto.
#
# Los hooks viven en scripts/ (versionados, se revisan como cualquier codigo)
# y este script los copia a .git/hooks/, que NO se versiona. Hay que correrlo
# una vez por clon.
#
# Uso:  .\scripts\instalar-hooks.ps1

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$destino = Join-Path $raiz ".git\hooks"

if (-not (Test-Path $destino)) {
    Write-Host "[X] No encuentro .git\hooks -- ¿estas dentro del repositorio?" -ForegroundColor Red
    exit 1
}

foreach ($hook in @("pre-push")) {
    $origen = Join-Path $PSScriptRoot $hook
    if (-not (Test-Path $origen)) { continue }
    Copy-Item $origen (Join-Path $destino $hook) -Force
    Write-Host "[OK] $hook instalado" -ForegroundColor Green
}

Write-Host ""
Write-Host "Los hooks corren pytest + ruff + tsc antes de cada push."
Write-Host "Para saltarlos en un caso puntual: git push --no-verify"
