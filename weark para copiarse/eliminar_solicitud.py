"""Script para eliminar una solicitud (presupuesto) de la base de datos"""
import os
import sys
from pathlib import Path
import sqlite3

# Obtener ruta de la base de datos
database_path = os.environ.get('DATABASE_PATH', 'instance/pedidos.db')

# Convertir a ruta absoluta si es relativa
if not os.path.isabs(database_path):
    database_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), database_path)

database_path = os.path.normpath(database_path)

def obtener_cliente_nombre(conn, cliente_id):
    """Obtener nombre del cliente"""
    cursor = conn.cursor()
    cursor.execute("SELECT nombre FROM clientes WHERE id = ?", (cliente_id,))
    result = cursor.fetchone()
    return result[0] if result else 'N/A'

def obtener_comercial_nombre(conn, comercial_id):
    """Obtener nombre del comercial"""
    cursor = conn.cursor()
    cursor.execute("SELECT nombre FROM comerciales WHERE id = ?", (comercial_id,))
    result = cursor.fetchone()
    return result[0] if result else 'N/A'

def eliminar_solicitud(solicitud_id):
    """Eliminar una solicitud y todos sus datos relacionados"""
    if not os.path.exists(database_path):
        print(f"Error: No se encontro la base de datos en {database_path}")
        return False
    
    try:
        conn = sqlite3.connect(database_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Buscar la solicitud
        cursor.execute("SELECT * FROM presupuestos WHERE id = ?", (solicitud_id,))
        solicitud = cursor.fetchone()
        
        if not solicitud:
            print(f"Error: No se encontro la solicitud con ID {solicitud_id}")
            conn.close()
            return False
        
        # Obtener información relacionada
        cliente_nombre = obtener_cliente_nombre(conn, solicitud['cliente_id'])
        comercial_nombre = obtener_comercial_nombre(conn, solicitud['comercial_id'])
        
        # Contar líneas
        cursor.execute("SELECT COUNT(*) FROM lineas_presupuesto WHERE presupuesto_id = ?", (solicitud_id,))
        num_lineas = cursor.fetchone()[0]
        
        # Contar registros de estado
        cursor.execute("SELECT COUNT(*) FROM registro_estado_solicitud WHERE presupuesto_id = ?", (solicitud_id,))
        num_registros = cursor.fetchone()[0]
        
        # Verificar si tiene pedidos relacionados
        cursor.execute("SELECT id FROM pedidos WHERE presupuesto_id = ?", (solicitud_id,))
        pedidos_relacionados = cursor.fetchall()
        num_pedidos = len(pedidos_relacionados)
        
        # Mostrar información de la solicitud
        print("=" * 60)
        print("INFORMACIÓN DE LA SOLICITUD A ELIMINAR")
        print("=" * 60)
        print(f"ID: {solicitud['id']}")
        print(f"Número de Solicitud: {solicitud['numero_solicitud'] or 'N/A'}")
        print(f"Cliente: {cliente_nombre}")
        print(f"Comercial: {comercial_nombre}")
        print(f"Estado: {solicitud['estado']}")
        print(f"Subestado: {solicitud['subestado'] or 'N/A'}")
        print(f"Tipo: {solicitud['tipo_pedido']}")
        fecha_creacion = solicitud['fecha_creacion']
        if fecha_creacion:
            print(f"Fecha de Creación: {fecha_creacion}")
        else:
            print(f"Fecha de Creación: N/A")
        print(f"Número de Líneas: {num_lineas}")
        print(f"Registros de Estado: {num_registros}")
        
        if num_pedidos > 0:
            print(f"\nADVERTENCIA: Esta solicitud tiene {num_pedidos} pedido(s) relacionado(s):")
            for pedido in pedidos_relacionados:
                print(f"   - Pedido ID: {pedido[0]}")
        
        print("=" * 60)
        
        # Confirmar eliminación (solo si no se pasó como argumento con --force)
        force = len(sys.argv) > 2 and sys.argv[2] == '--force'
        if not force:
            try:
                respuesta = input("\nEsta seguro de que desea eliminar esta solicitud? (s/n): ")
                if respuesta.lower() != 's':
                    print("\nOperacion cancelada")
                    conn.close()
                    return False
            except (EOFError, KeyboardInterrupt):
                print("\n\nOperacion cancelada")
                conn.close()
                return False
        
        # Eliminar registros de estado primero
        if num_registros > 0:
            print(f"\nEliminando {num_registros} registro(s) de estado...")
            cursor.execute("DELETE FROM registro_estado_solicitud WHERE presupuesto_id = ?", (solicitud_id,))
            conn.commit()
            print("Registros de estado eliminados")
        
        # Eliminar líneas de presupuesto
        if num_lineas > 0:
            print(f"Eliminando {num_lineas} linea(s) de presupuesto...")
            cursor.execute("DELETE FROM lineas_presupuesto WHERE presupuesto_id = ?", (solicitud_id,))
            conn.commit()
            print("Lineas eliminadas")
        
        # Eliminar la solicitud
        print(f"\nEliminando solicitud ID {solicitud_id}...")
        cursor.execute("DELETE FROM presupuestos WHERE id = ?", (solicitud_id,))
        conn.commit()
        
        print("\n" + "=" * 60)
        print("SOLICITUD ELIMINADA EXITOSAMENTE")
        print("=" * 60)
        print(f"ID eliminado: {solicitud_id}")
        print(f"Lineas eliminadas: {num_lineas}")
        print(f"Registros de estado eliminados: {num_registros}")
        
        if num_pedidos > 0:
            print(f"\nNOTA: Los {num_pedidos} pedido(s) relacionado(s) NO fueron eliminados.")
            print("   Si desea eliminarlos tambien, debe hacerlo manualmente.")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"\nError al eliminar la solicitud: {e}")
        import traceback
        traceback.print_exc()
        return False

