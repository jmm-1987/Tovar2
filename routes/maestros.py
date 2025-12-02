"""Rutas para gestión de maestros (comerciales, clientes, prendas)"""
from flask import Blueprint, render_template
from flask_login import login_required
from extensions import db
from models import Comercial, Cliente, Prenda, Usuario

maestros_bp = Blueprint('maestros', __name__)

@maestros_bp.route('/maestros')
@login_required
def maestros():
    """Página índice de maestros con acceso a comerciales, clientes y prendas"""
    # Obtener conteos para mostrar en las tarjetas
    total_comerciales = Comercial.query.join(Usuario).filter(
        Usuario.activo == True,
        Usuario.rol.in_(['comercial', 'administracion'])
    ).count()
    total_clientes = Cliente.query.count()
    total_prendas = Prenda.query.count()
    
    return render_template('maestros.html', 
                         total_comerciales=total_comerciales,
                         total_clientes=total_clientes,
                         total_prendas=total_prendas)




