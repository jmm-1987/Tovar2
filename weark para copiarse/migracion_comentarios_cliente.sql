-- Migración: Añadir columna comentarios_cliente a la tabla presupuestos
-- Ejecutar este script en la base de datos SQLite

-- Añadir columna comentarios_cliente (TEXT, nullable)
ALTER TABLE presupuestos ADD COLUMN comentarios_cliente TEXT;

