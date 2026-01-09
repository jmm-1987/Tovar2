"""Utilidades para envío de emails"""
from flask import current_app, render_template
from flask_mail import Message
from extensions import mail
from models import PlantillaEmail, Cliente
from datetime import datetime
from decimal import Decimal
import os
from io import BytesIO

def obtener_plantilla(tipo):
    """Obtener plantilla de email por tipo"""
    plantilla = PlantillaEmail.query.filter_by(tipo=tipo).first()
    if not plantilla:
        # Plantillas por defecto si no existen en BD
        plantillas_defecto = {
            'presupuesto': {
                'asunto': 'Presupuesto #{presupuesto_id} - {cliente_nombre}',
                'cuerpo': '''Estimado/a {cliente_nombre},

Adjuntamos el presupuesto #{presupuesto_id} solicitado.

Detalles del presupuesto:
- Tipo: {tipo_pedido}
- Fecha: {fecha_creacion}
- Total: {total_con_iva} €

Quedamos a su disposición para cualquier consulta.

Saludos cordiales,
{empresa_nombre}'''
            },
            'cambio_estado_pedido': {
                'asunto': 'Actualización del pedido #{pedido_id} - Estado: {nuevo_estado}',
                'cuerpo': '''Estimado/a {cliente_nombre},

Le informamos que el estado de su pedido #{pedido_id} ha cambiado.

Nuevo estado: {nuevo_estado}
Fecha de actualización: {fecha_actualizacion}

Detalles del pedido:
- Tipo: {tipo_pedido}
- Fecha de aceptación: {fecha_aceptacion}
- Fecha objetivo de entrega: {fecha_objetivo}

Quedamos a su disposición para cualquier consulta.

Saludos cordiales,
{empresa_nombre}'''
            }
        }
        return plantillas_defecto.get(tipo, {'asunto': '', 'cuerpo': ''})
    return {'asunto': plantilla.asunto, 'cuerpo': plantilla.cuerpo}

def formatear_texto(texto, variables):
    """Formatear texto con variables"""
    try:
        # Formatear el texto con las variables disponibles
        # Si una variable no está en el texto, simplemente se ignora
        resultado = texto
        for key, value in variables.items():
            resultado = resultado.replace(f'{{{key}}}', str(value))
        return resultado
    except Exception as e:
        # Si hay algún error, intentar formateo estándar
        try:
            return texto.format(**variables)
        except:
            return texto

def enviar_email_presupuesto(presupuesto, pdf_data=None):
    """Enviar presupuesto por email al cliente"""
    try:
        cliente = presupuesto.cliente
        if not cliente or not cliente.email:
            return False, 'El cliente no tiene email configurado'
        
        # Obtener plantilla
        plantilla = obtener_plantilla('presupuesto')
        
        # Calcular totales
        tipo_iva = 21
        base_imponible = Decimal('0.00')
        for linea in presupuesto.lineas:
            precio_unit = Decimal(str(linea.precio_unitario)) if linea.precio_unitario else Decimal('0.00')
            cantidad = Decimal(str(linea.cantidad))
            total_linea = precio_unit * cantidad
            base_imponible += total_linea
        
        iva_total = base_imponible * Decimal(str(tipo_iva)) / Decimal('100')
        total_con_iva = base_imponible + iva_total
        
        # Variables para la plantilla
        variables = {
            'presupuesto_id': presupuesto.id,
            'cliente_nombre': cliente.nombre,
            'tipo_pedido': presupuesto.tipo_pedido,
            'fecha_creacion': presupuesto.fecha_creacion.strftime('%d/%m/%Y') if presupuesto.fecha_creacion else '',
            'total_con_iva': f'{total_con_iva:.2f}',
            'empresa_nombre': current_app.config.get('MAIL_DEFAULT_SENDER', 'Nuestra Empresa')
        }
        
        # Formatear asunto y cuerpo
        asunto = formatear_texto(plantilla['asunto'], variables)
        cuerpo = formatear_texto(plantilla['cuerpo'], variables)
        
        # Crear mensaje
        msg = Message(
            subject=asunto,
            recipients=[cliente.email],
            body=cuerpo
        )
        
        # Adjuntar PDF si está disponible
        if pdf_data:
            msg.attach(
                f'presupuesto_{presupuesto.id}.pdf',
                'application/pdf',
                pdf_data
            )
        
        # Enviar email
        mail.send(msg)
        return True, 'Email enviado correctamente'
        
    except Exception as e:
        return False, f'Error al enviar email: {str(e)}'

