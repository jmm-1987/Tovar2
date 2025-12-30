"""Rutas para informes y reportes"""
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from datetime import datetime
from decimal import Decimal
from extensions import db
from models import Factura, FacturaProveedor, Nomina, Empleado, LineaFactura
from sqlalchemy import func, extract
from utils.auth import not_usuario_required

informes_bp = Blueprint('informes', __name__)

@informes_bp.route('/informes')
@login_required
@not_usuario_required
def index():
    """Página principal de informes"""
    return render_template('informes/index.html')

@informes_bp.route('/informes/facturacion-emitida')
@login_required
@not_usuario_required
def facturacion_emitida():
    """Informe de facturación emitida con filtros por mes o trimestre"""
    # Obtener parámetros de filtro
    tipo_filtro = request.args.get('tipo', 'mes')  # 'mes' o 'trimestre'
    año = request.args.get('año', datetime.now().year, type=int)
    periodo = request.args.get('periodo', None, type=int)
    
    # Base query
    query = Factura.query.filter(extract('year', Factura.fecha_expedicion) == año)
    
    if tipo_filtro == 'mes' and periodo:
        query = query.filter(extract('month', Factura.fecha_expedicion) == periodo)
        periodo_label = f"{['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'][periodo]} {año}"
    elif tipo_filtro == 'trimestre' and periodo:
        mes_inicio = (periodo - 1) * 3 + 1
        mes_fin = periodo * 3
        query = query.filter(extract('month', Factura.fecha_expedicion).between(mes_inicio, mes_fin))
        trimestres = {1: '1T', 2: '2T', 3: '3T', 4: '4T'}
        periodo_label = f"{trimestres.get(periodo, '')} {año}"
    else:
        periodo_label = f"Año {año}"
    
    facturas = query.order_by(Factura.fecha_expedicion.desc()).all()
    
    # Calcular totales
    total_facturacion = sum(f.importe_total for f in facturas)
    total_iva_repercutido = Decimal('0')
    tipo_iva = Decimal('21')  # IVA estándar al 21%
    
    # Calcular IVA repercutido desde las líneas de factura
    # Asumimos que el importe incluye IVA al 21%
    for factura in facturas:
        for linea in factura.lineas:
            importe_con_iva = Decimal(str(linea.importe))
            # Calcular base imponible: importe / (1 + tipo_iva/100)
            base_imponible = importe_con_iva / (Decimal('1') + tipo_iva / Decimal('100'))
            # Calcular IVA repercutido: base_imponible * (tipo_iva/100)
            iva_linea = base_imponible * tipo_iva / Decimal('100')
            total_iva_repercutido += iva_linea.quantize(Decimal('0.01'))
    
    return render_template('informes/facturacion_emitida.html', 
                         facturas=facturas,
                         total_facturacion=total_facturacion,
                         total_iva_repercutido=total_iva_repercutido,
                         tipo_filtro=tipo_filtro,
                         año=año,
                         periodo=periodo,
                         periodo_label=periodo_label)

@informes_bp.route('/informes/facturacion-soportada')
@login_required
@not_usuario_required
def facturacion_soportada():
    """Informe de facturación soportada (facturas de proveedor) con filtros por mes o trimestre"""
    # Obtener parámetros de filtro
    tipo_filtro = request.args.get('tipo', 'mes')  # 'mes' o 'trimestre'
    año = request.args.get('año', datetime.now().year, type=int)
    periodo = request.args.get('periodo', None, type=int)
    
    # Base query
    query = FacturaProveedor.query.filter(extract('year', FacturaProveedor.fecha_factura) == año)
    
    if tipo_filtro == 'mes' and periodo:
        query = query.filter(extract('month', FacturaProveedor.fecha_factura) == periodo)
        periodo_label = f"{['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'][periodo]} {año}"
    elif tipo_filtro == 'trimestre' and periodo:
        mes_inicio = (periodo - 1) * 3 + 1
        mes_fin = periodo * 3
        query = query.filter(extract('month', FacturaProveedor.fecha_factura).between(mes_inicio, mes_fin))
        trimestres = {1: '1T', 2: '2T', 3: '3T', 4: '4T'}
        periodo_label = f"{trimestres.get(periodo, '')} {año}"
    else:
        periodo_label = f"Año {año}"
    
    facturas = query.order_by(FacturaProveedor.fecha_factura.desc()).all()
    
    # Calcular totales
    total_facturacion = sum(f.total for f in facturas)
    total_base_imponible = sum(f.base_imponible for f in facturas)
    total_iva_soportado = sum(f.importe_iva for f in facturas)
    
    return render_template('informes/facturacion_soportada.html',
                         facturas=facturas,
                         total_facturacion=total_facturacion,
                         total_base_imponible=total_base_imponible,
                         total_iva_soportado=total_iva_soportado,
                         tipo_filtro=tipo_filtro,
                         año=año,
                         periodo=periodo,
                         periodo_label=periodo_label)

