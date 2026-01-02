"""Rutas para gestión de solicitudes (presupuestos y pedidos unificados)"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, make_response, jsonify, send_from_directory
from flask_login import login_required
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import os
import tempfile
from io import BytesIO
from extensions import db
from models import Comercial, Cliente, Prenda, Presupuesto, LineaPresupuesto, Usuario, RegistroEstadoSolicitud
from sqlalchemy.orm import joinedload
from flask import jsonify
from playwright.sync_api import sync_playwright
from decimal import Decimal
import base64
from utils.sftp_upload import upload_file_to_sftp, download_file_from_sftp, get_file_url, file_exists_on_sftp

solicitudes_bp = Blueprint('solicitudes', __name__)

# Estados unificados
ESTADOS_SOLICITUD = [
    'presupuesto',
    'rechazado',
    'aceptado',
    'mockup',
    'en preparacion',
    'terminado',
    'entregado al cliente'
]

# Subestados por estado principal
SUBESTADOS = {
    'mockup': [
        'encargado a',
        'REVISIÓN CLIENTE',
        'CAMBIOS 1',
        'CAMBIOS 2',
        'RECHAZADO',
        'aceptado'
    ],
    'en preparacion': [
        'hacer marcada',
        'imprimir',
        'calandra',
        'corte',
        'confeccion',
        'sublimacion',
        'bordado'
    ]
}

# Mapeo de estados a campos de fecha
ESTADOS_FECHAS = {
    'presupuesto': 'fecha_presupuesto',
    'aceptado': 'fecha_aceptado',
    'mockup': 'fecha_mockup',
    'en preparacion': 'fecha_en_preparacion',
    'terminado': 'fecha_terminado',
    'entregado al cliente': 'fecha_entregado_cliente'
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
            
            # Crear registro inicial del estado
            from flask_login import current_user
            registro_inicial = RegistroEstadoSolicitud(
                presupuesto_id=solicitud.id,
                estado='presupuesto',
                subestado=None,
                fecha_cambio=datetime.now(),
                usuario_id=current_user.id if current_user.is_authenticated else None
            )
            db.session.add(registro_inicial)
            
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
                        precio_final=precio_final_val
                    )
                    db.session.add(linea)
                    print(f"DEBUG: Línea {i} añadida - nombre_mostrar: '{nombre_mostrar_val}', prenda_id: {prenda_ids[i]}")
            
            print(f"DEBUG: Total líneas procesadas: {len([l for l in db.session.new if isinstance(l, LineaPresupuesto)])}")
            
            # Función auxiliar para subir imagen a SFTP
            def subir_imagen_sftp(file, nombre_archivo):
                """Subir imagen a SFTP y retornar ruta relativa"""
                try:
                    # Leer contenido del archivo
                    file_content = file.read()
                    file.seek(0)  # Resetear para posibles usos futuros
                    
                    # Construir ruta remota en SFTP
                    config = os.environ.get('SFTP_DIR', '/')
                    if config != '/':
                        remote_path = f"{config.rstrip('/')}/solicitudes/{nombre_archivo}"
                    else:
                        remote_path = f"/solicitudes/{nombre_archivo}"
                    
                    # Subir a SFTP
                    ruta_subida = upload_file_to_sftp(file_content, remote_path)
                    if ruta_subida:
                        return ruta_subida
                    else:
                        # Fallback: guardar localmente si SFTP falla
                        print(f"Error al subir a SFTP, guardando localmente: {nombre_archivo}")
                        upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'solicitudes')
                        os.makedirs(upload_folder, exist_ok=True)
                        filepath = os.path.join(upload_folder, nombre_archivo)
                        file.seek(0)
                        file.save(filepath)
                        return os.path.join('solicitudes', nombre_archivo).replace('\\', '/')
                except Exception as e:
                    print(f"Error al procesar imagen {nombre_archivo}: {e}")
                    # Fallback: guardar localmente
                    upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'solicitudes')
                    os.makedirs(upload_folder, exist_ok=True)
                    filepath = os.path.join(upload_folder, nombre_archivo)
                    file.seek(0)
                    file.save(filepath)
                    return os.path.join('solicitudes', nombre_archivo).replace('\\', '/')
            
            # Procesar imagen de diseño
            if 'imagen_diseno' in request.files:
                file = request.files['imagen_diseno']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    nombre_archivo = f"{solicitud.id}_diseno_{filename}"
                    ruta_relativa = subir_imagen_sftp(file, nombre_archivo)
                    solicitud.imagen_diseno = ruta_relativa
            
            # Procesar imagen de portada
            if 'imagen_portada' in request.files:
                file = request.files['imagen_portada']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    nombre_archivo = f"{solicitud.id}_portada_{filename}"
                    ruta_relativa = subir_imagen_sftp(file, nombre_archivo)
                    solicitud.imagen_portada = ruta_relativa
            
            # Procesar imágenes adicionales
            for i in range(1, 6):
                imagen_key = f'imagen_adicional_{i}'
                descripcion_key = f'descripcion_imagen_{i}'
                
                if imagen_key in request.files:
                    file = request.files[imagen_key]
                    if file and file.filename:
                        filename = secure_filename(file.filename)
                        nombre_archivo = f"{solicitud.id}_adicional_{i}_{filename}"
                        ruta_relativa = subir_imagen_sftp(file, nombre_archivo)
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
        joinedload(Presupuesto.comercial),
        joinedload(Presupuesto.mockup_encargado_a)
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
    
    # Obtener registros de cambios de estado ordenados por fecha (con eager loading de usuario)
    registros_estado = RegistroEstadoSolicitud.query.options(
        joinedload(RegistroEstadoSolicitud.usuario)
    ).filter_by(
        presupuesto_id=solicitud_id
    ).order_by(RegistroEstadoSolicitud.fecha_cambio.asc()).all()
    
    # Obtener usuarios activos para asignar mockup
    usuarios = Usuario.query.filter_by(activo=True).order_by(Usuario.usuario).all()
    
    hoy = datetime.now().date()
    
    return render_template('solicitudes/ver.html',
                         solicitud=solicitud,
                         estados=ESTADOS_SOLICITUD,
                         subestados=SUBESTADOS,
                         estados_fechas=ESTADOS_FECHAS,
                         registros_estado=registros_estado,
                         usuarios=usuarios,
                         hoy=hoy)

@solicitudes_bp.route('/solicitudes/<int:solicitud_id>/cambiar-estado', methods=['POST'])
@login_required
def cambiar_estado_solicitud(solicitud_id):
    """Cambiar el estado de una solicitud"""
    from flask_login import current_user
    solicitud = Presupuesto.query.get_or_404(solicitud_id)
    nuevo_estado = request.form.get('estado')
    nuevo_subestado = request.form.get('subestado', '')
    hoy = datetime.now().date()
    ahora = datetime.now()
    
    if nuevo_estado not in ESTADOS_SOLICITUD:
        flash('Estado no válido', 'error')
        return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))
    
    try:
        estado_anterior = solicitud.estado
        subestado_anterior = solicitud.subestado
        hubo_cambio = False
        
        # Si el estado cambia, resetear subestado
        if nuevo_estado != estado_anterior:
            solicitud.estado = nuevo_estado
            solicitud.subestado = None
            hubo_cambio = True
        
        # Si hay subestado y el estado lo permite
        if nuevo_subestado and nuevo_estado in SUBESTADOS:
            if nuevo_subestado in SUBESTADOS[nuevo_estado]:
                # Solo actualizar si el subestado cambió
                if nuevo_subestado != subestado_anterior:
                    solicitud.subestado = nuevo_subestado
                    hubo_cambio = True
                    
                    # Si el subestado es "encargado a", asignar el usuario
                    if nuevo_subestado == 'encargado a':
                        usuario_encargado_id = request.form.get('usuario_encargado', '')
                        if usuario_encargado_id:
                            try:
                                solicitud.mockup_encargado_a_id = int(usuario_encargado_id)
                            except (ValueError, TypeError):
                                flash('Usuario no válido', 'error')
                                return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))
                        else:
                            flash('Debe seleccionar un usuario para encargar el mockup', 'error')
                            return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))
        
        # Actualizar fecha correspondiente si no está establecida
        if nuevo_estado in ESTADOS_FECHAS:
            fecha_campo = ESTADOS_FECHAS[nuevo_estado]
            fecha_actual = getattr(solicitud, fecha_campo, None)
            if not fecha_actual:
                setattr(solicitud, fecha_campo, hoy)
        
        # Si entra en mockup, establecer fecha límite (3 días hábiles)
        if nuevo_estado == 'mockup' and estado_anterior != 'mockup':
            from utils.fechas import calcular_fecha_saltando_festivos
            solicitud.fecha_limite_mockup = calcular_fecha_saltando_festivos(hoy, 3)
        
        # Si se acepta, establecer fecha de aceptación y calcular fecha objetivo (20 días hábiles)
        if nuevo_estado == 'aceptado' and estado_anterior != 'aceptado':
            if not solicitud.fecha_aceptado:
                solicitud.fecha_aceptado = hoy
                solicitud.fecha_aceptacion = hoy  # Compatibilidad
                # Calcular fecha objetivo saltando días festivos
                from utils.fechas import calcular_fecha_saltando_festivos
                solicitud.fecha_objetivo = calcular_fecha_saltando_festivos(hoy, 20)
        
        # Crear registro del cambio solo si hubo cambio real
        if hubo_cambio or (nuevo_estado == estado_anterior and nuevo_subestado and nuevo_subestado != subestado_anterior):
            registro = RegistroEstadoSolicitud(
                presupuesto_id=solicitud_id,
                estado=nuevo_estado,
                subestado=solicitud.subestado,
                fecha_cambio=ahora,
                usuario_id=current_user.id if current_user.is_authenticated else None
            )
            db.session.add(registro)
        
        db.session.commit()
        
        # Enviar email si cambió el estado o el subestado
        debe_enviar_email = False
        if nuevo_estado != estado_anterior:
            # Cambió el estado principal
            debe_enviar_email = True
        elif nuevo_estado == 'en preparacion' and nuevo_subestado and nuevo_subestado != subestado_anterior:
            # Cambió el subestado dentro de "en preparacion"
            debe_enviar_email = True
        
        if debe_enviar_email:
            from utils.email import enviar_email_cambio_estado_solicitud
            try:
                exito, mensaje = enviar_email_cambio_estado_solicitud(
                    solicitud, 
                    nuevo_estado, 
                    subestado=solicitud.subestado,
                    estado_anterior=estado_anterior,
                    subestado_anterior=subestado_anterior
                )
                if not exito:
                    # No mostrar error al usuario, solo log
                    print(f"Email no enviado: {mensaje}")
            except Exception as e:
                # No mostrar error al usuario, solo log
                print(f"Error al intentar enviar email: {str(e)}")
        
        flash(f'Estado cambiado a "{nuevo_estado}"' + (f' - {solicitud.subestado}' if solicitud.subestado else ''), 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar el estado: {str(e)}', 'error')
        import traceback
        traceback.print_exc()
    
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
                """Actualizar imagen del formulario, subiendo a SFTP"""
                if campo_file in request.files:
                    file = request.files[campo_file]
                    if file and file.filename:
                        filename = secure_filename(file.filename)
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                        nombre_archivo = f"{solicitud.id}_{campo_db}_{timestamp}{filename}"
                        
                        # Subir a SFTP
                        ruta_relativa = subir_imagen_sftp(file, nombre_archivo)
                        setattr(solicitud, campo_db, ruta_relativa)
            
            # Función auxiliar para subir imagen a SFTP (reutilizada)
            def subir_imagen_sftp(file, nombre_archivo):
                """Subir imagen a SFTP y retornar ruta relativa"""
                try:
                    # Leer contenido del archivo
                    file_content = file.read()
                    file.seek(0)
                    
                    # Construir ruta remota en SFTP
                    config = os.environ.get('SFTP_DIR', '/')
                    if config != '/':
                        remote_path = f"{config.rstrip('/')}/solicitudes/{nombre_archivo}"
                    else:
                        remote_path = f"/solicitudes/{nombre_archivo}"
                    
                    # Subir a SFTP
                    ruta_subida = upload_file_to_sftp(file_content, remote_path)
                    if ruta_subida:
                        return ruta_subida
                    else:
                        # Fallback: guardar localmente si SFTP falla
                        print(f"Error al subir a SFTP, guardando localmente: {nombre_archivo}")
                        upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'solicitudes')
                        os.makedirs(upload_folder, exist_ok=True)
                        filepath = os.path.join(upload_folder, nombre_archivo)
                        file.seek(0)
                        file.save(filepath)
                        return os.path.join('solicitudes', nombre_archivo).replace('\\', '/')
                except Exception as e:
                    print(f"Error al procesar imagen {nombre_archivo}: {e}")
                    # Fallback: guardar localmente
                    upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'solicitudes')
                    os.makedirs(upload_folder, exist_ok=True)
                    filepath = os.path.join(upload_folder, nombre_archivo)
                    file.seek(0)
                    file.save(filepath)
                    return os.path.join('solicitudes', nombre_archivo).replace('\\', '/')
            
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
            
            # Crear nuevas líneas (similar a editar_solicitud)
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
                        precio_final=precio_final_val
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

def preparar_datos_imprimir_solicitud(solicitud_id):
    """Función auxiliar para preparar todos los datos necesarios para imprimir la solicitud"""
    solicitud = Presupuesto.query.get_or_404(solicitud_id)
    
    # Calcular totales
    tipo_iva = 21
    base_imponible = Decimal('0.00')
    
    for linea in solicitud.lineas:
        precio_unit = Decimal(str(linea.precio_unitario)) if linea.precio_unitario else Decimal('0.00')
        cantidad = Decimal(str(linea.cantidad))
        total_linea = precio_unit * cantidad
        base_imponible += total_linea
    
    iva_total = base_imponible * Decimal(str(tipo_iva)) / Decimal('100')
    total_con_iva = base_imponible + iva_total
    
    # Función auxiliar para convertir imagen a base64
    def convertir_imagen_a_base64(ruta_imagen):
        """Convertir imagen a base64, intentando primero localmente y luego desde SFTP"""
        if not ruta_imagen:
            return None
        
        imagen_data = None
        
        # Intentar leer localmente primero
        if os.path.exists(ruta_imagen):
            try:
                with open(ruta_imagen, 'rb') as f:
                    imagen_data = f.read()
            except Exception as e:
                print(f"Error al leer imagen local {ruta_imagen}: {e}")
        
        # Si no está localmente, intentar desde SFTP
        if not imagen_data:
            try:
                # Construir ruta remota en SFTP
                # La ruta puede ser relativa (ej: 'solicitudes/123_diseno.jpg') o absoluta
                if ruta_imagen.startswith('/'):
                    remote_path = ruta_imagen
                else:
                    # Si es relativa, construir ruta completa en SFTP
                    config = os.environ.get('SFTP_DIR', '/')
                    if config != '/':
                        remote_path = f"{config.rstrip('/')}/{ruta_imagen}"
                    else:
                        remote_path = f"/{ruta_imagen}"
                
                imagen_data = download_file_from_sftp(remote_path)
            except Exception as e:
                print(f"Error al descargar imagen desde SFTP {ruta_imagen}: {e}")
        
        if not imagen_data:
            return None
        
        try:
            imagen_base64 = base64.b64encode(imagen_data).decode('utf-8')
            # Detectar tipo MIME basado en extensión del archivo
            ruta_lower = ruta_imagen.lower()
            if ruta_lower.endswith('.png'):
                return f'data:image/png;base64,{imagen_base64}'
            elif ruta_lower.endswith(('.jpg', '.jpeg')):
                return f'data:image/jpeg;base64,{imagen_base64}'
            elif ruta_lower.endswith('.gif'):
                return f'data:image/gif;base64,{imagen_base64}'
            else:
                return f'data:image/png;base64,{imagen_base64}'  # Por defecto PNG
        except Exception as e:
            print(f"Error al codificar imagen a base64 {ruta_imagen}: {e}")
            return None
    
    # Convertir imágenes a base64
    logo_base64 = None
    imagen_diseno_base64 = None
    imagen_portada_base64 = None
    imagenes_adicionales_base64 = []
    descripciones_imagenes = []
    
    # Convertir logo a base64
    logo_path = os.path.join(current_app.static_folder, 'logo1.png')
    logo_base64 = convertir_imagen_a_base64(logo_path)
    
    # Convertir imagen de diseño a base64 si existe
    if solicitud.imagen_diseno:
        # Intentar primero localmente, luego desde SFTP
        imagen_path_local = os.path.join(current_app.config['UPLOAD_FOLDER'], solicitud.imagen_diseno)
        if os.path.exists(imagen_path_local):
            imagen_diseno_base64 = convertir_imagen_a_base64(imagen_path_local)
        else:
            # Intentar desde SFTP usando la ruta relativa guardada
            imagen_diseno_base64 = convertir_imagen_a_base64(solicitud.imagen_diseno)
    
    # Convertir imagen de portada a base64 si existe
    if solicitud.imagen_portada:
        imagen_path_local = os.path.join(current_app.config['UPLOAD_FOLDER'], solicitud.imagen_portada)
        if os.path.exists(imagen_path_local):
            imagen_portada_base64 = convertir_imagen_a_base64(imagen_path_local)
        else:
            imagen_portada_base64 = convertir_imagen_a_base64(solicitud.imagen_portada)
    
    # Convertir imágenes adicionales a base64 y obtener descripciones (5 imágenes)
    for i in range(1, 6):
        campo_imagen = f'imagen_adicional_{i}'
        campo_descripcion = f'descripcion_imagen_{i}'
        
        if hasattr(solicitud, campo_imagen) and getattr(solicitud, campo_imagen):
            imagen_nombre = getattr(solicitud, campo_imagen)
            imagen_path_local = os.path.join(current_app.config['UPLOAD_FOLDER'], imagen_nombre)
            if os.path.exists(imagen_path_local):
                imagen_base64 = convertir_imagen_a_base64(imagen_path_local)
            else:
                # Intentar desde SFTP
                imagen_base64 = convertir_imagen_a_base64(imagen_nombre)
            imagenes_adicionales_base64.append(imagen_base64)
        else:
            imagenes_adicionales_base64.append(None)
        
        # Obtener descripción
        descripcion = getattr(solicitud, campo_descripcion, '') if hasattr(solicitud, campo_descripcion) else ''
        descripciones_imagenes.append(descripcion)
    
    return {
        'presupuesto': solicitud,  # Mantener 'presupuesto' para compatibilidad con template
        'solicitud': solicitud,  # Agregar 'solicitud' también
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

@solicitudes_bp.route('/solicitudes/<int:solicitud_id>/imprimir')
@login_required
def imprimir_solicitud(solicitud_id):
    """Vista de impresión de la solicitud (HTML para imprimir desde navegador)"""
    datos = preparar_datos_imprimir_solicitud(solicitud_id)
    
    return render_template('imprimir_presupuesto.html', 
                         **datos,
                         use_base64=True)

@solicitudes_bp.route('/solicitudes/<int:solicitud_id>/descargar-albaran')
@login_required
def descargar_albaran_solicitud(solicitud_id):
    """Descargar albarán de solicitud en formato PDF (sin precios)"""
    try:
        datos = preparar_datos_imprimir_solicitud(solicitud_id)
        
        # Renderizar el HTML como albarán (sin precios)
        html = render_template('imprimir_presupuesto.html', 
                             **datos,
                             use_base64=True,
                             es_albaran=True)
        
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
            return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))
        
        # Preparar la respuesta con el PDF
        pdf_buffer.seek(0)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=albaran_solicitud_{solicitud_id}.pdf'
        
        return response
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error completo al generar PDF: {error_trace}")
        flash(f'Error al generar PDF: {str(e)}', 'error')
        return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))

@solicitudes_bp.route('/solicitudes/<int:solicitud_id>/descargar-pdf')
@login_required
def descargar_pdf_solicitud(solicitud_id):
    """Descargar solicitud en formato PDF"""
    try:
        datos = preparar_datos_imprimir_solicitud(solicitud_id)
        
        # Renderizar el HTML de la solicitud
        html = render_template('imprimir_presupuesto.html', 
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
            return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))
        
        # Preparar la respuesta con el PDF
        pdf_buffer.seek(0)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=solicitud_{solicitud_id}.pdf'
        
        return response
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error completo al generar PDF: {error_trace}")
        flash(f'Error al generar PDF: {str(e)}', 'error')
        return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))

@solicitudes_bp.route('/solicitudes/imagen/<path:ruta_imagen>')
@login_required
def servir_imagen_sftp(ruta_imagen):
    """Servir imagen desde SFTP o localmente como fallback"""
    try:
        # Intentar primero localmente
        imagen_path_local = os.path.join(current_app.config['UPLOAD_FOLDER'], ruta_imagen)
        if os.path.exists(imagen_path_local):
            return send_from_directory(
                os.path.dirname(imagen_path_local),
                os.path.basename(imagen_path_local)
            )
        
        # Si no está localmente, descargar desde SFTP
        config = os.environ.get('SFTP_DIR', '/')
        if config != '/':
            remote_path = f"{config.rstrip('/')}/{ruta_imagen}"
        else:
            remote_path = f"/{ruta_imagen}"
        
        imagen_data = download_file_from_sftp(remote_path)
        if imagen_data:
            # Determinar tipo MIME
            ruta_lower = ruta_imagen.lower()
            if ruta_lower.endswith('.png'):
                mimetype = 'image/png'
            elif ruta_lower.endswith(('.jpg', '.jpeg')):
                mimetype = 'image/jpeg'
            elif ruta_lower.endswith('.gif'):
                mimetype = 'image/gif'
            else:
                mimetype = 'image/png'
            
            response = make_response(imagen_data)
            response.headers['Content-Type'] = mimetype
            return response
        
        # Si no se encuentra, retornar 404
        flash('Imagen no encontrada', 'error')
        return '', 404
        
    except Exception as e:
        print(f"Error al servir imagen {ruta_imagen}: {e}")
        return '', 404

@solicitudes_bp.route('/solicitudes/<int:solicitud_id>/actualizar-seguimiento', methods=['POST'])
@login_required
def actualizar_seguimiento(solicitud_id):
    """Actualizar el campo de seguimiento de la solicitud"""
    solicitud = Presupuesto.query.get_or_404(solicitud_id)
    nuevo_seguimiento = request.form.get('seguimiento', '')
    
    try:
        solicitud.seguimiento = nuevo_seguimiento
        db.session.commit()
        flash('Seguimiento actualizado correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar seguimiento: {str(e)}', 'error')
    
    return redirect(url_for('solicitudes.ver_solicitud', solicitud_id=solicitud_id))