def enviar_email_cambio_estado_pedido(pedido, nuevo_estado, estado_anterior=None):
    """Enviar email al cliente cuando cambia el estado de un pedido"""
    try:
        cliente = pedido.cliente
        if not cliente or not cliente.email:
            return False, 'El cliente no tiene email configurado'
        
        # Obtener plantilla
        plantilla = obtener_plantilla('cambio_estado_pedido')
        
        # Variables para la plantilla
        variables = {
            'pedido_id': pedido.id,
            'cliente_nombre': cliente.nombre,
            'nuevo_estado': nuevo_estado,
            'estado_anterior': estado_anterior or 'N/A',
            'fecha_actualizacion': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'tipo_pedido': pedido.tipo_pedido,
            'fecha_aceptacion': pedido.fecha_aceptacion.strftime('%d/%m/%Y') if pedido.fecha_aceptacion else 'N/A',
            'fecha_objetivo': pedido.fecha_objetivo.strftime('%d/%m/%Y') if pedido.fecha_objetivo else 'N/A',
            'empresa_nombre': current_app.config.get('MAIL_DEFAULT_SENDER', 'Nuestra Empresa')
        }
        
        # Formatear asunto y cuerpo
        asunto = formatear_texto(plantilla['asunto'], variables)
        cuerpo = formatear_texto(plantilla['cuerpo'], variables)
        
        # Crear mensaje
        msg = Message(
            subject=asunto,
            recipients=[cliente.email],
            body=cuerpo
        )
        
        # Enviar email
        mail.send(msg)
        return True, 'Email enviado correctamente'
        
    except Exception as e:
        return False, f'Error al enviar email: {str(e)}'