@informes_bp.route('/informes/nominas')
@login_required
@not_usuario_required
def nominas():
    """Informe de nóminas por empleado y global"""
    # Obtener parámetros de filtro
    empleado_id = request.args.get('empleado_id', None, type=int)
    año = request.args.get('año', datetime.now().year, type=int)
    
    # Base query
    query = Nomina.query.filter(Nomina.año == año)
    
    if empleado_id:
        query = query.filter(Nomina.empleado_id == empleado_id)
    
    nominas = query.order_by(Nomina.mes.desc(), Nomina.empleado_id).all()
    
    # Calcular totales
    total_global = sum(n.total_devengado for n in nominas)
    
    # Totales por empleado
    totales_por_empleado = {}
    for nomina in nominas:
        empleado_nombre = nomina.empleado.nombre if nomina.empleado else 'Sin empleado'
        if empleado_nombre not in totales_por_empleado:
            totales_por_empleado[empleado_nombre] = Decimal('0')
        totales_por_empleado[empleado_nombre] += nomina.total_devengado
    
    # Obtener lista de empleados para el filtro
    empleados = Empleado.query.order_by(Empleado.nombre).all()
    
    return render_template('informes/nominas.html',
                         nominas=nominas,
                         total_global=total_global,
                         totales_por_empleado=totales_por_empleado,
                         empleados=empleados,
                         empleado_id=empleado_id,
                         año=año)

@informes_bp.route('/informes/iva')
@login_required
@not_usuario_required
def iva():
    """Informe de IVA: contrastar IVA repercutido vs IVA soportado"""
    # Obtener parámetros de filtro
    tipo_filtro = request.args.get('tipo', 'mes')  # 'mes' o 'trimestre'
    año = request.args.get('año', datetime.now().year, type=int)
    periodo = request.args.get('periodo', None, type=int)
    
    # Calcular IVA repercutido (de facturas emitidas)
    query_facturas = Factura.query.filter(extract('year', Factura.fecha_expedicion) == año)
    
    if tipo_filtro == 'mes' and periodo:
        query_facturas = query_facturas.filter(extract('month', Factura.fecha_expedicion) == periodo)
        periodo_label = f"{['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'][periodo]} {año}"
    elif tipo_filtro == 'trimestre' and periodo:
        mes_inicio = (periodo - 1) * 3 + 1
        mes_fin = periodo * 3
        query_facturas = query_facturas.filter(extract('month', Factura.fecha_expedicion).between(mes_inicio, mes_fin))
        trimestres = {1: '1T', 2: '2T', 3: '3T', 4: '4T'}
        periodo_label = f"{trimestres.get(periodo, '')} {año}"
    else:
        periodo_label = f"Año {año}"
    
    facturas_emitidas = query_facturas.all()
    iva_repercutido = Decimal('0')
    base_repercutida = Decimal('0')
    tipo_iva = Decimal('21')  # IVA estándar al 21%
    
    for factura in facturas_emitidas:
        for linea in factura.lineas:
            importe_con_iva = Decimal(str(linea.importe))
            # Calcular base imponible: importe / (1 + tipo_iva/100)
            base_imponible = importe_con_iva / (Decimal('1') + tipo_iva / Decimal('100'))
            base_imponible = base_imponible.quantize(Decimal('0.01'))
            base_repercutida += base_imponible
            # Calcular IVA repercutido: base_imponible * (tipo_iva/100)
            iva_linea = base_imponible * tipo_iva / Decimal('100')
            iva_repercutido += iva_linea.quantize(Decimal('0.01'))
    
    # Calcular IVA soportado (de facturas de proveedor)
    query_facturas_prov = FacturaProveedor.query.filter(extract('year', FacturaProveedor.fecha_factura) == año)
    
    if tipo_filtro == 'mes' and periodo:
        query_facturas_prov = query_facturas_prov.filter(extract('month', FacturaProveedor.fecha_factura) == periodo)
    elif tipo_filtro == 'trimestre' and periodo:
        mes_inicio = (periodo - 1) * 3 + 1
        mes_fin = periodo * 3
        query_facturas_prov = query_facturas_prov.filter(extract('month', FacturaProveedor.fecha_factura).between(mes_inicio, mes_fin))
    
    facturas_proveedor = query_facturas_prov.all()
    iva_soportado = sum(f.importe_iva for f in facturas_proveedor)
    base_soportada = sum(f.base_imponible for f in facturas_proveedor)
    
    # Calcular diferencia
    diferencia_iva = iva_repercutido - iva_soportado
    
    return render_template('informes/iva.html',
                         iva_repercutido=iva_repercutido,
                         base_repercutida=base_repercutida,
                         iva_soportado=iva_soportado,
                         base_soportada=base_soportada,
                         diferencia_iva=diferencia_iva,
                         tipo_filtro=tipo_filtro,
                         año=año,
                         periodo=periodo,
                         periodo_label=periodo_label,
                         num_facturas_emitidas=len(facturas_emitidas),
                         num_facturas_proveedor=len(facturas_proveedor))

