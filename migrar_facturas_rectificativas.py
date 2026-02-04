#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script para migrar la base de datos añadiendo columnas de facturas rectificativas
Ejecutar: python migrar_facturas_rectificativas.py
"""

from app import app, db
from sqlalchemy import inspect, text

def migrar_facturas_rectificativas():
    """Añadir columnas es_rectificativa y factura_rectificada_id a la tabla facturas"""
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            table_names = inspector.get_table_names()
            
            if 'facturas' in table_names:
                columns_facturas = [col['name'] for col in inspector.get_columns('facturas')]
                
                # Añadir columna es_rectificativa
                if 'es_rectificativa' not in columns_facturas:
                    try:
                        with db.engine.connect() as conn:
                            # SQLite usa INTEGER para BOOLEAN (0 o 1)
                            conn.execute(text('ALTER TABLE facturas ADD COLUMN es_rectificativa INTEGER DEFAULT 0 NOT NULL'))
                            conn.commit()
                            print("✓ Columna es_rectificativa agregada exitosamente a facturas")
                    except Exception as e:
                        print(f"✗ Error al agregar columna es_rectificativa a facturas: {e}")
                else:
                    print("✓ Columna es_rectificativa ya existe en facturas")
                
                # Añadir columna factura_rectificada_id
                if 'factura_rectificada_id' not in columns_facturas:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text('ALTER TABLE facturas ADD COLUMN factura_rectificada_id INTEGER'))
                            conn.commit()
                            print("✓ Columna factura_rectificada_id agregada exitosamente a facturas")
                    except Exception as e:
                        print(f"✗ Error al agregar columna factura_rectificada_id a facturas: {e}")
                else:
                    print("✓ Columna factura_rectificada_id ya existe en facturas")
                
                print("\n✅ Migración completada exitosamente")
            else:
                print("✗ La tabla facturas no existe en la base de datos")
                
        except Exception as e:
            print(f"✗ Error durante la migración: {e}")

if __name__ == '__main__':
    print("Iniciando migración de facturas rectificativas...")
    print("-" * 50)
    migrar_facturas_rectificativas()
    print("-" * 50)
    print("Migración finalizada")



