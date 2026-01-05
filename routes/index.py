"""Rutas para el panel de control (index)"""
from flask import Blueprint, render_template, flash, request
from flask_login import login_required
from datetime import datetime, timedelta
from models import Presupuesto

index_bp = Blueprint('index', __name__)

@index_bp.route('/')
@login_required
def index():
    """Página principal con lista de solicitudes (solo aceptadas hasta entregadas)"""
    try:
        # Obtener filtro de la URL
        filtro_activo = request.args.get('filtro', '')
        
        # Obtener solicitudes con estado entre "aceptado" y "entregado al cliente"
        from sqlalchemy.orm import joinedload
        from models import LineaPresupuesto
        from sqlalchemy import or_
        
        # Estados que se muestran en el panel: desde aceptado hasta entregado al cliente
        estados_mostrar = ['aceptado', 'mockup', 'en preparacion', 'revision y empaquetado', 'entregado al cliente']
        
        query = Presupuesto.query.filter(
            Presupuesto.estado.in_(estados_mostrar)
        )
        
        # Aplicar filtro si está seleccionado
        if filtro_activo == 'solo_mockup':
            query = query.filter(Presupuesto.estado == 'mockup')
        elif filtro_activo == 'solo_en_preparacion':
            query = query.filter(Presupuesto.estado == 'en preparacion')
        
        solicitudes = query.options(
            joinedload(Presupuesto.cliente),
            joinedload(Presupuesto.mockup_encargado_a),
            joinedload(Presupuesto.marcada_encargado_a)
        ).all()
        
        # Calcular fechas objetivo de entrega (25 y 17 días desde aceptación del mockup) y clasificar
        hoy = datetime.now().date()
        from extensions import db
        necesita_commit = False
        
        for solicitud in solicitudes:
            # Si tiene fecha de aceptación pero no tiene fechas objetivo, calcularlas
            # Esto puede pasar si el mockup fue aceptado antes de implementar las nuevas fechas
            if solicitud.fecha_aceptado:
                from utils.fechas import calcular_fecha_saltando_festivos
                if not solicitud.fecha_objetivo_25:
                    solicitud.fecha_objetivo_25 = calcular_fecha_saltando_festivos(solicitud.fecha_aceptado, 25)
                    necesita_commit = True
                if not solicitud.fecha_objetivo_17:
                    solicitud.fecha_objetivo_17 = calcular_fecha_saltando_festivos(solicitud.fecha_aceptado, 17)
                    necesita_commit = True
            
            # Clasificar según la fecha objetivo más próxima (17 días)
            if solicitud.fecha_objetivo_17:
                # Calcular días restantes hasta la fecha objetivo de 17 días
                dias_restantes = (solicitud.fecha_objetivo_17 - hoy).days
                
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
            elif solicitud.fecha_objetivo_25:
                # Si solo tiene la de 25 días, usar esa
                dias_restantes = (solicitud.fecha_objetivo_25 - hoy).days
                if dias_restantes <= 5:
                    solicitud.fecha_class = 'urgente'
                elif dias_restantes <= 10:
                    solicitud.fecha_class = 'proxima'
                else:
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
        
        # Ordenar por fecha objetivo más próxima (17 días primero, luego 25), los que no tienen fecha objetivo al final
        solicitudes.sort(key=lambda s: (
            s.fecha_objetivo_17 if s.fecha_objetivo_17 else (s.fecha_objetivo_25 if s.fecha_objetivo_25 else datetime.max.date()),
            s.fecha_aceptado if s.fecha_aceptado else datetime.max.date()
        ))
        
        return render_template('index.html', solicitudes=solicitudes, hoy=hoy, filtro_activo=filtro_activo)
    except Exception as e:
        import traceback
        error_msg = f"Error en index: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        flash(f'Error al cargar el panel de control: {str(e)}', 'error')
        hoy = datetime.now().date()
        filtro_activo = request.args.get('filtro', '')
        return render_template('index.html', solicitudes=[], hoy=hoy, filtro_activo=filtro_activo)

