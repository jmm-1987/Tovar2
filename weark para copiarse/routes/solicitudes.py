"""Rutas para gestión de solicitudes (presupuestos y pedidos unificados)"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, make_response, jsonify, send_from_directory
from flask_login import login_required
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import os
import tempfile
import json
from io import BytesIO
from extensions import db
from models import Comercial, Cliente, Prenda, Presupuesto, LineaPresupuesto, Usuario, RegistroEstadoSolicitud, CategoriaCliente, DireccionEnvio, PersonaContacto, Pedido
from sqlalchemy.orm import joinedload
from flask import jsonify
from playwright.sync_api import sync_playwright
from decimal import Decimal
import base64
import secrets
from urllib.parse import quote
from utils.sftp_upload import upload_file_to_sftp, download_file_from_sftp, get_file_url, file_exists_on_sftp
from utils.numeracion import obtener_siguiente_numero_solicitud
from utils.email import enviar_email_enlace_presupuesto_cliente, enviar_email_notificacion_respuesta_cliente
from utils.facturadirecta import (
    FacturaDirectaError,
    build_delivery_note_payload,
    create_delivery_note,
    net_unit_price_for_fd_line,
)

solicitudes_bp = Blueprint('presupuestos', __name__)
presupuestos_bp = solicitudes_bp

# Estados unificados
ESTADOS_SOLICITUD = [
    'presupuesto',
    'rechazado',
    'cancelado',
    'aceptado',
    'mockup',
    'en preparacion',
    'revision y empaquetado',
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
    'revision y empaquetado': 'fecha_terminado',
    'entregado al cliente': 'fecha_entregado_cliente'
}


def _unir_campos_por_prenda(form, campo_suffix, max_prendas=50, sep="\n"):
    """
    Une valores de campos repetidos por tarjeta de producto con formato:
    prenda1_<campo_suffix>, prenda2_<campo_suffix>, ...
    """
    valores = []
    for i in range(1, max_prendas + 1):
        key = f'prenda{i}_{campo_suffix}'
        v = (form.get(key, "") or "").strip()
        if v:
            valores.append(v)
    return sep.join(valores)


def _obtener_productos_solicitud(solicitud):
    """
    Devuelve productos del nuevo esquema guardados como JSON en referencias_web.
    Si no hay JSON válido, devuelve [] para permitir fallback legacy.
    """
    raw = (solicitud.referencias_web or '').strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        productos = []
        for idx, p in enumerate(data, start=1):
            if not isinstance(p, dict):
                continue
            productos.append({
                'numero': p.get('numero') or idx,
                'tipo_producto': (p.get('tipo') or '').strip(),
                'colores_principales': '',
                'colores_secundarios': '',
                'ubicacion_logo': '',
                'referencias_diseno': p.get('referencias_diseno', ''),
                'comentarios': p.get('comentarios', ''),
                'logos': p.get('logos', []) if isinstance(p.get('logos', []), list) else [],
                'fotos': p.get('fotos', []) if isinstance(p.get('fotos', []), list) else [],
                'tipo_tela': p.get('tipo_tela', ''),
                'medidas': p.get('medidas', ''),
                'grabacion': p.get('grabacion', ''),
                'costuras': p.get('costuras', ''),
                'tipo_grabacion': p.get('tipo_grabacion', ''),
                'tipo_prenda': p.get('tipo_prenda', ''),
                'color1': p.get('color1', ''),
                'color2': p.get('color2', ''),
                'color3': p.get('color3', ''),
                'tipo_tejido': p.get('tipo_tejido', ''),
                'marcada': p.get('marcada', ''),
            })
        return productos
    except (TypeError, ValueError):
        return []


def _subir_imagen_solicitud(file, nombre_archivo):
    """Sube archivo de imagen/PDF a SFTP (fallback local) y retorna ruta relativa."""
    try:
        file_content = file.read()
        file.seek(0)
        config = os.environ.get('SFTP_DIR', '/')
        if config != '/':
            remote_path = f"{config.rstrip('/')}/solicitudes/{nombre_archivo}"
        else:
            remote_path = f"/solicitudes/{nombre_archivo}"

        ruta_subida = upload_file_to_sftp(file_content, remote_path)
        if ruta_subida:
            return ruta_subida

        upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'solicitudes')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, nombre_archivo)
        file.seek(0)
        file.save(filepath)
        return os.path.join('solicitudes', nombre_archivo).replace('\\', '/')
    except Exception as e:
        print(f"Error al procesar imagen {nombre_archivo}: {e}")
        upload_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'solicitudes')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, nombre_archivo)
        file.seek(0)
        file.save(filepath)
        return os.path.join('solicitudes', nombre_archivo).replace('\\', '/')


def _token_expira_en():
    dias = int(current_app.config.get('CLIENT_TOKEN_EXPIRY_DAYS', 7))
    return datetime.utcnow() + timedelta(days=max(1, dias))


def _generar_token_cliente(solicitud):
    solicitud.cliente_token = secrets.token_urlsafe(32)
    solicitud.cliente_token_expira_en = _token_expira_en()
    return solicitud.cliente_token


def _token_cliente_valido(solicitud, token):
    if not token or token != solicitud.cliente_token:
        return False
    if not solicitud.cliente_token_expira_en:
        return False
    return solicitud.cliente_token_expira_en >= datetime.utcnow()


def _url_publica_cliente(solicitud):
    return url_for('presupuestos.ver_presupuesto_publico_cliente', token=solicitud.cliente_token, _external=True)


def _parse_historial_respuestas_cliente(solicitud):
    """Lista de entradas del historial de respuestas del portal (más reciente al final)."""
    raw = (getattr(solicitud, 'historial_respuestas_cliente', None) or '').strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


def _notif_respuesta_cliente_pendiente(solicitud):
    """True si hay respuesta del cliente y aún no se pulsó 'Marcar como visto' (o hubo respuesta más nueva)."""
    if not solicitud.cliente_respondido_at or not solicitud.cliente_respuesta:
        return False
    v = solicitud.respuesta_cliente_notif_vista_at
    if v is None:
        return True
    return v < solicitud.cliente_respondido_at


def _append_historial_respuesta_cliente(solicitud, accion, subestado, cliente_respuesta, comentario):
    """Añade una entrada al historial sin borrar las anteriores."""
    etiquetas_accion = {
        'aceptar': 'Aceptar cantidades y diseños',
        'cambios_1': 'Sugerir cambios (1)',
        'cambios_2': 'Sugerir cambios (2)',
        'rechazar': 'Rechazar',
    }
    hist = _parse_historial_respuestas_cliente(solicitud)
    hist.append({
        'en': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'accion': accion,
        'accion_label': etiquetas_accion.get(accion, accion),
        'subestado': subestado,
        'respuesta': cliente_respuesta,
        'comentario': (comentario or '').strip(),
    })
    solicitud.historial_respuestas_cliente = json.dumps(hist, ensure_ascii=False)


def _extraer_productos_form(form, max_productos=50):
    """Extrae productos prendaX_* del formulario y devuelve lista tipada."""
    productos = []
    for i in range(1, max_productos + 1):
        tipo = (form.get(f'prenda{i}_tipo', '') or '').strip().upper()
        if not tipo:
            break

        item = {
            'numero': i,
            'tipo': tipo,
            'comentarios': (form.get(f'prenda{i}_comentarios', '') or '').strip(),
            'referencias_diseno': (form.get(f'prenda{i}_referencias_diseno', '') or '').strip(),
            'logos': [],
            'fotos': []
        }

        logos_raw = (form.get(f'prenda{i}_logos_json', '') or '').strip()
        if logos_raw:
            try:
                logos = json.loads(logos_raw)
                if isinstance(logos, list):
                    item['logos'] = logos
            except (TypeError, ValueError):
                item['logos'] = []

        if tipo == 'LONA':
            item.update({
                'tipo_tela': (form.get(f'prenda{i}_tipo_tela', '') or '').strip(),
                'medidas': (form.get(f'prenda{i}_medidas', '') or '').strip(),
                'grabacion': (form.get(f'prenda{i}_grabacion', '') or '').strip(),
                'costuras': (form.get(f'prenda{i}_costuras', '') or '').strip(),
            })
        elif tipo == 'TELA POR METROS':
            item.update({
                'tipo_tela': (form.get(f'prenda{i}_tipo_tela', '') or '').strip(),
                'medidas': (form.get(f'prenda{i}_medidas', '') or '').strip(),
            })
        elif tipo == 'GRABACION':
            item.update({
                'tipo_grabacion': (form.get(f'prenda{i}_tipo_grabacion', '') or '').strip(),
                'tipo_prenda': (form.get(f'prenda{i}_tipo_prenda', '') or '').strip(),
            })
        elif tipo == 'ROPA':
            item.update({
                'tipo_prenda': (form.get(f'prenda{i}_tipo_prenda', '') or '').strip(),
                'color1': (form.get(f'prenda{i}_color1', '') or '').strip(),
                'color2': (form.get(f'prenda{i}_color2', '') or '').strip(),
                'color3': (form.get(f'prenda{i}_color3', '') or '').strip(),
                'tipo_tejido': (form.get(f'prenda{i}_tipo_tejido', '') or '').strip(),
                'marcada': (form.get(f'prenda{i}_marcada', '') or '').strip(),
            })
        productos.append(item)
    return productos


def _validar_productos(productos, files):
    """Valida requeridos por tipo y fotos mínimas en tipos que aplican."""
    # Permitido guardar presupuesto solo con líneas (sin productos)
    if not productos:
        return []

    errores = []
    for p in productos:
        n = p.get('numero')
        t = p.get('tipo')
        pref = f'Producto {n} ({t})'

        if t == 'LONA':
            for k in ['tipo_tela', 'medidas', 'grabacion', 'costuras']:
                if not p.get(k):
                    errores.append(f'{pref}: falta {k}')
            fotos = [f for f in files.getlist(f'prenda{n}_fotos[]') if getattr(f, 'filename', '')]
            if not fotos:
                errores.append(f'{pref}: debe tener al menos una foto')
        elif t == 'TELA POR METROS':
            for k in ['tipo_tela', 'medidas']:
                if not p.get(k):
                    errores.append(f'{pref}: falta {k}')
            fotos = [f for f in files.getlist(f'prenda{n}_fotos[]') if getattr(f, 'filename', '')]
            if not fotos:
                errores.append(f'{pref}: debe tener al menos una foto')
        elif t == 'GRABACION':
            for k in ['tipo_grabacion', 'tipo_prenda']:
                if not p.get(k):
                    errores.append(f'{pref}: falta {k}')
        elif t == 'ROPA':
            # color3 es opcional en productos de ropa
            for k in ['tipo_prenda', 'color1', 'color2', 'tipo_tejido', 'marcada']:
                if not p.get(k):
                    errores.append(f'{pref}: falta {k}')
        else:
            errores.append(f'{pref}: tipo no válido')
    return errores

@solicitudes_bp.route('/presupuestos')
@login_required
def listado_solicitudes():
    """Listado de solicitudes con filtros"""
    query = Presupuesto.query.options(
        joinedload(Presupuesto.lineas),
        joinedload(Presupuesto.cliente),
        joinedload(Presupuesto.comercial)
    )
    
    # Incluir presupuestos en estado rechazado (por defecto se excluyen salvo que el filtro sea solo "rechazado")
    incluir_rechazados = request.args.get('incluir_rechazados', '') in ('1', 'on', 'true', 'yes', 'si')
    estado_filtro = request.args.get('estado', '')
    if estado_filtro:
        query = query.filter(Presupuesto.estado == estado_filtro)
    elif not incluir_rechazados:
        query = query.filter(Presupuesto.estado != 'rechazado')
    
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
    
    # Ordenación
    sort_by = request.args.get('sort_by', 'fecha_creacion')
    sort_order = request.args.get('sort_order', 'desc')
    
    if sort_by == 'numero_solicitud':
        if sort_order == 'asc':
            query = query.order_by(Presupuesto.numero_solicitud.asc().nullslast(), Presupuesto.id.asc())
        else:
            query = query.order_by(Presupuesto.numero_solicitud.desc().nullslast(), Presupuesto.id.desc())
    elif sort_by == 'fecha_creacion':
        if sort_order == 'asc':
            query = query.order_by(Presupuesto.fecha_creacion.asc())
        else:
            query = query.order_by(Presupuesto.fecha_creacion.desc())
    elif sort_by == 'cliente':
        query = query.join(Cliente)
        if sort_order == 'asc':
            query = query.order_by(Cliente.nombre.asc())
        else:
            query = query.order_by(Cliente.nombre.desc())
    elif sort_by == 'comercial':
        query = query.join(Comercial).join(Usuario)
        if sort_order == 'asc':
            query = query.order_by(Usuario.usuario.asc())
        else:
            query = query.order_by(Usuario.usuario.desc())
    elif sort_by == 'tipo_pedido':
        if sort_order == 'asc':
            query = query.order_by(Presupuesto.tipo_pedido.asc())
        else:
            query = query.order_by(Presupuesto.tipo_pedido.desc())
    elif sort_by == 'estado':
        if sort_order == 'asc':
            query = query.order_by(Presupuesto.estado.asc())
        else:
            query = query.order_by(Presupuesto.estado.desc())
    else:
        # Por defecto ordenar por fecha descendente
        query = query.order_by(Presupuesto.fecha_creacion.desc())
    
    solicitudes = query.all()
    
    # Calcular base imponible, IVA y total para cada solicitud
    solicitudes_con_base = []
    for solicitud in solicitudes:
        base_imponible = Decimal('0.00')
        for linea in solicitud.lineas:
            cantidad = Decimal(str(linea.cantidad)) if linea.cantidad else Decimal('0')
            precio_unit = Decimal(str(linea.precio_unitario)) if linea.precio_unitario else Decimal('0.00')
            descuento = Decimal(str(linea.descuento)) if linea.descuento else Decimal('0')
            
            # Calcular precio final con descuento
            precio_final = precio_unit
            if descuento > 0:
                if linea.precio_final:
                    precio_final = Decimal(str(linea.precio_final))
                else:
                    precio_final = precio_unit * (Decimal('1') - descuento / Decimal('100'))
            
            total_linea = cantidad * precio_final
            base_imponible += total_linea
        
        # IVA según cliente (por defecto 21 %)
        tipo_iva = Decimal('21')
        if solicitud.cliente and getattr(solicitud.cliente, 'tipo_iva', None) is not None:
            try:
                tipo_iva = Decimal(str(solicitud.cliente.tipo_iva))
            except (ValueError, TypeError):
                pass
        iva_total = base_imponible * tipo_iva / Decimal('100')
        total_con_iva = base_imponible + iva_total
        
        solicitudes_con_base.append({
            'solicitud': solicitud,
            'base_imponible': base_imponible,
            'iva_total': iva_total,
            'total_con_iva': total_con_iva
        })
    
    # Ordenar por base imponible, IVA o total si es necesario (después de calcular)
    if sort_by == 'base_imponible':
        solicitudes_con_base.sort(key=lambda x: x['base_imponible'], reverse=(sort_order == 'desc'))
    elif sort_by == 'iva_total':
        solicitudes_con_base.sort(key=lambda x: x['iva_total'], reverse=(sort_order == 'desc'))
    elif sort_by == 'total_con_iva':
        solicitudes_con_base.sort(key=lambda x: x['total_con_iva'], reverse=(sort_order == 'desc'))
    
    # Obtener datos para filtros
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    cliente_seleccionado = Cliente.query.get(cliente_id) if cliente_id else None
    # Comercial.nombre es una propiedad, necesitamos ordenar por Usuario.usuario
    comerciales = Comercial.query.join(Usuario).order_by(Usuario.usuario).all()
    
    return render_template('solicitudes/listado.html',
                         solicitudes_con_base=solicitudes_con_base,
                         estados=ESTADOS_SOLICITUD,
                         clientes=clientes,
                         cliente_seleccionado=cliente_seleccionado,
                         comerciales=comerciales,
                         estado_filtro=estado_filtro,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta,
                         cliente_id=cliente_id,
                         comercial_id=comercial_id,
                         sort_by=sort_by,
                         sort_order=sort_order,
                         incluir_rechazados=incluir_rechazados)

@solicitudes_bp.route('/presupuestos/nueva', methods=['GET', 'POST'])
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
            fecha_objetivo_str = request.form.get('fecha_objetivo', '')

            # Nuevo esquema de productos por tarjeta (4 tipos)
            productos = _extraer_productos_form(request.form)
            errores_productos = _validar_productos(productos, request.files)

            # Legacy: compatibilidad mínima con modelo (campos no anulables)
            tipo_producto = 'N/A'
            colores_principales = ''
            colores_secundarios = ''
            ubicacion_logo = ''

            # Validaciones básicas
            if not comercial_id or not cliente_id or not tipo_pedido:
                flash('Debe completar todos los campos obligatorios', 'error')
                # Renderizar template con datos preservados en lugar de redirect
                clientes = Cliente.query.order_by(Cliente.nombre).all()
                comerciales = Comercial.query.join(Usuario).order_by(Usuario.usuario).all()
                prendas = Prenda.query.order_by(Prenda.nombre).all()
                categorias = CategoriaCliente.query.filter_by(activo=True).order_by(CategoriaCliente.nombre).all()
                return render_template('solicitudes/nueva.html',
                                     clientes=clientes,
                                     comerciales=comerciales,
                                     prendas=prendas,
                                     categorias=categorias,
                                     form_data=request.form)  # Pasar datos del formulario

            if errores_productos:
                flash(' | '.join(errores_productos[:6]), 'error')
                clientes = Cliente.query.order_by(Cliente.nombre).all()
                comerciales = Comercial.query.join(Usuario).order_by(Usuario.usuario).all()
                prendas = Prenda.query.order_by(Prenda.nombre).all()
                categorias = CategoriaCliente.query.filter_by(activo=True).order_by(CategoriaCliente.nombre).all()
                return render_template('solicitudes/nueva.html',
                                     clientes=clientes,
                                     comerciales=comerciales,
                                     prendas=prendas,
                                     categorias=categorias,
                                     form_data=request.form)

            referencias_web = '[]'
            datos_adicionales = referencias_web
            comentarios_cliente = request.form.get('comentarios_cliente', '')
            seguimiento = request.form.get('seguimiento', '')

            
            # Crear solicitud (presupuesto)
            solicitud = Presupuesto(
                comercial_id=comercial_id,
                cliente_id=cliente_id,
                tipo_pedido=tipo_pedido,
                forma_pago=forma_pago,
                seguimiento=seguimiento,
                comentarios_cliente=comentarios_cliente,
                tipo_producto=tipo_producto,
                colores_principales=colores_principales,
                colores_secundarios=colores_secundarios,
                ubicacion_logo=ubicacion_logo,
                referencias_web=referencias_web,
                datos_adicionales=datos_adicionales,
                estado='presupuesto'  # Estado inicial
            )
            
            # Establecer fecha_presupuesto si no existe
            if not solicitud.fecha_presupuesto:
                solicitud.fecha_presupuesto = datetime.now().date()
            
            # Generar número de solicitud automáticamente
            fecha_creacion = solicitud.fecha_presupuesto or datetime.now().date()
            solicitud.numero_solicitud = obtener_siguiente_numero_solicitud(fecha_creacion)
            
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
            prenda_nombres = request.form.getlist('prenda_nombre[]')  # Texto libre del modelo
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
            
            # Usar la longitud del array más largo para iterar
            max_len = max(len(prenda_ids), len(nombres_mostrar), len(cantidades))
            
            print(f"DEBUG: Procesando líneas - prenda_ids: {len(prenda_ids)}, nombres_mostrar: {len(nombres_mostrar)}, max_len: {max_len}")
            
            for i in range(max_len):
                # Verificar si hay datos para crear la línea
                prenda_id_val = prenda_ids[i] if i < len(prenda_ids) and prenda_ids[i] else None
                prenda_nombre_val = prenda_nombres[i] if i < len(prenda_nombres) and prenda_nombres[i] else ''
                nombre_mostrar_val = nombres_mostrar[i] if i < len(nombres_mostrar) and nombres_mostrar[i] else ''
                nombre_val = nombres[i] if i < len(nombres) and nombres[i] else ''
                
                print(f"DEBUG: Línea {i} - prenda_id: {prenda_id_val}, prenda_nombre: '{prenda_nombre_val}', nombre_mostrar: '{nombre_mostrar_val}', nombre: '{nombre_val}'")
                
                # Crear línea si tiene nombre_mostrar (prenda_id puede ser None para texto libre)
                if nombre_mostrar_val or nombre_val:
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
                    
                    # Convertir prenda_id a int si existe, sino None (texto libre)
                    prenda_id_final = None
                    prenda_nombre_texto_final = None
                    if prenda_id_val:
                        try:
                            prenda_id_final = int(prenda_id_val)
                        except (ValueError, TypeError):
                            prenda_id_final = None
                    
                    # Si no hay prenda_id pero hay texto libre, guardar el texto
                    if not prenda_id_final and prenda_nombre_val and prenda_nombre_val.strip():
                        prenda_nombre_texto_final = prenda_nombre_val.strip()
                    
                    linea = LineaPresupuesto(
                        presupuesto_id=solicitud.id,
                        prenda_id=prenda_id_final,  # Puede ser None para texto libre
                        prenda_nombre_texto=prenda_nombre_texto_final,  # Texto libre del modelo
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
                    print(f"DEBUG: Línea {i} añadida - nombre_mostrar: '{nombre_mostrar_val}', prenda_id: {prenda_id_final}")
            
            print(f"DEBUG: Total líneas procesadas: {len([l for l in db.session.new if isinstance(l, LineaPresupuesto)])}")
            
            # Guardar fotos por producto dentro del JSON de productos
            for p in productos:
                n = p.get('numero')
                if not n:
                    continue
                fotos_paths = []
                for foto in request.files.getlist(f'prenda{n}_fotos[]'):
                    if not foto or not foto.filename:
                        continue
                    filename = secure_filename(foto.filename)
                    nombre_archivo = f"{solicitud.id}_producto_{n}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{filename}"
                    ruta_relativa = _subir_imagen_solicitud(foto, nombre_archivo)
                    fotos_paths.append(ruta_relativa)
                p['fotos'] = fotos_paths

            referencias_web = json.dumps(productos, ensure_ascii=False)
            datos_adicionales = referencias_web
            solicitud.referencias_web = referencias_web
            solicitud.datos_adicionales = datos_adicionales
            
            # Procesar imagen de diseño
            if 'imagen_diseno' in request.files:
                file = request.files['imagen_diseno']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    nombre_archivo = f"{solicitud.id}_diseno_{filename}"
                    ruta_relativa = _subir_imagen_solicitud(file, nombre_archivo)
                    solicitud.imagen_diseno = ruta_relativa
            
            # Procesar imagen de portada
            if 'imagen_portada' in request.files:
                file = request.files['imagen_portada']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    nombre_archivo = f"{solicitud.id}_portada_{filename}"
                    ruta_relativa = _subir_imagen_solicitud(file, nombre_archivo)
                    solicitud.imagen_portada = ruta_relativa
            
            # Procesar imagen de mockup (PDF)
            if 'imagen_mockup' in request.files:
                file = request.files['imagen_mockup']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    nombre_archivo = f"{solicitud.id}_mockup_{filename}"
                    ruta_relativa = _subir_imagen_solicitud(file, nombre_archivo)
                    solicitud.imagen_mockup = ruta_relativa
            
            # Procesar imágenes adicionales
            for i in range(1, 6):
                imagen_key = f'imagen_adicional_{i}'
                descripcion_key = f'descripcion_imagen_{i}'
                
                if imagen_key in request.files:
                    file = request.files[imagen_key]
                    if file and file.filename:
                        filename = secure_filename(file.filename)
                        nombre_archivo = f"{solicitud.id}_adicional_{i}_{filename}"
                        ruta_relativa = _subir_imagen_solicitud(file, nombre_archivo)
                        setattr(solicitud, imagen_key, ruta_relativa)
                        setattr(solicitud, descripcion_key, request.form.get(descripcion_key, ''))
            
            db.session.commit()
            
            # Refrescar la solicitud para cargar las líneas
            db.session.refresh(solicitud)
            
            flash('Presupuesto creado correctamente', 'success')
            return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear el presupuesto: {str(e)}', 'error')
            import traceback
            traceback.print_exc()
            # Renderizar template con datos preservados en lugar de redirect
            clientes = Cliente.query.order_by(Cliente.nombre).all()
            comerciales = Comercial.query.join(Usuario).order_by(Usuario.usuario).all()
            prendas = Prenda.query.order_by(Prenda.nombre).all()
            categorias = CategoriaCliente.query.filter_by(activo=True).order_by(CategoriaCliente.nombre).all()
            return render_template('solicitudes/nueva.html',
                                 clientes=clientes,
                                 comerciales=comerciales,
                                 prendas=prendas,
                                 categorias=categorias,
                                 form_data=request.form)  # Pasar datos del formulario
    
    # GET: mostrar formulario
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    comerciales = Comercial.query.join(Usuario).order_by(Usuario.usuario).all()
    prendas = Prenda.query.order_by(Prenda.nombre).all()
    categorias = CategoriaCliente.query.filter_by(activo=True).order_by(CategoriaCliente.nombre).all()
    
    return render_template('solicitudes/nueva.html',
                         clientes=clientes,
                         comerciales=comerciales,
                         prendas=prendas,
                         categorias=categorias,
                         form_data=None)

@solicitudes_bp.route('/presupuestos/<int:solicitud_id>')
@login_required
def ver_solicitud(solicitud_id):
    """Ver detalles de una solicitud"""
    from sqlalchemy.orm import joinedload
    solicitud = Presupuesto.query.options(
        joinedload(Presupuesto.lineas).joinedload(LineaPresupuesto.prenda),
        joinedload(Presupuesto.cliente),
        joinedload(Presupuesto.comercial),
        joinedload(Presupuesto.mockup_encargado_a),
        joinedload(Presupuesto.marcada_encargado_a)
    ).get_or_404(solicitud_id)
    
    # Verificar directamente en la base de datos si no hay líneas en la relación
    if not solicitud.lineas:
        lineas_directas = LineaPresupuesto.query.filter_by(presupuesto_id=solicitud_id).all()
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
    
    # Parsear productos desde el nuevo esquema (JSON) o fallback legacy
    import re
    prendas_info = _obtener_productos_solicitud(solicitud)
    
    if not prendas_info and solicitud.tipo_producto:
        tipo_producto_texto = solicitud.tipo_producto
        
        # Detectar formato: si tiene " || " es el formato nuevo, si tiene " | " y contiene "Prenda" es el antiguo
        if ' || ' in tipo_producto_texto:
            # Formato nuevo: usar " || " como separador
            partes = tipo_producto_texto.split(' || ')
        elif ' | ' in tipo_producto_texto and 'Prenda' in tipo_producto_texto:
            # Formato antiguo: usar " | " como separador
            partes = tipo_producto_texto.split(' | ')
        else:
            # Solo una prenda, sin separadores
            partes = [tipo_producto_texto]
        
        # Primera parte es la primera prenda (sin prefijo "Prenda 1:")
        primera_prenda = partes[0].strip()
        
        # Agregar primera prenda con todos sus datos
        prendas_info.append({
            'numero': 1,
            'tipo_producto': primera_prenda,
            'colores_principales': solicitud.colores_principales or '',
            'colores_secundarios': solicitud.colores_secundarios or '',
            'ubicacion_logo': solicitud.ubicacion_logo or ''
        })
        
        # Procesar prendas adicionales (si existen)
        for parte in partes[1:]:
            parte = parte.strip()
            if not parte:
                continue
                
            # Intentar formato nuevo primero: "Prenda X: Tipo | ColPrinc: ... | ColSec: ... | Logo: ..."
            match_nuevo = re.match(r'Prenda\s+(\d+):\s*(.+?)(?:\s*\|\s*ColPrinc:\s*(.+?))?(?:\s*\|\s*ColSec:\s*(.+?))?(?:\s*\|\s*Logo:\s*(.+?))?$', parte)
            if match_nuevo:
                numero_prenda = int(match_nuevo.group(1))
                tipo_prenda = match_nuevo.group(2).strip()
                tipo_prenda = tipo_prenda.rstrip(' |')
                colores_principales_prenda = match_nuevo.group(3).strip() if match_nuevo.group(3) else ''
                colores_secundarios_prenda = match_nuevo.group(4).strip() if match_nuevo.group(4) else ''
                ubicacion_logo_prenda = match_nuevo.group(5).strip() if match_nuevo.group(5) else ''
                
                prendas_info.append({
                    'numero': numero_prenda,
                    'tipo_producto': tipo_prenda,
                    'colores_principales': colores_principales_prenda,
                    'colores_secundarios': colores_secundarios_prenda,
                    'ubicacion_logo': ubicacion_logo_prenda
                })
            else:
                # Intentar parsear manualmente si el regex no funciona
                if parte.startswith('Prenda') and ':' in parte:
                    try:
                        num_match = re.match(r'Prenda\s+(\d+):', parte)
                        if num_match:
                            numero_prenda = int(num_match.group(1))
                            resto = parte[num_match.end():].strip()
                            
                            tipo_prenda = ''
                            colores_principales_prenda = ''
                            colores_secundarios_prenda = ''
                            ubicacion_logo_prenda = ''
                            
                            campos = resto.split(' | ')
                            tipo_prenda = campos[0].strip() if campos else ''
                            
                            for campo in campos[1:]:
                                campo = campo.strip()
                                if campo.startswith('ColPrinc:'):
                                    colores_principales_prenda = campo.replace('ColPrinc:', '').strip()
                                elif campo.startswith('ColSec:'):
                                    colores_secundarios_prenda = campo.replace('ColSec:', '').strip()
                                elif campo.startswith('Logo:'):
                                    ubicacion_logo_prenda = campo.replace('Logo:', '').strip()
                            
                            prendas_info.append({
                                'numero': numero_prenda,
                                'tipo_producto': tipo_prenda,
                                'colores_principales': colores_principales_prenda,
                                'colores_secundarios': colores_secundarios_prenda,
                                'ubicacion_logo': ubicacion_logo_prenda
                            })
                        else:
                            raise ValueError("No se pudo parsear")
                    except:
                        # Formato antiguo: "Prenda X: Tipo - Colores" (compatibilidad)
                        match_antiguo = re.match(r'Prenda\s+(\d+):\s*(.+?)\s*-\s*(.+)', parte)
                        if match_antiguo:
                            numero_prenda = int(match_antiguo.group(1))
                            tipo_prenda = match_antiguo.group(2).strip()
                            colores_prenda = match_antiguo.group(3).strip()
                            
                            prendas_info.append({
                                'numero': numero_prenda,
                                'tipo_producto': tipo_prenda,
                                'colores_principales': colores_prenda,
                                'colores_secundarios': '',
                                'ubicacion_logo': ''
                            })
                else:
                    # Formato antiguo: "Prenda X: Tipo - Colores" (compatibilidad)
                    match_antiguo = re.match(r'Prenda\s+(\d+):\s*(.+?)\s*-\s*(.+)', parte)
                    if match_antiguo:
                        numero_prenda = int(match_antiguo.group(1))
                        tipo_prenda = match_antiguo.group(2).strip()
                        colores_prenda = match_antiguo.group(3).strip()
                        
                        prendas_info.append({
                            'numero': numero_prenda,
                            'tipo_producto': tipo_prenda,
                            'colores_principales': colores_prenda,
                            'colores_secundarios': '',
                            'ubicacion_logo': ''
                        })
    
    # Si no hay prendas extraídas, usar solo la primera
    if not prendas_info:
        prendas_info.append({
            'numero': 1,
            'tipo_producto': solicitud.tipo_producto or '',
            'colores_principales': solicitud.colores_principales or '',
            'colores_secundarios': solicitud.colores_secundarios or '',
            'ubicacion_logo': solicitud.ubicacion_logo or ''
        })
    
    hoy = datetime.now().date()
    
    historial_respuestas = list(reversed(_parse_historial_respuestas_cliente(solicitud)))
    notif_respuesta_cliente_pendiente = _notif_respuesta_cliente_pendiente(solicitud)

    return render_template('solicitudes/ver.html',
                         solicitud=solicitud,
                         estados=ESTADOS_SOLICITUD,
                         subestados=SUBESTADOS,
                         estados_fechas=ESTADOS_FECHAS,
                         registros_estado=registros_estado,
                         usuarios=usuarios,
                         hoy=hoy,
                         prendas_info=prendas_info,
                         historial_respuestas=historial_respuestas,
                         notif_respuesta_cliente_pendiente=notif_respuesta_cliente_pendiente)


@solicitudes_bp.route('/presupuestos/<int:solicitud_id>/marcar-respuesta-cliente-vista', methods=['POST'])
@login_required
def marcar_respuesta_cliente_vista(solicitud_id):
    """Marca la notificación de respuesta del cliente como vista (quita el aviso del menú)."""
    from flask_login import current_user
    if isinstance(current_user, Cliente):
        flash('No tienes permiso para esta acción.', 'error')
        return redirect(url_for('index.index'))
    solicitud = Presupuesto.query.get_or_404(solicitud_id)
    solicitud.respuesta_cliente_notif_vista_at = datetime.utcnow()
    try:
        db.session.commit()
        flash('Marcado como visto. La notificación dejará de mostrarse en el menú.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'No se pudo guardar: {e}', 'error')
    return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id) + '#modificaciones-cliente')


@solicitudes_bp.route('/presupuestos/<int:solicitud_id>/enviar-cliente', methods=['POST'])
@login_required
def enviar_presupuesto_a_cliente(solicitud_id):
    """Genera enlace seguro para cliente y envía por WhatsApp o Email."""
    from flask_login import current_user
    solicitud = Presupuesto.query.options(joinedload(Presupuesto.cliente)).get_or_404(solicitud_id)
    canal = (request.form.get('canal', '') or '').strip().lower()
    destino_tipo = (request.form.get('destino_tipo', '') or '').strip().lower()
    destino_manual = (request.form.get('destino_manual', '') or '').strip()

    if canal not in ('whatsapp', 'email'):
        return jsonify({'ok': False, 'error': 'Canal no válido'}), 400
    if destino_tipo not in ('ficha', 'manual'):
        return jsonify({'ok': False, 'error': 'Destino no válido'}), 400

    cliente = solicitud.cliente
    destino = destino_manual
    if destino_tipo == 'ficha':
        if canal == 'whatsapp':
            destino = (cliente.movil or cliente.telefono or '').strip() if cliente else ''
        else:
            destino = (cliente.email_comunicaciones or cliente.email_general or cliente.email or '').strip() if cliente else ''

    if not destino:
        return jsonify({'ok': False, 'error': 'No hay destinatario disponible'}), 400

    _generar_token_cliente(solicitud)
    enlace = _url_publica_cliente(solicitud)
    solicitud.cliente_enviado_at = datetime.utcnow()
    solicitud.cliente_respondido_at = None
    solicitud.cliente_respuesta = None
    solicitud.modificaciones_cliente = None
    solicitud.estado = 'mockup'
    solicitud.subestado = 'REVISIÓN CLIENTE'

    registro = RegistroEstadoSolicitud(
        presupuesto_id=solicitud.id,
        estado='mockup',
        subestado='REVISIÓN CLIENTE',
        usuario_id=current_user.id if hasattr(current_user, 'id') else None
    )
    db.session.add(registro)
    db.session.commit()

    if canal == 'whatsapp':
        texto = (
            f"Hola, te compartimos el Presupuesto {solicitud.numero_solicitud or solicitud.id}. "
            f"Puedes revisarlo y responder aquí: {enlace}"
        )
        telefono = ''.join(ch for ch in destino if ch.isdigit())
        wa_url = f"https://wa.me/{telefono}?text={quote(texto)}"
        return jsonify({'ok': True, 'canal': 'whatsapp', 'redirect_url': wa_url})

    ok_email, msg_email = enviar_email_enlace_presupuesto_cliente(solicitud, destino, enlace)
    if not ok_email:
        return jsonify({'ok': False, 'error': msg_email}), 500
    return jsonify({'ok': True, 'canal': 'email', 'mensaje': 'Email enviado correctamente'})


@solicitudes_bp.route('/cliente/presupuesto/<token>', methods=['GET'])
def ver_presupuesto_publico_cliente(token):
    """Vista pública de presupuesto para cliente por token."""
    solicitud = Presupuesto.query.options(
        joinedload(Presupuesto.lineas).joinedload(LineaPresupuesto.prenda),
        joinedload(Presupuesto.cliente),
        joinedload(Presupuesto.comercial)
    ).filter_by(cliente_token=token).first_or_404()

    if not _token_cliente_valido(solicitud, token):
        return render_template(
            'cliente/presupuesto_publico.html',
            token_expirado=True,
            solicitud=solicitud,
            historial_respuestas=[]
        )

    productos = _obtener_productos_solicitud(solicitud)
    historial_respuestas = list(reversed(_parse_historial_respuestas_cliente(solicitud)))
    return render_template(
        'cliente/presupuesto_publico.html',
        token_expirado=False,
        solicitud=solicitud,
        prendas_info=productos,
        historial_respuestas=historial_respuestas
    )


@solicitudes_bp.route('/cliente/presupuesto/<token>/descargar-pdf', methods=['GET'])
def descargar_pdf_presupuesto_publico_cliente(token):
    """Descarga el PDF del presupuesto desde la vista pública por token."""
    solicitud = Presupuesto.query.filter_by(cliente_token=token).first_or_404()
    if not _token_cliente_valido(solicitud, token):
        flash('El enlace ha expirado. Solicita uno nuevo.', 'error')
        return redirect(url_for('presupuestos.ver_presupuesto_publico_cliente', token=token))

    try:
        # Generar PDF de la vista pública real para que refleje exactamente la pantalla.
        vista_publica_url = url_for('presupuestos.ver_presupuesto_publico_cliente', token=token, _external=True)

        pdf_buffer = BytesIO()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(vista_publica_url, wait_until='networkidle')
                page.emulate_media(media='screen')
                page.wait_for_timeout(300)
                pdf_bytes = page.pdf(
                    format='A4',
                    print_background=True,
                    margin={
                        'top': '6mm',
                        'right': '6mm',
                        'bottom': '6mm',
                        'left': '6mm'
                    }
                )
                browser.close()

            pdf_buffer.write(pdf_bytes)
        except Exception as pdf_error:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Error al crear PDF público con playwright: {error_trace}")
            flash(f'Error al generar PDF: {str(pdf_error)}', 'error')
            return redirect(url_for('presupuestos.ver_presupuesto_publico_cliente', token=token))

        pdf_buffer.seek(0)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=presupuesto_{solicitud.numero_solicitud or solicitud.id}.pdf'
        return response

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error completo al generar PDF público: {error_trace}")
        flash(f'Error al generar PDF: {str(e)}', 'error')
        return redirect(url_for('presupuestos.ver_presupuesto_publico_cliente', token=token))


@solicitudes_bp.route('/cliente/presupuesto/<token>/responder', methods=['POST'])
def responder_presupuesto_publico_cliente(token):
    """Captura respuesta del cliente y actualiza subestado."""
    solicitud = Presupuesto.query.options(joinedload(Presupuesto.cliente), joinedload(Presupuesto.comercial)).filter_by(cliente_token=token).first_or_404()
    if not _token_cliente_valido(solicitud, token):
        flash('El enlace ha expirado. Solicita uno nuevo.', 'error')
        return redirect(url_for('presupuestos.ver_presupuesto_publico_cliente', token=token))

    accion = (request.form.get('accion', '') or '').strip().lower()
    comentario = (request.form.get('comentario', '') or '').strip()
    mapping = {
        'aceptar': ('aceptado', 'aceptado'),
        'cambios_1': ('CAMBIOS 1', 'CAMBIOS 1'),
        'cambios_2': ('CAMBIOS 2', 'CAMBIOS 2'),
        'rechazar': ('RECHAZADO', 'RECHAZADO')
    }
    if accion not in mapping:
        flash('Acción no válida.', 'error')
        return redirect(url_for('presupuestos.ver_presupuesto_publico_cliente', token=token))

    cliente_respuesta, subestado = mapping[accion]
    solicitud.estado = 'mockup'
    solicitud.subestado = subestado
    solicitud.cliente_respuesta = cliente_respuesta
    solicitud.modificaciones_cliente = comentario
    solicitud.cliente_respondido_at = datetime.utcnow()
    _append_historial_respuesta_cliente(solicitud, accion, subestado, cliente_respuesta, comentario)

    registro = RegistroEstadoSolicitud(
        presupuesto_id=solicitud.id,
        estado='mockup',
        subestado=subestado,
        usuario_id=None
    )
    db.session.add(registro)
    db.session.commit()

    enviar_email_notificacion_respuesta_cliente(solicitud, comentario)
    flash('Tu respuesta se ha enviado correctamente.', 'success')
    return redirect(url_for('presupuestos.ver_presupuesto_publico_cliente', token=token))

@solicitudes_bp.route('/presupuestos/<int:solicitud_id>/cambiar-estado', methods=['POST'])
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
        return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))
    
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
                                return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))
                        else:
                            flash('Debe seleccionar un usuario para encargar el mockup', 'error')
                            return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))
                    
                    # Si el subestado es "hacer marcada", asignar el usuario
                    if nuevo_subestado == 'hacer marcada':
                        usuario_encargado_id = request.form.get('usuario_encargado', '')
                        if usuario_encargado_id:
                            try:
                                solicitud.marcada_encargado_a_id = int(usuario_encargado_id)
                            except (ValueError, TypeError):
                                flash('Usuario no válido', 'error')
                                return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))
                        else:
                            flash('Debe seleccionar un usuario para encargar hacer marcada', 'error')
                            return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))
                    
                    # Si el mockup se acepta, calcular las fechas objetivo (25 y 17 días hábiles)
                    if nuevo_estado == 'mockup' and nuevo_subestado == 'aceptado':
                        if not solicitud.fecha_aceptado:
                            solicitud.fecha_aceptado = hoy
                            solicitud.fecha_aceptacion = hoy  # Compatibilidad
                        # Calcular ambas fechas objetivo saltando días festivos
                        from utils.fechas import calcular_fecha_saltando_festivos
                        if not solicitud.fecha_objetivo_25:
                            solicitud.fecha_objetivo_25 = calcular_fecha_saltando_festivos(hoy, 25)
                        if not solicitud.fecha_objetivo_17:
                            solicitud.fecha_objetivo_17 = calcular_fecha_saltando_festivos(hoy, 17)
        
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
        
        # Si se acepta la solicitud (estado aceptado), establecer fecha de aceptación
        # NOTA: Las fechas objetivo (25 y 17 días) se calculan cuando se acepta el mockup, no aquí
        if nuevo_estado == 'aceptado' and estado_anterior != 'aceptado':
            if not solicitud.fecha_aceptado:
                solicitud.fecha_aceptado = hoy
                solicitud.fecha_aceptacion = hoy  # Compatibilidad
        
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
    
    return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))

@solicitudes_bp.route('/presupuestos/<int:solicitud_id>/editar', methods=['GET', 'POST'])
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
            # Nuevo esquema de productos por tarjeta (4 tipos)
            productos = _extraer_productos_form(request.form)
            errores_productos = _validar_productos(productos, request.files)

            if errores_productos:
                flash(' | '.join(errores_productos[:6]), 'error')
                clientes = Cliente.query.order_by(Cliente.nombre).all()
                comerciales = Comercial.query.join(Usuario).order_by(Usuario.usuario).all()
                prendas = Prenda.query.order_by(Prenda.nombre).all()
                categorias = CategoriaCliente.query.filter_by(activo=True).order_by(CategoriaCliente.nombre).all()
                return render_template('solicitudes/editar.html',
                                     solicitud=solicitud,
                                     clientes=clientes,
                                     comerciales=comerciales,
                                     prendas=prendas,
                                     categorias=categorias,
                                     form_data=request.form)

            # Conservar fotos previas si no se suben nuevas en edición
            productos_previos = _obtener_productos_solicitud(solicitud)
            previos_por_num = {p.get('numero'): p for p in productos_previos if isinstance(p, dict)}
            for p in productos:
                n = p.get('numero')
                if not n:
                    p['fotos'] = []
                    continue
                nuevas_fotos = []
                for foto in request.files.getlist(f'prenda{n}_fotos[]'):
                    if not foto or not foto.filename:
                        continue
                    filename = secure_filename(foto.filename)
                    nombre_archivo = f"{solicitud.id}_producto_{n}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{filename}"
                    ruta_relativa = _subir_imagen_solicitud(foto, nombre_archivo)
                    nuevas_fotos.append(ruta_relativa)
                if nuevas_fotos:
                    p['fotos'] = nuevas_fotos
                else:
                    previo = previos_por_num.get(n, {})
                    p['fotos'] = previo.get('fotos', []) if isinstance(previo.get('fotos', []), list) else []

            referencias_web = json.dumps(productos, ensure_ascii=False)
            datos_adicionales = referencias_web
            solicitud.seguimiento = request.form.get('seguimiento', '')
            solicitud.comentarios_cliente = request.form.get('comentarios_cliente', '')

            # Legacy: compatibilidad mínima con modelo (campos no anulables)
            tipo_producto = 'N/A'
            colores_principales = ''
            colores_secundarios = ''
            ubicacion_logo = ''
            
            solicitud.tipo_producto = tipo_producto
            solicitud.colores_principales = colores_principales
            solicitud.colores_secundarios = colores_secundarios
            solicitud.ubicacion_logo = ubicacion_logo
            solicitud.referencias_web = referencias_web
            solicitud.datos_adicionales = datos_adicionales
            
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
                        
                        ruta_relativa = _subir_imagen_solicitud(file, nombre_archivo)
                        setattr(solicitud, campo_db, ruta_relativa)
            
            # Manejar actualización de imágenes
            actualizar_imagen('imagen_diseno', 'imagen_diseno')
            actualizar_imagen('imagen_mockup', 'imagen_mockup')
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
                # Renderizar template con datos preservados en lugar de redirect
                clientes = Cliente.query.order_by(Cliente.nombre).all()
                comerciales = Comercial.query.join(Usuario).order_by(Usuario.usuario).all()
                prendas = Prenda.query.order_by(Prenda.nombre).all()
                categorias = CategoriaCliente.query.filter_by(activo=True).order_by(CategoriaCliente.nombre).all()
                return render_template('solicitudes/editar.html',
                                     solicitud=solicitud,
                                     clientes=clientes,
                                     comerciales=comerciales,
                                     prendas=prendas,
                                     categorias=categorias,
                                     form_data=request.form)  # Pasar datos del formulario
            
            # Crear nuevas líneas (similar a editar_solicitud)
            prenda_ids = request.form.getlist('prenda_id[]')
            prenda_nombres = request.form.getlist('prenda_nombre[]')  # Texto libre del modelo
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
            
            max_len = max(len(prenda_ids), len(nombres_mostrar), len(cantidades))
            
            for i in range(max_len):
                # Procesar prenda_id: convertir cadenas vacías a None y valores válidos a entero
                prenda_id_raw = prenda_ids[i] if i < len(prenda_ids) else ''
                if prenda_id_raw and prenda_id_raw.strip():
                    try:
                        prenda_id_val = int(prenda_id_raw)
                    except (ValueError, TypeError):
                        prenda_id_val = None
                else:
                    prenda_id_val = None
                
                # Procesar prenda_nombre_texto: guardar texto libre cuando no hay prenda_id
                prenda_nombre_val = prenda_nombres[i] if i < len(prenda_nombres) and prenda_nombres[i] else ''
                prenda_nombre_texto_final = None
                if not prenda_id_val and prenda_nombre_val and prenda_nombre_val.strip():
                    prenda_nombre_texto_final = prenda_nombre_val.strip()
                
                nombre_mostrar_val = nombres_mostrar[i] if i < len(nombres_mostrar) and nombres_mostrar[i] else ''
                nombre_val = nombres[i] if i < len(nombres) and nombres[i] else ''
                
                if nombre_mostrar_val or nombre_val:
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
                        prenda_id=prenda_id_val,
                        prenda_nombre_texto=prenda_nombre_texto_final,  # Texto libre del modelo
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
            flash('Presupuesto actualizado correctamente', 'success')
            return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar el presupuesto: {str(e)}', 'error')
            import traceback
            traceback.print_exc()
            # Renderizar template con datos preservados en lugar de redirect
            clientes = Cliente.query.order_by(Cliente.nombre).all()
            comerciales = Comercial.query.join(Usuario).order_by(Usuario.usuario).all()
            prendas = Prenda.query.order_by(Prenda.nombre).all()
            categorias = CategoriaCliente.query.filter_by(activo=True).order_by(CategoriaCliente.nombre).all()
            return render_template('solicitudes/editar.html',
                                 solicitud=solicitud,
                                 clientes=clientes,
                                 comerciales=comerciales,
                                 prendas=prendas,
                                 categorias=categorias,
                                 form_data=request.form)  # Pasar datos del formulario
    
    # GET: mostrar formulario
    # Parsear productos desde el nuevo esquema para mostrarlos en el formulario
    import re
    prendas_info = _obtener_productos_solicitud(solicitud)
    
    if not prendas_info and solicitud.tipo_producto:
        tipo_producto_texto = solicitud.tipo_producto
        
        # Detectar formato: si tiene " || " es el formato nuevo, si tiene " | " y contiene "Prenda" es el antiguo
        if ' || ' in tipo_producto_texto:
            # Formato nuevo: usar " || " como separador
            partes = tipo_producto_texto.split(' || ')
        elif ' | ' in tipo_producto_texto and 'Prenda' in tipo_producto_texto:
            # Formato antiguo: usar " | " como separador
            partes = tipo_producto_texto.split(' | ')
        else:
            # Solo una prenda, sin separadores
            partes = [tipo_producto_texto]
        
        # Primera parte es la primera prenda (sin prefijo "Prenda 1:")
        primera_prenda = partes[0].strip()
        
        # Agregar primera prenda con todos sus datos
        prendas_info.append({
            'numero': 1,
            'tipo_producto': primera_prenda,
            'colores_principales': solicitud.colores_principales or '',
            'colores_secundarios': solicitud.colores_secundarios or '',
            'ubicacion_logo': solicitud.ubicacion_logo or ''
        })
        
        # Procesar prendas adicionales (si existen)
        for parte in partes[1:]:
            parte = parte.strip()
            if not parte:
                continue
                
            # Intentar formato nuevo primero: "Prenda X: Tipo | ColPrinc: ... | ColSec: ... | Logo: ..."
            match_nuevo = re.match(r'Prenda\s+(\d+):\s*(.+?)(?:\s*\|\s*ColPrinc:\s*(.+?))?(?:\s*\|\s*ColSec:\s*(.+?))?(?:\s*\|\s*Logo:\s*(.+?))?$', parte)
            if match_nuevo:
                numero_prenda = int(match_nuevo.group(1))
                tipo_prenda = match_nuevo.group(2).strip()
                tipo_prenda = tipo_prenda.rstrip(' |')
                colores_principales_prenda = match_nuevo.group(3).strip() if match_nuevo.group(3) else ''
                colores_secundarios_prenda = match_nuevo.group(4).strip() if match_nuevo.group(4) else ''
                ubicacion_logo_prenda = match_nuevo.group(5).strip() if match_nuevo.group(5) else ''
                
                prendas_info.append({
                    'numero': numero_prenda,
                    'tipo_producto': tipo_prenda,
                    'colores_principales': colores_principales_prenda,
                    'colores_secundarios': colores_secundarios_prenda,
                    'ubicacion_logo': ubicacion_logo_prenda
                })
            else:
                # Intentar parsear manualmente si el regex no funciona
                if parte.startswith('Prenda') and ':' in parte:
                    try:
                        num_match = re.match(r'Prenda\s+(\d+):', parte)
                        if num_match:
                            numero_prenda = int(num_match.group(1))
                            resto = parte[num_match.end():].strip()
                            
                            tipo_prenda = ''
                            colores_principales_prenda = ''
                            colores_secundarios_prenda = ''
                            ubicacion_logo_prenda = ''
                            
                            campos = resto.split(' | ')
                            tipo_prenda = campos[0].strip() if campos else ''
                            
                            for campo in campos[1:]:
                                campo = campo.strip()
                                if campo.startswith('ColPrinc:'):
                                    colores_principales_prenda = campo.replace('ColPrinc:', '').strip()
                                elif campo.startswith('ColSec:'):
                                    colores_secundarios_prenda = campo.replace('ColSec:', '').strip()
                                elif campo.startswith('Logo:'):
                                    ubicacion_logo_prenda = campo.replace('Logo:', '').strip()
                            
                            prendas_info.append({
                                'numero': numero_prenda,
                                'tipo_producto': tipo_prenda,
                                'colores_principales': colores_principales_prenda,
                                'colores_secundarios': colores_secundarios_prenda,
                                'ubicacion_logo': ubicacion_logo_prenda
                            })
                        else:
                            raise ValueError("No se pudo parsear")
                    except:
                        # Formato antiguo: "Prenda X: Tipo - Colores" (compatibilidad)
                        match_antiguo = re.match(r'Prenda\s+(\d+):\s*(.+?)\s*-\s*(.+)', parte)
                        if match_antiguo:
                            numero_prenda = int(match_antiguo.group(1))
                            tipo_prenda = match_antiguo.group(2).strip()
                            colores_prenda = match_antiguo.group(3).strip()
                            
                            prendas_info.append({
                                'numero': numero_prenda,
                                'tipo_producto': tipo_prenda,
                                'colores_principales': colores_prenda,
                                'colores_secundarios': '',
                                'ubicacion_logo': ''
                            })
                else:
                    # Formato antiguo: "Prenda X: Tipo - Colores" (compatibilidad)
                    match_antiguo = re.match(r'Prenda\s+(\d+):\s*(.+?)\s*-\s*(.+)', parte)
                    if match_antiguo:
                        numero_prenda = int(match_antiguo.group(1))
                        tipo_prenda = match_antiguo.group(2).strip()
                        colores_prenda = match_antiguo.group(3).strip()
                        
                        prendas_info.append({
                            'numero': numero_prenda,
                            'tipo_producto': tipo_prenda,
                            'colores_principales': colores_prenda,
                            'colores_secundarios': '',
                            'ubicacion_logo': ''
                        })
    
    # Si no hay prendas extraídas, usar solo la primera
    if not prendas_info:
        prendas_info.append({
            'numero': 1,
            'tipo_producto': solicitud.tipo_producto or '',
            'colores_principales': solicitud.colores_principales or '',
            'colores_secundarios': solicitud.colores_secundarios or '',
            'ubicacion_logo': solicitud.ubicacion_logo or ''
        })
    
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    comerciales = Comercial.query.join(Usuario).order_by(Usuario.usuario).all()
    prendas = Prenda.query.order_by(Prenda.nombre).all()
    categorias = CategoriaCliente.query.filter_by(activo=True).order_by(CategoriaCliente.nombre).all()
    
    return render_template('solicitudes/editar.html',
                         solicitud=solicitud,
                         clientes=clientes,
                         comerciales=comerciales,
                         prendas=prendas,
                         categorias=categorias,
                         form_data=None,
                         prendas_info=prendas_info)  # Pasar prendas parseadas


@solicitudes_bp.route('/presupuestos/<int:solicitud_id>/eliminar', methods=['POST'])
@login_required
def eliminar_solicitud(solicitud_id):
    """Eliminar una solicitud (presupuesto)"""
    try:
        solicitud = Presupuesto.query.get_or_404(solicitud_id)
        
        # Verificar si hay pedidos relacionados
        pedidos_relacionados = Pedido.query.filter_by(presupuesto_id=solicitud_id).all()
        num_pedidos = len(pedidos_relacionados)
        
        if num_pedidos > 0:
            flash(f'Advertencia: Este presupuesto tiene {num_pedidos} pedido(s) relacionado(s). El presupuesto se eliminará pero los pedidos permanecerán.', 'warning')
        
        # Eliminar registros de estado
        registros_estado = RegistroEstadoSolicitud.query.filter_by(presupuesto_id=solicitud_id).all()
        for registro in registros_estado:
            db.session.delete(registro)
        
        # Las líneas se eliminan automáticamente por cascade='all, delete-orphan'
        
        # Eliminar la solicitud
        db.session.delete(solicitud)
        db.session.commit()
        
        flash('Presupuesto eliminado correctamente.', 'success')
        return redirect(url_for('presupuestos.listado_solicitudes'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar el presupuesto: {str(e)}', 'error')
        import traceback
        traceback.print_exc()
        return redirect(url_for('presupuestos.editar_solicitud', solicitud_id=solicitud_id))


@solicitudes_bp.route('/presupuestos/crear-cliente-ajax', methods=['POST'])
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
        
        categoria_id = request.form.get('categoria_id', '').strip()
        categoria_id = int(categoria_id) if categoria_id else None
        
        # Procesar tipo de IVA
        tipo_iva_str = request.form.get('tipo_iva', '21').strip()
        tipo_iva = float(tipo_iva_str) if tipo_iva_str else 21.0
        
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
            email=request.form.get('email', ''),  # Mantener para compatibilidad
            email_general=request.form.get('email_general', ''),
            email_comunicaciones=request.form.get('email_comunicaciones', ''),
            categoria_id=categoria_id,
            anotaciones=request.form.get('anotaciones', ''),
            numero_cuenta=request.form.get('numero_cuenta', '').strip(),
            usuario_web=request.form.get('usuario_web', '').strip() or None,
            fecha_alta=fecha_alta,
            comercial_id=comercial_id,
            tipo_iva=tipo_iva
        )
        
        password_web = request.form.get('password_web', '').strip()
        if cliente.usuario_web and password_web:
            cliente.set_password(password_web)
        
        db.session.add(cliente)
        db.session.flush()  # Para obtener el ID del cliente
        
        # Procesar direcciones de envío
        direcciones_data = request.form.getlist('direcciones_envio[]')
        if direcciones_data:
            for i, dir_data in enumerate(direcciones_data):
                if dir_data.strip():  # Si hay datos
                    # Obtener los campos de la dirección
                    nombre = request.form.get(f'direcciones_envio_nombre_{i}', f'Dirección envío {i+2}')
                    direccion = request.form.get(f'direcciones_envio_direccion_{i}', '')
                    poblacion = request.form.get(f'direcciones_envio_poblacion_{i}', '')
                    provincia = request.form.get(f'direcciones_envio_provincia_{i}', '')
                    codigo_postal = request.form.get(f'direcciones_envio_codigo_postal_{i}', '')
                    pais = request.form.get(f'direcciones_envio_pais_{i}', 'España')
                    
                    direccion_envio = DireccionEnvio(
                        cliente_id=cliente.id,
                        nombre=nombre,
                        direccion=direccion,
                        poblacion=poblacion,
                        provincia=provincia,
                        codigo_postal=codigo_postal,
                        pais=pais
                    )
                    db.session.add(direccion_envio)
        
        # Procesar personas de contacto
        personas_data = request.form.getlist('personas_contacto[]')
        if personas_data:
            for i, persona_data in enumerate(personas_data):
                if persona_data.strip():  # Si hay datos
                    nombre = request.form.get(f'personas_contacto_nombre_{i}', '').strip()
                    cargo = request.form.get(f'personas_contacto_cargo_{i}', '').strip()
                    movil = request.form.get(f'personas_contacto_movil_{i}', '').strip()
                    email = request.form.get(f'personas_contacto_email_{i}', '').strip()
                    
                    if nombre:  # Solo crear si tiene nombre
                        persona_contacto = PersonaContacto(
                            cliente_id=cliente.id,
                            nombre=nombre,
                            cargo=cargo,
                            movil=movil,
                            email=email
                        )
                        db.session.add(persona_contacto)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'cliente': {
                'id': cliente.id,
                'nombre': cliente.nombre,
                'tipo_iva': float(cliente.tipo_iva) if cliente.tipo_iva else 21.0
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
    from sqlalchemy.orm import joinedload
    import re
    solicitud = Presupuesto.query.options(
        joinedload(Presupuesto.lineas).joinedload(LineaPresupuesto.prenda),
        joinedload(Presupuesto.cliente),
        joinedload(Presupuesto.comercial)
    ).get_or_404(solicitud_id)
    
    # Extraer información de productos (nuevo JSON) con fallback legacy
    # Formato nuevo: "Prenda1 || Prenda 2: Tipo | ColPrinc: ... | ColSec: ... | Logo: ... || Prenda 3: ..."
    # Formato antiguo: "Prenda1 | Prenda 2: Tipo - Colores | Prenda 3: Tipo - Colores"
    prendas_info = _obtener_productos_solicitud(solicitud)
    
    if not prendas_info and solicitud.tipo_producto:
        tipo_producto_texto = solicitud.tipo_producto
        # Debug: mostrar qué se está parseando
        print(f"DEBUG: Parseando tipo_producto: {tipo_producto_texto}")
        
        # Detectar formato: si tiene " || " es el formato nuevo, si tiene " | " y contiene "Prenda" es el antiguo
        if ' || ' in tipo_producto_texto:
            # Formato nuevo: usar " || " como separador
            partes = tipo_producto_texto.split(' || ')
            print(f"DEBUG: Formato nuevo detectado, partes: {partes}")
        elif ' | ' in tipo_producto_texto and 'Prenda' in tipo_producto_texto:
            # Formato antiguo: usar " | " como separador
            partes = tipo_producto_texto.split(' | ')
            print(f"DEBUG: Formato antiguo detectado, partes: {partes}")
        else:
            # Solo una prenda, sin separadores
            partes = [tipo_producto_texto]
            print(f"DEBUG: Solo una prenda detectada")
        
        # Primera parte es la primera prenda (sin prefijo "Prenda 1:")
        primera_prenda = partes[0].strip()
        
        # Agregar primera prenda con todos sus datos
        prendas_info.append({
            'numero': 1,
            'tipo_producto': primera_prenda,
            'colores_principales': solicitud.colores_principales or '',
            'colores_secundarios': solicitud.colores_secundarios or '',
            'ubicacion_logo': solicitud.ubicacion_logo or ''
        })
        
        # Procesar prendas adicionales (si existen)
        for parte in partes[1:]:
            parte = parte.strip()
            if not parte:
                continue
                
            # Intentar formato nuevo primero: "Prenda X: Tipo | ColPrinc: ... | ColSec: ... | Logo: ..."
            # Mejorar el regex para capturar correctamente todos los campos
            match_nuevo = re.match(r'Prenda\s+(\d+):\s*(.+?)(?:\s*\|\s*ColPrinc:\s*(.+?))?(?:\s*\|\s*ColSec:\s*(.+?))?(?:\s*\|\s*Logo:\s*(.+?))?$', parte)
            if match_nuevo:
                numero_prenda = int(match_nuevo.group(1))
                tipo_prenda = match_nuevo.group(2).strip()
                # Limpiar el tipo_prenda por si tiene espacios extra al final
                tipo_prenda = tipo_prenda.rstrip(' |')
                colores_principales_prenda = match_nuevo.group(3).strip() if match_nuevo.group(3) else ''
                colores_secundarios_prenda = match_nuevo.group(4).strip() if match_nuevo.group(4) else ''
                ubicacion_logo_prenda = match_nuevo.group(5).strip() if match_nuevo.group(5) else ''
                
                # Agregar prenda adicional con toda su información
                prendas_info.append({
                    'numero': numero_prenda,
                    'tipo_producto': tipo_prenda,
                    'colores_principales': colores_principales_prenda,
                    'colores_secundarios': colores_secundarios_prenda,
                    'ubicacion_logo': ubicacion_logo_prenda
                })
            else:
                # Intentar parsear manualmente si el regex no funciona
                # Formato: "Prenda X: Tipo | ColPrinc: ... | ColSec: ... | Logo: ..."
                if parte.startswith('Prenda') and ':' in parte:
                    try:
                        # Extraer número de prenda
                        num_match = re.match(r'Prenda\s+(\d+):', parte)
                        if num_match:
                            numero_prenda = int(num_match.group(1))
                            # Extraer el resto después de "Prenda X: "
                            resto = parte[num_match.end():].strip()
                            
                            # Parsear campos individuales
                            tipo_prenda = ''
                            colores_principales_prenda = ''
                            colores_secundarios_prenda = ''
                            ubicacion_logo_prenda = ''
                            
                            # Dividir por " | " y procesar cada parte
                            campos = resto.split(' | ')
                            tipo_prenda = campos[0].strip() if campos else ''
                            
                            for campo in campos[1:]:
                                campo = campo.strip()
                                if campo.startswith('ColPrinc:'):
                                    colores_principales_prenda = campo.replace('ColPrinc:', '').strip()
                                elif campo.startswith('ColSec:'):
                                    colores_secundarios_prenda = campo.replace('ColSec:', '').strip()
                                elif campo.startswith('Logo:'):
                                    ubicacion_logo_prenda = campo.replace('Logo:', '').strip()
                            
                            prendas_info.append({
                                'numero': numero_prenda,
                                'tipo_producto': tipo_prenda,
                                'colores_principales': colores_principales_prenda,
                                'colores_secundarios': colores_secundarios_prenda,
                                'ubicacion_logo': ubicacion_logo_prenda
                            })
                        else:
                            # Si no se puede parsear, intentar formato antiguo
                            raise ValueError("No se pudo parsear")
                    except:
                        # Si falla el parseo manual, intentar formato antiguo
                        # Formato antiguo: "Prenda X: Tipo - Colores" (compatibilidad)
                        match_antiguo = re.match(r'Prenda\s+(\d+):\s*(.+?)\s*-\s*(.+)', parte)
                        if match_antiguo:
                            numero_prenda = int(match_antiguo.group(1))
                            tipo_prenda = match_antiguo.group(2).strip()
                            colores_prenda = match_antiguo.group(3).strip()
                            
                            prendas_info.append({
                                'numero': numero_prenda,
                                'tipo_producto': tipo_prenda,
                                'colores_principales': colores_prenda,
                                'colores_secundarios': '',
                                'ubicacion_logo': ''
                            })
                else:
                    # Formato antiguo: "Prenda X: Tipo - Colores" (compatibilidad)
                    match_antiguo = re.match(r'Prenda\s+(\d+):\s*(.+?)\s*-\s*(.+)', parte)
                    if match_antiguo:
                        numero_prenda = int(match_antiguo.group(1))
                        tipo_prenda = match_antiguo.group(2).strip()
                        colores_prenda = match_antiguo.group(3).strip()
                        
                        prendas_info.append({
                            'numero': numero_prenda,
                            'tipo_producto': tipo_prenda,
                            'colores_principales': colores_prenda,
                            'colores_secundarios': '',
                            'ubicacion_logo': ''
                        })
                # Si no coincide con ningún patrón, podría ser solo el tipo sin "Prenda X:"
                # En este caso, lo ignoramos ya que debería estar en la primera parte
                # (No hay else aquí porque ya manejamos todos los casos posibles arriba)
    
    # Si no hay prendas extraídas, usar solo la primera
    if not prendas_info:
        prendas_info.append({
            'numero': 1,
            'tipo_producto': solicitud.tipo_producto or '',
            'colores_principales': solicitud.colores_principales or '',
            'colores_secundarios': solicitud.colores_secundarios or '',
            'ubicacion_logo': solicitud.ubicacion_logo or ''
        })
    
    # Calcular totales
    # Obtener tipo de IVA del cliente (por defecto 21%)
    tipo_iva = 21.0  # Valor por defecto
    if solicitud.cliente:
        try:
            # Asegurar que el cliente esté cargado completamente
            db.session.refresh(solicitud.cliente)
            cliente_tipo_iva = solicitud.cliente.tipo_iva
            
            # Verificar si el campo existe y tiene valor
            if cliente_tipo_iva is not None:
                # Convertir a float, manejando Decimal y otros tipos numéricos
                if hasattr(cliente_tipo_iva, '__float__'):
                    tipo_iva = float(cliente_tipo_iva)
                else:
                    tipo_iva = float(str(cliente_tipo_iva))
                print(f"DEBUG: Tipo IVA del cliente '{solicitud.cliente.nombre}' (ID: {solicitud.cliente.id}): {tipo_iva}%")
            else:
                print(f"DEBUG: Cliente '{solicitud.cliente.nombre}' (ID: {solicitud.cliente.id}) tiene tipo_iva=None, usando 21% por defecto")
        except Exception as e:
            print(f"DEBUG: Error al obtener tipo_iva del cliente: {e}, usando 21% por defecto")
            import traceback
            traceback.print_exc()
            tipo_iva = 21.0
    else:
        print("DEBUG: Solicitud no tiene cliente asociado, usando 21% por defecto")
    
    base_imponible = Decimal('0.00')
    
    for linea in solicitud.lineas:
        precio_unit = Decimal(str(linea.precio_unitario)) if linea.precio_unitario else Decimal('0.00')
        cantidad = Decimal(str(linea.cantidad))
        descuento = Decimal(str(linea.descuento)) if linea.descuento else Decimal('0')
        
        # Calcular precio final con descuento
        precio_final = precio_unit
        if descuento > 0:
            # Si hay precio_final guardado, usarlo directamente
            if linea.precio_final:
                precio_final = Decimal(str(linea.precio_final))
            else:
                # Calcular precio final aplicando el descuento porcentual
                precio_final = precio_unit * (Decimal('1') - descuento / Decimal('100'))
        
        # Calcular total de la línea usando el precio final (después del descuento)
        total_linea = cantidad * precio_final
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
    
    # Asegurar que tipo_iva sea un número para el template
    tipo_iva_para_template = float(tipo_iva)
    print(f"DEBUG: Tipo IVA que se pasa al template: {tipo_iva_para_template}%")
    
    # Obtener datos de configuración para protección de datos y número de cuenta
    from models import Configuracion
    texto_proteccion_datos = None
    numero_cuenta_iban = None
    forma_pago_texto = None
    
    # Buscar configuración de protección de datos
    config_proteccion = Configuracion.query.filter_by(clave='texto_proteccion_datos').first()
    if config_proteccion and config_proteccion.valor:
        texto_proteccion_datos = config_proteccion.valor
    else:
        # Valor por defecto
        texto_proteccion_datos = 'Finalidad: Prestar los servicios solicitados y enviar comunicaciones comerciales vía electrónica; Legitimación: Ejecución de un contrato, interés legítimo del Responsable; Destinatarios: Están previstas cesiones de datos a: previstas transferencias a terceros países (whatsapp); Derechos: Tiene derecho a acceder, rectificar y suprimir los datos, así como otros derechos, indicados en la información adicional, que puede ejercer dirigiéndose a marisa@weark.es o C/ MARQUESA DE PINARES, 11 - 06800 - MERIDA; Procedencia: El propio. En la información completa de las cláusulas informativas.'
    
    # Buscar configuración de número de cuenta/IBAN
    config_iban = Configuracion.query.filter_by(clave='numero_cuenta_iban').first()
    if config_iban and config_iban.valor:
        numero_cuenta_iban = config_iban.valor
    else:
        # Valor por defecto
        numero_cuenta_iban = 'ES2200495247862816942248'
    
    # Buscar configuración de forma de pago
    config_forma_pago = Configuracion.query.filter_by(clave='forma_pago_texto').first()
    if config_forma_pago and config_forma_pago.valor:
        forma_pago_texto = config_forma_pago.valor
    else:
        # Valor por defecto
        forma_pago_texto = 'Transferencia'
    
    return {
        'presupuesto': solicitud,  # Mantener 'presupuesto' para compatibilidad con template
        'solicitud': solicitud,  # Agregar 'solicitud' también
        'base_imponible': float(base_imponible),
        'iva_total': float(iva_total),
        'total_con_iva': float(total_con_iva),
        'tipo_iva': tipo_iva_para_template,  # Asegurar que sea float
        'logo_base64': logo_base64,
        'imagen_diseno_base64': imagen_diseno_base64,
        'imagen_portada_base64': imagen_portada_base64,
        'imagenes_adicionales_base64': imagenes_adicionales_base64,
        'descripciones_imagenes': descripciones_imagenes,
        'prendas_info': prendas_info,  # Información de todas las prendas
        'texto_proteccion_datos': texto_proteccion_datos,
        'numero_cuenta_iban': numero_cuenta_iban,
        'forma_pago_texto': forma_pago_texto
    }

@solicitudes_bp.route('/presupuestos/<int:solicitud_id>/imprimir')
@login_required
def imprimir_solicitud(solicitud_id):
    """Vista de impresión de la solicitud (HTML para imprimir desde navegador)"""
    datos = preparar_datos_imprimir_solicitud(solicitud_id)
    
    return render_template('imprimir_presupuesto.html', 
                         **datos,
                         use_base64=True)

@solicitudes_bp.route('/presupuestos/<int:solicitud_id>/descargar-pdf')
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
                
                # Esperar a que el JavaScript actualice los números de página
                page.wait_for_timeout(500)  # Esperar 500ms para que el script se ejecute
                
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
            return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))
        
        # Preparar la respuesta con el PDF
        pdf_buffer.seek(0)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=presupuesto_{solicitud_id}.pdf'
        
        return response
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error completo al generar PDF: {error_trace}")
        flash(f'Error al generar PDF: {str(e)}', 'error')
        return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))

@solicitudes_bp.route('/presupuestos/<int:solicitud_id>/descargar-pdf-detallado')
@login_required
def descargar_pdf_detallado_solicitud(solicitud_id):
    """Descargar solicitud en formato PDF detallado con todos los campos de las líneas"""
    try:
        datos = preparar_datos_imprimir_solicitud(solicitud_id)
        
        # Renderizar el HTML de la solicitud detallada
        html = render_template('imprimir_presupuesto_detallado.html', 
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
                
                # Esperar a que el JavaScript actualice los números de página
                page.wait_for_timeout(500)  # Esperar 500ms para que el script se ejecute
                
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
            print(f"Error al crear PDF detallado con playwright: {error_trace}")
            flash(f'Error al generar PDF detallado: {str(pdf_error)}', 'error')
            return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))
        
        # Preparar la respuesta con el PDF
        pdf_buffer.seek(0)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=presupuesto_detallado_{solicitud_id}.pdf'
        
        return response
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error completo al generar PDF detallado: {error_trace}")
        flash(f'Error al generar PDF detallado: {str(e)}', 'error')
        return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))

@solicitudes_bp.route('/presupuestos/<int:solicitud_id>/descargar-albaran')
@login_required
def descargar_albaran_solicitud(solicitud_id):
    """Descargar albarán en formato PDF (solo primera página, sin precios)"""
    try:
        datos = preparar_datos_imprimir_solicitud(solicitud_id)
        
        # Renderizar el HTML del albarán (solo primera página, sin precios)
        html = render_template('imprimir_presupuesto.html', 
                             **datos,
                             es_albaran=True,
                             solo_primera_pagina=True,
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
                
                # Esperar a que el JavaScript actualice los números de página
                page.wait_for_timeout(500)  # Esperar 500ms para que el script se ejecute
                
                # Generar PDF solo de la primera página
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
            print(f"Error al crear albarán con playwright: {error_trace}")
            flash(f'Error al generar albarán: {str(pdf_error)}', 'error')
            return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))
        
        # Preparar la respuesta con el PDF
        pdf_buffer.seek(0)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=albaran_{solicitud_id}.pdf'
        
        return response
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error completo al generar albarán: {error_trace}")
        flash(f'Error al generar albarán: {str(e)}', 'error')
        return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))


@solicitudes_bp.route('/presupuestos/<int:solicitud_id>/enviar-fd', methods=['POST'])
@login_required
def enviar_albaran_presupuesto_a_facturadirecta(solicitud_id):
    """Envía las líneas del presupuesto como albarán (delivery note) a FacturaDirecta."""
    solicitud = Presupuesto.query.options(
        joinedload(Presupuesto.lineas),
        joinedload(Presupuesto.cliente),
    ).get_or_404(solicitud_id)

    # Si ya se envió, no duplicar (salvo modo temporal FACTURADIRECTA_ALLOW_RESEND)
    if solicitud.fd_deliverynote_uuid and not current_app.config.get('FACTURADIRECTA_ALLOW_RESEND'):
        flash(f'Ya existe un albarán en FacturaDirecta para este presupuesto ({solicitud.fd_deliverynote_doc_number or solicitud.fd_deliverynote_uuid}).', 'info')
        return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))

    try:
        tipo_iva = Decimal(str(solicitud.cliente.tipo_iva)) if solicitud.cliente and solicitud.cliente.tipo_iva is not None else Decimal('21')

        lines = []
        for lp in (solicitud.lineas or []):
            qty = Decimal(str(lp.cantidad or 0))
            # Permitir líneas de abono (cantidad negativa). Solo ignorar líneas neutras.
            if qty == 0:
                continue

            # Concepto/Texto
            base_text = (lp.nombre_mostrar or lp.prenda_nombre_texto or (lp.prenda.nombre if lp.prenda else '') or '').strip()
            if lp.talla:
                text = f"{base_text} (Talla: {lp.talla})"
            else:
                text = base_text

            unit_price = net_unit_price_for_fd_line(lp.precio_unitario, lp.precio_final, lp.descuento)

            lines.append({
                "quantity": qty,
                "text": text or "Línea",
                "unitPrice": unit_price,
            })

        if not lines:
            raise FacturaDirectaError('No hay líneas válidas para enviar a FacturaDirecta.')

        payload = build_delivery_note_payload(
            doc_reference=solicitud.numero_solicitud or str(solicitud.id),
            cliente=solicitud.cliente,
            lines=lines,
            tipo_iva_percent=tipo_iva,
            notes=f"Presupuesto WEARK: {solicitud.numero_solicitud or solicitud.id}",
        )

        resp = create_delivery_note(payload)
        content = resp.get("content") or {}
        main = content.get("main") or {}
        doc_number = main.get("docNumber") or {}
        solicitud.fd_deliverynote_uuid = content.get("uuid")
        solicitud.fd_deliverynote_doc_number = doc_number.get("formatted") or doc_number.get("series")  # fallback
        solicitud.fd_deliverynote_sent_at = datetime.utcnow()
        solicitud.fd_deliverynote_last_error = None
        db.session.commit()

        flash('Enviado a FacturaDirecta correctamente.', 'success')
        return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))
    except Exception as e:
        db.session.rollback()
        # Guardar el error completo para poder verlo en la UI
        solicitud.fd_deliverynote_last_error = str(e)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(f'Error al enviar a FacturaDirecta: {e}', 'error')
        return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))

@solicitudes_bp.route('/presupuestos/<int:solicitud_id>/descargar-hoja-trabajo')
@login_required
def descargar_hoja_trabajo_solicitud(solicitud_id):
    """Descargar hoja de trabajo en PDF con el mismo orden del presupuesto público, sin condicionado."""
    try:
        solicitud = Presupuesto.query.options(
            joinedload(Presupuesto.lineas).joinedload(LineaPresupuesto.prenda),
            joinedload(Presupuesto.cliente),
            joinedload(Presupuesto.comercial)
        ).get_or_404(solicitud_id)

        productos = _obtener_productos_solicitud(solicitud)
        historial_respuestas = list(reversed(_parse_historial_respuestas_cliente(solicitud)))

        html = render_template(
            'cliente/presupuesto_publico.html',
            token_expirado=False,
            solicitud=solicitud,
            prendas_info=productos,
            historial_respuestas=historial_respuestas,
            modo_hoja_trabajo=True,
            mostrar_boton_descarga=False,
            incluir_condiciones=False,
            incluir_historial=False,
            incluir_respuesta_cliente=False
        )
        
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
                
                # Cargar el HTML desde el archivo temporal (mismo aspecto que vista en pantalla)
                page.goto(f'file://{temp_html_path}')
                page.emulate_media(media='screen')
                page.wait_for_timeout(400)
                pdf_bytes = page.pdf(
                    format='A4',
                    print_background=True,
                    margin={
                        'top': '6mm',
                        'right': '6mm',
                        'bottom': '6mm',
                        'left': '6mm'
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
            return redirect(url_for('index.index'))
        
        # Preparar la respuesta con el PDF
        pdf_buffer.seek(0)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=hoja_trabajo_{solicitud.numero_solicitud or solicitud.id}.pdf'
        
        return response
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error completo al generar hoja de trabajo: {error_trace}")
        flash(f'Error al generar hoja de trabajo: {str(e)}', 'error')
        return redirect(url_for('index.index'))

@solicitudes_bp.route('/presupuestos/imagen/<path:ruta_imagen>')
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
            if ruta_lower.endswith('.pdf'):
                mimetype = 'application/pdf'
            elif ruta_lower.endswith('.png'):
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

@solicitudes_bp.route('/presupuestos/<int:solicitud_id>/actualizar-seguimiento', methods=['POST'])
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
    
    return redirect(url_for('presupuestos.ver_solicitud', solicitud_id=solicitud_id))

