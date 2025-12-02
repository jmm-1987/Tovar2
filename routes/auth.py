"""Rutas de autenticación"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import Usuario
from datetime import datetime

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Página de login"""
    if current_user.is_authenticated:
        return redirect(url_for('index.index'))
    
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        password = request.form.get('password')
        
        if not usuario or not password:
            flash('Por favor, completa todos los campos', 'error')
            return render_template('login.html')
        
        # Buscar usuario
        user = Usuario.query.filter_by(usuario=usuario, activo=True).first()
        
        if user and user.check_password(password):
            # Actualizar último acceso
            user.ultimo_acceso = datetime.utcnow()
            db.session.commit()
            
            # Iniciar sesión
            login_user(user)
            
            # Redirigir según el rol
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            
            return redirect(url_for('index.index'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
    
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    """Cerrar sesión"""
    logout_user()
    flash('Has cerrado sesión correctamente', 'info')
    return redirect(url_for('auth.login'))


