"""Utilidades de autenticación y decoradores"""
from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user

def supervisor_required(f):
    """Decorador para requerir rol de supervisor"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Debes iniciar sesión para acceder a esta página', 'error')
            return redirect(url_for('auth.login'))
        if not current_user.is_supervisor():
            flash('No tienes permisos para acceder a esta página', 'error')
            return redirect(url_for('index.index'))
        return f(*args, **kwargs)
    return decorated_function

def login_required_custom(f):
    """Decorador personalizado para requerir login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Debes iniciar sesión para acceder a esta página', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function






