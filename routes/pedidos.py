"""Rutas para gestión de pedidos"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, make_response
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from io import BytesIO
import os
import tempfile
from extensions import db
from models import Comercial, Cliente, Prenda, Pedido, LineaPedido, Usuario, RegistroCambioEstado
from playwright.sync_api import sync_playwright

pedidos_bp = Blueprint('pedidos', __name__)

@pedidos_bp.route('/pedidos')
@login_required
def listado_pedidos():
    """Listado de pedidos con opciones de editar y eliminar"""
    query = Pedido.query
    
    # Verificar si se deben mostrar pedidos entregados al cliente
    mostrar_entregados = request.args.get('mostrar_entregados', '') == 'on'
    
    # Filtro por estado específico (si se selecciona uno del dropdown)
    estado_filtro = request.args.get('estado', '')
    if estado_filtro:
        query = query.filter(Pedido.estado == estado_filtro)
    else:
        # Si no hay filtro específico, excluir "Entregado al cliente" por defecto
        if not mostrar_entregados:
            query = query.filter(Pedido.estado != 'Entregado al cliente')
    
    # Filtro por fecha desde
    fecha_desde = request.args.get('fecha_desde', '')
    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            query = query.filter(Pedido.fecha_creacion >= datetime.combine(fecha_desde_obj, datetime.min.time()))
        except ValueError:
            pass
    
    # Filtro por fecha hasta
    fecha_hasta = request.args.get('fecha_hasta', '')
    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            query = query.filter(Pedido.fecha_creacion <= datetime.combine(fecha_hasta_obj, datetime.max.time()))
        except ValueError:
            pass
    
    # Obtener pedidos
    pedidos = query.order_by(Pedido.id.desc()).all()
    
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
    
    # Obtener estados únicos para el filtro
    estados = db.session.query(Pedido.estado).distinct().all()
    estados_list = [estado[0] for estado in estados if estado[0]]
    
    return render_template('listado_pedidos.html', 
                         pedidos=pedidos,
                         estados=estados_list,
                         estado_filtro=estado_filtro,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta,
                         mostrar_entregados=mostrar_entregados)

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
            
            # Establecer fecha_pendiente con fecha_creacion (ya que el estado inicial es Pendiente)
            if pedido.fecha_creacion:
                pedido.fecha_pendiente = pedido.fecha_creacion.date()
            
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
            # No actualizar el estado al editar, mantener el estado actual
            # pedido.estado se mantiene como está
            pedido.forma_pago = request.form.get('forma_pago', '')
            
            # Actualizar fecha_objetivo si se proporciona
            if request.form.get('fecha_objetivo'):
                pedido.fecha_objetivo = datetime.strptime(request.form.get('fecha_objetivo'), '%Y-%m-%d').date()
            
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
            'Pendiente': ('fecha_pendiente', 'Pendiente'),
            'Diseño': ('fecha_diseno', 'Diseño'),
            'En preparación': ('fecha_aceptacion', 'En preparación'),
            'Todo listo': ('fecha_todo_listo', 'Todo listo'),
            'Enviado': ('fecha_enviado', 'Enviado'),
            'Entregado al cliente': ('fecha_entrega_cliente', 'Entregado al cliente')
        }
        
        if nuevo_estado in estados_fechas:
            fecha_campo, estado_nombre = estados_fechas[nuevo_estado]
            
            # Actualizar el estado
            pedido.estado = estado_nombre
            
            # Guardar la fecha solo si no existe (no sobrescribir fechas anteriores)
            if fecha_campo:
                fecha_actual = getattr(pedido, fecha_campo)
                if not fecha_actual:  # Solo establecer si no tiene fecha
                    setattr(pedido, fecha_campo, hoy)
            
            # Para "Pendiente", usar fecha_creacion si no tiene fecha_pendiente
            if estado_nombre == 'Pendiente' and not pedido.fecha_pendiente and pedido.fecha_creacion:
                pedido.fecha_pendiente = pedido.fecha_creacion.date()
            
            # Para "En preparación", también calcular fecha_objetivo si no existe
            if estado_nombre == 'En preparación' and not pedido.fecha_objetivo:
                pedido.fecha_objetivo = hoy + timedelta(days=20)
            
            # Registrar el cambio de estado
            if estado_anterior != estado_nombre:
                registro = RegistroCambioEstado(
                    tipo_cambio='pedido',
                    pedido_id=pedido.id,
                    linea_id=None,
                    estado_anterior=estado_anterior,
                    estado_nuevo=estado_nombre,
                    usuario_id=current_user.id
                )
                db.session.add(registro)
            
            db.session.commit()
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
            estado_anterior_linea = linea.estado
            linea.estado = nuevo_estado
            
            # Registrar el cambio de estado de la línea
            if estado_anterior_linea != nuevo_estado:
                registro = RegistroCambioEstado(
                    tipo_cambio='linea_pedido',
                    pedido_id=pedido_id,
                    linea_id=linea.id,
                    estado_anterior=estado_anterior_linea,
                    estado_nuevo=nuevo_estado,
                    usuario_id=current_user.id
                )
                db.session.add(registro)
            
            db.session.commit()
            flash(f'Estado de la línea "{linea.nombre}" cambiado a "{nuevo_estado}"', 'success')
        else:
            flash('Estado no válido', 'error')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar el estado: {str(e)}', 'error')
    
    return redirect(url_for('pedidos.ver_pedido', pedido_id=pedido_id))

@pedidos_bp.route('/pedidos/<int:pedido_id>/registro')
@login_required
def registro_cambios(pedido_id):
    """Mostrar registro de cambios de estado de un pedido"""
    # Verificar permisos (solo administración y supervisor)
    if current_user.rol not in ['administracion', 'supervisor']:
        flash('No tienes permisos para acceder a esta página', 'error')
        return redirect(url_for('pedidos.ver_pedido', pedido_id=pedido_id))
    
    # Cargar el pedido con sus líneas para poder mostrar información de las líneas en el registro
    from sqlalchemy.orm import joinedload
    pedido = Pedido.query.options(joinedload(Pedido.lineas)).get_or_404(pedido_id)
    
    # Obtener todos los registros de cambios para este pedido, ordenados por fecha descendente
    # Cargar relación de usuario para evitar consultas adicionales
    registros = RegistroCambioEstado.query.filter_by(pedido_id=pedido_id)\
        .options(joinedload(RegistroCambioEstado.usuario))\
        .order_by(RegistroCambioEstado.fecha_cambio.desc())\
        .all()
    
    return render_template('pedidos/registro_cambios.html', pedido=pedido, registros=registros)

@pedidos_bp.route('/pedidos/<int:pedido_id>/imprimir')
@login_required
def imprimir_pedido(pedido_id):
    """Vista de impresión del pedido"""
    pedido = Pedido.query.get_or_404(pedido_id)
    return render_template('imprimir_pedido.html', pedido=pedido)

def preparar_datos_imprimir_pedido(pedido_id):
    """Función auxiliar para preparar todos los datos necesarios para imprimir el pedido"""
    from decimal import Decimal
    import base64
    
    pedido = Pedido.query.get_or_404(pedido_id)
    
    # Calcular totales
    tipo_iva = 21
    base_imponible = Decimal('0.00')
    
    for linea in pedido.lineas:
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
    if pedido.imagen_diseno:
        imagen_path = os.path.join(current_app.config['UPLOAD_FOLDER'], pedido.imagen_diseno)
        imagen_diseno_base64 = convertir_imagen_a_base64(imagen_path)
    
    # Convertir imagen de portada a base64 si existe
    if pedido.imagen_portada:
        imagen_path = os.path.join(current_app.config['UPLOAD_FOLDER'], pedido.imagen_portada)
        imagen_portada_base64 = convertir_imagen_a_base64(imagen_path)
    
    # Convertir imágenes adicionales a base64 y obtener descripciones (5 imágenes)
    for i in range(1, 6):
        campo_imagen = f'imagen_adicional_{i}'
        campo_descripcion = f'descripcion_imagen_{i}'
        
        if hasattr(pedido, campo_imagen) and getattr(pedido, campo_imagen):
            imagen_nombre = getattr(pedido, campo_imagen)
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
        descripcion = getattr(pedido, campo_descripcion, '') if hasattr(pedido, campo_descripcion) else ''
        descripciones_imagenes.append(descripcion)
    
    return {
        'pedido': pedido,
        'base_imponible': float(base_imponible),
        'iva_total': float(iva_total),
        'total_con_iva': float(total_con_iva),
        'tipo_iva': tipo_iva,
        'logo_base64': logo_base64,
        'imagen_diseno_base64': imagen_diseno_base64,
        'imagen_portada_base64': imagen_portada_base64,
        'imagenes_adicionales_base64': imagenes_adicionales_base64,
        'descripciones_imagenes': descripciones_imagenes
    }

@pedidos_bp.route('/pedidos/<int:pedido_id>/descargar-pdf')
@login_required
def descargar_pdf_pedido(pedido_id):
    """Descargar pedido en formato PDF"""
    try:
        datos = preparar_datos_imprimir_pedido(pedido_id)
        
        # Renderizar el HTML del pedido
        html = render_template('imprimir_pedido_pdf.html', 
                             **datos,
                             use_base64=True)
        
        # Crear el PDF en memoria usando playwright
        pdf_buffer = BytesIO()
        
        try:
            # Guardar HTML temporalmente para que playwright pueda acceder a él
            # Crear un archivo HTML temporal
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
            
            # Limpiar archivo temporal
            try:
                os.unlink(temp_html_path)
            except:
                pass
            
        except Exception as pdf_error:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Error al crear PDF con playwright: {error_trace}")
            flash(f'Error al generar PDF: {str(pdf_error)}', 'error')
            return redirect(url_for('pedidos.ver_pedido', pedido_id=pedido_id))
        
        # Preparar la respuesta con el PDF
        pdf_buffer.seek(0)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=pedido_{pedido_id}.pdf'
        
        return response
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error completo al generar PDF: {error_trace}")
        flash(f'Error al generar PDF: {str(e)}', 'error')
        return redirect(url_for('pedidos.ver_pedido', pedido_id=pedido_id))


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

