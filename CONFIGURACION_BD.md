# Configuración de la Base de Datos

## Ubicación de la Configuración

La configuración de la base de datos se encuentra en el archivo **`app.py`** en las líneas **26-40**.

```26:40:app.py
# Configuración de la base de datos PostgreSQL
# Usar DATABASE_URL (misma para local y producción)
database_url = os.environ.get('DATABASE_URL')
if not database_url:
    raise ValueError(
        "DATABASE_URL no está configurada. "
        "Por favor, configura la variable de entorno DATABASE_URL con la URL completa de PostgreSQL. "
        "Ejemplo: postgresql://usuario:password@host:puerto/nombre_base_datos"
    )

# Render usa postgres:// pero SQLAlchemy necesita postgresql://
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
```

## Variables de Entorno

La aplicación utiliza la variable de entorno **`DATABASE_URL`** para conectarse a PostgreSQL.

### Configuración Local

1. Crea un archivo `.env` en la raíz del proyecto (copia `env.example` como base)
2. Agrega la siguiente línea con tus credenciales:

```env
DATABASE_URL=postgresql://usuario:password@localhost:5432/nombre_bd
```

### Configuración en Producción (Render)

En Render, la variable `DATABASE_URL` se configura automáticamente cuando:
1. Creas una base de datos PostgreSQL en Render Dashboard
2. Render añade automáticamente la variable `DATABASE_URL` a tu servicio web

**Nota**: Render usa el formato `postgres://` pero el código lo convierte automáticamente a `postgresql://` que es el formato requerido por SQLAlchemy.

## Verificar la Configuración

Para verificar que la base de datos está configurada correctamente:

1. **Localmente**: Verifica que el archivo `.env` existe y contiene `DATABASE_URL`
2. **En producción**: Verifica en Render Dashboard → Environment que existe la variable `DATABASE_URL`

## Formato de la URL

El formato de `DATABASE_URL` es:
```
postgresql://[usuario]:[password]@[host]:[puerto]/[nombre_base_datos]
```

Ejemplo:
```
postgresql://admin:mi_password123@localhost:5432/tovar_db
```












