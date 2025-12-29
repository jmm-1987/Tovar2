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
        excluir_sabados: si se deben excluir sábados (None para obtener de BD)
        excluir_domingos: si se deben excluir domingos (None para obtener de BD)
    
    Returns:
        True si es día festivo/no laborable, False en caso contrario
    """
    # Obtener configuración de sábados y domingos si no se proporciona
    if excluir_sabados is None:
        try:
            config_sabados = Configuracion.query.filter_by(clave='excluir_sabados').first()
            excluir_sabados = config_sabados.valor.lower() == 'true' if config_sabados else False
        except:
            excluir_sabados = False
    
    if excluir_domingos is None:
        try:
            config_domingos = Configuracion.query.filter_by(clave='excluir_domingos').first()
            excluir_domingos = config_domingos.valor.lower() == 'true' if config_domingos else False
        except:
            excluir_domingos = False
    
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
    except:
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
    
    while dias_sumados < dias_habiles:
        fecha_actual += timedelta(days=1)
        # Si no es día festivo, contar como día hábil
        if not es_dia_festivo(fecha_actual):
            dias_sumados += 1
    
    return fecha_actual

