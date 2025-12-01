"""Rutas para gestión de clientes"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import db
from models import Cliente

clientes_bp = Blueprint('clientes', __name__)

@clientes_bp.route('/clientes', methods=['GET', 'POST'])
def gestion_clientes():
    if request.method == 'POST':
        try:
            cliente = Cliente(
                nombre=request.form.get('nombre'),
                direccion=request.form.get('direccion', ''),
                telefono=request.form.get('telefono', ''),
                email=request.form.get('email', '')
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

@clientes_bp.route('/clientes/<int:id>/eliminar', methods=['POST'])
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

