"""Utilidades para generar números de facturas y tickets"""
from datetime import datetime
from extensions import db
from models import Factura, Ticket, Presupuesto

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

def obtener_siguiente_numero_solicitud(fecha_creacion=None):
    """
    Obtiene el siguiente número de solicitud para el mes actual.
    Formato: aamm_contador (ej: 2601_01, 2601_02, etc.)
    - aa = año (2 dígitos)
    - mm = mes (2 dígitos)
    - contador = contador de 2 dígitos que se reinicia cada mes
    """
    if fecha_creacion is None:
        fecha_creacion = datetime.now().date()
    
    año = fecha_creacion.strftime('%y')  # Año con 2 dígitos (26 para 2026)
    mes = fecha_creacion.strftime('%m')  # Mes con 2 dígitos (01 para enero)
    
    # Prefijo con formato aamm
    prefijo = f'{año}{mes}'
    
    # Buscar todas las solicitudes que empiecen con este prefijo
    solicitudes_del_mes = Presupuesto.query.filter(
        Presupuesto.numero_solicitud.like(f'{prefijo}_%')
    ).all()
    
    if not solicitudes_del_mes:
        # Si no hay solicitudes para este mes, empezar en 01
        siguiente_contador = 1
    else:
        # Extraer los contadores y encontrar el máximo
        contadores = []
        for solicitud in solicitudes_del_mes:
            if solicitud.numero_solicitud:
                try:
                    # El número tiene formato 2601_01, extraer solo la parte del contador
                    partes = solicitud.numero_solicitud.split('_')
                    if len(partes) == 2 and partes[0] == prefijo:
                        contador_str = partes[1]
                        if contador_str.isdigit():
                            contadores.append(int(contador_str))
                except:
                    continue
        
        if contadores:
            siguiente_contador = max(contadores) + 1
        else:
            siguiente_contador = 1
    
    # Formatear el número completo: aamm_contador (con contador de 2 dígitos)
    numero_completo = f'{prefijo}_{siguiente_contador:02d}'
    
    return numero_completo

def obtener_siguiente_numero_albaran(fecha_expedicion=None):
    """
    Obtiene el siguiente número de albarán para el mes actual.
    Formato: A + aamm_contador (ej: A2601_001, A2601_002, etc.)
    - A = prefijo de Albarán
    - aa = año (2 dígitos)
    - mm = mes (2 dígitos)
    - contador = contador de 3 dígitos que se reinicia cada mes
    """
    if fecha_expedicion is None:
        fecha_expedicion = datetime.now().date()
    
    año = fecha_expedicion.strftime('%y')  # Año con 2 dígitos (26 para 2026)
    mes = fecha_expedicion.strftime('%m')  # Mes con 2 dígitos (01 para enero)
    
    # Prefijo con formato A + aamm
    prefijo_completo = f'A{año}{mes}'
    prefijo_busqueda = f'A{año}{mes}_'
    
    # Buscar todas las facturas (albaranes) que empiecen con este prefijo
    # Los albaranes son facturas con estado='pendiente' y número que empieza con A
    albaranes_del_mes = Factura.query.filter(
        Factura.numero.like(f'{prefijo_busqueda}%')
    ).all()
    
    if not albaranes_del_mes:
        # Si no hay albaranes para este mes, empezar en 001
        siguiente_contador = 1
    else:
        # Extraer los contadores y encontrar el máximo
        contadores = []
        for albaran in albaranes_del_mes:
            if albaran.numero:
                try:
                    # El número tiene formato A2601_001, extraer solo la parte del contador
                    partes = albaran.numero.split('_')
                    if len(partes) == 2 and partes[0] == prefijo_completo:
                        contador_str = partes[1]
                        if contador_str.isdigit():
                            contadores.append(int(contador_str))
                except:
                    continue
        
        if contadores:
            siguiente_contador = max(contadores) + 1
        else:
            siguiente_contador = 1
    
    # Formatear el número completo: Aaamm_contador (con contador de 3 dígitos)
    numero_completo = f'{prefijo_completo}_{siguiente_contador:03d}'
    
    return numero_completo
