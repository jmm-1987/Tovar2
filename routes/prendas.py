"""Rutas para gestión de prendas"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from extensions import db
from models import Prenda
from decimal import Decimal

prendas_bp = Blueprint('prendas', __name__)

@prendas_bp.route('/prendas', methods=['GET', 'POST'])
@login_required
def gestion_prendas():
    if request.method == 'POST':
        try:
            precio_coste = request.form.get('precio_coste', '0') or '0'
            precio_venta = request.form.get('precio_venta', '0') or '0'
            
            prenda = Prenda(
                nombre=request.form.get('nombre'),
                tipo=request.form.get('tipo'),
                precio_coste=Decimal(precio_coste),
                precio_venta=Decimal(precio_venta)
            )
            db.session.add(prenda)
            db.session.commit()
            flash('Prenda creada correctamente', 'success')
            return redirect(url_for('prendas.gestion_prendas'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    prendas = Prenda.query.order_by(Prenda.nombre).all()
    return render_template('prendas.html', prendas=prendas)

@prendas_bp.route('/prendas/<int:id>/editar', methods=['POST'])
@login_required
def editar_prenda(id):
    prenda = Prenda.query.get_or_404(id)
    try:
        prenda.nombre = request.form.get('nombre')
        prenda.tipo = request.form.get('tipo')
        precio_coste = request.form.get('precio_coste', '0') or '0'
        precio_venta = request.form.get('precio_venta', '0') or '0'
        prenda.precio_coste = Decimal(precio_coste)
        prenda.precio_venta = Decimal(precio_venta)
        db.session.commit()
        flash('Prenda actualizada correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar prenda: {str(e)}', 'error')
    return redirect(url_for('prendas.gestion_prendas'))

@prendas_bp.route('/prendas/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar_prenda(id):
    prenda = Prenda.query.get_or_404(id)
    try:
        db.session.delete(prenda)
        db.session.commit()
        flash('Prenda eliminada', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar prenda: {str(e)}', 'error')
    return redirect(url_for('prendas.gestion_prendas'))

