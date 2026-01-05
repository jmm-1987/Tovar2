"""Utilidades para cálculos de fechas considerando días festivos"""
from datetime import date, timedelta
from flask import current_app
from extensions import db
from models import DiaFestivo, Configuracion

def es_dia_festivo(fecha, excluir_sabados=None, excluir_domingos=None):
    """
    Verificar si una fecha es día festivo o no laborable
    
    Args:
        fecha: objeto date a verificar
        excluir_sabados: si se deben excluir sábados (None para obtener de BD, True por defecto)
        excluir_domingos: si se deben excluir domingos (None para obtener de BD, True por defecto)
    
    Returns:
        True si es día festivo/no laborable, False en caso contrario
    """
    # SIEMPRE excluir sábados y domingos (son días no laborables)
    # La configuración solo se usa si se proporciona explícitamente el parámetro
    if excluir_sabados is None:
        # Por defecto, SIEMPRE excluir sábados
        excluir_sabados = True
    
    if excluir_domingos is None:
        # Por defecto, SIEMPRE excluir domingos
        excluir_domingos = True
    
    # Verificar si es sábado o domingo
    dia_semana = fecha.weekday()  # 0=Lunes, 6=Domingo
    if excluir_sabados and dia_semana == 5:  # Sábado
        return True
    if excluir_domingos and dia_semana == 6:  # Domingo
        return True
    
    # Verificar si está en la lista de días festivos activos
    try:
        dia_festivo = DiaFestivo.query.filter_by(fecha=fecha, activo=True).first()
        if dia_festivo:
            return True
    except Exception as e:
        print(f"Error al verificar día festivo {fecha}: {e}")
        pass
    
    return False

def calcular_fecha_saltando_festivos(fecha_inicio, dias_habiles):
    """
    Calcular una fecha sumando días hábiles, saltando días festivos
    
    Args:
        fecha_inicio: fecha de inicio (date)
        dias_habiles: número de días hábiles a sumar
    
    Returns:
        fecha final (date) después de sumar los días hábiles
    """
    fecha_actual = fecha_inicio
    dias_sumados = 0
    max_iteraciones = dias_habiles * 3  # Límite de seguridad (máximo 3 veces los días hábiles)
    iteraciones = 0
    
    while dias_sumados < dias_habiles and iteraciones < max_iteraciones:
        fecha_actual += timedelta(days=1)
        iteraciones += 1
        # Si no es día festivo, contar como día hábil
        if not es_dia_festivo(fecha_actual):
            dias_sumados += 1
    
    if iteraciones >= max_iteraciones:
        print(f"ADVERTENCIA: Se alcanzó el límite de iteraciones al calcular fecha. Inicio: {fecha_inicio}, Días hábiles: {dias_habiles}, Fecha final: {fecha_actual}")
    
    return fecha_actual

