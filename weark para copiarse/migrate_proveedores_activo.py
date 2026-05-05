"""Script para migrar la columna activo en la tabla proveedores"""
from app import app, db
from sqlalchemy import text, inspect

def migrate_proveedores_activo():
    """Añadir columna activo a la tabla proveedores si no existe"""
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            table_names = inspector.get_table_names()
            
            if 'proveedores' in table_names:
                columns_proveedor = [col['name'] for col in inspector.get_columns('proveedores')]
                print(f"Columnas actuales en proveedores: {columns_proveedor}")
                
                if 'activo' not in columns_proveedor:
                    print("Añadiendo columna activo a proveedores...")
                    with db.engine.connect() as conn:
                        # SQLite usa INTEGER para booleanos (0/1), pero SQLAlchemy lo maneja como BOOLEAN
                        conn.execute(text('ALTER TABLE proveedores ADD COLUMN activo INTEGER DEFAULT 1'))
                        conn.commit()
                    print("✓ Columna activo agregada exitosamente a proveedores")
                    
                    # Verificar que se agregó correctamente
                    columns_after = [col['name'] for col in inspector.get_columns('proveedores')]
                    print(f"Columnas después de la migración: {columns_after}")
                else:
                    print("✓ La columna activo ya existe en proveedores")
            else:
                print("⚠ La tabla proveedores no existe. Se creará con db.create_all()")
                db.create_all()
                print("✓ Tabla proveedores creada")
        except Exception as e:
            print(f"✗ Error durante la migración: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    migrate_proveedores_activo()


