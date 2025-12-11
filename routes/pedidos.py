"""Rutas para gestión de pedidos"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, make_response
from flask_login import login_required
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from io import BytesIO
import os
from extensions import db
from models import Comercial, Cliente, Prenda, Pedido, LineaPedido, Usuario

pedidos_bp = Blueprint('pedidos', __name__)

@pedidos_bp.route('/pedidos')
@login_required
def listado_pedidos():
    """Listado de pedidos con opciones de editar y eliminar"""
    # Obtener todos los pedidos
    pedidos = Pedido.query.order_by(Pedido.id.desc()).all()
    
    # Calcular fecha objetivo de entrega (20 días desde aceptación) y clasificar
    hoy = datetime.now().date()
    
    for pedido in pedidos:
        # Si no tiene fecha objetivo pero tiene fecha de aceptación, calcularla (20 días)
        if pedido.fecha_aceptacion and not pedido.fecha_objetivo:
            pedido.fecha_objetivo = pedido.fecha_aceptacion + timedelta(days=20)
        
        if pedido.fecha_objetivo:
            # Calcular días restantes hasta la fecha objetivo
            dias_restantes = (pedido.fecha_objetivo - hoy).days
            
            # Clasificar fecha objetivo según días restantes
            if dias_restantes <= 5:
                # 5 días o menos (incluye vencidos): Rojo
                pedido.fecha_class = 'urgente'
            elif dias_restantes <= 10:
                # Entre 6 y 10 días: Naranja
                pedido.fecha_class = 'proxima'
            else:
                # Más de 10 días: Verde
                pedido.fecha_class = 'ok'
        else:
            pedido.fecha_class = ''
    
    return render_template('listado_pedidos.html', pedidos=pedidos)

@pedidos_bp.route('/pedidos/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_pedido():
    """Crear nuevo pedido"""
    if request.method == 'POST':
        try:
            # Procesar fechas
            fecha_aceptacion = None
            if request.form.get('fecha_aceptacion'):
                fecha_aceptacion = datetime.strptime(request.form.get('fecha_aceptacion'), '%Y-%m-%d').date()
            
            fecha_objetivo = None
            if request.form.get('fecha_objetivo'):
                # Si se proporciona fecha objetivo, usarla
                fecha_objetivo = datetime.strptime(request.form.get('fecha_objetivo'), '%Y-%m-%d').date()
            elif fecha_aceptacion:
                # Si no se proporciona pero hay fecha de aceptación, calcularla automáticamente (20 días)
                fecha_objetivo = fecha_aceptacion + timedelta(days=20)
            
            # Crear pedido
            pedido = Pedido(
                comercial_id=request.form.get('comercial_id'),
                cliente_id=request.form.get('cliente_id'),
                tipo_pedido=request.form.get('tipo_pedido'),
                estado='Pendiente',  # Siempre se establece como Pendiente al crear
                forma_pago=request.form.get('forma_pago', ''),
                fecha_aceptacion=fecha_aceptacion,
                fecha_objetivo=fecha_objetivo
            )
            
            # Manejar imagen de diseño
            if 'imagen_diseno' in request.files:
                file = request.files['imagen_diseno']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                    filename = timestamp + filename
                    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    pedido.imagen_diseno = filename
            
            db.session.add(pedido)
            db.session.flush()  # Para obtener el ID del pedido
            
            # Crear líneas de pedido
            prenda_ids = request.form.getlist('prenda_id[]')
            nombres = request.form.getlist('nombre[]')  # Mantenido para compatibilidad
            cargos = request.form.getlist('cargo[]')  # Mantenido para compatibilidad
            nombres_mostrar = request.form.getlist('nombre_mostrar[]')
            cantidades = request.form.getlist('cantidad[]')
            colores = request.form.getlist('color[]')
            formas = request.form.getlist('forma[]')
            tipos_manda = request.form.getlist('tipo_manda[]')
            sexos = request.form.getlist('sexo[]')
            tallas = request.form.getlist('talla[]')
            tejidos = request.form.getlist('tejido[]')
            precios_unitarios = request.form.getlist('precio_unitario[]')
            estados_lineas = request.form.getlist('estado_linea[]')
            
            for i in range(len(prenda_ids)):
                if prenda_ids[i] and (nombres_mostrar[i] if i < len(nombres_mostrar) else nombres[i] if i < len(nombres) else ''):
                    from decimal import Decimal
                    precio_unitario = None
                    if i < len(precios_unitarios) and precios_unitarios[i]:
                        try:
                            precio_unitario = Decimal(str(precios_unitarios[i]))
                        except:
                            precio_unitario = None
                    
                    # Usar nombre_mostrar si existe, sino usar nombre (compatibilidad)
                    nombre_mostrar_val = nombres_mostrar[i] if i < len(nombres_mostrar) and nombres_mostrar[i] else (nombres[i] if i < len(nombres) else '')
                    
                    linea = LineaPedido(
                        pedido_id=pedido.id,
                        prenda_id=prenda_ids[i],
                        nombre=nombres[i] if i < len(nombres) else '',  # Mantenido para compatibilidad
                        cargo=cargos[i] if i < len(cargos) else '',  # Mantenido para compatibilidad
                        nombre_mostrar=nombre_mostrar_val,
                        cantidad=int(cantidades[i]) if cantidades[i] else 1,
                        color=colores[i] if i < len(colores) else '',
                        forma=formas[i] if i < len(formas) else '',
                        tipo_manda=tipos_manda[i] if i < len(tipos_manda) else '',
                        sexo=sexos[i] if i < len(sexos) else '',
                        talla=tallas[i] if i < len(tallas) else '',
                        tejido=tejidos[i] if i < len(tejidos) else '',
                        precio_unitario=precio_unitario,
                        estado=estados_lineas[i] if i < len(estados_lineas) and estados_lineas[i] else 'pendiente'
                    )
                    db.session.add(linea)
            
            db.session.commit()
            flash('Pedido creado correctamente', 'success')
            return redirect(url_for('index.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear pedido: {str(e)}', 'error')
    
    comerciales = Comercial.query.join(Usuario).filter(
        Usuario.activo == True,
        Usuario.rol.in_(['comercial', 'administracion'])
    ).all()
    clientes = Cliente.query.all()
    prendas = Prenda.query.all()
    return render_template('nuevo_pedido.html', 
                         comerciales=comerciales, 
                         clientes=clientes, 
                         prendas=prendas)

@pedidos_bp.route('/pedidos/<int:pedido_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_pedido(pedido_id):
    """Editar pedido existente"""
    pedido = Pedido.query.get_or_404(pedido_id)
    
    if request.method == 'POST':
        try:
            pedido.comercial_id = request.form.get('comercial_id')
            pedido.cliente_id = request.form.get('cliente_id')
            pedido.tipo_pedido = request.form.get('tipo_pedido')
            pedido.estado = request.form.get('estado')
            pedido.forma_pago = request.form.get('forma_pago', '')
            
            # Fechas
            if request.form.get('fecha_aceptacion'):
                pedido.fecha_aceptacion = datetime.strptime(request.form.get('fecha_aceptacion'), '%Y-%m-%d')
            if request.form.get('fecha_entrega_trabajo'):
                pedido.fecha_entrega_trabajo = datetime.strptime(request.form.get('fecha_entrega_trabajo'), '%Y-%m-%d')
            if request.form.get('fecha_envio_taller'):
                pedido.fecha_envio_taller = datetime.strptime(request.form.get('fecha_envio_taller'), '%Y-%m-%d')
            if request.form.get('fecha_entrega_bordados'):
                pedido.fecha_entrega_bordados = datetime.strptime(request.form.get('fecha_entrega_bordados'), '%Y-%m-%d')
            if request.form.get('fecha_entrega_cliente'):
                pedido.fecha_entrega_cliente = datetime.strptime(request.form.get('fecha_entrega_cliente'), '%Y-%m-%d')
            
            # Manejar nueva imagen de diseño
            if 'imagen_diseno' in request.files:
                file = request.files['imagen_diseno']
                if file and file.filename:
                    # Eliminar imagen anterior si existe
                    if pedido.imagen_diseno:
                        old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], pedido.imagen_diseno)
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                    filename = timestamp + filename
                    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    pedido.imagen_diseno = filename
            
            # Eliminar líneas existentes (dentro de la misma transacción)
            try:
                LineaPedido.query.filter_by(pedido_id=pedido.id).delete()
            except Exception as e:
                db.session.rollback()
                flash(f'Error al eliminar líneas anteriores: {str(e)}', 'error')
                return redirect(url_for('pedidos.editar_pedido', pedido_id=pedido_id))
            
            # Crear nuevas líneas
            prenda_ids = request.form.getlist('prenda_id[]')
            nombres = request.form.getlist('nombre[]')  # Mantenido para compatibilidad
            cargos = request.form.getlist('cargo[]')  # Mantenido para compatibilidad
            nombres_mostrar = request.form.getlist('nombre_mostrar[]')
            cantidades = request.form.getlist('cantidad[]')
            colores = request.form.getlist('color[]')
            formas = request.form.getlist('forma[]')
            tipos_manda = request.form.getlist('tipo_manda[]')
            sexos = request.form.getlist('sexo[]')
            tallas = request.form.getlist('talla[]')
            tejidos = request.form.getlist('tejido[]')
            precios_unitarios = request.form.getlist('precio_unitario[]')
            estados_lineas = request.form.getlist('estado_linea[]')
            
            for i in range(len(prenda_ids)):
                if prenda_ids[i] and (nombres_mostrar[i] if i < len(nombres_mostrar) else nombres[i] if i < len(nombres) else ''):
                    from decimal import Decimal
                    precio_unitario = None
                    if i < len(precios_unitarios) and precios_unitarios[i]:
                        try:
                            precio_unitario = Decimal(str(precios_unitarios[i]))
                        except:
                            precio_unitario = None
                    
                    # Usar nombre_mostrar si existe, sino usar nombre (compatibilidad)
                    nombre_mostrar_val = nombres_mostrar[i] if i < len(nombres_mostrar) and nombres_mostrar[i] else (nombres[i] if i < len(nombres) else '')
                    
                    linea = LineaPedido(
                        pedido_id=pedido.id,
                        prenda_id=prenda_ids[i],
                        nombre=nombres[i] if i < len(nombres) else '',  # Mantenido para compatibilidad
                        cargo=cargos[i] if i < len(cargos) else '',  # Mantenido para compatibilidad
                        nombre_mostrar=nombre_mostrar_val,
                        cantidad=int(cantidades[i]) if cantidades[i] else 1,
                        color=colores[i] if i < len(colores) else '',
                        forma=formas[i] if i < len(formas) else '',
                        tipo_manda=tipos_manda[i] if i < len(tipos_manda) else '',
                        sexo=sexos[i] if i < len(sexos) else '',
                        talla=tallas[i] if i < len(tallas) else '',
                        tejido=tejidos[i] if i < len(tejidos) else '',
                        precio_unitario=precio_unitario,
                        estado=estados_lineas[i] if i < len(estados_lineas) and estados_lineas[i] else 'pendiente'
                    )
                    db.session.add(linea)
            
            db.session.commit()
            flash('Pedido actualizado correctamente', 'success')
            return redirect(url_for('index.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar pedido: {str(e)}', 'error')
    
    comerciales = Comercial.query.join(Usuario).filter(
        Usuario.activo == True,
        Usuario.rol.in_(['comercial', 'administracion'])
    ).all()
    clientes = Cliente.query.all()
    prendas = Prenda.query.all()
    return render_template('editar_pedido.html', 
                         pedido=pedido,
                         comerciales=comerciales, 
                         clientes=clientes, 
                         prendas=prendas)

@pedidos_bp.route('/pedidos/<int:pedido_id>')
@login_required
def ver_pedido(pedido_id):
    """Vista detallada del pedido"""
    pedido = Pedido.query.get_or_404(pedido_id)
    # Calcular fecha objetivo
    hoy = datetime.now().date()
    fecha_objetivo = None
    fecha_class = ''
    
    # Usar fecha objetivo guardada, o calcularla si no existe (20 días desde aceptación)
    if pedido.fecha_objetivo:
        fecha_objetivo = pedido.fecha_objetivo
    elif pedido.fecha_aceptacion:
        fecha_objetivo = pedido.fecha_aceptacion + timedelta(days=20)
    else:
        fecha_objetivo = None
    
    if fecha_objetivo:
        # Calcular días restantes hasta la fecha objetivo
        dias_restantes = (fecha_objetivo - hoy).days
        
        # Clasificar fecha objetivo según días restantes
        if dias_restantes <= 5:
            # 5 días o menos (incluye vencidos): Rojo
            fecha_class = 'urgente'
        elif dias_restantes <= 10:
            # Entre 6 y 10 días: Naranja
            fecha_class = 'proxima'
        else:
            # Más de 10 días: Verde
            fecha_class = 'ok'
    else:
        fecha_class = ''
    
    return render_template('ver_pedido.html', 
                         pedido=pedido, 
                         fecha_objetivo=fecha_objetivo,
                         fecha_class=fecha_class)

@pedidos_bp.route('/pedidos/<int:pedido_id>/cambiar-estado', methods=['POST'])
@login_required
def cambiar_estado_pedido(pedido_id):
    """Cambiar el estado del pedido y actualizar la fecha correspondiente"""
    pedido = Pedido.query.get_or_404(pedido_id)
    nuevo_estado = request.form.get('estado')
    hoy = datetime.now().date()
    
    try:
        # Guardar el estado anterior
        estado_anterior = pedido.estado
        
        # Mapeo de estados a fechas y nombres de estado
        estados_fechas = {
            'Pendiente': (None, 'Pendiente'),
            'Diseño': (None, 'Diseño'),
            'En preparación': ('fecha_aceptacion', 'En preparación'),
            'Todo listo': (None, 'Todo listo'),
            'Enviado': (None, 'Enviado'),
            'Entregado al cliente': ('fecha_entrega_cliente', 'Entregado al cliente')
        }
        
        if nuevo_estado in estados_fechas:
            fecha_campo, estado_nombre = estados_fechas[nuevo_estado]
            
            # Actualizar el estado
            pedido.estado = estado_nombre
            
            # Si tiene fecha asociada, actualizar la fecha a hoy
            if fecha_campo:
                setattr(pedido, fecha_campo, hoy)
            
            db.session.commit()
            
            # Enviar email al cliente si el estado cambió
            if estado_anterior != estado_nombre:
                try:
                    from utils.email import enviar_email_cambio_estado_pedido
                    exito, mensaje = enviar_email_cambio_estado_pedido(pedido, estado_nombre, estado_anterior)
                    if exito:
                        flash(f'Estado del pedido cambiado a "{estado_nombre}". Email enviado al cliente.', 'success')
                    else:
                        flash(f'Estado del pedido cambiado a "{estado_nombre}". Error al enviar email: {mensaje}', 'warning')
                except Exception as e:
                    flash(f'Estado del pedido cambiado a "{estado_nombre}". Error al enviar email: {str(e)}', 'warning')
            else:
                flash(f'Estado del pedido cambiado a "{estado_nombre}"', 'success')
        else:
            flash('Estado no válido', 'error')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar el estado: {str(e)}', 'error')
    
    return redirect(url_for('pedidos.ver_pedido', pedido_id=pedido_id))

@pedidos_bp.route('/pedidos/<int:pedido_id>/lineas/<int:linea_id>/cambiar-estado', methods=['POST'])
@login_required
def cambiar_estado_linea(pedido_id, linea_id):
    """Cambiar el estado de una línea de pedido"""
    linea = LineaPedido.query.get_or_404(linea_id)
    nuevo_estado = request.form.get('estado')
    
    # Validar que la línea pertenece al pedido
    if linea.pedido_id != pedido_id:
        flash('La línea no pertenece a este pedido', 'error')
        return redirect(url_for('pedidos.ver_pedido', pedido_id=pedido_id))
    
    # Validar estados permitidos
    estados_permitidos = ['pendiente', 'en confección', 'en bordado', 'listo']
    
    try:
        if nuevo_estado in estados_permitidos:
            linea.estado = nuevo_estado
            db.session.commit()
            flash(f'Estado de la línea "{linea.nombre}" cambiado a "{nuevo_estado}"', 'success')
        else:
            flash('Estado no válido', 'error')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar el estado: {str(e)}', 'error')
    
    return redirect(url_for('pedidos.ver_pedido', pedido_id=pedido_id))

@pedidos_bp.route('/pedidos/<int:pedido_id>/imprimir')
@login_required
def imprimir_pedido(pedido_id):
    """Vista de impresión del pedido"""
    pedido = Pedido.query.get_or_404(pedido_id)
    return render_template('imprimir_pedido.html', pedido=pedido)

@pedidos_bp.route('/pedidos/<int:pedido_id>/descargar-pdf')
@login_required
def descargar_pdf_pedido(pedido_id):
    """Generar y descargar PDF del pedido"""
    try:
        pdf_data = generar_pdf_pedido(pedido_id)
        response = make_response(pdf_data)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=pedido_{pedido_id}.pdf'
        return response
    except ImportError:
        flash('La librería xhtml2pdf no está instalada. Por favor, ejecuta: pip install xhtml2pdf', 'error')
        return redirect(url_for('pedidos.ver_pedido', pedido_id=pedido_id))
    except Exception as e:
        flash(f'Error al generar PDF: {str(e)}', 'error')
        return redirect(url_for('pedidos.ver_pedido', pedido_id=pedido_id))

def generar_pdf_pedido(pedido_id):
    """Generar PDF del pedido y retornar los datos del PDF"""
    try:
        from decimal import Decimal
        from xhtml2pdf import pisa
        
        pedido = Pedido.query.get_or_404(pedido_id)
        
        # Renderizar template HTML
        html = render_template('imprimir_pedido.html', pedido=pedido)
        
        # Generar PDF
        result = BytesIO()
        
        pdf = pisa.pisaDocument(
            BytesIO(html.encode("UTF-8")), 
            result
        )
        
        if not pdf.err:
            return result.getvalue()
        else:
            raise Exception(f'Error al generar PDF: {pdf.err}')
            
    except Exception as e:
        import traceback
        print(f"Error en generar_pdf_pedido: {traceback.format_exc()}")
        raise

@pedidos_bp.route('/pedidos/<int:pedido_id>/enviar-email-cliente')
@login_required
def enviar_pedido_email_cliente(pedido_id):
    """Generar PDF y enviar por email directamente al cliente"""
    try:
        pedido = Pedido.query.get_or_404(pedido_id)
        
        # Verificar que el cliente tenga email
        if not pedido.cliente or not pedido.cliente.email:
            flash('El cliente no tiene email configurado', 'error')
            return redirect(url_for('pedidos.listado_pedidos'))
        
        # Generar PDF
        try:
            pdf_data = generar_pdf_pedido(pedido_id)
        except Exception as e:
            flash(f'Error al generar PDF: {str(e)}', 'error')
            return redirect(url_for('pedidos.listado_pedidos'))
        
        # Enviar email usando Flask-Mail
        from utils.email import enviar_email_pedido
        exito, mensaje = enviar_email_pedido(pedido, pdf_data)
        
        if exito:
            flash(f'Pedido enviado por email a {pedido.cliente.email}', 'success')
        else:
            flash(f'Error al enviar email: {mensaje}', 'error')
        
    except Exception as e:
        flash(f'Error al enviar pedido por email: {str(e)}', 'error')
    
    return redirect(url_for('pedidos.listado_pedidos'))

@pedidos_bp.route('/pedidos/<int:pedido_id>/eliminar', methods=['POST'])
@login_required
def eliminar_pedido(pedido_id):
    """Eliminar pedido"""
    pedido = Pedido.query.get_or_404(pedido_id)
    try:
        # Eliminar imagen si existe
        if pedido.imagen_diseno:
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], pedido.imagen_diseno)
            if os.path.exists(filepath):
                os.remove(filepath)
        
        db.session.delete(pedido)
        db.session.commit()
        flash('Pedido eliminado correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar pedido: {str(e)}', 'error')
    
    return redirect(url_for('index.index'))

