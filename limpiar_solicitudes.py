"""
Script para eliminar todos los presupuestos, pedidos y solicitudes del sistema.
IMPORTANTE: Esto eliminará TODOS los datos relacionados.
"""
from app import app
from extensions import db
from models import (
    Presupuesto, LineaPresupuesto,
    Pedido, LineaPedido,
    Factura, LineaFactura
)

def limpiar_todo():
    """Eliminar todos los presupuestos, pedidos y solicitudes"""
    with app.app_context():
        try:
            print("Iniciando limpieza de datos...")
            
            # 1. Eliminar facturas relacionadas con presupuestos o pedidos
            print("\n1. Eliminando facturas relacionadas con presupuestos/pedidos...")
            facturas_con_presupuesto = Factura.query.filter(
                Factura.presupuesto_id.isnot(None)
            ).all()
            facturas_con_pedido = Factura.query.filter(
                Factura.pedido_id.isnot(None)
            ).all()
            
            # Combinar y eliminar duplicados
            facturas_a_eliminar = list(set(facturas_con_presupuesto + facturas_con_pedido))
            for factura in facturas_a_eliminar:
                # Eliminar líneas de factura primero
                for linea in factura.lineas:
                    db.session.delete(linea)
                db.session.delete(factura)
            print(f"   Eliminadas {len(facturas_a_eliminar)} facturas relacionadas")
            
            # 2. Eliminar líneas de factura huérfanas (que referencian líneas de pedido que se eliminarán)
            print("\n2. Eliminando líneas de factura con referencia a pedidos...")
            lineas_factura_con_pedido = LineaFactura.query.filter(
                LineaFactura.linea_pedido_id.isnot(None)
            ).all()
            for linea in lineas_factura_con_pedido:
                db.session.delete(linea)
            print(f"   Eliminadas {len(lineas_factura_con_pedido)} líneas de factura huérfanas")
            
            # 3. Eliminar líneas de presupuesto (se eliminarán automáticamente con cascade, pero lo hacemos explícitamente)
            print("\n3. Eliminando líneas de presupuesto...")
            lineas_presupuesto = LineaPresupuesto.query.all()
            for linea in lineas_presupuesto:
                db.session.delete(linea)
            print(f"   Eliminadas {len(lineas_presupuesto)} líneas de presupuesto")
            
            # 4. Eliminar presupuestos (solicitudes)
            print("\n4. Eliminando presupuestos/solicitudes...")
            presupuestos = Presupuesto.query.all()
            for presupuesto in presupuestos:
                db.session.delete(presupuesto)
            print(f"   Eliminados {len(presupuestos)} presupuestos/solicitudes")
            
            # 5. Eliminar líneas de pedido
            print("\n5. Eliminando líneas de pedido...")
            lineas_pedido = LineaPedido.query.all()
            for linea in lineas_pedido:
                db.session.delete(linea)
            print(f"   Eliminadas {len(lineas_pedido)} líneas de pedido")
            
            # 6. Eliminar pedidos
            print("\n6. Eliminando pedidos...")
            pedidos = Pedido.query.all()
            for pedido in pedidos:
                db.session.delete(pedido)
            print(f"   Eliminados {len(pedidos)} pedidos")
            
            # Confirmar todos los cambios
            db.session.commit()
            print("\nLimpieza completada exitosamente!")
            print(f"\nResumen:")
            print(f"  - Facturas relacionadas eliminadas: {len(facturas_a_eliminar)}")
            print(f"  - Líneas de factura huérfanas eliminadas: {len(lineas_factura_con_pedido)}")
            print(f"  - Líneas de presupuesto eliminadas: {len(lineas_presupuesto)}")
            print(f"  - Presupuestos/Solicitudes eliminados: {len(presupuestos)}")
            print(f"  - Líneas de pedido eliminadas: {len(lineas_pedido)}")
            print(f"  - Pedidos eliminados: {len(pedidos)}")
            
        except Exception as e:
            db.session.rollback()
            print(f"\nERROR durante la limpieza: {str(e)}")
            import traceback
            traceback.print_exc()
            raise

if __name__ == '__main__':
    print("ADVERTENCIA: Esto eliminara TODOS los presupuestos, pedidos y solicitudes del sistema.")
    respuesta = input("Estas seguro de que quieres continuar? (escribe 'SI' para confirmar): ")
    
    if respuesta == 'SI':
        limpiar_todo()
    else:
        print("Operacion cancelada.")

