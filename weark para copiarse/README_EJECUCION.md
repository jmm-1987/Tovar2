# Cómo ejecutar la aplicación

## Método 1: Usando el script PowerShell (Recomendado)

```powershell
.\ejecutar_app.ps1
```

Este script:
- Verifica que el entorno virtual exista
- Instala automáticamente las dependencias faltantes
- Ejecuta la aplicación usando el Python del entorno virtual

## Método 2: Usando el script Batch (Windows CMD)

```cmd
ejecutar_app.bat
```

## Método 3: Manualmente

```powershell
# 1. Activar el entorno virtual
.\.venv\Scripts\Activate.ps1

# 2. Verificar/instalar dependencias
python -m pip install -r requirements.txt

# 3. Ejecutar la aplicación
python app.py
```

## Método 4: Directamente con el Python del entorno virtual

```powershell
.\.venv\Scripts\python.exe app.py
```

## Configuración de VS Code

Si usas VS Code, el archivo `.vscode/settings.json` ya está configurado para usar el entorno virtual automáticamente.

Para configurar manualmente:
1. Presiona `Ctrl+Shift+P`
2. Busca "Python: Select Interpreter"
3. Selecciona: `.venv\Scripts\python.exe`

## Solución de problemas

Si ves errores de módulos no encontrados:
1. Asegúrate de que el entorno virtual esté activo
2. Ejecuta: `python -m pip install -r requirements.txt`
3. Verifica que estás usando el Python correcto: `where.exe python`