@informes_bp.route('/informes/facturacion-emitida/detalle')
@login_required
@not_usuario_required
def facturacion_emitida_detalle():
    """Detalle de facturación emitida con listado completo de facturas"""
    # Obtener parámetros de filtro (mismos que en el informe principal)
    tipo_filtro = request.args.get('tipo', 'mes')
    año = request.args.get('año', datetime.now().year, type=int)
    periodo = request.args.get('periodo', None, type=int)
    
    # Base query
    query = Factura.query.filter(extract('year', Factura.fecha_expedicion) == año)
    
    if tipo_filtro == 'mes' and periodo:
        query = query.filter(extract('month', Factura.fecha_expedicion) == periodo)
        periodo_label = f"{['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'][periodo]} {año}"
    elif tipo_filtro == 'trimestre' and periodo:
        mes_inicio = (periodo - 1) * 3 + 1
        mes_fin = periodo * 3
        query = query.filter(extract('month', Factura.fecha_expedicion).between(mes_inicio, mes_fin))
        trimestres = {1: '1T', 2: '2T', 3: '3T', 4: '4T'}
        periodo_label = f"{trimestres.get(periodo, '')} {año}"
    else:
        periodo_label = f"Año {año}"
    
    facturas = query.order_by(Factura.fecha_expedicion.desc()).all()
    
    return render_template('informes/detalle_facturacion_emitida.html',
                         facturas=facturas,
                         tipo_filtro=tipo_filtro,
                         año=año,
                         periodo=periodo,
                         periodo_label=periodo_label)

@informes_bp.route('/informes/facturacion-soportada/detalle')
@login_required
@not_usuario_required
def facturacion_soportada_detalle():
    """Detalle de facturación soportada con listado completo de facturas de proveedor"""
    # Obtener parámetros de filtro
    tipo_filtro = request.args.get('tipo', 'mes')
    año = request.args.get('año', datetime.now().year, type=int)
    periodo = request.args.get('periodo', None, type=int)
    
    # Base query
    query = FacturaProveedor.query.filter(extract('year', FacturaProveedor.fecha_factura) == año)
    
    if tipo_filtro == 'mes' and periodo:
        query = query.filter(extract('month', FacturaProveedor.fecha_factura) == periodo)
        periodo_label = f"{['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'][periodo]} {año}"
    elif tipo_filtro == 'trimestre' and periodo:
        mes_inicio = (periodo - 1) * 3 + 1
        mes_fin = periodo * 3
        query = query.filter(extract('month', FacturaProveedor.fecha_factura).between(mes_inicio, mes_fin))
        trimestres = {1: '1T', 2: '2T', 3: '3T', 4: '4T'}
        periodo_label = f"{trimestres.get(periodo, '')} {año}"
    else:
        periodo_label = f"Año {año}"
    
    facturas = query.order_by(FacturaProveedor.fecha_factura.desc()).all()
    
    return render_template('informes/detalle_facturacion_soportada.html',
                         facturas=facturas,
                         tipo_filtro=tipo_filtro,
                         año=año,
                         periodo=periodo,
                         periodo_label=periodo_label)

