"""Rutas para el panel de control (index)"""
from flask import Blueprint, render_template, flash
from flask_login import login_required
from datetime import datetime, timedelta
from models import Presupuesto

index_bp = Blueprint('index', __name__)

@index_bp.route('/')
@login_required
def index():
    """Página principal con lista de solicitudes (solo aceptadas hasta entregadas)"""
    try:
        # Obtener solicitudes con estado entre "aceptado" y "entregado al cliente"
        from sqlalchemy.orm import joinedload
        from models import LineaPresupuesto
        from sqlalchemy import or_
        
        # Estados que se muestran en el panel: desde aceptado hasta entregado al cliente
        estados_mostrar = ['aceptado', 'diseño', 'diseño finalizado', 'en preparacion', 'todo listo', 'enviado']
        
        solicitudes = Presupuesto.query.filter(
            Presupuesto.estado.in_(estados_mostrar)
        ).options(
            joinedload(Presupuesto.cliente),
            joinedload(Presupuesto.lineas).joinedload(LineaPresupuesto.prenda)
        ).all()
        
        # Calcular fecha objetivo de entrega (20 días desde aceptación) y clasificar
        hoy = datetime.now().date()
        from extensions import db
        necesita_commit = False
        
        for solicitud in solicitudes:
            # Si no tiene fecha objetivo pero tiene fecha de aceptación, calcularla (20 días)
            if solicitud.fecha_aceptado and not solicitud.fecha_objetivo:
                solicitud.fecha_objetivo = solicitud.fecha_aceptado + timedelta(days=20)
                necesita_commit = True
            
            if solicitud.fecha_objetivo:
                # Calcular días restantes hasta la fecha objetivo
                dias_restantes = (solicitud.fecha_objetivo - hoy).days
                
                # Clasificar fecha objetivo según días restantes
                if dias_restantes <= 5:
                    # 5 días o menos (incluye vencidos): Rojo
                    solicitud.fecha_class = 'urgente'
                elif dias_restantes <= 10:
                    # Entre 6 y 10 días: Naranja
                    solicitud.fecha_class = 'proxima'
                else:
                    # Más de 10 días: Verde
                    solicitud.fecha_class = 'ok'
            else:
                solicitud.fecha_class = ''
        
        # Guardar cambios si se calcularon fechas objetivo
        if necesita_commit:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"Error al guardar fechas objetivo: {e}")
        
        # Ordenar por fecha objetivo (más próximos primero), los que no tienen fecha objetivo al final
        solicitudes.sort(key=lambda s: (
            s.fecha_objetivo if s.fecha_objetivo else datetime.max.date(),
            s.fecha_aceptado if s.fecha_aceptado else datetime.max.date()
        ))
        
        return render_template('index.html', solicitudes=solicitudes)
    except Exception as e:
        import traceback
        error_msg = f"Error en index: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        flash(f'Error al cargar el panel de control: {str(e)}', 'error')
        return render_template('index.html', solicitudes=[])

