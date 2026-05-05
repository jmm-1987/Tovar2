"""Extensiones de Flask (SQLAlchemy, etc.)"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail

# Crear instancia de SQLAlchemy (se inicializará en app.py)
db = SQLAlchemy()

# Crear instancia de LoginManager (se inicializará en app.py)
login_manager = LoginManager()

# Crear instancia de Mail (se inicializará en app.py)
mail = Mail()




