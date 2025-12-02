"""Rutas para gestión de tickets de tienda (Facturas simplificadas)"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
from datetime import datetime
from decimal import Decimal
import os
import requests
import json
from extensions import db
from models import Ticket, LineaTicket
from utils.numeracion import obtener_siguiente_numero_ticket

tickets_bp = Blueprint('tickets', __name__)

@tickets_bp.route('/tickets')
@login_required
def listado_tickets():
    """Listado de tickets con opciones de ver y eliminar"""
    # Obtener todos los tickets
    tickets = Ticket.query.order_by(Ticket.id.desc()).all()
    
    return render_template('listado_tickets.html', tickets=tickets)

@tickets_bp.route('/tickets/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_ticket():
    """Crear nuevo ticket (factura simplificada)"""
    if request.method == 'POST':
        try:
            # Procesar fecha de expedición
            fecha_expedicion = datetime.strptime(request.form.get('fecha_expedicion'), '%Y-%m-%d').date()
            
            # Generar número de ticket automáticamente
            serie = 'A'  # Serie fija
            numero = obtener_siguiente_numero_ticket(fecha_expedicion)
            
            # Crear ticket
            ticket = Ticket(
                serie=serie,
                numero=numero,
                fecha_expedicion=fecha_expedicion,
                tipo_factura=request.form.get('tipo_factura', 'F2'),
                descripcion=request.form.get('descripcion', ''),
                nif=request.form.get('nif', ''),
                nombre=request.form.get('nombre'),
                forma_pago=request.form.get('forma_pago', ''),
                tipo_calculo_iva=request.form.get('tipo_calculo_iva', 'desglosar'),
                importe_total=Decimal('0.00'),
                estado='pendiente'
            )
            
            db.session.add(ticket)
            db.session.flush()  # Para obtener el ID del ticket
            
            # Crear líneas de ticket
            descripciones = request.form.getlist('descripcion_linea[]')
            cantidades = request.form.getlist('cantidad[]')
            precios_unitarios = request.form.getlist('precio_unitario[]')
            
            tipo_calculo_iva = request.form.get('tipo_calculo_iva', 'desglosar')
            tipo_iva = Decimal('21')  # IVA al 21%
            
            importe_total = Decimal('0.00')
            
            for i in range(len(descripciones)):
                if descripciones[i] and cantidades[i] and precios_unitarios[i]:
                    cantidad = Decimal(cantidades[i])
                    precio_unitario = Decimal(precios_unitarios[i])
                    
                    # Calcular importe según el tipo de cálculo de IVA
                    if tipo_calculo_iva == 'incrementar':
                        # Precio unitario es sin IVA, calcular con IVA
                        precio_con_iva = precio_unitario * (Decimal('1') + tipo_iva / Decimal('100'))
                        importe = cantidad * precio_con_iva
                    else:  # desglosar
                        # Precio unitario ya incluye IVA
                        importe = cantidad * precio_unitario
                    
                    importe_total += importe
                    
                    linea = LineaTicket(
                        ticket_id=ticket.id,
                        descripcion=descripciones[i],
                        cantidad=cantidad,
                        precio_unitario=precio_unitario,
                        importe=importe
                    )
                    db.session.add(linea)
            
            # Actualizar importe total del ticket
            ticket.importe_total = importe_total
            
            # Enviar a Verifactu
            verifactu_url = os.environ.get('VERIFACTU_URL', 'https://api.verifacti.com/verifactu/create')
            verifactu_token = os.environ.get('VERIFACTU_TOKEN', '')
            
            if verifactu_token:
                # Preparar datos para la API
                # Calcular base imponible e IVA para cada línea
                # Asumimos que el importe incluye IVA al 21%
                tipo_impositivo = 21  # IVA estándar en España
                lineas_payload = []
                total_base_imponible = Decimal('0.00')
                total_cuota_repercutida = Decimal('0.00')
                
                for linea in ticket.lineas:
                    # Si el importe incluye IVA, calcular base imponible
                    importe_con_iva = Decimal(str(linea.importe))
                    # Calcular base imponible: importe / (1 + tipo_impositivo/100)
                    base_imponible = importe_con_iva / (Decimal('1') + Decimal(str(tipo_impositivo)) / Decimal('100'))
                    # Calcular cuota repercutida: base_imponible * (tipo_impositivo/100)
                    cuota_repercutida = base_imponible * (Decimal(str(tipo_impositivo)) / Decimal('100'))
                    
                    # Redondear a 2 decimales
                    base_imponible = base_imponible.quantize(Decimal('0.01'))
                    cuota_repercutida = cuota_repercutida.quantize(Decimal('0.01'))
                    
                    total_base_imponible += base_imponible
                    total_cuota_repercutida += cuota_repercutida
                    
                    lineas_payload.append({
                        'base_imponible': str(base_imponible),
                        'tipo_impositivo': str(tipo_impositivo),
                        'cuota_repercutida': str(cuota_repercutida)
                    })
                
                # Para facturas simplificadas (F2) no se envían nombre, nif ni id_otro
                payload = {
                    'serie': ticket.serie,
                    'numero': ticket.numero,
                    'fecha_expedicion': ticket.fecha_expedicion.strftime('%d-%m-%Y'),
                    'tipo_factura': ticket.tipo_factura,
                    'descripcion': ticket.descripcion or 'Descripcion de la operacion',
                    'lineas': lineas_payload,
                    'importe_total': str(ticket.importe_total)
                }
                
                # Solo agregar nombre y nif si NO es factura simplificada (aunque para F2 no debería ser necesario)
                # Pero por seguridad, no los incluimos para F2
                
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {verifactu_token}'
                }
                
                try:
                    response = requests.post(verifactu_url, json=payload, headers=headers, timeout=30)
                    
                    if response.status_code == 200 or response.status_code == 201:
                        # Éxito: guardar la huella
                        response_data = response.json()
                        ticket.huella_verifactu = json.dumps(response_data)
                        ticket.estado = 'confirmado'
                        ticket.fecha_confirmacion = datetime.utcnow()
                        flash('Ticket creado y enviado a Verifactu correctamente.', 'success')
                    else:
                        # Error en la API
                        ticket.estado = 'error'
                        ticket.huella_verifactu = json.dumps({
                            'error': response.text,
                            'status_code': response.status_code
                        })
                        flash(f'Error al enviar a Verifactu: {response.status_code} - {response.text}', 'error')
                except requests.exceptions.RequestException as e:
                    # Error de conexión
                    ticket.estado = 'error'
                    ticket.huella_verifactu = json.dumps({'error': str(e)})
                    flash(f'Error de conexión con Verifactu: {str(e)}', 'error')
            else:
                # Sin token, solo guardar como pendiente
                ticket.estado = 'pendiente'
                flash('Ticket creado. Configure VERIFACTU_TOKEN para enviar automáticamente.', 'warning')
            
            db.session.commit()
            return redirect(url_for('tickets.listado_tickets'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear el ticket: {str(e)}', 'error')
            return redirect(url_for('tickets.nuevo_ticket'))
    
    # GET: mostrar formulario
    return render_template('nuevo_ticket.html')

@tickets_bp.route('/tickets/<int:ticket_id>')
@login_required
def ver_ticket(ticket_id):
    """Ver detalles de un ticket"""
    ticket = Ticket.query.get_or_404(ticket_id)
    return render_template('ver_ticket.html', ticket=ticket)

@tickets_bp.route('/tickets/<int:ticket_id>/eliminar', methods=['POST'])
@login_required
def eliminar_ticket(ticket_id):
    """Eliminar un ticket"""
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        db.session.delete(ticket)
        db.session.commit()
        flash('Ticket eliminado correctamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar el ticket: {str(e)}', 'error')
    
    return redirect(url_for('tickets.listado_tickets'))

@tickets_bp.route('/tickets/<int:ticket_id>/reenviar', methods=['POST'])
@login_required
def reenviar_ticket(ticket_id):
    """Reenviar un ticket a Verifactu"""
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        
        verifactu_url = os.environ.get('VERIFACTU_URL', 'https://api.verifacti.com/verifactu/create')
        verifactu_token = os.environ.get('VERIFACTU_TOKEN', '')
        
        if not verifactu_token:
            flash('No se ha configurado VERIFACTU_TOKEN.', 'error')
            return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))
        
        # Preparar datos para la API
        # Calcular base imponible e IVA para cada línea
        # Asumimos que el importe incluye IVA al 21%
        tipo_impositivo = 21  # IVA estándar en España
        lineas_payload = []
        total_base_imponible = Decimal('0.00')
        total_cuota_repercutida = Decimal('0.00')
        
        for linea in ticket.lineas:
            # Si el importe incluye IVA, calcular base imponible
            importe_con_iva = Decimal(str(linea.importe))
            # Calcular base imponible: importe / (1 + tipo_impositivo/100)
            base_imponible = importe_con_iva / (Decimal('1') + Decimal(str(tipo_impositivo)) / Decimal('100'))
            # Calcular cuota repercutida: base_imponible * (tipo_impositivo/100)
            cuota_repercutida = base_imponible * (Decimal(str(tipo_impositivo)) / Decimal('100'))
            
            # Redondear a 2 decimales
            base_imponible = base_imponible.quantize(Decimal('0.01'))
            cuota_repercutida = cuota_repercutida.quantize(Decimal('0.01'))
            
            total_base_imponible += base_imponible
            total_cuota_repercutida += cuota_repercutida
            
            lineas_payload.append({
                'base_imponible': str(base_imponible),
                'tipo_impositivo': str(tipo_impositivo),
                'cuota_repercutida': str(cuota_repercutida)
            })
        
        # Para facturas simplificadas (F2) no se envían nombre, nif ni id_otro
        payload = {
            'serie': ticket.serie,
            'numero': ticket.numero,
            'fecha_expedicion': ticket.fecha_expedicion.strftime('%d-%m-%Y'),
            'tipo_factura': ticket.tipo_factura,
            'descripcion': ticket.descripcion or 'Descripcion de la operacion',
            'lineas': lineas_payload,
            'importe_total': str(ticket.importe_total)
        }
        
        # Solo agregar nombre y nif si NO es factura simplificada (aunque para F2 no debería ser necesario)
        # Pero por seguridad, no los incluimos para F2
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {verifactu_token}'
        }
        
        try:
            response = requests.post(verifactu_url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200 or response.status_code == 201:
                # Éxito: guardar la huella
                response_data = response.json()
                ticket.huella_verifactu = json.dumps(response_data)
                ticket.estado = 'confirmado'
                ticket.fecha_confirmacion = datetime.utcnow()
                db.session.commit()
                flash('Ticket reenviado a Verifactu correctamente.', 'success')
            else:
                # Error en la API
                ticket.estado = 'error'
                ticket.huella_verifactu = json.dumps({
                    'error': response.text,
                    'status_code': response.status_code
                })
                db.session.commit()
                flash(f'Error al reenviar a Verifactu: {response.status_code} - {response.text}', 'error')
        except requests.exceptions.RequestException as e:
            # Error de conexión
            ticket.estado = 'error'
            ticket.huella_verifactu = json.dumps({'error': str(e)})
            db.session.commit()
            flash(f'Error de conexión con Verifactu: {str(e)}', 'error')
        
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al reenviar el ticket: {str(e)}', 'error')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

