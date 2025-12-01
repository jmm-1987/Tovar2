"""Rutas para gestión de prendas"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import db
from models import Prenda

prendas_bp = Blueprint('prendas', __name__)

@prendas_bp.route('/prendas', methods=['GET', 'POST'])
def gestion_prendas():
    if request.method == 'POST':
        try:
            prenda = Prenda(
                nombre=request.form.get('nombre'),
                tipo=request.form.get('tipo')
            )
            db.session.add(prenda)
            db.session.commit()
            flash('Prenda creada correctamente', 'success')
            return redirect(url_for('prendas.gestion_prendas'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    prendas = Prenda.query.all()
    return render_template('prendas.html', prendas=prendas)

@prendas_bp.route('/prendas/<int:id>/eliminar', methods=['POST'])
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

