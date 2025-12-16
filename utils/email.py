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
    """Obtener plantilla de email por tipo.

    Devuelve siempre un diccionario con claves:
    - asunto
    - cuerpo
    - enviar_activo (bool): True si debe enviarse email para este tipo.
    """
    plantilla = PlantillaEmail.query.filter_by(tipo=tipo).first()
    if plantilla:
        return {
            'asunto': plantilla.asunto,
            'cuerpo': plantilla.cuerpo,
            'enviar_activo': plantilla.enviar_activo if plantilla.enviar_activo is not None else True,
        }

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
{empresa_nombre}''',
            'enviar_activo': True,
        },
    }
    # Si no hay plantilla conocida, devolver estructura vacía pero activa
    return plantillas_defecto.get(tipo, {'asunto': '', 'cuerpo': '', 'enviar_activo': True})

def formatear_texto(texto, variables):
    """Formatear texto con variables"""
    try:
        return texto.format(**variables)
    except KeyError as e:
        # Si falta una variable, usar valor por defecto
        return texto.format(**{k: variables.get(k, f'{{{k}}}') for k in variables})

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
        
        # Crear mensaje con sender explícito
        sender = current_app.config.get('MAIL_DEFAULT_SENDER')
        if not sender:
            sender = current_app.config.get('MAIL_USERNAME', 'noreply@tovar.com')
        
        msg = Message(
            subject=asunto,
            sender=sender,
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

def enviar_email_pedido(pedido, pdf_data=None):
    """Enviar pedido por email al cliente"""
    try:
        cliente = pedido.cliente
        if not cliente or not cliente.email:
            return False, 'El cliente no tiene email configurado'
        
        # Preparar asunto y cuerpo
        asunto = f"Pedido #{pedido.id} - {cliente.nombre}"
        cuerpo = f"""Estimado/a {cliente.nombre},

Adjuntamos el pedido #{pedido.id} solicitado.

Detalles del pedido:
- Tipo: {pedido.tipo_pedido}
- Estado: {pedido.estado}
- Fecha de aceptación: {pedido.fecha_aceptacion.strftime('%d/%m/%Y') if pedido.fecha_aceptacion else 'N/A'}

Quedamos a su disposición para cualquier consulta.

Saludos cordiales,
{current_app.config.get('MAIL_DEFAULT_SENDER', 'Nuestra Empresa')}"""
        
        # Crear mensaje con sender explícito
        sender = current_app.config.get('MAIL_DEFAULT_SENDER')
        if not sender:
            sender = current_app.config.get('MAIL_USERNAME', 'noreply@tovar.com')
        
        msg = Message(
            subject=asunto,
            sender=sender,
            recipients=[cliente.email],
            body=cuerpo
        )
        
        # Adjuntar PDF si está disponible
        if pdf_data:
            msg.attach(
                f'pedido_{pedido.id}.pdf',
                'application/pdf',
                pdf_data
            )
        
        # Enviar email
        mail.send(msg)
        return True, 'Email enviado correctamente'
        
    except Exception as e:
        return False, f'Error al enviar email: {str(e)}'

def _slug_estado(estado: str) -> str:
    """Convertir un nombre de estado a un slug para usar en el tipo de plantilla."""
    if not estado:
        return ''
    slug = estado.lower()
    # Normalizar caracteres habituales en los estados
    slug = (
        slug.replace(' ', '_')
        .replace('ó', 'o')
        .replace('í', 'i')
        .replace('é', 'e')
        .replace('á', 'a')
        .replace('ú', 'u')
    )
    return slug


def enviar_email_cambio_estado_pedido(pedido, nuevo_estado, estado_anterior=None):
    """Enviar email al cliente cuando cambia el estado de un pedido.

    Intenta usar una plantilla específica por estado (por ejemplo:
    - cambio_estado_pedido_pendiente
    - cambio_estado_pedido_diseno
    - cambio_estado_pedido_en_preparacion
    - cambio_estado_pedido_todo_listo
    - cambio_estado_pedido_enviado
    - cambio_estado_pedido_entregado_al_cliente

    Si no existe una plantilla específica o está desactivada, no se envía email.
    """
    try:
        cliente = pedido.cliente
        if not cliente or not cliente.email:
            return False, 'El cliente no tiene email configurado'

        # Intentar plantilla específica por estado
        tipo_especifico = f"cambio_estado_pedido_{_slug_estado(nuevo_estado)}"
        plantilla = obtener_plantilla(tipo_especifico)

        # Si no hay asunto/cuerpo configurado, no enviar email
        if not plantilla.get('asunto') or not plantilla.get('cuerpo'):
            return False, f'No hay plantilla configurada para el estado "{nuevo_estado}"'
        
        # Verificar si la plantilla está activa
        if not plantilla.get('enviar_activo', True):
            return False, f'La plantilla para el estado "{nuevo_estado}" está desactivada'

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

        # Crear mensaje con sender explícito
        sender = current_app.config.get('MAIL_DEFAULT_SENDER')
        if not sender:
            sender = current_app.config.get('MAIL_USERNAME', 'noreply@tovar.com')
        
        msg = Message(
            subject=asunto,
            sender=sender,
            recipients=[cliente.email],
            body=cuerpo
        )

        # Enviar email
        mail.send(msg)
        return True, 'Email enviado correctamente'

    except Exception as e:
        return False, f'Error al enviar email: {str(e)}'




