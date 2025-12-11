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
                estado='Pendiente de enviar',  # Siempre se establece como Pendiente de enviar al crear
                forma_pago=request.form.get('forma_pago', ''),
                seguimiento=request.form.get('seguimiento', '')
            )
            
            # Función auxiliar para guardar imagen
            def guardar_imagen(campo_file, campo_db):
                """Guardar imagen del formulario"""
                if campo_file in request.files:
                    file = request.files[campo_file]
                    if file and file.filename:
                        filename = secure_filename(file.filename)
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                        filename = timestamp + filename
                        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                        file.save(filepath)
                        setattr(presupuesto, campo_db, filename)
            
            # Manejar imágenes
            guardar_imagen('imagen_diseno', 'imagen_diseno')
            guardar_imagen('imagen_adicional_1', 'imagen_adicional_1')
            guardar_imagen('imagen_adicional_2', 'imagen_adicional_2')
            guardar_imagen('imagen_adicional_3', 'imagen_adicional_3')
            guardar_imagen('imagen_adicional_4', 'imagen_adicional_4')
            
            # Guardar descripciones de imágenes
            presupuesto.descripcion_imagen_1 = request.form.get('descripcion_imagen_1', '')
            presupuesto.descripcion_imagen_2 = request.form.get('descripcion_imagen_2', '')
            presupuesto.descripcion_imagen_3 = request.form.get('descripcion_imagen_3', '')
            presupuesto.descripcion_imagen_4 = request.form.get('descripcion_imagen_4', '')
            
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

def preparar_datos_imprimir_presupuesto(presupuesto_id):
    """Función auxiliar para preparar todos los datos necesarios para imprimir/generar PDF del presupuesto"""
    from decimal import Decimal
    import base64
    
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
    
    # Convertir imágenes a base64
    logo_base64 = None
    imagen_diseno_base64 = None
    imagen_portada_base64 = None
    imagenes_adicionales_base64 = []
    descripciones_imagenes = []
    
    # Convertir logo a base64
    logo_path = os.path.join(current_app.static_folder, 'logo.png')
    logo_base64 = convertir_imagen_a_base64(logo_path)
    
    # Convertir imagen de diseño a base64 si existe
    if presupuesto.imagen_diseno:
        imagen_path = os.path.join(current_app.config['UPLOAD_FOLDER'], presupuesto.imagen_diseno)
        imagen_diseno_base64 = convertir_imagen_a_base64(imagen_path)
    
    # Convertir imagen de portada a base64 si existe
    if presupuesto.imagen_portada:
        imagen_path = os.path.join(current_app.config['UPLOAD_FOLDER'], presupuesto.imagen_portada)
        imagen_portada_base64 = convertir_imagen_a_base64(imagen_path)
    
    # Convertir imágenes adicionales a base64 y obtener descripciones (solo 4 imágenes)
    for i in range(1, 5):
        campo_imagen = f'imagen_adicional_{i}'
        campo_descripcion = f'descripcion_imagen_{i}'
        
        if hasattr(presupuesto, campo_imagen) and getattr(presupuesto, campo_imagen):
            imagen_nombre = getattr(presupuesto, campo_imagen)
            imagen_path = os.path.join(current_app.config['UPLOAD_FOLDER'], imagen_nombre)
            if os.path.exists(imagen_path):
                imagen_base64 = convertir_imagen_a_base64(imagen_path)
                imagenes_adicionales_base64.append(imagen_base64)
            else:
                print(f"ADVERTENCIA: No se encontró la imagen {imagen_path}")
                imagenes_adicionales_base64.append(None)
        else:
            imagenes_adicionales_base64.append(None)
        
        # Obtener descripción
        descripcion = getattr(presupuesto, campo_descripcion, '') if hasattr(presupuesto, campo_descripcion) else ''
        descripciones_imagenes.append(descripcion)
    
    return {
        'presupuesto': presupuesto,
        'base_imponible': base_imponible,
        'iva_total': iva_total,
        'total_con_iva': total_con_iva,
        'tipo_iva': tipo_iva,
        'logo_base64': logo_base64,
        'imagen_diseno_base64': imagen_diseno_base64,
        'imagen_portada_base64': imagen_portada_base64,
        'imagenes_adicionales_base64': imagenes_adicionales_base64,
        'descripciones_imagenes': descripciones_imagenes
    }

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/imprimir')
@login_required
def imprimir_presupuesto(presupuesto_id):
    """Vista de impresión del presupuesto (HTML para imprimir desde navegador)"""
    datos = preparar_datos_imprimir_presupuesto(presupuesto_id)
    
    return render_template('imprimir_presupuesto.html', 
                         **datos,
                         use_base64=True)

