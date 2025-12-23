"""Script para agregar las columnas imagen_adicional_5 y descripcion_imagen_5 a la tabla presupuestos"""
from app import app, db
from sqlalchemy import inspect, text

def agregar_columnas_imagen_5():
    """Agregar columnas imagen_adicional_5 y descripcion_imagen_5 si no existen"""
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            
            # Verificar si existe la tabla presupuestos
            if 'presupuestos' not in inspector.get_table_names():
                print("La tabla presupuestos no existe. Ejecutando create_all()...")
                db.create_all()
                return
            
            # Obtener columnas existentes
            columns_presupuesto = [col['name'] for col in inspector.get_columns('presupuestos')]
            
            # Agregar imagen_adicional_5 si no existe
            if 'imagen_adicional_5' not in columns_presupuesto:
                try:
                    with db.engine.connect() as conn:
                        conn.execute(text('ALTER TABLE presupuestos ADD COLUMN imagen_adicional_5 VARCHAR(255)'))
                        conn.commit()
                    print("✓ Columna imagen_adicional_5 agregada exitosamente")
                except Exception as e:
                    print(f"✗ Error al agregar imagen_adicional_5: {e}")
            else:
                print("✓ Columna imagen_adicional_5 ya existe")
            
            # Agregar descripcion_imagen_5 si no existe
            if 'descripcion_imagen_5' not in columns_presupuesto:
                try:
                    with db.engine.connect() as conn:
                        conn.execute(text('ALTER TABLE presupuestos ADD COLUMN descripcion_imagen_5 TEXT'))
                        conn.commit()
                    print("✓ Columna descripcion_imagen_5 agregada exitosamente")
                except Exception as e:
                    print(f"✗ Error al agregar descripcion_imagen_5: {e}")
            else:
                print("✓ Columna descripcion_imagen_5 ya existe")
                
        except Exception as e:
            print(f"Error general: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    print("Ejecutando migración para agregar imagen_adicional_5 y descripcion_imagen_5...")
    agregar_columnas_imagen_5()
    print("Migración completada.")

















