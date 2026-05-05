@echo off
REM Script para ejecutar la aplicación usando el entorno virtual (Windows CMD)
echo === Ejecutando aplicacion Flask ===

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: No se encuentra el entorno virtual en .venv
    echo Ejecuta primero: recrear_entorno.ps1
    pause
    exit /b 1
)

echo Usando Python: .venv\Scripts\python.exe
echo Verificando dependencias...

echo.
echo Iniciando aplicacion Flask...
echo Presiona Ctrl+C para detener
echo.

REM Ejecutar la aplicación
.venv\Scripts\python.exe app.py

pause