def generar_pdf_presupuesto(presupuesto_id):
    """Generar PDF del presupuesto y retornar los datos del PDF"""
    try:
        from xhtml2pdf import pisa
        
        # Usar la misma función auxiliar para preparar los datos
        datos = preparar_datos_imprimir_presupuesto(presupuesto_id)
        
        # Renderizar template HTML con los mismos datos que la vista de impresión
        html = render_template('imprimir_presupuesto.html', 
                             **datos,
                             use_base64=True)
        
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
        print(f"Error en generar_pdf_presupuesto: {traceback.format_exc()}")
        raise

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/descargar-pdf')
@login_required
def descargar_pdf_presupuesto(presupuesto_id):
    """Generar y descargar PDF del presupuesto"""
    try:
        pdf_data = generar_pdf_presupuesto(presupuesto_id)
        response = make_response(pdf_data)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=presupuesto_{presupuesto_id}.pdf'
        return response
    except ImportError:
        flash('La librería xhtml2pdf no está instalada. Por favor, ejecuta: pip install xhtml2pdf', 'error')
        return redirect(url_for('presupuestos.ver_presupuesto', presupuesto_id=presupuesto_id))
    except Exception as e:
        flash(f'Error al generar PDF: {str(e)}', 'error')
        return redirect(url_for('presupuestos.ver_presupuesto', presupuesto_id=presupuesto_id))

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/enviar-email', methods=['POST'])
@login_required
def enviar_presupuesto_email(presupuesto_id):
    """Enviar presupuesto por email al cliente"""
    try:
        presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
        
        # Verificar que el cliente tenga email
        if not presupuesto.cliente or not presupuesto.cliente.email:
            flash('El cliente no tiene email configurado', 'error')
            return redirect(url_for('presupuestos.ver_presupuesto', presupuesto_id=presupuesto_id))
        
        # Generar PDF
        try:
            pdf_data = generar_pdf_presupuesto(presupuesto_id)
        except Exception as e:
            flash(f'Error al generar PDF: {str(e)}', 'error')
            return redirect(url_for('presupuestos.ver_presupuesto', presupuesto_id=presupuesto_id))
        
        # Enviar email
        from utils.email import enviar_email_presupuesto
        exito, mensaje = enviar_email_presupuesto(presupuesto, pdf_data)
        
        if exito:
            flash(f'Presupuesto enviado por email a {presupuesto.cliente.email}', 'success')
        else:
            flash(f'Error al enviar email: {mensaje}', 'error')
        
    except Exception as e:
        flash(f'Error al enviar presupuesto por email: {str(e)}', 'error')
    
    return redirect(url_for('presupuestos.ver_presupuesto', presupuesto_id=presupuesto_id))

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/enviar-whatsapp')
@login_required
def enviar_presupuesto_whatsapp(presupuesto_id):
    """Generar PDF y preparar para enviar por WhatsApp"""
    try:
        presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
        
        # Verificar que el cliente tenga teléfono
        if not presupuesto.cliente or not presupuesto.cliente.telefono:
            flash('El cliente no tiene teléfono configurado', 'error')
            return redirect(url_for('presupuestos.listado_presupuestos'))
        
        # Generar PDF
        try:
            pdf_data = generar_pdf_presupuesto(presupuesto_id)
        except Exception as e:
            flash(f'Error al generar PDF: {str(e)}', 'error')
            return redirect(url_for('presupuestos.listado_presupuestos'))
        
        # Guardar PDF temporalmente
        import tempfile
        import base64
        temp_dir = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
        os.makedirs(temp_dir, exist_ok=True)
        
        pdf_filename = f'presupuesto_{presupuesto_id}.pdf'
        pdf_path = os.path.join(temp_dir, pdf_filename)
        
        with open(pdf_path, 'wb') as f:
            f.write(pdf_data)
        
        # Preparar mensaje para WhatsApp
        from urllib.parse import urlencode
        telefono = presupuesto.cliente.telefono.replace(' ', '').replace('-', '').replace('+', '')
        mensaje = f"Hola {presupuesto.cliente.nombre}, te envío el presupuesto #{presupuesto_id}."
        mensaje_encoded = urlencode({'text': mensaje})
        
        # Retornar template con JavaScript para abrir WhatsApp
        return render_template('enviar_whatsapp.html', 
                             pdf_path=pdf_path,
                             pdf_filename=pdf_filename,
                             telefono=telefono,
                             mensaje_encoded=mensaje_encoded,
                             tipo='presupuesto',
                             id_documento=presupuesto_id)
        
    except Exception as e:
        flash(f'Error al preparar envío por WhatsApp: {str(e)}', 'error')
        return redirect(url_for('presupuestos.listado_presupuestos'))

