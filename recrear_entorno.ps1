# Script para recrear el entorno virtual desde cero
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  RECREANDO ENTORNO VIRTUAL" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Paso 1: Eliminar entorno virtual existente
Write-Host "[1/5] Eliminando entorno virtual existente..." -ForegroundColor Yellow
if (Test-Path .venv) {
    Remove-Item -Recurse -Force .venv
    Write-Host "  ✓ Entorno virtual eliminado" -ForegroundColor Green
} else {
    Write-Host "  ℹ No existe entorno virtual previo" -ForegroundColor Gray
}

# Paso 2: Crear nuevo entorno virtual
Write-Host "[2/5] Creando nuevo entorno virtual..." -ForegroundColor Yellow
python -m venv .venv
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ Entorno virtual creado" -ForegroundColor Green
} else {
    Write-Host "  ✗ Error creando entorno virtual" -ForegroundColor Red
    exit 1
}

# Paso 3: Actualizar pip
Write-Host "[3/5] Actualizando pip..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Host
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ pip actualizado" -ForegroundColor Green
} else {
    Write-Host "  ✗ Error actualizando pip" -ForegroundColor Red
    exit 1
}

# Paso 4: Instalar dependencias
Write-Host "[4/5] Instalando dependencias desde requirements.txt..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt | Out-Host
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ Dependencias instaladas" -ForegroundColor Green
} else {
    Write-Host "  ✗ Error instalando dependencias" -ForegroundColor Red
    exit 1
}

# Paso 5: Verificar instalación
Write-Host "[5/5] Verificando instalación..." -ForegroundColor Yellow
$flaskCheck = & .\.venv\Scripts\python.exe -c "import flask; print(flask.__version__)" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ Flask instalado correctamente (versión: $flaskCheck)" -ForegroundColor Green
} else {
    Write-Host "  ✗ Flask NO está instalado" -ForegroundColor Red
    Write-Host "  Error: $flaskCheck" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  ✓ ENTORNO VIRTUAL LISTO" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Para ejecutar la aplicación:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe app.py" -ForegroundColor White
Write-Host ""
Write-Host "O activa el entorno y ejecuta:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "  python app.py" -ForegroundColor White
Write-Host ""









