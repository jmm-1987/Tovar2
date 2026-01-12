"""Script para crear la tabla personas_contacto si no existe"""
from app import app, db
from sqlalchemy import text, inspect

def crear_tabla_personas_contacto():
    """Crear tabla personas_contacto si no existe"""
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            table_names = inspector.get_table_names()
            
            if 'personas_contacto' not in table_names:
                print("Creando tabla personas_contacto...")
                with db.engine.connect() as conn:
                    conn.execute(text('''
                        CREATE TABLE personas_contacto (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            cliente_id INTEGER NOT NULL,
                            nombre VARCHAR(200) NOT NULL,
                            cargo VARCHAR(200),
                            movil VARCHAR(50),
                            email VARCHAR(100),
                            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
                        )
                    '''))
                    conn.commit()
                print("✓ Tabla personas_contacto creada exitosamente")
            else:
                print("✓ La tabla personas_contacto ya existe")
        except Exception as e:
            print(f"✗ Error al crear la tabla: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    crear_tabla_personas_contacto()











