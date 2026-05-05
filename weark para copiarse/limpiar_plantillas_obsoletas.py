"""Script para identificar y eliminar plantillas de email obsoletas"""
from app import app
from extensions import db
from models import PlantillaEmail

def identificar_plantillas_obsoletas():
    """Identificar plantillas que no corresponden a estados actuales"""
    with app.app_context():
        # Plantillas válidas según estados actuales
        plantillas_validas = [
            'presupuesto',  # Plantilla genérica
            'cambio_estado_solicitud_presupuesto',
            'cambio_estado_solicitud_aceptado',
            'cambio_estado_solicitud_mockup',
            'cambio_estado_solicitud_en_preparacion',
            'cambio_estado_solicitud_terminado',
            'cambio_estado_solicitud_entregado_al_cliente',
            'cambio_subestado_en_preparacion_hacer_marcada',
            'cambio_subestado_en_preparacion_imprimir',
            'cambio_subestado_en_preparacion_calandra',
            'cambio_subestado_en_preparacion_corte',
            'cambio_subestado_en_preparacion_confeccion',
            'cambio_subestado_en_preparacion_sublimacion',
            'cambio_subestado_en_preparacion_bordado'
        ]
        
        # Obtener todas las plantillas
        todas_plantillas = PlantillaEmail.query.all()
        plantillas_obsoletas = []
        plantillas_validas_encontradas = []
        
        print("=" * 60)
        print("REVISIÓN DE PLANTILLAS DE EMAIL")
        print("=" * 60)
        print(f"\nTotal de plantillas en BD: {len(todas_plantillas)}\n")
        
        for plantilla in todas_plantillas:
            if plantilla.tipo in plantillas_validas:
                plantillas_validas_encontradas.append(plantilla.tipo)
            elif (plantilla.tipo.startswith('cambio_estado_solicitud_') or 
                  plantilla.tipo.startswith('cambio_subestado_') or
                  plantilla.tipo.startswith('cambio_estado_pedido')):
                # Es una plantilla de solicitud o pedido pero no está en la lista de válidas
                plantillas_obsoletas.append(plantilla)
        
        print(f"Plantillas válidas encontradas: {len(plantillas_validas_encontradas)}")
        for tipo in sorted(plantillas_validas_encontradas):
            print(f"  ✓ {tipo}")
        
        print(f"\nPlantillas OBSOLETAS encontradas: {len(plantillas_obsoletas)}")
        if plantillas_obsoletas:
            print("\nLas siguientes plantillas serán ELIMINADAS:")
            for plantilla in plantillas_obsoletas:
                print(f"  ✗ {plantilla.tipo} (ID: {plantilla.id})")
            
            respuesta = input("\n¿Desea eliminar estas plantillas? (s/n): ")
            if respuesta.lower() == 's':
                for plantilla in plantillas_obsoletas:
                    db.session.delete(plantilla)
                db.session.commit()
                print(f"\n✓ Se eliminaron {len(plantillas_obsoletas)} plantillas obsoletas")
            else:
                print("\n✗ Operación cancelada")
        else:
            print("\n✓ No se encontraron plantillas obsoletas")
        
        print("\n" + "=" * 60)

if __name__ == '__main__':
    identificar_plantillas_obsoletas()

