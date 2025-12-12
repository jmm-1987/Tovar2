-- Script SQL para agregar las columnas imagen_adicional_5 y descripcion_imagen_5
-- Ejecutar este script en tu base de datos PostgreSQL

-- Agregar columna imagen_adicional_5 si no existe
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'presupuestos' 
        AND column_name = 'imagen_adicional_5'
    ) THEN
        ALTER TABLE presupuestos ADD COLUMN imagen_adicional_5 VARCHAR(255);
        RAISE NOTICE 'Columna imagen_adicional_5 agregada exitosamente';
    ELSE
        RAISE NOTICE 'Columna imagen_adicional_5 ya existe';
    END IF;
END $$;

-- Agregar columna descripcion_imagen_5 si no existe
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'presupuestos' 
        AND column_name = 'descripcion_imagen_5'
    ) THEN
        ALTER TABLE presupuestos ADD COLUMN descripcion_imagen_5 TEXT;
        RAISE NOTICE 'Columna descripcion_imagen_5 agregada exitosamente';
    ELSE
        RAISE NOTICE 'Columna descripcion_imagen_5 ya existe';
    END IF;
END $$;