def listar_solicitudes_recientes(limite=10):
    """Listar las solicitudes más recientes"""
    if not os.path.exists(database_path):
        print(f"❌ Error: No se encontró la base de datos en {database_path}")
        return
    
    try:
        conn = sqlite3.connect(database_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT p.id, p.numero_solicitud, p.estado, p.fecha_creacion, p.cliente_id, c.nombre as cliente_nombre
            FROM presupuestos p
            LEFT JOIN clientes c ON p.cliente_id = c.id
            ORDER BY p.fecha_creacion DESC
            LIMIT ?
        """, (limite,))
        
        solicitudes = cursor.fetchall()
        
        if not solicitudes:
            print("No se encontraron solicitudes en la base de datos.")
            conn.close()
            return
        
        print("\n" + "=" * 80)
        print("SOLICITUDES MÁS RECIENTES")
        print("=" * 80)
        print(f"{'ID':<6} {'Número':<12} {'Cliente':<30} {'Estado':<20} {'Fecha':<12}")
        print("-" * 80)
        
        for solicitud in solicitudes:
            cliente_nombre = solicitud['cliente_nombre'] or 'N/A'
            if len(cliente_nombre) > 28:
                cliente_nombre = cliente_nombre[:25] + "..."
            
            numero = solicitud['numero_solicitud'] or 'N/A'
            estado = solicitud['estado'][:18] if len(solicitud['estado']) > 18 else solicitud['estado']
            fecha_creacion = solicitud['fecha_creacion']
            if fecha_creacion:
                # Intentar parsear la fecha
                try:
                    from datetime import datetime
                    fecha_obj = datetime.fromisoformat(fecha_creacion.replace('Z', '+00:00'))
                    fecha = fecha_obj.strftime('%d/%m/%Y')
                except:
                    fecha = fecha_creacion[:10] if len(fecha_creacion) >= 10 else fecha_creacion
            else:
                fecha = 'N/A'
            
            print(f"{solicitud['id']:<6} {numero:<12} {cliente_nombre:<30} {estado:<20} {fecha:<12}")
        
        print("=" * 80)
        conn.close()
        
    except Exception as e:
        print(f"Error al listar solicitudes: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    # Configurar encoding para Windows
    import sys
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    
    print("\n" + "=" * 60)
    print("SCRIPT DE ELIMINACION DE SOLICITUDES")
    print("=" * 60)
    
    # Mostrar solicitudes recientes
    listar_solicitudes_recientes(10)
    
    # Obtener ID desde argumentos de línea de comandos o input
    solicitud_id = None
    
    if len(sys.argv) > 1:
        # Si se pasa como argumento
        try:
            solicitud_id = int(sys.argv[1])
        except ValueError:
            print(f"\nError: '{sys.argv[1]}' no es un ID valido")
            sys.exit(1)
    else:
        # Si no hay argumentos, pedir input
        print("\n")
        try:
            solicitud_input = input("Ingrese el ID de la solicitud a eliminar (o 'q' para salir): ").strip()
            
            if solicitud_input.lower() == 'q':
                print("\nOperacion cancelada")
                sys.exit(0)
            
            solicitud_id = int(solicitud_input)
        except ValueError:
            print("\nError: Debe ingresar un numero valido")
            sys.exit(1)
        except (EOFError, KeyboardInterrupt):
            print("\n\nOperacion cancelada")
            sys.exit(0)
    
    if solicitud_id is None:
        print("\nError: No se especifico un ID de solicitud")
        sys.exit(1)
    
    try:
        if eliminar_solicitud(solicitud_id):
            print("\nProceso completado exitosamente")
        else:
            print("\nEl proceso no se completo")
            sys.exit(1)
    except Exception as e:
        print(f"\nError inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

