#!/usr/bin/env python
"""
Script de migración para hacer nullable la columna prenda_id en lineas_presupuesto
Ejecutar con: python migrate_prenda_id.py
"""
import sys
import os

# Agregar el directorio del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from sqlalchemy import text, inspect
import re

def migrate_prenda_id():
    """Migrar prenda_id a nullable en lineas_presupuesto"""
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            table_names = inspector.get_table_names()
            
            if 'lineas_presupuesto' not in table_names:
                print("La tabla lineas_presupuesto no existe. No hay nada que migrar.")
                return
            
            # Verificar estructura actual
            test_result = db.session.execute(text('''
                SELECT sql FROM sqlite_master 
                WHERE type='table' AND name='lineas_presupuesto'
            ''')).fetchone()
            
            if test_result and test_result[0]:
                sql_create = test_result[0].upper()
                # Verificar si ya es nullable
                pattern = r'PRENDA_ID\s+INTEGER\s+NOT\s+NULL'
                if not re.search(pattern, sql_create):
                    print("La columna prenda_id ya es nullable. No se necesita migración.")
                    return
            
            print("Iniciando migración de prenda_id a nullable...")
            
            with db.engine.connect() as conn:
                # Desactivar temporalmente las foreign keys
                conn.execute(text('PRAGMA foreign_keys = OFF'))
                
                # Crear tabla temporal con la estructura correcta (prenda_id nullable)
                conn.execute(text('''
                    CREATE TABLE lineas_presupuesto_temp (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        presupuesto_id INTEGER NOT NULL,
                        prenda_id INTEGER,
                        nombre VARCHAR(200) NOT NULL,
                        cargo VARCHAR(100),
                        nombre_mostrar VARCHAR(200),
                        cantidad INTEGER NOT NULL DEFAULT 1,
                        color VARCHAR(50),
                        forma VARCHAR(100),
                        tipo_manda VARCHAR(100),
                        sexo VARCHAR(20),
                        talla VARCHAR(20),
                        tejido VARCHAR(100),
                        precio_unitario NUMERIC(10, 2),
                        descuento NUMERIC(5, 2) NOT NULL DEFAULT 0,
                        precio_final NUMERIC(10, 2),
                        estado VARCHAR(50) NOT NULL DEFAULT 'pendiente',
                        FOREIGN KEY (presupuesto_id) REFERENCES presupuestos(id),
                        FOREIGN KEY (prenda_id) REFERENCES prendas(id)
                    )
                '''))
                
                # Obtener columnas existentes
                columns_originales = [col['name'] for col in inspector.get_columns('lineas_presupuesto')]
                
                # Construir la lista de columnas a copiar
                columnas_copiar = ['id', 'presupuesto_id', 'prenda_id', 'nombre', 'cargo', 'nombre_mostrar', 
                                 'cantidad', 'color', 'forma', 'tipo_manda', 'sexo', 'talla', 'tejido', 
                                 'precio_unitario', 'descuento', 'precio_final', 'estado']
                
                # Filtrar columnas que existen en la tabla original
                columnas_existentes = [col for col in columnas_copiar if col in columns_originales]
                
                # Construir la consulta INSERT dinámicamente
                columnas_str = ', '.join(columnas_existentes)
                conn.execute(text(f'''
                    INSERT INTO lineas_presupuesto_temp ({columnas_str})
                    SELECT {columnas_str}
                    FROM lineas_presupuesto
                '''))
                
                # Eliminar tabla antigua
                conn.execute(text('DROP TABLE lineas_presupuesto'))
                
                # Renombrar tabla temporal
                conn.execute(text('ALTER TABLE lineas_presupuesto_temp RENAME TO lineas_presupuesto'))
                
                # Reactivar foreign keys
                conn.execute(text('PRAGMA foreign_keys = ON'))
                
                conn.commit()
                print("✓ Migración completada exitosamente. La columna prenda_id ahora es nullable.")
                
        except Exception as e:
            print(f"✗ Error durante la migración: {e}")
            import traceback
            traceback.print_exc()
            # Intentar reactivar foreign keys en caso de error
            try:
                with db.engine.connect() as conn:
                    conn.execute(text('PRAGMA foreign_keys = ON'))
                    conn.commit()
            except:
                pass
            return False
    
    return True

if __name__ == '__main__':
    print("=" * 60)
    print("Migración de prenda_id en lineas_presupuesto")
    print("=" * 60)
    success = migrate_prenda_id()
    if success:
        print("\n✓ Migración completada. Puedes crear solicitudes ahora.")
    else:
        print("\n✗ La migración falló. Revisa los errores arriba.")
    sys.exit(0 if success else 1)




