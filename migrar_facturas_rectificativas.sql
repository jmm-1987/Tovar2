-- Migración para añadir campos de facturas rectificativas
-- Ejecutar este script si las columnas no se crean automáticamente

-- Añadir columna es_rectificativa (BOOLEAN en SQLite se representa como INTEGER)
ALTER TABLE facturas ADD COLUMN es_rectificativa INTEGER DEFAULT 0 NOT NULL;

-- Añadir columna factura_rectificada_id (Foreign Key a la factura original)
ALTER TABLE facturas ADD COLUMN factura_rectificada_id INTEGER;

