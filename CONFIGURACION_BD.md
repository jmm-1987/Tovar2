# Configuración de la Base de Datos

## Ubicación de la Configuración

La configuración de la base de datos se encuentra en el archivo **`app.py`** en las líneas **26-40**.

```26:40:app.py
# Configuración de la base de datos SQLite
# Usar DATABASE_PATH para especificar la ruta del archivo SQLite (opcional)
# Si no se especifica, se usa una base de datos por defecto en instance/
database_path = os.environ.get('DATABASE_PATH', 'instance/pedidos.db')

# Asegurar que el directorio instance existe
os.makedirs(os.path.dirname(database_path), exist_ok=True)

# Configurar URI de SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{database_path}'

# Configuración de SQLite
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {'check_same_thread': False},  # Permitir conexiones desde múltiples threads
}
```

## Variables de Entorno

La aplicación utiliza SQLite como base de datos. La variable de entorno **`DATABASE_PATH`** es opcional y permite especificar una ruta personalizada para el archivo de base de datos.

### Configuración Local

Por defecto, la aplicación crea la base de datos en `instance/pedidos.db`. No es necesario configurar nada adicional.

Si deseas usar una ruta diferente, crea un archivo `.env` en la raíz del proyecto (copia `env.example` como base) y agrega:

```env
DATABASE_PATH=instance/pedidos.db
```

### Configuración en Producción (Render)

En producción, la base de datos SQLite se almacena en el sistema de archivos del servicio. Por defecto se usa `instance/pedidos.db`.

**IMPORTANTE**: En Render, los archivos en el sistema de archivos son efímeros y se pierden al reiniciar el servicio. Para producción, considera:

1. Usar un volumen persistente si Render lo soporta
2. Implementar backups automáticos de la base de datos
3. O considerar usar un servicio de base de datos externo

## Migración desde PostgreSQL

Si estás migrando desde PostgreSQL y necesitas conservar los datos de clientes:

1. **Exportar datos desde PostgreSQL**:
   ```bash
   python exportar_clientes_postgresql.py
   ```
   Esto creará un archivo `clientes_exportados.json` con todos los datos de clientes.

2. **Importar datos a SQLite**:
   ```bash
   python importar_clientes_sqlite.py
   ```
   Esto importará los datos desde el JSON a la nueva base de datos SQLite.

**Nota**: Solo se migran los datos de clientes. Todos los demás datos (pedidos, presupuestos, facturas, etc.) se perderán y deberás crearlos de nuevo.

## Verificar la Configuración

Para verificar que la base de datos está configurada correctamente:

1. **Localmente**: Ejecuta la aplicación y verifica que se crea el archivo `instance/pedidos.db`
2. **En producción**: Verifica los logs de la aplicación para confirmar que la base de datos se crea correctamente

## Ventajas de SQLite

- **Simplicidad**: No requiere servidor de base de datos separado
- **Portabilidad**: La base de datos es un solo archivo fácil de respaldar
- **Rendimiento**: Excelente para aplicaciones de tamaño pequeño a mediano
- **Sin configuración**: Funciona inmediatamente sin configuración adicional

## Limitaciones de SQLite

- **Concurrencia**: Limitada comparada con PostgreSQL
- **Tamaño**: Recomendado para bases de datos menores a 100GB
- **Características avanzadas**: No soporta todas las características de PostgreSQL

Para esta aplicación, SQLite es adecuado para la mayoría de casos de uso.
