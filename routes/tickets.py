"""Rutas para gestión de tickets de tienda (Facturas simplificadas)"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_file
from flask_login import login_required
from datetime import datetime
from decimal import Decimal
import os
import requests
import json
import base64
import tempfile
from io import BytesIO
from extensions import db
from models import Ticket, LineaTicket, ClienteTienda
from flask import jsonify
from utils.numeracion import obtener_siguiente_numero_ticket
from playwright.sync_api import sync_playwright

tickets_bp = Blueprint('tickets', __name__)

@tickets_bp.route('/tickets/clientes-tienda')
@login_required
def listado_clientes_tienda():
    """Listado de clientes de tienda"""
    clientes = ClienteTienda.query.order_by(ClienteTienda.nombre).all()
    return render_template('listado_clientes_tienda.html', clientes=clientes)

@tickets_bp.route('/tickets')
@login_required
def listado_tickets():
    """Listado de tickets con opciones de ver y eliminar"""
    query = Ticket.query
    
    # Filtro por estado
    estado_filtro = request.args.get('estado', '')
    if estado_filtro:
        query = query.filter(Ticket.estado == estado_filtro)
    
    # Filtro por fecha desde
    fecha_desde = request.args.get('fecha_desde', '')
    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            query = query.filter(Ticket.fecha_expedicion >= fecha_desde_obj)
        except ValueError:
            pass
    
    # Filtro por fecha hasta
    fecha_hasta = request.args.get('fecha_hasta', '')
    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            query = query.filter(Ticket.fecha_expedicion <= fecha_hasta_obj)
        except ValueError:
            pass
    
    tickets = query.order_by(Ticket.id.desc()).all()
    
    # Obtener estados únicos para el filtro
    estados = db.session.query(Ticket.estado).distinct().all()
    estados_list = [estado[0] for estado in estados if estado[0]]
    
    return render_template('listado_tickets.html', 
                         tickets=tickets,
                         estados=estados_list,
                         estado_filtro=estado_filtro,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta)

@tickets_bp.route('/tickets/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_ticket():
    """Crear nuevo ticket (factura simplificada)"""
    if request.method == 'POST':
        try:
            # Procesar fecha de expedición
            fecha_expedicion = datetime.strptime(request.form.get('fecha_expedicion'), '%Y-%m-%d').date()
            
            # Generar número de ticket automáticamente
            serie = 'T'  # Serie fija
            numero = obtener_siguiente_numero_ticket(fecha_expedicion)
            
            # Obtener datos del cliente
            nombre_cliente = request.form.get('nombre')
            nif_cliente = request.form.get('nif', '')
            email_cliente = request.form.get('email', '')
            categoria_cliente = request.form.get('categoria', '')
            
            # Guardar o actualizar cliente de tienda
            cliente_tienda = ClienteTienda.query.filter_by(
                nombre=nombre_cliente,
                nif=nif_cliente if nif_cliente else None
            ).first()
            
            if not cliente_tienda:
                cliente_tienda = ClienteTienda(
                    nombre=nombre_cliente,
                    nif=nif_cliente if nif_cliente else None,
                    email=email_cliente if email_cliente else None,
                    categoria=categoria_cliente
                )
                db.session.add(cliente_tienda)
                db.session.flush()
            else:
                # Actualizar email y categoría si están presentes
                if email_cliente:
                    cliente_tienda.email = email_cliente
                if categoria_cliente:
                    cliente_tienda.categoria = categoria_cliente
            
            # Crear ticket
            ticket = Ticket(
                serie=serie,
                numero=numero,
                fecha_expedicion=fecha_expedicion,
                tipo_factura=request.form.get('tipo_factura', 'F2'),
                descripcion=request.form.get('descripcion', ''),
                nif=nif_cliente,
                nombre=nombre_cliente,
                email=email_cliente,
                categoria=categoria_cliente,
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
                    precio_unitario_input = Decimal(precios_unitarios[i])
                    
                    # Siempre guardar precio sin IVA
                    # El precio que viene del formulario ya es sin IVA (después de los cambios en el frontend)
                    precio_unitario_sin_iva = precio_unitario_input
                    
                    # Calcular importe sin IVA
                    importe_sin_iva = cantidad * precio_unitario_sin_iva
                    
                    # Calcular importe con IVA para el total del ticket
                    importe_con_iva = importe_sin_iva * (Decimal('1') + tipo_iva / Decimal('100'))
                    importe_total += importe_con_iva
                    
                    # Guardar precio sin IVA e importe sin IVA en la línea
                    linea = LineaTicket(
                        ticket_id=ticket.id,
                        descripcion=descripciones[i],
                        cantidad=cantidad,
                        precio_unitario=precio_unitario_sin_iva,
                        importe=importe_sin_iva  # Guardar importe sin IVA
                    )
                    db.session.add(linea)
            
            # Actualizar importe total del ticket
            ticket.importe_total = importe_total
            
            # Verificar si el envío a Verifactu está activado
            from models import Configuracion
            config = Configuracion.query.filter_by(clave='verifactu_enviar_activo').first()
            verifactu_enviar_activo = True  # Por defecto activado
            if config:
                verifactu_enviar_activo = config.valor.lower() == 'true'
            
            # Enviar a Verifactu solo si está activado y hay token
            verifactu_url = os.environ.get('VERIFACTU_URL', 'https://api.verifacti.com/verifactu/create')
            verifactu_token = os.environ.get('VERIFACTU_TOKEN', '')
            
            if verifactu_token and verifactu_enviar_activo:
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
            elif not verifactu_enviar_activo:
                # Envío desactivado, solo guardar como pendiente
                ticket.estado = 'pendiente'
                flash('Ticket creado. El envío automático a Verifactu está desactivado.', 'info')
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

def preparar_datos_imprimir_ticket(ticket_id):
    """Preparar datos del ticket para impresión en PDF"""
    ticket = Ticket.query.get_or_404(ticket_id)
    
    # Calcular base imponible e IVA
    if ticket.tipo_calculo_iva == 'incrementar':
        # El importe_total es base + IVA
        base_imponible = float(ticket.importe_total) / 1.21
        iva_total = float(ticket.importe_total) - base_imponible
    else:
        # El importe_total ya incluye IVA
        base_imponible = float(ticket.importe_total) / 1.21
        iva_total = float(ticket.importe_total) - base_imponible
    
    # Función auxiliar para convertir imagen a base64
    def convertir_imagen_a_base64(ruta_imagen):
        """Convertir imagen a base64"""
        if not ruta_imagen or not os.path.exists(ruta_imagen):
            return None
        try:
            with open(ruta_imagen, 'rb') as f:
                imagen_data = f.read()
                imagen_base64 = base64.b64encode(imagen_data).decode('utf-8')
                # Detectar tipo MIME
                if ruta_imagen.lower().endswith('.png'):
                    return f'data:image/png;base64,{imagen_base64}'
                elif ruta_imagen.lower().endswith(('.jpg', '.jpeg')):
                    return f'data:image/jpeg;base64,{imagen_base64}'
                elif ruta_imagen.lower().endswith('.gif'):
                    return f'data:image/gif;base64,{imagen_base64}'
                else:
                    return f'data:image/png;base64,{imagen_base64}'  # Por defecto PNG
        except Exception as e:
            print(f"Error al leer imagen {ruta_imagen}: {e}")
            return None
    
    # Convertir logo a base64
    logo_base64 = None
    logo_path = os.path.join(current_app.static_folder, 'logo1.png')
    logo_base64 = convertir_imagen_a_base64(logo_path)
    
    return {
        'ticket': ticket,
        'base_imponible': float(base_imponible),
        'iva_total': float(iva_total),
        'total_con_iva': float(ticket.importe_total),
        'logo_base64': logo_base64
    }

@tickets_bp.route('/tickets/<int:ticket_id>/imprimir')
@login_required
def imprimir_ticket(ticket_id):
    """Vista previa del ticket para imprimir"""
    datos = preparar_datos_imprimir_ticket(ticket_id)
    return render_template('imprimir_ticket_pdf.html', **datos, use_base64=False)

@tickets_bp.route('/tickets/<int:ticket_id>/descargar-pdf')
@login_required
def descargar_pdf_ticket(ticket_id):
    """Descargar ticket en formato PDF"""
    try:
        datos = preparar_datos_imprimir_ticket(ticket_id)
        
        # Renderizar el HTML como ticket
        html = render_template('imprimir_ticket_pdf.html', 
                             **datos,
                             use_base64=True)
        
        # Crear el PDF en memoria usando playwright
        pdf_buffer = BytesIO()
        
        try:
            # Guardar HTML temporalmente para que playwright pueda acceder a él
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as temp_file:
                temp_file.write(html)
                temp_html_path = temp_file.name
            
            # Usar playwright para generar el PDF
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                # Cargar el HTML desde el archivo temporal
                page.goto(f'file://{temp_html_path}')
                
                # Generar PDF
                pdf_bytes = page.pdf(
                    format='A4',
                    print_background=True,
                    margin={
                        'top': '10mm',
                        'right': '10mm',
                        'bottom': '10mm',
                        'left': '10mm'
                    }
                )
                
                browser.close()
            
            # Escribir el PDF al buffer
            pdf_buffer.write(pdf_bytes)
            pdf_buffer.seek(0)
            
            # Limpiar archivo temporal
            try:
                os.unlink(temp_html_path)
            except:
                pass
            
            # Devolver el PDF
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ticket_{datos["ticket"].serie}_{datos["ticket"].numero}.pdf'
            )
            
        except Exception as e:
            # Limpiar archivo temporal en caso de error
            try:
                if 'temp_html_path' in locals():
                    os.unlink(temp_html_path)
            except:
                pass
            raise e
            
    except Exception as e:
        flash(f'Error al generar PDF: {str(e)}', 'error')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

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

@tickets_bp.route('/tickets/cuadre-caja')
@login_required
def cuadre_caja():
    """Cuadre de caja diario - mostrar totales por forma de pago"""
    # Obtener fecha del filtro o usar hoy por defecto
    fecha_cuadre = request.args.get('fecha', '')
    
    if fecha_cuadre:
        try:
            fecha_cuadre_obj = datetime.strptime(fecha_cuadre, '%Y-%m-%d').date()
        except ValueError:
            fecha_cuadre_obj = datetime.now().date()
    else:
        fecha_cuadre_obj = datetime.now().date()
    
    # Obtener todos los tickets del día seleccionado
    tickets_dia = Ticket.query.filter(
        Ticket.fecha_expedicion == fecha_cuadre_obj
    ).all()
    
    # Calcular totales por forma de pago
    total_efectivo = Decimal('0.00')
    total_tarjeta = Decimal('0.00')
    total_bizum = Decimal('0.00')
    total_transferencia = Decimal('0.00')
    total_general = Decimal('0.00')
    
    # Contadores por forma de pago
    cantidad_efectivo = 0
    cantidad_tarjeta = 0
    cantidad_bizum = 0
    cantidad_transferencia = 0
    
    for ticket in tickets_dia:
        importe = Decimal(str(ticket.importe_total))
        forma_pago = ticket.forma_pago.lower() if ticket.forma_pago else ''
        
        total_general += importe
        
        if forma_pago == 'efectivo':
            total_efectivo += importe
            cantidad_efectivo += 1
        elif forma_pago == 'tarjeta':
            total_tarjeta += importe
            cantidad_tarjeta += 1
        elif forma_pago == 'bizum':
            total_bizum += importe
            cantidad_bizum += 1
        elif forma_pago == 'transferencia':
            total_transferencia += importe
            cantidad_transferencia += 1
    
    # Preparar datos para el template
    resumen = {
        'fecha': fecha_cuadre_obj,
        'total_efectivo': float(total_efectivo),
        'total_tarjeta': float(total_tarjeta),
        'total_bizum': float(total_bizum),
        'total_transferencia': float(total_transferencia),
        'total_general': float(total_general),
        'cantidad_efectivo': cantidad_efectivo,
        'cantidad_tarjeta': cantidad_tarjeta,
        'cantidad_bizum': cantidad_bizum,
        'cantidad_transferencia': cantidad_transferencia,
        'tickets_dia': tickets_dia,
        'total_tickets': len(tickets_dia)
    }
    
    return render_template('tickets/cuadre_caja.html', **resumen)

@tickets_bp.route('/tickets/<int:ticket_id>/reenviar', methods=['POST'])
@login_required
def reenviar_ticket(ticket_id):
    """Reenviar un ticket a Verifactu"""
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        
        # Verificar si el envío a Verifactu está activado
        from models import Configuracion
        config = Configuracion.query.filter_by(clave='verifactu_enviar_activo').first()
        verifactu_enviar_activo = True  # Por defecto activado
        if config:
            verifactu_enviar_activo = config.valor.lower() == 'true'
        
        verifactu_url = os.environ.get('VERIFACTU_URL', 'https://api.verifacti.com/verifactu/create')
        verifactu_token = os.environ.get('VERIFACTU_TOKEN', '')
        
        if not verifactu_token:
            flash('No se ha configurado VERIFACTU_TOKEN.', 'error')
            return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))
        
        if not verifactu_enviar_activo:
            flash('El envío automático a Verifactu está desactivado. Actívalo en Configuración > Verifactu para reenviar.', 'warning')
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

