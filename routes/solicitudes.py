"""Rutas para gestión de solicitudes (presupuestos y pedidos unificados)"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, make_response, jsonify
from flask_login import login_required
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import os
import tempfile
from io import BytesIO
from extensions import db
from models import Comercial, Cliente, Prenda, Presupuesto, LineaPresupuesto, Usuario
from sqlalchemy.orm import joinedload
from flask import jsonify
from playwright.sync_api import sync_playwright
from decimal import Decimal

solicitudes_bp = Blueprint('solicitudes', __name__)

# Estados unificados
ESTADOS_SOLICITUD = [
    'presupuesto',
    'aceptado',
    'diseño',
    'diseño finalizado',
    'en preparacion',
    'todo listo',
    'enviado',
    'entregado al cliente',
    'pedido rechazado'
]

# Mapeo de estados a campos de fecha
ESTADOS_FECHAS = {
    'presupuesto': 'fecha_presupuesto',
    'aceptado': 'fecha_aceptado',
    'diseño': 'fecha_diseno',
    'diseño finalizado': 'fecha_diseno_finalizado',
    'en preparacion': 'fecha_en_preparacion',
    'todo listo': 'fecha_todo_listo',
    'enviado': 'fecha_enviado',
    'entregado al cliente': 'fecha_entregado_cliente',
    'pedido rechazado': 'fecha_rechazado'
}

@solicitudes_bp.route('/solicitudes')
@login_required
def listado_solicitudes():
    """Listado de solicitudes con filtros"""
    query = Presupuesto.query
    
    # Filtro por estado específico
    estado_filtro = request.args.get('estado', '')
    if estado_filtro:
        query = query.filter(Presupuesto.estado == estado_filtro)
    
    # Filtro por fecha desde
    fecha_desde = request.args.get('fecha_desde', '')
    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            query = query.filter(Presupuesto.fecha_creacion >= datetime.combine(fecha_desde_obj, datetime.min.time()))
        except ValueError:
            pass
    
    # Filtro por fecha hasta
    fecha_hasta = request.args.get('fecha_hasta', '')
    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            query = query.filter(Presupuesto.fecha_creacion <= datetime.combine(fecha_hasta_obj, datetime.max.time()))
        except ValueError:
            pass
    
    # Filtro por cliente
    cliente_id = request.args.get('cliente_id', '')
    if cliente_id:
        try:
            query = query.filter(Presupuesto.cliente_id == int(cliente_id))
        except ValueError:
            pass
    
    # Filtro por comercial
    comercial_id = request.args.get('comercial_id', '')
    if comercial_id:
        try:
            query = query.filter(Presupuesto.comercial_id == int(comercial_id))
        except ValueError:
            pass
    
    solicitudes = query.order_by(Presupuesto.fecha_creacion.desc()).all()
    
    # Obtener datos para filtros
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    # Comercial.nombre es una propiedad, necesitamos ordenar por Usuario.usuario
    comerciales = Comercial.query.join(Usuario).order_by(Usuario.usuario).all()
    
    return render_template('solicitudes/listado.html',
                         solicitudes=solicitudes,
                         estados=ESTADOS_SOLICITUD,
                         clientes=clientes,
                         comerciales=comerciales,
                         estado_filtro=estado_filtro,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta,
                         cliente_id=cliente_id,
                         comercial_id=comercial_id)

@solicitudes_bp.route('/solicitudes/nueva', methods=['GET', 'POST'])
@login_required
def nueva_solicitud():
    """Crear nueva solicitud (igual que presupuesto)"""
    if request.method == 'POST':
        try:
            # Obtener datos del formulario
            comercial_id = request.form.get('comercial_id')
            cliente_id = request.form.get('cliente_id')
            tipo_pedido = request.form.get('tipo_pedido')
            forma_pago = request.form.get('forma_pago', '')
            seguimiento = request.form.get('seguimiento', '')
            fecha_objetivo_str = request.form.get('fecha_objetivo', '')
            
            # Validaciones
            if not comercial_id or not cliente_id or not tipo_pedido:
                flash('Debe completar todos los campos obligatorios', 'error')
                return redirect(url_for('solicitudes.nueva_solicitud'))
            
            # Crear solicitud (presupuesto)
            solicitud = Presupuesto(
                comercial_id=comercial_id,
                cliente_id=cliente_id,
                tipo_pedido=tipo_pedido,
                forma_pago=forma_pago,
                seguimiento=seguimiento,
                estado='presupuesto'  # Estado inicial
            )
            
            # Establecer fecha_presupuesto si no existe
            if not solicitud.fecha_presupuesto:
                solicitud.fecha_presupuesto = datetime.now().date()
            
            # Procesar fecha objetivo si se proporciona
            if fecha_objetivo_str:
                try:
                    solicitud.fecha_objetivo = datetime.strptime(fecha_objetivo_str, '%Y-%m-%d').date()
                except ValueError:
                    pass  # Si hay error en el formato, se ignora
            
            db.session.add(solicitud)
            db.session.flush()  # Para obtener el ID
            
            # Procesar líneas de solicitud (igual que en editar)
            prenda_ids = request.form.getlist('prenda_id[]')
            nombres = request.form.getlist('nombre[]')
            nombres_mostrar = request.form.getlist('nombre_mostrar[]')
            cargos = request.form.getlist('cargo[]')
            cantidades = request.form.getlist('cantidad[]')
            colores = request.form.getlist('color[]')
            formas = request.form.getlist('forma[]')
            tipos_manda = request.form.getlist('tipo_manda[]')
            sexos = request.form.getlist('sexo[]')
            tallas = request.form.getlist('talla[]')
            tejidos = request.form.getlist('tejido[]')
            precios_unitarios = request.form.getlist('precio_unitario[]')
            descuentos = request.form.getlist('descuento[]')
            precios_finales = request.form.getlist('precio_final[]')
            estados_linea = request.form.getlist('estado_linea[]')
            
            print(f"DEBUG: Procesando líneas - prenda_ids: {len(prenda_ids)}, nombres_mostrar: {len(nombres_mostrar)}")
            
            for i in range(len(prenda_ids)):
                # Verificar si hay datos para crear la línea
                nombre_mostrar_val = nombres_mostrar[i] if i < len(nombres_mostrar) and nombres_mostrar[i] else ''
                nombre_val = nombres[i] if i < len(nombres) and nombres[i] else ''
                
                print(f"DEBUG: Línea {i} - prenda_id: {prenda_ids[i]}, nombre_mostrar: '{nombre_mostrar_val}', nombre: '{nombre_val}'")
                
                # Crear línea si tiene prenda_id y algún nombre
                if prenda_ids[i] and (nombre_mostrar_val or nombre_val):
                    precio_unitario = None
                    if i < len(precios_unitarios) and precios_unitarios[i]:
                        try:
                            precio_unitario = Decimal(str(precios_unitarios[i]))
                        except:
                            precio_unitario = None
                    
                    # Usar nombre_mostrar si existe, sino usar nombre (compatibilidad)
                    nombre_mostrar_val = nombres_mostrar[i] if i < len(nombres_mostrar) and nombres_mostrar[i] else (nombres[i] if i < len(nombres) else '')
                    
                    # Calcular descuento y precio_final
                    descuento = Decimal('0')
                    if i < len(descuentos) and descuentos[i]:
                        try:
                            descuento = Decimal(str(descuentos[i]))
                        except:
                            descuento = Decimal('0')
                    
                    precio_final = None
                    if i < len(precios_finales) and precios_finales[i]:
                        try:
                            precio_final = Decimal(str(precios_finales[i]))
                        except:
                            precio_final = None
                    
                    if precio_final is None and precio_unitario:
                        if descuento > 0:
                            precio_final = precio_unitario * (Decimal('1') - descuento / Decimal('100'))
                        else:
                            precio_final = precio_unitario
                    
                    estado_linea = estados_linea[i] if i < len(estados_linea) and estados_linea[i] else 'pendiente'
                    
                    # Convertir Decimal a float para SQLite
                    cantidad_val = float(Decimal(str(cantidades[i])) if i < len(cantidades) and cantidades[i] else Decimal('1'))
                    precio_unitario_val = float(precio_unitario) if precio_unitario else None
                    descuento_val = float(descuento) if descuento else 0.0
                    precio_final_val = float(precio_final) if precio_final else None
                    
                    linea = LineaPresupuesto(
                        presupuesto_id=solicitud.id,
                        prenda_id=prenda_ids[i],
                        nombre=nombres[i] if i < len(nombres) else '',  # Mantenido para compatibilidad
                        nombre_mostrar=nombre_mostrar_val,
                        cargo=cargos[i] if i < len(cargos) else '',
                        cantidad=cantidad_val,
                        color=colores[i] if i < len(colores) else '',
                        forma=formas[i] if i < len(formas) else '',
                        tipo_manda=tipos_manda[i] if i < len(tipos_manda) else '',
                        sexo=sexos[i] if i < len(sexos) else '',
                        talla=tallas[i] if i < len(tallas) else '',
                        tejido=tejidos[i] if i < len(tejidos) else '',
                        precio_unitario=precio_unitario_val,
                        descuento=descuento_val,
                        precio_final=precio_final_val,
                        estado=estado_linea
                    )
                    db.session.add(linea)
                    print(f"DEBUG: Línea {i} añadida - nombre_mostrar: '{nombre_mostrar_val}', prenda_id: {prenda_ids[i]}")
            
            print(f"DEBUG: Total líneas procesadas: {len([l for l in db.session.new if isinstance(l, LineaPresupuesto)])}")
            
            # Procesar imagen de diseño
            if 'imagen_diseno' in request.files:
                file = request.files['imagen_diseno']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'solicitudes')
                    os.makedirs(upload_folder, exist_ok=True)
                    filepath = os.path.join(upload_folder, f"{solicitud.id}_diseno_{filename}")
                    file.save(filepath)
                    # Guardar solo la ruta relativa desde static/uploads/
                    solicitud.imagen_diseno = os.path.join('solicitudes', f"{solicitud.id}_diseno_{filename}").replace('\\', '/')
            
            # Procesar imagen de portada
            if 'imagen_portada' in request.files:
                file = request.files['imagen_portada']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'solicitudes')
                    os.makedirs(upload_folder, exist_ok=True)
                    filepath = os.path.join(upload_folder, f"{solicitud.id}_portada_{filename}")
                    file.save(filepath)
                    # Guardar solo la ruta relativa desde static/uploads/
                    solicitud.imagen_portada = os.path.join('solicitudes', f"{solicitud.id}_portada_{filename}").replace('\\', '/')
            
            # Procesar imágenes adicionales
            for i in range(1, 6):
                imagen_key = f'imagen_adicional_{i}'
                descripcion_key = f'descripcion_imagen_{i}'
                
                if imagen_key in request.files:
                    file = request.files[imagen_key]
                    if file and file.filename:
                        filename = secure_filename(file.filename)
                        upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'solicitudes')
                        os.makedirs(upload_folder, exist_ok=True)
                        filepath = os.path.join(upload_folder, f"{solicitud.id}_adicional_{i}_{filename}")
                        file.save(filepath)
                        # Guardar solo la ruta relativa desde static/uploads/
                        ruta_relativa = os.path.join('solicitudes', f"{solicitud.id}_adicional_{i}_{filename}").replace('\\', '/')
                        setattr(solicitud, imagen_key, ruta_relativa)
                        setattr(solicitud, descripcion_key, request.form.get(descripcion_key, ''))
            
            db.session.commit()
            
            # Refrescar la solicitud para cargar las líneas
            db.session.refresh(solicitud)
            
            flash('Solicitud creada correctamente', 'success')
            return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear la solicitud: {str(e)}', 'error')
            import traceback
            traceback.print_exc()
    
    # GET: mostrar formulario
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    comerciales = Comercial.query.join(Usuario).order_by(Usuario.usuario).all()
    prendas = Prenda.query.order_by(Prenda.nombre).all()
    
    return render_template('solicitudes/nueva.html',
                         clientes=clientes,
                         comerciales=comerciales,
                         prendas=prendas)

@solicitudes_bp.route('/solicitudes/<int:solicitud_id>')
@login_required
def ver_solicitud(solicitud_id):
    """Ver detalles de una solicitud"""
    from sqlalchemy.orm import joinedload
    solicitud = Presupuesto.query.options(
        joinedload(Presupuesto.lineas).joinedload(LineaPresupuesto.prenda),
        joinedload(Presupuesto.cliente),
        joinedload(Presupuesto.comercial)
    ).get_or_404(solicitud_id)
    
    # Debug: verificar si hay líneas
    print(f"DEBUG ver_solicitud: Solicitud {solicitud_id} tiene {len(solicitud.lineas) if solicitud.lineas else 0} líneas")
    if solicitud.lineas:
        for linea in solicitud.lineas:
            print(f"DEBUG ver_solicitud: Línea {linea.id} - nombre_mostrar: '{linea.nombre_mostrar}', nombre: '{linea.nombre}', prenda_id: {linea.prenda_id}")
    else:
        # Verificar directamente en la base de datos
        lineas_directas = LineaPresupuesto.query.filter_by(presupuesto_id=solicitud_id).all()
        print(f"DEBUG ver_solicitud: Consulta directa encontró {len(lineas_directas)} líneas")
        for linea in lineas_directas:
            print(f"DEBUG ver_solicitud: Línea directa {linea.id} - nombre_mostrar: '{linea.nombre_mostrar}', nombre: '{linea.nombre}'")
        # Si hay líneas directas pero no en la relación, recargar
        if lineas_directas:
            db.session.refresh(solicitud)
            solicitud = Presupuesto.query.options(
                joinedload(Presupuesto.lineas).joinedload(LineaPresupuesto.prenda),
                joinedload(Presupuesto.cliente),
                joinedload(Presupuesto.comercial)
            ).get(solicitud_id)
    
    return render_template('solicitudes/ver.html',
                         solicitud=solicitud,
                         estados=ESTADOS_SOLICITUD,
                         estados_fechas=ESTADOS_FECHAS)

@solicitudes_bp.route('/solicitudes/<int:solicitud_id>/cambiar-estado', methods=['POST'])
@login_required
def cambiar_estado_solicitud(solicitud_id):
    """Cambiar el estado de una solicitud"""
    solicitud = Presupuesto.query.get_or_404(solicitud_id)
    nuevo_estado = request.form.get('estado')
    hoy = datetime.now().date()
    
    if nuevo_estado not in ESTADOS_SOLICITUD:
        flash('Estado no válido', 'error')
        return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))
    
    try:
        estado_anterior = solicitud.estado
        solicitud.estado = nuevo_estado
        
        # Actualizar fecha correspondiente si no está establecida
        if nuevo_estado in ESTADOS_FECHAS:
            fecha_campo = ESTADOS_FECHAS[nuevo_estado]
            fecha_actual = getattr(solicitud, fecha_campo)
            if not fecha_actual:
                setattr(solicitud, fecha_campo, hoy)
        
        # Si se rechaza, marcar fecha de rechazo
        if nuevo_estado == 'pedido rechazado':
            if not solicitud.fecha_rechazado:
                solicitud.fecha_rechazado = hoy
        
        # Si se acepta, establecer fecha de aceptación y calcular fecha objetivo (20 días)
        if nuevo_estado == 'aceptado':
            if not solicitud.fecha_aceptado:
                solicitud.fecha_aceptado = hoy
                solicitud.fecha_aceptacion = hoy  # Compatibilidad
                solicitud.fecha_objetivo = hoy + timedelta(days=20)
        
        db.session.commit()
        flash(f'Estado cambiado a "{nuevo_estado}"', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar el estado: {str(e)}', 'error')
    
    return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))

@solicitudes_bp.route('/solicitudes/<int:solicitud_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_solicitud(solicitud_id):
    """Editar una solicitud"""
    solicitud = Presupuesto.query.get_or_404(solicitud_id)
    
    if request.method == 'POST':
        try:
            # Actualizar datos básicos
            solicitud.comercial_id = request.form.get('comercial_id')
            solicitud.cliente_id = request.form.get('cliente_id')
            solicitud.tipo_pedido = request.form.get('tipo_pedido')
            solicitud.forma_pago = request.form.get('forma_pago', '')
            solicitud.seguimiento = request.form.get('seguimiento', '')
            
            # Actualizar fecha objetivo si se proporciona
            fecha_objetivo_str = request.form.get('fecha_objetivo', '')
            if fecha_objetivo_str:
                try:
                    solicitud.fecha_objetivo = datetime.strptime(fecha_objetivo_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            
            # Función auxiliar para actualizar imagen
            def actualizar_imagen(campo_file, campo_db):
                """Actualizar imagen del formulario, eliminando la anterior si existe"""
                if campo_file in request.files:
                    file = request.files[campo_file]
                    if file and file.filename:
                        # Eliminar imagen anterior si existe
                        imagen_anterior = getattr(solicitud, campo_db, None)
                        if imagen_anterior:
                            # La imagen anterior puede estar guardada como ruta relativa o absoluta
                            if os.path.isabs(imagen_anterior):
                                old_path = imagen_anterior
                            else:
                                old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], imagen_anterior)
                            if os.path.exists(old_path):
                                try:
                                    os.remove(old_path)
                                except Exception as e:
                                    print(f"Error al eliminar imagen anterior {imagen_anterior}: {e}")
                        
                        filename = secure_filename(file.filename)
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                        filename = timestamp + filename
                        # Determinar subcarpeta según el tipo de imagen
                        if 'diseno' in campo_db or 'portada' in campo_db or 'adicional' in campo_db:
                            upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'solicitudes')
                            os.makedirs(upload_folder, exist_ok=True)
                            filepath = os.path.join(upload_folder, filename)
                            ruta_relativa = os.path.join('solicitudes', filename).replace('\\', '/')
                        else:
                            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                            ruta_relativa = filename
                        file.save(filepath)
                        setattr(solicitud, campo_db, ruta_relativa)
            
            # Manejar actualización de imágenes
            actualizar_imagen('imagen_diseno', 'imagen_diseno')
            actualizar_imagen('imagen_portada', 'imagen_portada')
            actualizar_imagen('imagen_adicional_1', 'imagen_adicional_1')
            actualizar_imagen('imagen_adicional_2', 'imagen_adicional_2')
            actualizar_imagen('imagen_adicional_3', 'imagen_adicional_3')
            actualizar_imagen('imagen_adicional_4', 'imagen_adicional_4')
            actualizar_imagen('imagen_adicional_5', 'imagen_adicional_5')
            
            # Actualizar descripciones de imágenes
            solicitud.descripcion_imagen_1 = request.form.get('descripcion_imagen_1', '')
            solicitud.descripcion_imagen_2 = request.form.get('descripcion_imagen_2', '')
            solicitud.descripcion_imagen_3 = request.form.get('descripcion_imagen_3', '')
            solicitud.descripcion_imagen_4 = request.form.get('descripcion_imagen_4', '')
            solicitud.descripcion_imagen_5 = request.form.get('descripcion_imagen_5', '')
            
            # Eliminar líneas existentes
            try:
                LineaPresupuesto.query.filter_by(presupuesto_id=solicitud.id).delete()
            except Exception as e:
                db.session.rollback()
                flash(f'Error al eliminar líneas anteriores: {str(e)}', 'error')
                return redirect(url_for('solicitudes.editar_solicitud', solicitud_id=solicitud_id))
            
            # Crear nuevas líneas (similar a editar_presupuesto)
            prenda_ids = request.form.getlist('prenda_id[]')
            nombres = request.form.getlist('nombre[]')
            nombres_mostrar = request.form.getlist('nombre_mostrar[]')
            cargos = request.form.getlist('cargo[]')
            cantidades = request.form.getlist('cantidad[]')
            colores = request.form.getlist('color[]')
            formas = request.form.getlist('forma[]')
            tipos_manda = request.form.getlist('tipo_manda[]')
            sexos = request.form.getlist('sexo[]')
            tallas = request.form.getlist('talla[]')
            tejidos = request.form.getlist('tejido[]')
            precios_unitarios = request.form.getlist('precio_unitario[]')
            descuentos = request.form.getlist('descuento[]')
            precios_finales = request.form.getlist('precio_final[]')
            estados_linea = request.form.getlist('estado_linea[]')
            
            for i in range(len(prenda_ids)):
                if prenda_ids[i] and (nombres_mostrar[i] if i < len(nombres_mostrar) else nombres[i] if i < len(nombres) else ''):
                    precio_unitario = None
                    if i < len(precios_unitarios) and precios_unitarios[i]:
                        try:
                            precio_unitario = Decimal(str(precios_unitarios[i]))
                        except:
                            precio_unitario = None
                    
                    # Usar nombre_mostrar si existe, sino usar nombre (compatibilidad)
                    nombre_mostrar_val = nombres_mostrar[i] if i < len(nombres_mostrar) and nombres_mostrar[i] else (nombres[i] if i < len(nombres) else '')
                    
                    # Calcular descuento y precio_final
                    descuento = Decimal('0')
                    if i < len(descuentos) and descuentos[i]:
                        try:
                            descuento = Decimal(str(descuentos[i]))
                        except:
                            descuento = Decimal('0')
                    
                    precio_final = None
                    if i < len(precios_finales) and precios_finales[i]:
                        try:
                            precio_final = Decimal(str(precios_finales[i]))
                        except:
                            precio_final = None
                    
                    if precio_final is None and precio_unitario:
                        if descuento > 0:
                            precio_final = precio_unitario * (Decimal('1') - descuento / Decimal('100'))
                        else:
                            precio_final = precio_unitario
                    
                    estado_linea = estados_linea[i] if i < len(estados_linea) and estados_linea[i] else 'pendiente'
                    
                    # Convertir Decimal a float para SQLite
                    cantidad_val = float(Decimal(str(cantidades[i])) if i < len(cantidades) and cantidades[i] else Decimal('1'))
                    precio_unitario_val = float(precio_unitario) if precio_unitario else None
                    descuento_val = float(descuento) if descuento else 0.0
                    precio_final_val = float(precio_final) if precio_final else None
                    
                    linea = LineaPresupuesto(
                        presupuesto_id=solicitud.id,
                        prenda_id=prenda_ids[i],
                        nombre=nombres[i] if i < len(nombres) else '',  # Mantenido para compatibilidad
                        nombre_mostrar=nombre_mostrar_val,
                        cargo=cargos[i] if i < len(cargos) else '',
                        cantidad=cantidad_val,
                        color=colores[i] if i < len(colores) else '',
                        forma=formas[i] if i < len(formas) else '',
                        tipo_manda=tipos_manda[i] if i < len(tipos_manda) else '',
                        sexo=sexos[i] if i < len(sexos) else '',
                        talla=tallas[i] if i < len(tallas) else '',
                        tejido=tejidos[i] if i < len(tejidos) else '',
                        precio_unitario=precio_unitario_val,
                        descuento=descuento_val,
                        precio_final=precio_final_val,
                        estado=estado_linea
                    )
                    db.session.add(linea)
            
            db.session.commit()
            flash('Solicitud actualizada correctamente', 'success')
            return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar la solicitud: {str(e)}', 'error')
    
    # GET: mostrar formulario
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    comerciales = Comercial.query.join(Usuario).order_by(Usuario.usuario).all()
    prendas = Prenda.query.order_by(Prenda.nombre).all()
    
    return render_template('solicitudes/editar.html',
                         solicitud=solicitud,
                         clientes=clientes,
                         comerciales=comerciales,
                         prendas=prendas)

@solicitudes_bp.route('/solicitudes/<int:solicitud_id>/lineas/<int:linea_id>/cambiar-estado', methods=['POST'])
@login_required
def cambiar_estado_linea(solicitud_id, linea_id):
    """Cambiar el estado de una línea de solicitud"""
    linea = LineaPresupuesto.query.get_or_404(linea_id)
    nuevo_estado = request.form.get('estado')
    
    # Validar que la línea pertenece a la solicitud
    if linea.presupuesto_id != solicitud_id:
        flash('La línea no pertenece a esta solicitud', 'error')
        return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))
    
    # Validar estados permitidos
    estados_permitidos = ['pendiente', 'en confección', 'en bordado', 'listo']
    
    try:
        if nuevo_estado in estados_permitidos:
            linea.estado = nuevo_estado
            db.session.commit()
            flash(f'Estado de la línea "{linea.nombre_mostrar or linea.nombre}" cambiado a "{nuevo_estado}"', 'success')
        else:
            flash('Estado no válido', 'error')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar el estado: {str(e)}', 'error')
    
    return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))

@solicitudes_bp.route('/solicitudes/crear-cliente-ajax', methods=['POST'])
@login_required
def crear_cliente_ajax():
    """Crear cliente desde AJAX"""
    try:
        fecha_alta_str = request.form.get('fecha_alta', '')
        fecha_alta = None
        if fecha_alta_str:
            try:
                fecha_alta = datetime.strptime(fecha_alta_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        comercial_id = request.form.get('comercial_id', '').strip()
        comercial_id = int(comercial_id) if comercial_id else None
        
        cliente = Cliente(
            nombre=request.form.get('nombre'),
            alias=request.form.get('alias', ''),
            nif=request.form.get('nif', ''),
            direccion=request.form.get('direccion', ''),
            poblacion=request.form.get('poblacion', ''),
            provincia=request.form.get('provincia', ''),
            codigo_postal=request.form.get('codigo_postal', ''),
            pais=request.form.get('pais', 'España'),
            telefono=request.form.get('telefono', ''),
            movil=request.form.get('movil', ''),
            email=request.form.get('email', ''),
            personas_contacto=request.form.get('personas_contacto', ''),
            anotaciones=request.form.get('anotaciones', ''),
            usuario_web=request.form.get('usuario_web', '').strip() or None,
            fecha_alta=fecha_alta,
            comercial_id=comercial_id
        )
        
        password_web = request.form.get('password_web', '').strip()
        if cliente.usuario_web and password_web:
            cliente.set_password(password_web)
        
        db.session.add(cliente)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'cliente': {
                'id': cliente.id,
                'nombre': cliente.nombre
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

