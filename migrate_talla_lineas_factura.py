"""Script de migración para agregar columna talla a lineas_factura"""
import sqlite3
import os
from pathlib import Path

# Obtener ruta de la base de datos
database_path = os.environ.get('DATABASE_PATH', 'instance/pedidos.db')

# Convertir a ruta absoluta si es relativa
if not os.path.isabs(database_path):
    database_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), database_path)

database_path = os.path.normpath(database_path)

print(f"Migrando base de datos: {database_path}")

if not os.path.exists(database_path):
    print(f"Error: No se encontró la base de datos en {database_path}")
    exit(1)

try:
    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()
    
    # Verificar si la columna ya existe
    cursor.execute("PRAGMA table_info(lineas_factura)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'talla' in columns:
        print("La columna 'talla' ya existe en lineas_factura. No se necesita migración.")
    else:
        # Agregar la columna talla
        cursor.execute("ALTER TABLE lineas_factura ADD COLUMN talla VARCHAR(20)")
        conn.commit()
        print("✓ Migración exitosa: Columna 'talla' agregada a lineas_factura")
    
    conn.close()
    print("Migración completada correctamente.")
    
except Exception as e:
    print(f"Error durante la migración: {e}")
    import traceback
    traceback.print_exc()
    exit(1)








