"""Rutas para gestión de clientes"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from extensions import db
from models import Cliente, Presupuesto, Factura, Pedido, Comercial, Usuario
from sqlalchemy import or_
from datetime import datetime

clientes_bp = Blueprint('clientes', __name__)

@clientes_bp.route('/clientes', methods=['GET', 'POST'])
@login_required
def gestion_clientes():
    if request.method == 'POST':
        try:
            # Procesar fecha de alta
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
                categoria=request.form.get('categoria', ''),
                personas_contacto=request.form.get('personas_contacto', ''),
                anotaciones=request.form.get('anotaciones', ''),
                usuario_web=request.form.get('usuario_web', '').strip() or None,
                fecha_alta=fecha_alta,
                comercial_id=comercial_id
            )
            
            # Si se proporciona usuario web, también establecer contraseña si se proporciona
            password_web = request.form.get('password_web', '').strip()
            if cliente.usuario_web and password_web:
                cliente.set_password(password_web)
            
            db.session.add(cliente)
            db.session.commit()
            flash('Cliente creado correctamente', 'success')
            return redirect(url_for('clientes.gestion_clientes'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    # Obtener parámetros de búsqueda y ordenamiento
    busqueda = request.args.get('busqueda', '').strip()
    orden = request.args.get('orden', 'id')  # 'id' o 'nombre'
    
    # Construir consulta
    query = Cliente.query
    
    # Aplicar filtro de búsqueda
    if busqueda:
        query = query.filter(
            db.or_(
                Cliente.nombre.ilike(f'%{busqueda}%'),
                Cliente.alias.ilike(f'%{busqueda}%'),
                Cliente.nif.ilike(f'%{busqueda}%'),
                Cliente.poblacion.ilike(f'%{busqueda}%'),
                Cliente.provincia.ilike(f'%{busqueda}%')
            )
        )
    
    # Aplicar ordenamiento
    if orden == 'nombre':
        clientes = query.order_by(Cliente.nombre.asc()).all()
    else:
        clientes = query.order_by(Cliente.id.asc()).all()
    
    # Obtener comerciales para el formulario
    comerciales = Comercial.query.join(Usuario).filter(
        Usuario.activo == True,
        Usuario.rol.in_(['comercial', 'administracion'])
    ).all()
    
    return render_template('clientes.html', 
                         clientes=clientes,
                         busqueda=busqueda,
                         orden=orden,
                         comerciales=comerciales)

@clientes_bp.route('/clientes/<int:id>')
@login_required
def ficha_cliente(id):
    """Ficha completa del cliente con historial"""
    cliente = Cliente.query.get_or_404(id)
    
    # Obtener historial de presupuestos
    presupuestos = Presupuesto.query.filter_by(cliente_id=id).order_by(Presupuesto.fecha_creacion.desc()).limit(20).all()
    
    # Obtener historial de pedidos (ahora son presupuestos/solicitudes)
    # Obtener solicitudes (presupuestos) del cliente en lugar de pedidos
    pedidos = Presupuesto.query.filter_by(cliente_id=id).order_by(Presupuesto.fecha_creacion.desc()).limit(20).all()
    
    # Obtener historial de facturas (a través de presupuestos/solicitudes o pedidos antiguos)
    # Las facturas pueden venir de presupuestos (nuevo sistema) o de pedidos (sistema antiguo)
    facturas = Factura.query.filter(
        or_(
            Factura.presupuesto_id.in_(
                db.session.query(Presupuesto.id).filter_by(cliente_id=id)
            ),
            Factura.pedido_id.in_(
                db.session.query(Pedido.id).filter_by(cliente_id=id)
            )
        )
    ).order_by(Factura.fecha_creacion.desc()).limit(20).all()
    
    return render_template('ficha_cliente.html', 
                         cliente=cliente,
                         presupuestos=presupuestos,
                         pedidos=pedidos,
                         facturas=facturas)

@clientes_bp.route('/clientes/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    """Editar cliente"""
    cliente = Cliente.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            cliente.nombre = request.form.get('nombre')
            cliente.alias = request.form.get('alias', '')
            cliente.nif = request.form.get('nif', '')
            cliente.direccion = request.form.get('direccion', '')
            cliente.poblacion = request.form.get('poblacion', '')
            cliente.provincia = request.form.get('provincia', '')
            cliente.codigo_postal = request.form.get('codigo_postal', '')
            cliente.pais = request.form.get('pais', 'España')
            cliente.telefono = request.form.get('telefono', '')
            cliente.movil = request.form.get('movil', '')
            cliente.email = request.form.get('email', '')
            cliente.categoria = request.form.get('categoria', '')
            cliente.personas_contacto = request.form.get('personas_contacto', '')
            cliente.anotaciones = request.form.get('anotaciones', '')
            
            # Procesar comercial asignado
            comercial_id = request.form.get('comercial_id', '').strip()
            cliente.comercial_id = int(comercial_id) if comercial_id else None
            
            # Procesar fecha de alta
            fecha_alta_str = request.form.get('fecha_alta', '')
            if fecha_alta_str:
                try:
                    cliente.fecha_alta = datetime.strptime(fecha_alta_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            else:
                cliente.fecha_alta = None
            
            # Manejar acceso web
            usuario_web = request.form.get('usuario_web', '').strip()
            password_web = request.form.get('password_web', '').strip()
            
            if usuario_web:
                cliente.usuario_web = usuario_web
                # Solo actualizar contraseña si se proporciona una nueva
                if password_web:
                    cliente.set_password(password_web)
            else:
                # Si se elimina el usuario, también eliminar la contraseña
                cliente.usuario_web = None
                cliente.password_hash = None
            
            db.session.commit()
            flash('Cliente actualizado correctamente', 'success')
            return redirect(url_for('clientes.ficha_cliente', id=id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar cliente: {str(e)}', 'error')
    
    # Obtener comerciales para el formulario
    comerciales = Comercial.query.join(Usuario).filter(
        Usuario.activo == True,
        Usuario.rol.in_(['comercial', 'administracion'])
    ).all()
    
    return render_template('editar_cliente.html', cliente=cliente, comerciales=comerciales)

@clientes_bp.route('/clientes/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    try:
        db.session.delete(cliente)
        db.session.commit()
        flash('Cliente eliminado', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar cliente: {str(e)}', 'error')
    return redirect(url_for('clientes.gestion_clientes'))

