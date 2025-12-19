-- Script SQL para agregar las columnas móvil y fecha_alta a la tabla clientes
-- Ejecutar este script en tu base de datos PostgreSQL

-- Agregar columna móvil si no existe
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'clientes' 
        AND column_name = 'movil'
    ) THEN
        ALTER TABLE clientes ADD COLUMN movil VARCHAR(50);
        RAISE NOTICE 'Columna movil agregada exitosamente';
    ELSE
        RAISE NOTICE 'Columna movil ya existe';
    END IF;
END $$;

-- Agregar columna fecha_alta si no existe
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'clientes' 
        AND column_name = 'fecha_alta'
    ) THEN
        ALTER TABLE clientes ADD COLUMN fecha_alta DATE;
        RAISE NOTICE 'Columna fecha_alta agregada exitosamente';
    ELSE
        RAISE NOTICE 'Columna fecha_alta ya existe';
    END IF;
END $$;












