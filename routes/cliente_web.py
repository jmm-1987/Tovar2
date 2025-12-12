"""Rutas para acceso web de clientes"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import Cliente, Pedido, Prenda, Comercial, Usuario, Factura
from datetime import datetime
from werkzeug.utils import secure_filename
import os

cliente_web_bp = Blueprint('cliente_web', __name__, url_prefix='/cliente')

def es_cliente():
    """Verificar si el usuario actual es un cliente"""
    return current_user.is_authenticated and isinstance(current_user, Cliente)

@cliente_web_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login para clientes"""
    # Si ya está autenticado como cliente, redirigir
    if current_user.is_authenticated and isinstance(current_user, Cliente):
        return redirect(url_for('cliente_web.dashboard'))
    
    # Si está autenticado como usuario del sistema, cerrar sesión primero
    if current_user.is_authenticated:
        logout_user()
    
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        password = request.form.get('password')
        
        if not usuario or not password:
            flash('Por favor, completa todos los campos', 'error')
            return render_template('cliente_web/login.html')
        
        # Buscar cliente por usuario_web
        cliente = Cliente.query.filter_by(usuario_web=usuario).first()
        
        if cliente and cliente.tiene_acceso_web() and cliente.check_password(password):
            # Actualizar último acceso
            cliente.ultimo_acceso = datetime.utcnow()
            db.session.commit()
            
            # Iniciar sesión
            login_user(cliente)
            
            flash(f'Bienvenido, {cliente.nombre}', 'success')
            return redirect(url_for('cliente_web.dashboard'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
    
    return render_template('cliente_web/login.html')

@cliente_web_bp.route('/logout')
@login_required
def logout():
    """Cerrar sesión de cliente"""
    if not es_cliente():
        flash('Acceso no autorizado', 'error')
        return redirect(url_for('auth.login'))
    
    logout_user()
    flash('Has cerrado sesión correctamente', 'info')
    return redirect(url_for('cliente_web.login'))

@cliente_web_bp.route('/dashboard')
@login_required
def dashboard():
    """Dashboard del cliente"""
    if not es_cliente():
        flash('Acceso no autorizado', 'error')
        return redirect(url_for('auth.login'))
    
    cliente = current_user
    
    # Obtener estadísticas
    total_pedidos = Pedido.query.filter_by(cliente_id=cliente.id).count()
    pedidos_pendientes = Pedido.query.filter(
        Pedido.cliente_id == cliente.id,
        Pedido.estado.in_(['Pendiente', 'Pendiente de enviar'])
    ).count()
    pedidos_en_preparacion = Pedido.query.filter_by(cliente_id=cliente.id, estado='En preparación').count()
    
    # Obtener facturas a través de pedidos
    total_facturas = Factura.query.join(Pedido).filter(Pedido.cliente_id == cliente.id).count()
    
    # Últimos pedidos
    ultimos_pedidos = Pedido.query.filter_by(cliente_id=cliente.id).order_by(Pedido.fecha_creacion.desc()).limit(5).all()
    
    # Últimas facturas
    ultimas_facturas = Factura.query.join(Pedido).filter(Pedido.cliente_id == cliente.id).order_by(Factura.fecha_creacion.desc()).limit(5).all()
    
    return render_template('cliente_web/dashboard.html',
                         cliente=cliente,
                         total_pedidos=total_pedidos,
                         pedidos_pendientes=pedidos_pendientes,
                         pedidos_en_preparacion=pedidos_en_preparacion,
                         total_facturas=total_facturas,
                         ultimos_pedidos=ultimos_pedidos,
                         ultimas_facturas=ultimas_facturas)

@cliente_web_bp.route('/pedidos')
@login_required
def ver_pedidos():
    """Ver todos los pedidos del cliente"""
    if not es_cliente():
        flash('Acceso no autorizado', 'error')
        return redirect(url_for('auth.login'))
    
    cliente = current_user
    pedidos = Pedido.query.filter_by(cliente_id=cliente.id).order_by(Pedido.fecha_creacion.desc()).all()
    
    return render_template('cliente_web/pedidos.html', pedidos=pedidos, cliente=cliente)

@cliente_web_bp.route('/pedidos/<int:pedido_id>')
@login_required
def ver_pedido(pedido_id):
    """Ver detalle de un pedido"""
    if not es_cliente():
        flash('Acceso no autorizado', 'error')
        return redirect(url_for('auth.login'))
    
    cliente = current_user
    pedido = Pedido.query.get_or_404(pedido_id)
    
    # Verificar que el pedido pertenece al cliente
    if pedido.cliente_id != cliente.id:
        flash('No tienes permiso para ver este pedido', 'error')
        return redirect(url_for('cliente_web.ver_pedidos'))
    
    return render_template('cliente_web/ver_pedido.html', pedido=pedido, cliente=cliente)

@cliente_web_bp.route('/facturas')
@login_required
def ver_facturas():
    """Ver todas las facturas del cliente"""
    if not es_cliente():
        flash('Acceso no autorizado', 'error')
        return redirect(url_for('auth.login'))
    
    cliente = current_user
    facturas = Factura.query.join(Pedido).filter(Pedido.cliente_id == cliente.id).order_by(Factura.fecha_creacion.desc()).all()
    
    return render_template('cliente_web/facturas.html', facturas=facturas, cliente=cliente)

@cliente_web_bp.route('/facturas/<int:factura_id>')
@login_required
def ver_factura(factura_id):
    """Ver detalle de una factura"""
    if not es_cliente():
        flash('Acceso no autorizado', 'error')
        return redirect(url_for('auth.login'))
    
    cliente = current_user
    factura = Factura.query.get_or_404(factura_id)
    
    # Verificar que la factura pertenece al cliente
    if factura.pedido.cliente_id != cliente.id:
        flash('No tienes permiso para ver esta factura', 'error')
        return redirect(url_for('cliente_web.ver_facturas'))
    
    return render_template('cliente_web/ver_factura.html', factura=factura, cliente=cliente)

@cliente_web_bp.route('/nuevo-pedido', methods=['GET', 'POST'])
@login_required
def nuevo_pedido():
    """Crear nuevo pedido desde el cliente"""
    if not es_cliente():
        flash('Acceso no autorizado', 'error')
        return redirect(url_for('auth.login'))
    
    cliente = current_user
    
    if request.method == 'POST':
        try:
            from flask import current_app
            from models import LineaPedido
            from decimal import Decimal
            from datetime import timedelta
            
            # Obtener el primer comercial activo como predeterminado
            comercial = Comercial.query.join(Usuario).filter(
                Usuario.activo == True,
                Usuario.rol.in_(['comercial', 'administracion'])
            ).first()
            
            if not comercial:
                flash('No hay comerciales disponibles. Contacte con el administrador.', 'error')
                return redirect(url_for('cliente_web.nuevo_pedido'))
            
            # Crear pedido - siempre tipo "cliente web" para pedidos creados desde el área cliente
            # No se permite forma de pago ni imagen de diseño desde el área cliente
            pedido = Pedido(
                comercial_id=comercial.id,
                cliente_id=cliente.id,
                tipo_pedido='cliente web',  # Siempre cliente web para pedidos desde área cliente
                estado='Pendiente de enviar',
                forma_pago='',  # No se permite desde área cliente
                fecha_aceptacion=None,  # Se establecerá cuando el comercial lo acepte
                fecha_objetivo=None
                # imagen_diseno se deja como None - no se permite desde área cliente
            )
            
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
            
            for i in range(len(prenda_ids)):
                if prenda_ids[i] and (nombres_mostrar[i] if i < len(nombres_mostrar) else nombres[i] if i < len(nombres) else ''):
                    precio_unitario = None
                    if i < len(precios_unitarios) and precios_unitarios[i]:
                        try:
                            precio_unitario = Decimal(str(precios_unitarios[i]))
                        except:
                            precio_unitario = None
                    
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
                        estado='pendiente'
                    )
                    db.session.add(linea)
            
            db.session.commit()
            flash('Pedido creado correctamente. Será revisado por nuestro equipo.', 'success')
            return redirect(url_for('cliente_web.ver_pedidos'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear pedido: {str(e)}', 'error')
    
    prendas = Prenda.query.all()
    return render_template('cliente_web/nuevo_pedido.html', 
                         cliente=cliente,
                         prendas=prendas)

