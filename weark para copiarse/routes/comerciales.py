"""Rutas para gestión de comerciales"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from extensions import db
from models import Comercial, Usuario
from utils.auth import not_usuario_required

comerciales_bp = Blueprint('comerciales', __name__)

@comerciales_bp.route('/comerciales')
@login_required
@not_usuario_required
def gestion_comerciales():
    """Listar comerciales (usuarios con rol comercial o administracion)"""
    # Obtener todos los comerciales (usuarios con rol comercial o administracion)
    comerciales = Comercial.query.join(Usuario).filter(
        Usuario.activo == True,
        Usuario.rol.in_(['comercial', 'administracion'])
    ).all()
    
    return render_template('comerciales.html', comerciales=comerciales)

