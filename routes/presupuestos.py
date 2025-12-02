"""Rutas para gestión de presupuestos"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, make_response
from flask_login import login_required
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import os
from io import BytesIO
from extensions import db
from models import Comercial, Cliente, Prenda, Pedido, LineaPedido, Presupuesto, LineaPresupuesto, Usuario

presupuestos_bp = Blueprint('presupuestos', __name__)

@presupuestos_bp.route('/presupuestos')
@login_required
def listado_presupuestos():
    """Listado de presupuestos"""
    presupuestos = Presupuesto.query.order_by(Presupuesto.id.desc()).all()
    return render_template('listado_presupuestos.html', presupuestos=presupuestos)

@presupuestos_bp.route('/presupuestos/nuevo', methods=['GET', 'POST'])
def nuevo_presupuesto():
    """Crear nuevo presupuesto"""
    if request.method == 'POST':
        try:
            # Crear presupuesto
            presupuesto = Presupuesto(
                comercial_id=request.form.get('comercial_id'),
                cliente_id=request.form.get('cliente_id'),
                tipo_pedido=request.form.get('tipo_pedido'),
                estado=request.form.get('estado', 'Pendiente de enviar'),
                forma_pago=request.form.get('forma_pago', ''),
                seguimiento=request.form.get('seguimiento', '')
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
                    presupuesto.imagen_diseno = filename
            
            db.session.add(presupuesto)
            db.session.flush()  # Para obtener el ID del presupuesto
            
            # Crear líneas de presupuesto
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
                    
                    linea = LineaPresupuesto(
                        presupuesto_id=presupuesto.id,
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
                        precio_unitario=precio_unitario
                    )
                    db.session.add(linea)
            
            db.session.commit()
            flash('Presupuesto creado correctamente', 'success')
            return redirect(url_for('presupuestos.listado_presupuestos'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear presupuesto: {str(e)}', 'error')
    
    comerciales = Comercial.query.join(Usuario).filter(
        Usuario.activo == True,
        Usuario.rol.in_(['comercial', 'administracion'])
    ).all()
    clientes = Cliente.query.all()
    prendas = Prenda.query.all()
    return render_template('nuevo_presupuesto.html', 
                         comerciales=comerciales, 
                         clientes=clientes, 
                         prendas=prendas)

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>')
@login_required
def ver_presupuesto(presupuesto_id):
    """Vista detallada del presupuesto"""
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    return render_template('ver_presupuesto.html', presupuesto=presupuesto)

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/imprimir')
@login_required
def imprimir_presupuesto(presupuesto_id):
    """Vista de impresión del presupuesto (HTML para imprimir desde navegador)"""
    from decimal import Decimal
    
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    
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
    
    return render_template('imprimir_presupuesto.html', 
                         presupuesto=presupuesto,
                         base_imponible=base_imponible,
                         iva_total=iva_total,
                         total_con_iva=total_con_iva,
                         tipo_iva=tipo_iva)

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/descargar-pdf')
@login_required
def descargar_pdf_presupuesto(presupuesto_id):
    """Generar y descargar PDF del presupuesto"""
    try:
        from decimal import Decimal
        from xhtml2pdf import pisa
        from flask import url_for
        
        presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
        
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
        
        # Obtener URL base para recursos estáticos
        base_url = request.url_root.rstrip('/')
        
        # Renderizar template HTML con URLs absolutas
        html = render_template('imprimir_presupuesto.html', 
                             presupuesto=presupuesto,
                             base_imponible=base_imponible,
                             iva_total=iva_total,
                             total_con_iva=total_con_iva,
                             tipo_iva=tipo_iva,
                             base_url=base_url)
        
        # Generar PDF
        result = BytesIO()
        
        # Función para manejar enlaces e imágenes
        def link_callback(uri, rel):
            # Convertir URIs relativas a absolutas
            if uri.startswith('/'):
                return base_url + uri
            return uri
        
        pdf = pisa.pisaDocument(
            BytesIO(html.encode("UTF-8")), 
            result,
            link_callback=link_callback
        )
        
        if not pdf.err:
            response = make_response(result.getvalue())
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = f'attachment; filename=presupuesto_{presupuesto_id}.pdf'
            return response
        else:
            flash(f'Error al generar PDF: {pdf.err}', 'error')
            return redirect(url_for('presupuestos.ver_presupuesto', presupuesto_id=presupuesto_id))
            
    except ImportError:
        flash('La librería xhtml2pdf no está instalada. Por favor, ejecuta: pip install xhtml2pdf', 'error')
        return redirect(url_for('presupuestos.ver_presupuesto', presupuesto_id=presupuesto_id))
    except Exception as e:
        flash(f'Error al generar PDF: {str(e)}', 'error')
        import traceback
        print(f"Error en descargar_pdf_presupuesto: {traceback.format_exc()}")
        return redirect(url_for('presupuestos.ver_presupuesto', presupuesto_id=presupuesto_id))

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_presupuesto(presupuesto_id):
    """Editar presupuesto existente"""
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    
    if request.method == 'POST':
        try:
            presupuesto.comercial_id = request.form.get('comercial_id')
            presupuesto.cliente_id = request.form.get('cliente_id')
            presupuesto.tipo_pedido = request.form.get('tipo_pedido')
            presupuesto.estado = request.form.get('estado')
            presupuesto.forma_pago = request.form.get('forma_pago', '')
            presupuesto.seguimiento = request.form.get('seguimiento', '')
            
            # Fechas
            if request.form.get('fecha_envio'):
                presupuesto.fecha_envio = datetime.strptime(request.form.get('fecha_envio'), '%Y-%m-%d').date()
            if request.form.get('fecha_respuesta'):
                presupuesto.fecha_respuesta = datetime.strptime(request.form.get('fecha_respuesta'), '%Y-%m-%d').date()
            
            # Manejar nueva imagen de diseño
            if 'imagen_diseno' in request.files:
                file = request.files['imagen_diseno']
                if file and file.filename:
                    # Eliminar imagen anterior si existe
                    if presupuesto.imagen_diseno:
                        old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], presupuesto.imagen_diseno)
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                    filename = timestamp + filename
                    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    presupuesto.imagen_diseno = filename
            
            # Eliminar líneas existentes (dentro de la misma transacción)
            try:
                LineaPresupuesto.query.filter_by(presupuesto_id=presupuesto.id).delete()
            except Exception as e:
                db.session.rollback()
                flash(f'Error al eliminar líneas anteriores: {str(e)}', 'error')
                return redirect(url_for('presupuestos.editar_presupuesto', presupuesto_id=presupuesto.id))
            
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
                    
                    linea = LineaPresupuesto(
                        presupuesto_id=presupuesto.id,
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
                        precio_unitario=precio_unitario
                    )
                    db.session.add(linea)
            
            db.session.commit()
            flash('Presupuesto actualizado correctamente', 'success')
            return redirect(url_for('presupuestos.listado_presupuestos'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar presupuesto: {str(e)}', 'error')
    
    comerciales = Comercial.query.join(Usuario).filter(
        Usuario.activo == True,
        Usuario.rol.in_(['comercial', 'administracion'])
    ).all()
    clientes = Cliente.query.all()
    prendas = Prenda.query.all()
    return render_template('editar_presupuesto.html', 
                         presupuesto=presupuesto,
                         comerciales=comerciales, 
                         clientes=clientes, 
                         prendas=prendas)

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/cambiar-estado', methods=['POST'])
@login_required
def cambiar_estado_presupuesto(presupuesto_id):
    """Cambiar el estado del presupuesto y actualizar la fecha correspondiente"""
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    nuevo_estado = request.form.get('estado')
    hoy = datetime.now().date()
    
    print(f"DEBUG: cambiar_estado_presupuesto llamado - presupuesto_id: {presupuesto_id}, nuevo_estado: {nuevo_estado}")
    
    try:
        # Guardar el estado anterior antes de actualizarlo
        estado_anterior = presupuesto.estado
        print(f"DEBUG: estado_anterior: {estado_anterior}")
        
        # Mapeo de estados a fechas
        estados_fechas = {
            'Pendiente de enviar': (None, 'Pendiente de enviar'),
            'Enviado': ('fecha_envio', 'Enviado'),
            'Aceptado': ('fecha_respuesta', 'Aceptado'),
            'Rechazado': ('fecha_respuesta', 'Rechazado')
        }
        
        if nuevo_estado in estados_fechas:
            fecha_campo, estado_nombre = estados_fechas[nuevo_estado]
            
            # Actualizar el estado
            presupuesto.estado = estado_nombre
            
            # Si tiene fecha asociada, actualizar la fecha a hoy
            if fecha_campo:
                setattr(presupuesto, fecha_campo, hoy)
            
            # Si el presupuesto se acepta, crear un pedido automáticamente
            if nuevo_estado == 'Aceptado' and estado_anterior != 'Aceptado':
                print(f"DEBUG: Condición cumplida - nuevo_estado es 'Aceptado' y estado_anterior no es 'Aceptado'")
                # Solo crear pedido si el presupuesto no estaba ya aceptado
                # Asegurarse de que las líneas estén cargadas
                lineas_presupuesto = LineaPresupuesto.query.filter_by(presupuesto_id=presupuesto.id).all()
                print(f"DEBUG: Líneas encontradas: {len(lineas_presupuesto)}")
                
                if not lineas_presupuesto:
                    db.session.commit()
                    flash('Presupuesto aceptado, pero no se pudo crear el pedido porque no tiene prendas asociadas', 'error')
                    return redirect(url_for('presupuestos.ver_presupuesto', presupuesto_id=presupuesto_id))
                
                try:
                    print(f"DEBUG: Creando pedido para presupuesto {presupuesto.id}")
                    # Crear nuevo pedido basado en el presupuesto
                    pedido = Pedido(
                        comercial_id=presupuesto.comercial_id,
                        cliente_id=presupuesto.cliente_id,
                        tipo_pedido=presupuesto.tipo_pedido,
                        estado='Pendiente',
                        forma_pago=presupuesto.forma_pago or '',
                        imagen_diseno=presupuesto.imagen_diseno,
                        fecha_aceptacion=hoy,
                        fecha_objetivo=hoy + timedelta(days=20)  # 20 días desde aceptación
                    )
                    db.session.add(pedido)
                    db.session.flush()  # Para obtener el ID del pedido
                    print(f"DEBUG: Pedido creado con ID: {pedido.id}")
                    
                    # Copiar las líneas del presupuesto al pedido
                    for linea_presupuesto in lineas_presupuesto:
                        linea_pedido = LineaPedido(
                            pedido_id=pedido.id,
                            prenda_id=linea_presupuesto.prenda_id,
                            nombre=linea_presupuesto.nombre or '',  # Mantenido para compatibilidad
                            cargo=linea_presupuesto.cargo or '',  # Mantenido para compatibilidad
                            nombre_mostrar=linea_presupuesto.nombre_mostrar or '',  # Copiar nombre para mostrar
                            cantidad=linea_presupuesto.cantidad,
                            color=linea_presupuesto.color or '',
                            forma=linea_presupuesto.forma or '',
                            tipo_manda=linea_presupuesto.tipo_manda or '',
                            sexo=linea_presupuesto.sexo or '',
                            talla=linea_presupuesto.talla or '',
                            tejido=linea_presupuesto.tejido or '',
                            precio_unitario=linea_presupuesto.precio_unitario,  # Copiar precio del presupuesto
                            estado='pendiente'
                        )
                        db.session.add(linea_pedido)
                    
                    print(f"DEBUG: Líneas agregadas, haciendo commit...")
                    db.session.commit()
                    print(f"DEBUG: Commit exitoso. Pedido #{pedido.id} creado")
                    flash(f'Presupuesto aceptado. Se ha creado el pedido #{pedido.id} en estado Pendiente', 'success')
                except Exception as e_inner:
                    db.session.rollback()
                    import traceback
                    print(f"ERROR al crear pedido: {traceback.format_exc()}")
                    flash(f'Error al crear el pedido: {str(e_inner)}', 'error')
            else:
                print(f"DEBUG: No se cumple la condición para crear pedido - nuevo_estado: {nuevo_estado}, estado_anterior: {estado_anterior}")
                db.session.commit()
                if nuevo_estado == 'Aceptado' and estado_anterior == 'Aceptado':
                    flash(f'El presupuesto ya estaba aceptado. Estado actualizado.', 'success')
                else:
                    flash(f'Estado del presupuesto cambiado a "{estado_nombre}"', 'success')
        else:
            flash(f'Estado no válido: {nuevo_estado}', 'error')
            
    except Exception as e:
        db.session.rollback()
        import traceback
        error_msg = f'Error al cambiar el estado: {str(e)}'
        print(f"Error completo: {traceback.format_exc()}")
        flash(error_msg, 'error')
    
    return redirect(url_for('presupuestos.ver_presupuesto', presupuesto_id=presupuesto_id))

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/actualizar-seguimiento', methods=['POST'])
@login_required
def actualizar_seguimiento(presupuesto_id):
    """Actualizar el campo de seguimiento del presupuesto"""
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    nuevo_seguimiento = request.form.get('seguimiento', '')
    
    try:
        presupuesto.seguimiento = nuevo_seguimiento
        db.session.commit()
        flash('Seguimiento actualizado correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar seguimiento: {str(e)}', 'error')
    
    return redirect(url_for('presupuestos.ver_presupuesto', presupuesto_id=presupuesto_id))

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/eliminar', methods=['POST'])
@login_required
def eliminar_presupuesto(presupuesto_id):
    """Eliminar presupuesto"""
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    try:
        # Eliminar imagen si existe
        if presupuesto.imagen_diseno:
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], presupuesto.imagen_diseno)
            if os.path.exists(filepath):
                os.remove(filepath)
        
        db.session.delete(presupuesto)
        db.session.commit()
        flash('Presupuesto eliminado correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar presupuesto: {str(e)}', 'error')
    
    return redirect(url_for('presupuestos.listado_presupuestos'))