@informes_bp.route('/informes/nominas/detalle')
@login_required
@not_usuario_required
def nominas_detalle():
    """Detalle de nóminas con listado completo"""
    # Obtener parámetros de filtro
    empleado_id = request.args.get('empleado_id', None, type=int)
    año = request.args.get('año', datetime.now().year, type=int)
    
    # Base query
    query = Nomina.query.filter(Nomina.año == año)
    
    if empleado_id:
        query = query.filter(Nomina.empleado_id == empleado_id)
    
    nominas = query.order_by(Nomina.mes.desc(), Nomina.empleado_id).all()
    
    # Obtener lista de empleados para el filtro
    empleados = Empleado.query.order_by(Empleado.nombre).all()
    empleado_seleccionado = Empleado.query.get(empleado_id) if empleado_id else None
    
    return render_template('informes/detalle_nominas.html',
                         nominas=nominas,
                         empleados=empleados,
                         empleado_id=empleado_id,
                         empleado_seleccionado=empleado_seleccionado,
                         año=año)

@informes_bp.route('/informes/iva/detalle')
@login_required
@not_usuario_required
def iva_detalle():
    """Detalle de IVA con listado completo de facturas emitidas y de proveedor"""
    # Obtener parámetros de filtro
    tipo_filtro = request.args.get('tipo', 'mes')
    año = request.args.get('año', datetime.now().year, type=int)
    periodo = request.args.get('periodo', None, type=int)
    
    # Calcular IVA repercutido (de facturas emitidas)
    query_facturas = Factura.query.filter(extract('year', Factura.fecha_expedicion) == año)
    
    if tipo_filtro == 'mes' and periodo:
        query_facturas = query_facturas.filter(extract('month', Factura.fecha_expedicion) == periodo)
        periodo_label = f"{['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'][periodo]} {año}"
    elif tipo_filtro == 'trimestre' and periodo:
        mes_inicio = (periodo - 1) * 3 + 1
        mes_fin = periodo * 3
        query_facturas = query_facturas.filter(extract('month', Factura.fecha_expedicion).between(mes_inicio, mes_fin))
        trimestres = {1: '1T', 2: '2T', 3: '3T', 4: '4T'}
        periodo_label = f"{trimestres.get(periodo, '')} {año}"
    else:
        periodo_label = f"Año {año}"
    
    facturas_emitidas = query_facturas.order_by(Factura.fecha_expedicion.desc()).all()
    
    # Calcular IVA soportado (de facturas de proveedor)
    query_facturas_prov = FacturaProveedor.query.filter(extract('year', FacturaProveedor.fecha_factura) == año)
    
    if tipo_filtro == 'mes' and periodo:
        query_facturas_prov = query_facturas_prov.filter(extract('month', FacturaProveedor.fecha_factura) == periodo)
    elif tipo_filtro == 'trimestre' and periodo:
        mes_inicio = (periodo - 1) * 3 + 1
        mes_fin = periodo * 3
        query_facturas_prov = query_facturas_prov.filter(extract('month', FacturaProveedor.fecha_factura).between(mes_inicio, mes_fin))
    
    facturas_proveedor = query_facturas_prov.order_by(FacturaProveedor.fecha_factura.desc()).all()
    
    # Precalcular totales para evitar problemas de tipo en las plantillas
    tipo_iva_decimal = Decimal('21')
    total_base_emitida = Decimal('0')
    total_iva_emitido = Decimal('0')
    total_facturacion_emitida = Decimal('0')
    
    for factura in facturas_emitidas:
        total_facturacion_emitida += Decimal(str(factura.importe_total))
        for linea in factura.lineas:
            importe_con_iva = Decimal(str(linea.importe))
            base_imponible = importe_con_iva / (Decimal('1') + tipo_iva_decimal / Decimal('100'))
            base_imponible = base_imponible.quantize(Decimal('0.01'))
            total_base_emitida += base_imponible
            iva_linea = base_imponible * tipo_iva_decimal / Decimal('100')
            total_iva_emitido += iva_linea.quantize(Decimal('0.01'))
    
    total_base_soportada = sum(Decimal(str(f.base_imponible)) for f in facturas_proveedor)
    total_iva_soportado = sum(Decimal(str(f.importe_iva)) for f in facturas_proveedor)
    total_facturacion_soportada = sum(Decimal(str(f.total)) for f in facturas_proveedor)
    
    return render_template('informes/detalle_iva.html',
                         facturas_emitidas=facturas_emitidas,
                         facturas_proveedor=facturas_proveedor,
                         tipo_filtro=tipo_filtro,
                         año=año,
                         periodo=periodo,
                         periodo_label=periodo_label,
                         tipo_iva_decimal=tipo_iva_decimal,
                         total_base_emitida=total_base_emitida,
                         total_iva_emitido=total_iva_emitido,
                         total_facturacion_emitida=total_facturacion_emitida,
                         total_base_soportada=total_base_soportada,
                         total_iva_soportado=total_iva_soportado,
                         total_facturacion_soportada=total_facturacion_soportada)

