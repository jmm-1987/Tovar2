"""Rutas para gestión de comerciales"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import db
from models import Comercial

comerciales_bp = Blueprint('comerciales', __name__)

@comerciales_bp.route('/comerciales', methods=['GET', 'POST'])
def gestion_comerciales():
    if request.method == 'POST':
        try:
            comercial = Comercial(nombre=request.form.get('nombre'))
            db.session.add(comercial)
            db.session.commit()
            flash('Comercial creado correctamente', 'success')
            return redirect(url_for('comerciales.gestion_comerciales'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    comerciales = Comercial.query.all()
    return render_template('comerciales.html', comerciales=comerciales)

@comerciales_bp.route('/comerciales/<int:id>/eliminar', methods=['POST'])
def eliminar_comercial(id):
    comercial = Comercial.query.get_or_404(id)
    try:
        db.session.delete(comercial)
        db.session.commit()
        flash('Comercial eliminado', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar comercial: {str(e)}', 'error')
    return redirect(url_for('comerciales.gestion_comerciales'))