@presupuestos_bp.route('/presupuestos/<int:presupuesto_id>/enviar-email-cliente')
@login_required
def enviar_presupuesto_email_cliente(presupuesto_id):
    """Generar PDF y enviar por email directamente al cliente"""
    try:
        presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
        
        # Verificar que el cliente tenga email
        if not presupuesto.cliente or not presupuesto.cliente.email:
            flash('El cliente no tiene email configurado', 'error')
            return redirect(url_for('presupuestos.listado_presupuestos'))
        
        # Generar PDF
        try:
            pdf_data = generar_pdf_presupuesto(presupuesto_id)
        except Exception as e:
            flash(f'Error al generar PDF: {str(e)}', 'error')
            return redirect(url_for('presupuestos.listado_presupuestos'))
        
        # Enviar email usando Flask-Mail
        from utils.email import enviar_email_presupuesto
        exito, mensaje = enviar_email_presupuesto(presupuesto, pdf_data)
        
        if exito:
            flash(f'Presupuesto enviado por email a {presupuesto.cliente.email}', 'success')
        else:
            flash(f'Error al enviar email: {mensaje}', 'error')
        
    except Exception as e:
        flash(f'Error al enviar presupuesto por email: {str(e)}', 'error')
    
    return redirect(url_for('presupuestos.listado_presupuestos'))

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
            
            # Función auxiliar para actualizar imagen
            def actualizar_imagen(campo_file, campo_db):
                """Actualizar imagen del formulario, eliminando la anterior si existe"""
                if campo_file in request.files:
                    file = request.files[campo_file]
                    if file and file.filename:
                        # Eliminar imagen anterior si existe
                        imagen_anterior = getattr(presupuesto, campo_db, None)
                        if imagen_anterior:
                            old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], imagen_anterior)
                            if os.path.exists(old_path):
                                try:
                                    os.remove(old_path)
                                except Exception as e:
                                    print(f"Error al eliminar imagen anterior {imagen_anterior}: {e}")
                        
                        filename = secure_filename(file.filename)
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                        filename = timestamp + filename
                        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                        file.save(filepath)
                        setattr(presupuesto, campo_db, filename)
            
            # Manejar actualización de imágenes
            actualizar_imagen('imagen_diseno', 'imagen_diseno')
            actualizar_imagen('imagen_portada', 'imagen_portada')
            actualizar_imagen('imagen_adicional_1', 'imagen_adicional_1')
            actualizar_imagen('imagen_adicional_2', 'imagen_adicional_2')
            actualizar_imagen('imagen_adicional_3', 'imagen_adicional_3')
            actualizar_imagen('imagen_adicional_4', 'imagen_adicional_4')
            
            # Actualizar descripciones de imágenes
            presupuesto.descripcion_imagen_1 = request.form.get('descripcion_imagen_1', '')
            presupuesto.descripcion_imagen_2 = request.form.get('descripcion_imagen_2', '')
            presupuesto.descripcion_imagen_3 = request.form.get('descripcion_imagen_3', '')
            presupuesto.descripcion_imagen_4 = request.form.get('descripcion_imagen_4', '')
            
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
            'Diseño': (None, 'Diseño'),
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

