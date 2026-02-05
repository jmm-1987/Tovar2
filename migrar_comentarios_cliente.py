#!/usr/bin/env python3
"""
Script para añadir la columna comentarios_cliente a la tabla presupuestos
Ejecutar: python migrar_comentarios_cliente.py
"""

import sqlite3
import os
import sys

# Ruta de la base de datos
database_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'pedidos.db')

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
        cursor.execute("ALTER TABLE presupuestos ADD COLUMN comentarios_cliente TEXT")
        conn.commit()
        print("✓ Columna 'comentarios_cliente' añadida exitosamente a la tabla presupuestos")
    
    conn.close()
    print("Migración completada correctamente")
    
except sqlite3.Error as e:
    print(f"Error al ejecutar la migración: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error inesperado: {e}")
    sys.exit(1)

