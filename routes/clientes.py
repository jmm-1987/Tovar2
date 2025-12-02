"""Rutas para gestión de clientes"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from extensions import db
from models import Cliente, Presupuesto, Factura, Pedido
from datetime import datetime

clientes_bp = Blueprint('clientes', __name__)

@clientes_bp.route('/clientes', methods=['GET', 'POST'])
@login_required
def gestion_clientes():
    if request.method == 'POST':
        try:
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
                email=request.form.get('email', ''),
                personas_contacto=request.form.get('personas_contacto', ''),
                anotaciones=request.form.get('anotaciones', '')
            )
            db.session.add(cliente)
            db.session.commit()
            flash('Cliente creado correctamente', 'success')
            return redirect(url_for('clientes.gestion_clientes'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    clientes = Cliente.query.all()
    return render_template('clientes.html', clientes=clientes)

@clientes_bp.route('/clientes/<int:id>')
@login_required
def ficha_cliente(id):
    """Ficha completa del cliente con historial"""
    cliente = Cliente.query.get_or_404(id)
    
    # Obtener historial de presupuestos
    presupuestos = Presupuesto.query.filter_by(cliente_id=id).order_by(Presupuesto.fecha_creacion.desc()).limit(20).all()
    
    # Obtener historial de pedidos
    pedidos = Pedido.query.filter_by(cliente_id=id).order_by(Pedido.fecha_creacion.desc()).limit(20).all()
    
    # Obtener historial de facturas (a través de pedidos)
    facturas = Factura.query.join(Pedido).filter(Pedido.cliente_id == id).order_by(Factura.fecha_creacion.desc()).limit(20).all()
    
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
            cliente.email = request.form.get('email', '')
            cliente.personas_contacto = request.form.get('personas_contacto', '')
            cliente.anotaciones = request.form.get('anotaciones', '')
            
            db.session.commit()
            flash('Cliente actualizado correctamente', 'success')
            return redirect(url_for('clientes.ficha_cliente', id=id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar cliente: {str(e)}', 'error')
    
    return render_template('editar_cliente.html', cliente=cliente)

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

