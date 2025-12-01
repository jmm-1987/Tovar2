"""Rutas para gestión de maestros (comerciales, clientes, prendas)"""
from flask import Blueprint, render_template
from extensions import db
from models import Comercial, Cliente, Prenda

maestros_bp = Blueprint('maestros', __name__)

@maestros_bp.route('/maestros')
def maestros():
    """Página índice de maestros con acceso a comerciales, clientes y prendas"""
    # Obtener conteos para mostrar en las tarjetas
    total_comerciales = Comercial.query.count()
    total_clientes = Cliente.query.count()
    total_prendas = Prenda.query.count()
    
    return render_template('maestros.html', 
                         total_comerciales=total_comerciales,
                         total_clientes=total_clientes,
                         total_prendas=total_prendas)




