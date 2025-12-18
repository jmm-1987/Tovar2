-- Migración para agregar columnas de descripción de imágenes a la tabla presupuestos
-- Ejecutar este script en la base de datos PostgreSQL

ALTER TABLE presupuestos ADD COLUMN IF NOT EXISTS descripcion_imagen_1 TEXT;
ALTER TABLE presupuestos ADD COLUMN IF NOT EXISTS descripcion_imagen_2 TEXT;
ALTER TABLE presupuestos ADD COLUMN IF NOT EXISTS descripcion_imagen_3 TEXT;
ALTER TABLE presupuestos ADD COLUMN IF NOT EXISTS descripcion_imagen_4 TEXT;

-- Opcional: Eliminar columnas de imágenes 5 y 6 si existen (ya no se usan)
ALTER TABLE presupuestos DROP COLUMN IF EXISTS imagen_adicional_5;
ALTER TABLE presupuestos DROP COLUMN IF EXISTS imagen_adicional_6;











