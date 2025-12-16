"""Rutas para facturación"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from datetime import datetime
from decimal import Decimal
import os
import requests
import json
from sqlalchemy import not_
from extensions import db
from models import Pedido, LineaPedido, Factura, LineaFactura
from utils.numeracion import obtener_siguiente_numero_factura

facturacion_bp = Blueprint('facturacion', __name__)

@facturacion_bp.route('/facturacion')
@login_required
def facturacion():
    """Página de facturación con prefacturas (pendientes) y facturas (formalizadas)"""
    # Tipo de vista: 'pendientes' o 'formalizadas'
    tipo_vista = request.args.get('tipo_vista', 'pendientes')
    
    # Filtro por estado
    estado_filtro = request.args.get('estado', '')
    
    # Filtros de fecha
    fecha_desde = request.args.get('fecha_desde', '')
    fecha_hasta = request.args.get('fecha_hasta', '')
    
    prefacturas = []
    facturas = []
    
    if tipo_vista == 'pendientes':
        # Obtener prefacturas: pedidos que aún no tienen factura formalizada
        pedidos_con_factura_ids = [f.pedido_id for f in Factura.query.with_entities(Factura.pedido_id).all()]
        query = Pedido.query
        if pedidos_con_factura_ids:
            query = query.filter(not_(Pedido.id.in_(pedidos_con_factura_ids)))
        
        # Aplicar filtro de estado
        if estado_filtro:
            query = query.filter(Pedido.estado == estado_filtro)
        
        # Aplicar filtros de fecha
        if fecha_desde:
            try:
                fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
                query = query.filter(Pedido.fecha_creacion >= datetime.combine(fecha_desde_obj, datetime.min.time()))
            except ValueError:
                pass
        
        if fecha_hasta:
            try:
                fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
                query = query.filter(Pedido.fecha_creacion <= datetime.combine(fecha_hasta_obj, datetime.max.time()))
            except ValueError:
                pass
        
        prefacturas = query.order_by(Pedido.id.desc()).all()
        
        # Obtener estados únicos de pedidos para el filtro
        estados = db.session.query(Pedido.estado).distinct().all()
        estados_list = [estado[0] for estado in estados if estado[0]]
    else:
        # Obtener facturas formalizadas
        query = Factura.query
        
        # Aplicar filtro de estado
        if estado_filtro:
            query = query.filter(Factura.estado == estado_filtro)
        
        # Aplicar filtros de fecha
        if fecha_desde:
            try:
                fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
                query = query.filter(Factura.fecha_expedicion >= fecha_desde_obj)
            except ValueError:
                pass
        
        if fecha_hasta:
            try:
                fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
                query = query.filter(Factura.fecha_expedicion <= fecha_hasta_obj)
            except ValueError:
                pass
        
        facturas = query.order_by(Factura.fecha_creacion.desc()).all()
        
        # Obtener estados únicos de facturas para el filtro
        estados = db.session.query(Factura.estado).distinct().all()
        estados_list = [estado[0] for estado in estados if estado[0]]
    
    return render_template('facturacion.html', 
                         prefacturas=prefacturas, 
                         facturas=facturas,
                         estados=estados_list,
                         tipo_vista=tipo_vista,
                         estado_filtro=estado_filtro,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta)

@facturacion_bp.route('/facturacion/<int:pedido_id>')
@login_required
def ver_factura(pedido_id):
    """Vista detallada de una factura para introducir importes"""
    pedido = Pedido.query.get_or_404(pedido_id)
    
    # Verificar si ya existe una factura para este pedido
    factura_existente = Factura.query.filter_by(pedido_id=pedido_id).first()
    
    return render_template('ver_factura.html', pedido=pedido, factura_existente=factura_existente)

@facturacion_bp.route('/facturacion/<int:pedido_id>/formalizar', methods=['POST'])
@login_required
def formalizar_factura(pedido_id):
    """Formalizar una factura y enviarla a Verifactu"""
    try:
        pedido = Pedido.query.get_or_404(pedido_id)
        
        # Verificar si ya existe una factura para este pedido
        factura_existente = Factura.query.filter_by(pedido_id=pedido_id).first()
        if factura_existente:
            flash('Este pedido ya tiene una factura formalizada.', 'warning')
            return redirect(url_for('facturacion.ver_factura', pedido_id=pedido_id))
        
        # Obtener datos del formulario
        data = request.get_json()
        
        fecha_expedicion_str = data.get('fecha_expedicion', '')
        descripcion = data.get('descripcion', '')
        lineas_data = data.get('lineas', [])
        
        if not fecha_expedicion_str:
            return jsonify({'success': False, 'error': 'La fecha de expedición es obligatoria'}), 400
        
        if not lineas_data:
            return jsonify({'success': False, 'error': 'Debe haber al menos una línea con importe'}), 400
        
        # Procesar fecha
        fecha_expedicion = datetime.strptime(fecha_expedicion_str, '%Y-%m-%d').date()
        
        # Generar número de factura automáticamente
        serie = 'A'  # Serie fija
        numero = obtener_siguiente_numero_factura(fecha_expedicion)
        
        # Calcular importe total
        importe_total = Decimal('0.00')
        for linea_data in lineas_data:
            importe = Decimal(str(linea_data.get('importe', 0)))
            importe_total += importe
        
        # Crear factura
        cliente = pedido.cliente if pedido.cliente else None
        factura = Factura(
            pedido_id=pedido_id,
            serie=serie,
            numero=numero,
            fecha_expedicion=fecha_expedicion,
            tipo_factura='F1',  # Factura completa
            descripcion=descripcion,
            nif=cliente.nif if cliente and cliente.nif else '',
            nombre=cliente.nombre if cliente else 'Sin cliente',
            importe_total=importe_total,
            estado='pendiente'
        )
        
        db.session.add(factura)
        db.session.flush()  # Para obtener el ID de la factura
        
        # Crear líneas de factura
        for linea_data in lineas_data:
            linea_pedido_id = linea_data.get('linea_pedido_id')
            descripcion_linea = linea_data.get('descripcion', '')
            cantidad = Decimal(str(linea_data.get('cantidad', 1)))
            precio_unitario = Decimal(str(linea_data.get('precio_unitario', 0)))
            importe = Decimal(str(linea_data.get('importe', 0)))
            
            linea_factura = LineaFactura(
                factura_id=factura.id,
                linea_pedido_id=linea_pedido_id,
                descripcion=descripcion_linea,
                cantidad=cantidad,
                precio_unitario=precio_unitario,
                importe=importe
            )
            db.session.add(linea_factura)
        
        # Enviar a Verifactu
        verifactu_url = os.environ.get('VERIFACTU_URL', 'https://api.verifacti.com/verifactu/create')
        verifactu_token = os.environ.get('VERIFACTU_TOKEN', '')
        
        if verifactu_token:
            # Preparar datos para la API
            # Calcular base imponible e IVA para cada línea
            # Asumimos que el importe incluye IVA al 21%
            tipo_impositivo = 21  # IVA estándar en España
            lineas_payload = []
            total_base_imponible = Decimal('0.00')
            total_cuota_repercutida = Decimal('0.00')
            
            for linea in factura.lineas:
                # Si el importe incluye IVA, calcular base imponible
                importe_con_iva = Decimal(str(linea.importe))
                # Calcular base imponible: importe / (1 + tipo_impositivo/100)
                base_imponible = importe_con_iva / (Decimal('1') + Decimal(str(tipo_impositivo)) / Decimal('100'))
                # Calcular cuota repercutida: base_imponible * (tipo_impositivo/100)
                cuota_repercutida = base_imponible * (Decimal(str(tipo_impositivo)) / Decimal('100'))
                
                # Redondear a 2 decimales
                base_imponible = base_imponible.quantize(Decimal('0.01'))
                cuota_repercutida = cuota_repercutida.quantize(Decimal('0.01'))
                
                total_base_imponible += base_imponible
                total_cuota_repercutida += cuota_repercutida
                
                lineas_payload.append({
                    'base_imponible': str(base_imponible),
                    'tipo_impositivo': str(tipo_impositivo),
                    'cuota_repercutida': str(cuota_repercutida)
                })
            
            payload = {
                'serie': factura.serie,
                'numero': factura.numero,
                'fecha_expedicion': factura.fecha_expedicion.strftime('%d-%m-%Y'),
                'tipo_factura': factura.tipo_factura,
                'descripcion': factura.descripcion or 'Descripcion de la operacion',
                'nif': factura.nif or '',
                'nombre': factura.nombre,
                'lineas': lineas_payload,
                'importe_total': str(factura.importe_total)
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {verifactu_token}'
            }
            
            try:
                response = requests.post(verifactu_url, json=payload, headers=headers, timeout=30)
                
                if response.status_code == 200 or response.status_code == 201:
                    # Éxito: guardar la huella
                    response_data = response.json()
                    factura.huella_verifactu = json.dumps(response_data)
                    factura.estado = 'confirmado'
                    factura.fecha_confirmacion = datetime.utcnow()
                    db.session.commit()
                    return jsonify({
                        'success': True,
                        'message': 'Factura formalizada y enviada a Verifactu correctamente.',
                        'factura_id': factura.id
                    })
                else:
                    # Error en la API
                    factura.estado = 'error'
                    factura.huella_verifactu = json.dumps({
                        'error': response.text,
                        'status_code': response.status_code
                    })
                    db.session.commit()
                    return jsonify({
                        'success': False,
                        'error': f'Error al enviar a Verifactu: {response.status_code} - {response.text}'
                    }), 400
            except requests.exceptions.RequestException as e:
                # Error de conexión
                factura.estado = 'error'
                factura.huella_verifactu = json.dumps({'error': str(e)})
                db.session.commit()
                return jsonify({
                    'success': False,
                    'error': f'Error de conexión con Verifactu: {str(e)}'
                }), 400
        else:
            # Sin token, solo guardar como pendiente
            factura.estado = 'pendiente'
            db.session.commit()
            return jsonify({
                'success': True,
                'message': 'Factura creada. Configure VERIFACTU_TOKEN para enviar automáticamente.',
                'factura_id': factura.id
            })
            
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Error al formalizar la factura: {str(e)}'
        }), 500

@facturacion_bp.route('/facturacion/factura/<int:factura_id>/imprimir')
@login_required
def imprimir_factura(factura_id):
    """Vista de impresión de una factura formalizada"""
    from decimal import Decimal
    
    factura = Factura.query.get_or_404(factura_id)
    pedido = factura.pedido
    
    # Calcular totales
    tipo_iva = 21
    base_imponible = Decimal('0.00')
    
    for linea in factura.lineas:
        importe = Decimal(str(linea.importe))
        # Si el importe incluye IVA, calcular base imponible
        base_linea = importe / (Decimal('1') + Decimal(str(tipo_iva)) / Decimal('100'))
        base_imponible += base_linea.quantize(Decimal('0.01'))
    
    iva_total = base_imponible * Decimal(str(tipo_iva)) / Decimal('100')
    iva_total = iva_total.quantize(Decimal('0.01'))
    total_con_iva = base_imponible + iva_total
    
    return render_template('imprimir_factura.html', 
                         factura=factura,
                         pedido=pedido,
                         base_imponible=base_imponible,
                         iva_total=iva_total,
                         total_con_iva=total_con_iva,
                         tipo_iva=tipo_iva)

