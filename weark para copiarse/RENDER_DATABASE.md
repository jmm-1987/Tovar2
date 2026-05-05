# Configuración de Base de Datos en Render

## ⚠️ IMPORTANTE: Base de Datos Persistente

Para evitar que la base de datos de producción se sobrescriba con la local, debes configurar un **volumen persistente** en Render.

## Opción 1: Usar Volumen Persistente (RECOMENDADO)

1. En el dashboard de Render, ve a tu servicio web
2. Ve a la sección **"Persistent Disk"** o **"Volumes"**
3. Crea un volumen persistente (ej: `/data`)
4. Configura la variable de entorno `DATABASE_PATH` en Render:
   ```
   DATABASE_PATH=/data/pedidos.db
   ```

## Opción 2: Usar Variable de Entorno

Si no puedes usar volúmenes persistentes, configura `DATABASE_PATH` en Render con una ruta absoluta:

1. Ve a tu servicio en Render
2. Ve a **"Environment"** → **"Environment Variables"**
3. Agrega:
   ```
   DATABASE_PATH=/opt/render/project/src/pedidos.db
   ```

**Nota**: Esta opción puede perder datos si Render reinicia el servicio, ya que el sistema de archivos es efímero.

## Verificación

Después de configurar, verifica en los logs de Render que aparezca:
```
[PRODUCCION] Usando base de datos en: /ruta/configurada/pedidos.db
```

## Backup de Base de Datos

Para hacer backup de la base de datos de producción:

1. Usa la función "Descargar BD" desde la aplicación (si está disponible)
2. O conecta por SSH a Render y copia el archivo `.db`

## Prevención de Sobrescritura

- ✅ La base de datos local (`instance/pedidos.db`) está en `.gitignore`
- ✅ El código detecta automáticamente si está en producción
- ✅ En producción usa una ruta diferente por defecto
- ⚠️ **DEBES configurar `DATABASE_PATH` en Render para usar un volumen persistente**

