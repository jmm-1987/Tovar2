"""
Script para importar datos de clientes desde JSON a SQLite
Ejecutar después de exportar desde PostgreSQL
"""
import os
import json
import sys
from datetime import datetime
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def importar_clientes():
    """Importar datos de clientes desde JSON a SQLite"""
    input_file = 'clientes_exportados.json'
    
    if not os.path.exists(input_file):
        print(f"ERROR: No se encuentra el archivo {input_file}")
        print("Primero debes ejecutar exportar_clientes_postgresql.py")
        sys.exit(1)
    
    try:
        # Cargar datos desde JSON
        print(f"Cargando datos desde {input_file}...")
        with open(input_file, 'r', encoding='utf-8') as f:
            clientes_data = json.load(f)
        
        print(f"Encontrados {len(clientes_data)} clientes para importar")
        
        # Importar app para tener acceso a la base de datos SQLite
        from app import app, db
        from models import Cliente
        
        with app.app_context():
            # Crear tablas si no existen
            db.create_all()
            
            # Importar cada cliente
            clientes_importados = 0
            clientes_actualizados = 0
            errores = []
            
            for cliente_data in clientes_data:
                try:
                    # Verificar si el cliente ya existe
                    cliente_existente = Cliente.query.get(cliente_data['id'])
                    
                    if cliente_existente:
                        # Actualizar cliente existente
                        for key, value in cliente_data.items():
                            if key == 'id':
                                continue  # No actualizar el ID
                            if hasattr(cliente_existente, key):
                                # Convertir strings de fecha a objetos datetime/date
                                if key in ['fecha_creacion', 'ultimo_acceso'] and value:
                                    try:
                                        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                    except:
                                        pass
                                elif key == 'fecha_alta' and value:
                                    try:
                                        from datetime import date
                                        value = datetime.fromisoformat(value).date()
                                    except:
                                        pass
                                setattr(cliente_existente, key, value)
                        clientes_actualizados += 1
                    else:
                        # Crear nuevo cliente
                        cliente = Cliente()
                        for key, value in cliente_data.items():
                            if hasattr(cliente, key):
                                # Convertir strings de fecha a objetos datetime/date
                                if key in ['fecha_creacion', 'ultimo_acceso'] and value:
                                    try:
                                        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                                    except:
                                        value = None
                                elif key == 'fecha_alta' and value:
                                    try:
                                        from datetime import date
                                        value = datetime.fromisoformat(value).date()
                                    except:
                                        value = None
                                setattr(cliente, key, value)
                        db.session.add(cliente)
                        clientes_importados += 1
                        
                except Exception as e:
                    errores.append({
                        'cliente_id': cliente_data.get('id', 'N/A'),
                        'error': str(e)
                    })
                    print(f"  ⚠ Error al importar cliente ID {cliente_data.get('id', 'N/A')}: {e}")
            
            # Confirmar cambios
            try:
                db.session.commit()
                print(f"✓ Importados {clientes_importados} clientes nuevos")
                print(f"✓ Actualizados {clientes_actualizados} clientes existentes")
                
                if errores:
                    print(f"⚠ {len(errores)} errores durante la importación")
                    for error in errores:
                        print(f"  - Cliente ID {error['cliente_id']}: {error['error']}")
                else:
                    print("✓ Todos los clientes se importaron correctamente")
                    
            except Exception as e:
                db.session.rollback()
                print(f"ERROR al confirmar cambios: {e}")
                import traceback
                traceback.print_exc()
                sys.exit(1)
        
    except Exception as e:
        print(f"ERROR al importar clientes: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    print("=" * 60)
    print("IMPORTACIÓN DE CLIENTES A SQLITE")
    print("=" * 60)
    print()
    print("Este script importará los datos de clientes")
    print("desde clientes_exportados.json a SQLite.")
    print()
    print("ADVERTENCIA: Los clientes existentes con el mismo ID")
    print("serán actualizados con los datos del archivo JSON.")
    print()
    
    respuesta = input("¿Continuar? (s/n): ")
    if respuesta.lower() != 's':
        print("Operación cancelada.")
        sys.exit(0)
    
    importar_clientes()
    print()
    print("=" * 60)
    print("✓ Importación completada")
    print("=" * 60)



