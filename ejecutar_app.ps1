# Script para ejecutar la aplicación usando el entorno virtual
Write-Host "=== Ejecutando aplicación Flask ===" -ForegroundColor Cyan

$pythonExe = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Host "ERROR: No se encuentra el entorno virtual en .venv" -ForegroundColor Red
    Write-Host "Ejecuta primero: .\recrear_entorno.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host "Usando Python: $pythonExe" -ForegroundColor Yellow
Write-Host "Verificando dependencias..." -ForegroundColor Yellow

# Verificar e instalar dependencias faltantes
$deps = @("flask")
foreach ($dep in $deps) {
    $check = & $pythonExe -c "import $dep" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Instalando $dep..." -ForegroundColor Yellow
        & $pythonExe -m pip install $dep
    }
}

Write-Host "`n✓ Todas las dependencias están instaladas" -ForegroundColor Green
Write-Host "`nIniciando aplicación Flask..." -ForegroundColor Green
Write-Host "Presiona Ctrl+C para detener`n" -ForegroundColor Gray

# Ejecutar la aplicación
& $pythonExe app.py
