#!/usr/bin/env python3
"""
Script para ejecutar la migración de comentarios_cliente
Ejecutar desde el directorio del proyecto: python ejecutar_migracion.py
"""

import sys
import os

# Añadir el directorio del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Importar la aplicación Flask
from app import app
import sqlite3

with app.app_context():
    # Obtener la ruta de la base de datos desde la configuración
    database_uri = app.config['SQLALCHEMY_DATABASE_URI']
    # Extraer la ruta del archivo (sqlite:///ruta/archivo.db)
    database_path = database_uri.replace('sqlite:///', '').replace('sqlite:///', '')
    
    print(f"Conectando a la base de datos: {database_path}")
    
    if not os.path.exists(database_path):
        print(f"Error: No se encontró la base de datos en {database_path}")
        sys.exit(1)
    
    try:
        # Conectar a la base de datos
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()
        
        # Verificar si la columna ya existe
        cursor.execute("PRAGMA table_info(presupuestos)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'comentarios_cliente' in columns:
            print("✓ La columna 'comentarios_cliente' ya existe en la tabla presupuestos")
        else:
            # Añadir la columna
            print("Añadiendo columna comentarios_cliente...")
            cursor.execute("ALTER TABLE presupuestos ADD COLUMN comentarios_cliente TEXT")
            conn.commit()
            print("✓ Columna 'comentarios_cliente' añadida exitosamente")
        
        conn.close()
        print("Migración completada correctamente")
        
    except sqlite3.Error as e:
        print(f"Error al ejecutar la migración: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

