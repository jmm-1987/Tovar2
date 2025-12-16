"""Rutas para el panel de control (index)"""
from flask import Blueprint, render_template, flash
from flask_login import login_required
from datetime import datetime, timedelta
from models import Pedido

index_bp = Blueprint('index', __name__)

@index_bp.route('/')
@login_required
def index():
    """Página principal con lista de pedidos"""
    try:
        # Obtener todos los pedidos con sus relaciones cargadas, excluyendo los entregados al cliente
        from sqlalchemy.orm import joinedload
        from models import LineaPedido
        pedidos = Pedido.query.filter(
            Pedido.estado != 'Entregado al cliente'
        ).options(
            joinedload(Pedido.cliente),
            joinedload(Pedido.lineas).joinedload(LineaPedido.prenda)
        ).all()
        
        # Calcular fecha objetivo de entrega (20 días desde aceptación) y clasificar
        hoy = datetime.now().date()
        
        for pedido in pedidos:
            # Si no tiene fecha objetivo pero tiene fecha de aceptación, calcularla (20 días)
            if pedido.fecha_aceptacion and not pedido.fecha_objetivo:
                pedido.fecha_objetivo = pedido.fecha_aceptacion + timedelta(days=20)
            
            if pedido.fecha_objetivo:
                # Calcular días restantes hasta la fecha objetivo
                dias_restantes = (pedido.fecha_objetivo - hoy).days
                
                # Clasificar fecha objetivo según días restantes
                if dias_restantes <= 5:
                    # 5 días o menos (incluye vencidos): Rojo
                    pedido.fecha_class = 'urgente'
                elif dias_restantes <= 10:
                    # Entre 6 y 10 días: Naranja
                    pedido.fecha_class = 'proxima'
                else:
                    # Más de 10 días: Verde
                    pedido.fecha_class = 'ok'
            else:
                pedido.fecha_class = ''
        
        # Ordenar por fecha objetivo (más próximos primero), los que no tienen fecha objetivo al final
        pedidos.sort(key=lambda p: (
            p.fecha_objetivo if p.fecha_objetivo else datetime.max.date(),
            p.fecha_aceptacion if p.fecha_aceptacion else datetime.max.date()
        ))
        
        return render_template('index.html', pedidos=pedidos)
    except Exception as e:
        import traceback
        error_msg = f"Error en index: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        flash(f'Error al cargar el panel de control: {str(e)}', 'error')
        return render_template('index.html', pedidos=[])

