"""Utilidades para generar números de facturas y tickets"""
from datetime import datetime
from extensions import db
from models import Factura, Ticket

def obtener_siguiente_numero_factura(fecha_expedicion=None):
    """
    Obtiene el siguiente número de factura para el año actual.
    Formato: F + año (2 dígitos) + número contador
    Ejemplo: F251, F252, etc.
    """
    if fecha_expedicion is None:
        fecha_expedicion = datetime.now().date()
    
    año = fecha_expedicion.strftime('%y')  # Año con 2 dígitos (25 para 2025)
    
    # Buscar el último número de factura para este año
    # El formato es F + año + número
    prefijo = f'F{año}'
    
    # Buscar todas las facturas que empiecen con este prefijo
    facturas_del_año = Factura.query.filter(
        Factura.numero.like(f'{prefijo}%')
    ).all()
    
    if not facturas_del_año:
        # Si no hay facturas para este año, empezar en 1
        siguiente_numero = 1
    else:
        # Extraer los números y encontrar el máximo
        numeros = []
        for factura in facturas_del_año:
            try:
                # El número tiene formato F251, extraer solo la parte numérica final
                numero_str = factura.numero.replace(prefijo, '')
                if numero_str.isdigit():
                    numeros.append(int(numero_str))
            except:
                continue
        
        if numeros:
            siguiente_numero = max(numeros) + 1
        else:
            siguiente_numero = 1
    
    # Formatear el número con el prefijo
    numero_completo = f'{prefijo}{siguiente_numero}'
    
    return numero_completo

def obtener_siguiente_numero_ticket(fecha_expedicion=None):
    """
    Obtiene el siguiente número de ticket para el año actual.
    Formato: T + año (2 dígitos) + número contador
    Ejemplo: T251, T252, etc.
    """
    if fecha_expedicion is None:
        fecha_expedicion = datetime.now().date()
    
    año = fecha_expedicion.strftime('%y')  # Año con 2 dígitos (25 para 2025)
    
    # Buscar el último número de ticket para este año
    # El formato es T + año + número
    prefijo = f'T{año}'
    
    # Buscar todos los tickets que empiecen con este prefijo
    tickets_del_año = Ticket.query.filter(
        Ticket.numero.like(f'{prefijo}%')
    ).all()
    
    if not tickets_del_año:
        # Si no hay tickets para este año, empezar en 1
        siguiente_numero = 1
    else:
        # Extraer los números y encontrar el máximo
        numeros = []
        for ticket in tickets_del_año:
            try:
                # El número tiene formato T251, extraer solo la parte numérica final
                numero_str = ticket.numero.replace(prefijo, '')
                if numero_str.isdigit():
                    numeros.append(int(numero_str))
            except:
                continue
        
        if numeros:
            siguiente_numero = max(numeros) + 1
        else:
            siguiente_numero = 1
    
    # Formatear el número con el prefijo
    numero_completo = f'{prefijo}{siguiente_numero}'
    
    return numero_completo

