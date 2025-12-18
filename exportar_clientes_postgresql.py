"""
Script para exportar datos de clientes desde PostgreSQL a JSON
Ejecutar antes de migrar a SQLite
"""
import os
import json
import sys
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Intentar importar psycopg2
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("ERROR: psycopg2 no está instalado.")
    print("Instálalo con: pip install psycopg2-binary")
    sys.exit(1)

def exportar_clientes():
    """Exportar todos los datos de clientes desde PostgreSQL"""
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        print("ERROR: DATABASE_URL no está configurada en el archivo .env")
        print("Necesitas la URL de PostgreSQL para exportar los datos")
        sys.exit(1)
    
    # Convertir postgres:// a postgresql:// si es necesario
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    try:
        # Conectar a PostgreSQL
        print("Conectando a PostgreSQL...")
        conn = psycopg2.connect(database_url)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Obtener todos los clientes
        print("Exportando datos de clientes...")
        cur.execute("SELECT * FROM clientes ORDER BY id")
        clientes = cur.fetchall()
        
        # Convertir a lista de diccionarios
        clientes_data = []
        for cliente in clientes:
            cliente_dict = dict(cliente)
            # Convertir tipos que no son JSON serializables
            for key, value in cliente_dict.items():
                if hasattr(value, 'isoformat'):  # datetime, date
                    cliente_dict[key] = value.isoformat()
                elif value is None:
                    cliente_dict[key] = None
            clientes_data.append(cliente_dict)
        
        # Guardar en archivo JSON
        output_file = 'clientes_exportados.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(clientes_data, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"✓ Exportados {len(clientes_data)} clientes a {output_file}")
        
        cur.close()
        conn.close()
        
        return output_file
        
    except Exception as e:
        print(f"ERROR al exportar clientes: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    print("=" * 60)
    print("EXPORTACIÓN DE CLIENTES DESDE POSTGRESQL")
    print("=" * 60)
    print()
    print("Este script exportará todos los datos de clientes")
    print("desde PostgreSQL a un archivo JSON.")
    print()
    
    respuesta = input("¿Continuar? (s/n): ")
    if respuesta.lower() != 's':
        print("Operación cancelada.")
        sys.exit(0)
    
    archivo = exportar_clientes()
    print()
    print("=" * 60)
    print(f"✓ Exportación completada: {archivo}")
    print("=" * 60)
    print()
    print("Siguiente paso: Ejecutar importar_clientes_sqlite.py")
    print("para importar estos datos a SQLite")