def enviar_email_cambio_estado_solicitud(solicitud, nuevo_estado, subestado=None, estado_anterior=None, subestado_anterior=None):
    """Enviar email al cliente cuando cambia el estado o subestado de una solicitud (presupuesto)"""
    try:
        cliente = solicitud.cliente
        if not cliente or not cliente.email:
            return False, 'El cliente no tiene email configurado'
        
        # Si hay subestado y el estado es "en preparacion", intentar usar plantilla específica del subestado
        tipo_plantilla = None
        if subestado and nuevo_estado == 'en preparacion':
            tipo_plantilla = f'cambio_subestado_en_preparacion_{subestado.replace(" ", "_")}'
            plantilla = obtener_plantilla(tipo_plantilla)
            # Si existe plantilla específica del subestado, usarla
            if plantilla and plantilla.get('asunto'):
                plantilla_db = PlantillaEmail.query.filter_by(tipo=tipo_plantilla).first()
                if plantilla_db and not plantilla_db.enviar_activo:
                    print(f"DEBUG: Plantilla {tipo_plantilla} está desactivada")
                    return False, f'La plantilla para el subestado {subestado} está desactivada'
            else:
                # Si no hay plantilla específica del subestado, usar la del estado
                tipo_plantilla = f'cambio_estado_solicitud_{nuevo_estado.replace(" ", "_")}'
        else:
            # Determinar el tipo de plantilla según el estado
            tipo_plantilla = f'cambio_estado_solicitud_{nuevo_estado.replace(" ", "_")}'
        
        # Obtener plantilla
        plantilla = obtener_plantilla(tipo_plantilla)
        
        # Si no existe plantilla específica, no enviar email
        if not plantilla or not plantilla.get('asunto'):
            print(f"DEBUG: No hay plantilla para {tipo_plantilla}")
            return False, f'No hay plantilla configurada para el estado {nuevo_estado}'
        
        # Verificar si la plantilla está activa
        plantilla_db = PlantillaEmail.query.filter_by(tipo=tipo_plantilla).first()
        if plantilla_db and not plantilla_db.enviar_activo:
            print(f"DEBUG: Plantilla {tipo_plantilla} está desactivada")
            return False, f'La plantilla para {nuevo_estado} está desactivada'
        
        # Variables para la plantilla
        subestado_info = f'- Subestado: {subestado.title()}' if subestado else ''
        variables = {
            'solicitud_id': solicitud.id,
            'cliente_nombre': cliente.nombre,
            'nuevo_estado': nuevo_estado.title(),
            'subestado': subestado.title() if subestado else '',
            'subestado_info': subestado_info,
            'estado_anterior': estado_anterior.title() if estado_anterior else 'N/A',
            'fecha_actualizacion': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'tipo_pedido': solicitud.tipo_pedido.title(),
            'fecha_aceptacion': solicitud.fecha_aceptado.strftime('%d/%m/%Y') if solicitud.fecha_aceptado else 'N/A',
            'fecha_objetivo': solicitud.fecha_objetivo.strftime('%d/%m/%Y') if solicitud.fecha_objetivo else 'N/A',
            'empresa_nombre': current_app.config.get('MAIL_DEFAULT_SENDER', 'Nuestra Empresa')
        }
        
        # Formatear asunto y cuerpo
        asunto = formatear_texto(plantilla['asunto'], variables)
        cuerpo = formatear_texto(plantilla['cuerpo'], variables)
        
        # Crear mensaje
        msg = Message(
            subject=asunto,
            recipients=[cliente.email],
            body=cuerpo
        )
        
        # Adjuntar mockup si está disponible
        if solicitud.imagen_mockup:
            try:
                from utils.sftp_upload import download_file_from_sftp
                import os
                
                # Construir ruta remota en SFTP
                ruta_mockup = solicitud.imagen_mockup
                if ruta_mockup.startswith('/'):
                    remote_path = ruta_mockup
                else:
                    # Si es relativa, construir ruta completa en SFTP
                    config = os.environ.get('SFTP_DIR', '/')
                    if config != '/':
                        remote_path = f"{config.rstrip('/')}/{ruta_mockup}"
                    else:
                        remote_path = f"/{ruta_mockup}"
                
                # Intentar descargar desde SFTP primero
                mockup_data = download_file_from_sftp(remote_path)
                
                # Si no está en SFTP, intentar leer localmente
                if not mockup_data:
                    imagen_path_local = os.path.join(current_app.config['UPLOAD_FOLDER'], ruta_mockup)
                    if os.path.exists(imagen_path_local):
                        with open(imagen_path_local, 'rb') as f:
                            mockup_data = f.read()
                
                # Adjuntar al email si se encontró el archivo
                if mockup_data:
                    # Obtener nombre del archivo
                    nombre_archivo = os.path.basename(ruta_mockup)
                    if not nombre_archivo.endswith('.pdf'):
                        nombre_archivo = f"mockup_solicitud_{solicitud.id}.pdf"
                    
                    msg.attach(
                        nombre_archivo,
                        'application/pdf',
                        mockup_data
                    )
            except Exception as e:
                print(f"Error al adjuntar mockup al email: {e}")
        
        # Enviar email
        try:
            mail.send(msg)
            print(f"DEBUG: Email enviado correctamente a {cliente.email} (plantilla: {tipo_plantilla})")
            return True, 'Email enviado correctamente'
        except Exception as e:
            print(f"DEBUG: Error al enviar email: {str(e)}")
            return False, f'Error al enviar email: {str(e)}'
        
    except Exception as e:
        import traceback
        print(f"DEBUG: Excepción en enviar_email_cambio_estado_solicitud: {str(e)}")
        print(traceback.format_exc())
        return False, f'Error al enviar email: {str(e)}'




