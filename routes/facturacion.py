"""Rutas para facturación"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, make_response
from flask_login import login_required
from datetime import datetime
from decimal import Decimal
import os
import requests
import json
import tempfile
import base64
from io import BytesIO
from sqlalchemy import not_
from extensions import db
from models import Factura, LineaFactura, Cliente, Presupuesto, LineaPresupuesto
from utils.numeracion import obtener_siguiente_numero_factura
from playwright.sync_api import sync_playwright

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
        # Obtener prefacturas: solicitudes aceptadas que aún no tienen factura formalizada
        # Filtrar solo facturas con presupuesto_id (excluir facturas directas)
        presupuestos_con_factura_ids = [f.presupuesto_id for f in Factura.query.with_entities(Factura.presupuesto_id).filter(Factura.presupuesto_id.isnot(None)).all()]
        
        # Obtener solicitudes (presupuestos) aceptadas sin factura
        query_solicitudes = Presupuesto.query.filter(Presupuesto.estado == 'aceptado')
        if presupuestos_con_factura_ids:
            query_solicitudes = query_solicitudes.filter(not_(Presupuesto.id.in_(presupuestos_con_factura_ids)))
        
        # Aplicar filtro de estado a solicitudes
        if estado_filtro:
            query_solicitudes = query_solicitudes.filter(Presupuesto.estado == estado_filtro)
        
        # Aplicar filtros de fecha a solicitudes
        if fecha_desde:
            try:
                fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
                query_solicitudes = query_solicitudes.filter(Presupuesto.fecha_creacion >= datetime.combine(fecha_desde_obj, datetime.min.time()))
            except ValueError:
                pass
        
        if fecha_hasta:
            try:
                fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
                query_solicitudes = query_solicitudes.filter(Presupuesto.fecha_creacion <= datetime.combine(fecha_hasta_obj, datetime.max.time()))
            except ValueError:
                pass
        
        solicitudes = query_solicitudes.order_by(Presupuesto.id.desc()).all()
        
        # Las solicitudes son las prefacturas
        prefacturas = list(solicitudes)
        # Ordenar por fecha de creación descendente
        prefacturas.sort(key=lambda x: x.fecha_creacion if x.fecha_creacion else datetime.min, reverse=True)
        
        # Obtener estados únicos de presupuestos para el filtro
        estados_presupuestos = db.session.query(Presupuesto.estado).distinct().all()
        estados_list = list(set([estado[0] for estado in estados_presupuestos if estado[0]]))
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

@facturacion_bp.route('/facturacion/solicitud/<int:presupuesto_id>')
@login_required
def ver_factura_solicitud(presupuesto_id):
    """Vista detallada de una factura para introducir importes desde una solicitud"""
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    
    # Verificar si ya existe una factura para este presupuesto
    factura_existente = Factura.query.filter_by(presupuesto_id=presupuesto_id).first()
    
    return render_template('ver_factura_solicitud.html', solicitud=presupuesto, factura_existente=factura_existente)

@facturacion_bp.route('/facturacion/solicitud/<int:presupuesto_id>/formalizar', methods=['POST'])
@login_required
def formalizar_factura_solicitud(presupuesto_id):
    """Formalizar una factura desde una solicitud y enviarla a Verifactu"""
    try:
        presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
        
        # Verificar si ya existe una factura para este presupuesto
        factura_existente = Factura.query.filter_by(presupuesto_id=presupuesto_id).first()
        if factura_existente:
            return jsonify({'success': False, 'error': 'Esta solicitud ya tiene una factura formalizada.'}), 400
        
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
        cliente = presupuesto.cliente if presupuesto.cliente else None
        factura = Factura(
            presupuesto_id=presupuesto_id,
            pedido_id=None,
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
        
        # Crear líneas de factura (usando lineas de presupuesto)
        for linea_data in lineas_data:
            linea_presupuesto_id = linea_data.get('linea_presupuesto_id')
            descripcion_linea = linea_data.get('descripcion', '')
            cantidad = Decimal(str(linea_data.get('cantidad', 1)))
            precio_unitario = Decimal(str(linea_data.get('precio_unitario', 0)))
            importe = Decimal(str(linea_data.get('importe', 0)))
            
            # Obtener descuento y precio_final de la línea de presupuesto si existe
            descuento = Decimal('0')
            precio_final = None
            if linea_presupuesto_id:
                linea_presupuesto = LineaPresupuesto.query.get(linea_presupuesto_id)
                if linea_presupuesto:
                    descuento = Decimal(str(linea_presupuesto.descuento)) if linea_presupuesto.descuento else Decimal('0')
                    precio_final = Decimal(str(linea_presupuesto.precio_final)) if linea_presupuesto.precio_final else None
            
            linea_factura = LineaFactura(
                factura_id=factura.id,
                linea_pedido_id=None,  # No hay línea de pedido, es de presupuesto
                descripcion=descripcion_linea,
                cantidad=cantidad,
                precio_unitario=precio_unitario,
                descuento=descuento,
                precio_final=precio_final,
                importe=importe
            )
            db.session.add(linea_factura)
        
        # Verificar si el envío a Verifactu está activado
        from models import Configuracion
        config = Configuracion.query.filter_by(clave='verifactu_enviar_activo').first()
        verifactu_enviar_activo = True  # Por defecto activado
        if config:
            verifactu_enviar_activo = config.valor.lower() == 'true'
        
        # Enviar a Verifactu solo si está activado y hay token
        verifactu_url = os.environ.get('VERIFACTU_URL', 'https://api.verifacti.com/verifactu/create')
        verifactu_token = os.environ.get('VERIFACTU_TOKEN', '')
        
        if verifactu_token and verifactu_enviar_activo:
            # Preparar datos para la API
            tipo_impositivo = 21  # IVA estándar en España
            lineas_payload = []
            total_base_imponible = Decimal('0.00')
            total_cuota_repercutida = Decimal('0.00')
            
            for linea in factura.lineas:
                importe_con_iva = Decimal(str(linea.importe))
                base_imponible = importe_con_iva / (Decimal('1') + Decimal(str(tipo_impositivo)) / Decimal('100'))
                cuota_repercutida = base_imponible * (Decimal(str(tipo_impositivo)) / Decimal('100'))
                
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
                factura.estado = 'error'
                factura.huella_verifactu = json.dumps({'error': str(e)})
                db.session.commit()
                return jsonify({
                    'success': False,
                    'error': f'Error de conexión con Verifactu: {str(e)}'
                }), 400
        elif not verifactu_enviar_activo:
            factura.estado = 'pendiente'
            db.session.commit()
            return jsonify({
                'success': True,
                'message': 'Factura creada. El envío automático a Verifactu está desactivado.',
                'factura_id': factura.id
            })
        else:
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
        
        # Verificar si el envío a Verifactu está activado
        from models import Configuracion
        config = Configuracion.query.filter_by(clave='verifactu_enviar_activo').first()
        verifactu_enviar_activo = True  # Por defecto activado
        if config:
            verifactu_enviar_activo = config.valor.lower() == 'true'
        
        # Enviar a Verifactu solo si está activado y hay token
        verifactu_url = os.environ.get('VERIFACTU_URL', 'https://api.verifacti.com/verifactu/create')
        verifactu_token = os.environ.get('VERIFACTU_TOKEN', '')
        
        if verifactu_token and verifactu_enviar_activo:
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
        elif not verifactu_enviar_activo:
            # Envío desactivado, solo guardar como pendiente
            factura.estado = 'pendiente'
            db.session.commit()
            return jsonify({
                'success': True,
                'message': 'Factura creada. El envío automático a Verifactu está desactivado.',
                'factura_id': factura.id
            })
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

@facturacion_bp.route('/facturacion/nueva', methods=['GET', 'POST'])
@login_required
def nueva_factura():
    """Crear una factura directamente sin pedido"""
    if request.method == 'POST':
        try:
            # Obtener datos del formulario
            fecha_expedicion_str = request.form.get('fecha_expedicion', '')
            tipo_factura = request.form.get('tipo_factura', 'F1')
            descripcion = request.form.get('descripcion', '')
            nombre_cliente = request.form.get('nombre_cliente', '')
            nif_cliente = request.form.get('nif_cliente', '')
            cliente_id = request.form.get('cliente_id', '')
            
            # Obtener líneas de factura
            descripciones = request.form.getlist('descripcion_linea[]')
            cantidades = request.form.getlist('cantidad[]')
            precios_unitarios = request.form.getlist('precio_unitario[]')
            
            if not fecha_expedicion_str:
                flash('La fecha de expedición es obligatoria', 'error')
                return redirect(url_for('facturacion.nueva_factura'))
            
            if not nombre_cliente:
                flash('El nombre del cliente es obligatorio', 'error')
                return redirect(url_for('facturacion.nueva_factura'))
            
            if not descripciones or not any(descripciones):
                flash('Debe haber al menos una línea en la factura', 'error')
                return redirect(url_for('facturacion.nueva_factura'))
            
            # Procesar fecha
            fecha_expedicion = datetime.strptime(fecha_expedicion_str, '%Y-%m-%d').date()
            
            # Si hay cliente_id, obtener datos del cliente
            if cliente_id:
                cliente = Cliente.query.get(cliente_id)
                if cliente:
                    nombre_cliente = cliente.nombre
                    if not nif_cliente and cliente.nif:
                        nif_cliente = cliente.nif
            
            # Generar número de factura automáticamente
            serie = 'A'
            numero = obtener_siguiente_numero_factura(fecha_expedicion)
            
            # Calcular importe total
            importe_total = Decimal('0.00')
            lineas_data = []
            for i in range(len(descripciones)):
                if descripciones[i]:
                    cantidad = Decimal(str(cantidades[i])) if i < len(cantidades) and cantidades[i] else Decimal('1')
                    precio_unitario = Decimal(str(precios_unitarios[i])) if i < len(precios_unitarios) and precios_unitarios[i] else Decimal('0')
                    importe = cantidad * precio_unitario
                    importe_total += importe
                    lineas_data.append({
                        'descripcion': descripciones[i],
                        'cantidad': cantidad,
                        'precio_unitario': precio_unitario,
                        'importe': importe
                    })
            
            # Crear factura sin pedido
            factura = Factura(
                pedido_id=None,  # Factura directa sin pedido
                serie=serie,
                numero=numero,
                fecha_expedicion=fecha_expedicion,
                tipo_factura=tipo_factura,
                descripcion=descripcion,
                nif=nif_cliente,
                nombre=nombre_cliente,
                importe_total=importe_total,
                estado='pendiente'
            )
            
            db.session.add(factura)
            db.session.flush()  # Para obtener el ID de la factura
            
            # Crear líneas de factura
            for linea_data in lineas_data:
                linea_factura = LineaFactura(
                    factura_id=factura.id,
                    linea_pedido_id=None,  # Sin línea de pedido asociada
                    descripcion=linea_data['descripcion'],
                    cantidad=linea_data['cantidad'],
                    precio_unitario=linea_data['precio_unitario'],
                    importe=linea_data['importe']
                )
                db.session.add(linea_factura)
            
            # Verificar si el envío a Verifactu está activado
            from models import Configuracion
            config = Configuracion.query.filter_by(clave='verifactu_enviar_activo').first()
            verifactu_enviar_activo = True  # Por defecto activado
            if config:
                verifactu_enviar_activo = config.valor.lower() == 'true'
            
            # Enviar a Verifactu solo si está activado y hay token
            verifactu_url = os.environ.get('VERIFACTU_URL', 'https://api.verifacti.com/verifactu/create')
            verifactu_token = os.environ.get('VERIFACTU_TOKEN', '')
            
            if verifactu_token and verifactu_enviar_activo:
                # Preparar datos para la API
                tipo_impositivo = 21  # IVA estándar en España
                lineas_payload = []
                total_base_imponible = Decimal('0.00')
                total_cuota_repercutida = Decimal('0.00')
                
                for linea_data in lineas_data:
                    importe_con_iva = linea_data['importe']
                    base_imponible = importe_con_iva / (Decimal('1') + Decimal(str(tipo_impositivo)) / Decimal('100'))
                    cuota_repercutida = base_imponible * (Decimal(str(tipo_impositivo)) / Decimal('100'))
                    
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
                        response_data = response.json()
                        factura.huella_verifactu = json.dumps(response_data)
                        factura.estado = 'confirmado'
                        db.session.commit()
                        flash('Factura creada y enviada a Verifactu correctamente.', 'success')
                    else:
                        factura.estado = 'error'
                        factura.huella_verifactu = json.dumps({
                            'error': response.text,
                            'status_code': response.status_code
                        })
                        db.session.commit()
                        flash(f'Error al enviar a Verifactu: {response.status_code} - {response.text}', 'error')
                except requests.exceptions.RequestException as e:
                    factura.estado = 'error'
                    factura.huella_verifactu = json.dumps({'error': str(e)})
                    db.session.commit()
                    flash(f'Error de conexión con Verifactu: {str(e)}', 'error')
            elif not verifactu_enviar_activo:
                factura.estado = 'pendiente'
                db.session.commit()
                flash('Factura creada. El envío automático a Verifactu está desactivado.', 'info')
            else:
                factura.estado = 'pendiente'
                db.session.commit()
                flash('Factura creada. Configure VERIFACTU_TOKEN para enviar automáticamente.', 'warning')
            
            return redirect(url_for('facturacion.facturacion', tipo_vista='formalizadas'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear la factura: {str(e)}', 'error')
            import traceback
            traceback.print_exc()
    
    # GET: mostrar formulario
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    # Establecer fecha de hoy por defecto
    fecha_hoy = datetime.now().strftime('%Y-%m-%d')
    return render_template('facturacion/nueva_factura.html', clientes=clientes, fecha_hoy=fecha_hoy)

def preparar_datos_imprimir_factura(factura_id):
    """Función auxiliar para preparar todos los datos necesarios para imprimir la factura"""
    from decimal import Decimal
    
    factura = Factura.query.get_or_404(factura_id)
    pedido = factura.pedido
    
    # Calcular totales usando precio_unitario y descuento de las líneas
    tipo_iva = 21
    base_imponible = Decimal('0.00')
    
    for linea in factura.lineas:
        cantidad = Decimal(str(linea.cantidad))
        precio_unitario = Decimal(str(linea.precio_unitario)) if linea.precio_unitario else Decimal('0.00')
        descuento = Decimal(str(linea.descuento)) if linea.descuento else Decimal('0')
        
        # Calcular precio final con descuento
        precio_final = precio_unitario
        if descuento > 0:
            precio_final = precio_unitario * (Decimal('1') - descuento / Decimal('100'))
        
        # Si hay precio_final guardado, usarlo
        if linea.precio_final:
            precio_final = Decimal(str(linea.precio_final))
        
        # Calcular total de la línea (sin IVA)
        total_linea = cantidad * precio_final
        base_imponible += total_linea
    
    iva_total = base_imponible * Decimal(str(tipo_iva)) / Decimal('100')
    iva_total = iva_total.quantize(Decimal('0.01'))
    total_con_iva = base_imponible + iva_total
    
    # Función auxiliar para convertir imagen a base64
    def convertir_imagen_a_base64(ruta_imagen):
        """Convertir imagen a base64"""
        if not ruta_imagen or not os.path.exists(ruta_imagen):
            return None
        try:
            with open(ruta_imagen, 'rb') as f:
                imagen_data = f.read()
                imagen_base64 = base64.b64encode(imagen_data).decode('utf-8')
                # Detectar tipo MIME
                if ruta_imagen.lower().endswith('.png'):
                    return f'data:image/png;base64,{imagen_base64}'
                elif ruta_imagen.lower().endswith(('.jpg', '.jpeg')):
                    return f'data:image/jpeg;base64,{imagen_base64}'
                elif ruta_imagen.lower().endswith('.gif'):
                    return f'data:image/gif;base64,{imagen_base64}'
                else:
                    return f'data:image/png;base64,{imagen_base64}'  # Por defecto PNG
        except Exception as e:
            print(f"Error al leer imagen {ruta_imagen}: {e}")
            return None
    
    # Convertir logo a base64
    logo_base64 = None
    logo_path = os.path.join(current_app.static_folder, 'logo.png')
    logo_base64 = convertir_imagen_a_base64(logo_path)
    
    return {
        'factura': factura,
        'pedido': pedido,
        'base_imponible': float(base_imponible),
        'iva_total': float(iva_total),
        'total_con_iva': float(total_con_iva),
        'tipo_iva': tipo_iva,
        'logo_base64': logo_base64
    }

@facturacion_bp.route('/facturacion/factura/<int:factura_id>/imprimir')
@login_required
def imprimir_factura(factura_id):
    """Vista de impresión de una factura formalizada"""
    datos = preparar_datos_imprimir_factura(factura_id)
    return render_template('imprimir_factura.html', **datos)

def preparar_datos_imprimir_albaran(factura_id=None, pedido_id=None):
    """Función auxiliar para preparar todos los datos necesarios para imprimir el albarán"""
    from decimal import Decimal
    
    if factura_id:
        # Si tenemos factura_id, obtener factura y pedido
        factura = Factura.query.get_or_404(factura_id)
        pedido = factura.pedido
        lineas = factura.lineas
    elif pedido_id:
        # Si solo tenemos pedido_id (prefactura), obtener pedido y usar sus líneas
        pedido = Pedido.query.get_or_404(pedido_id)
        factura = None
        lineas = pedido.lineas
    else:
        raise ValueError("Se debe proporcionar factura_id o pedido_id")
    
    # Función auxiliar para convertir imagen a base64
    def convertir_imagen_a_base64(ruta_imagen):
        """Convertir imagen a base64"""
        if not ruta_imagen or not os.path.exists(ruta_imagen):
            return None
        try:
            with open(ruta_imagen, 'rb') as f:
                imagen_data = f.read()
                imagen_base64 = base64.b64encode(imagen_data).decode('utf-8')
                # Detectar tipo MIME
                if ruta_imagen.lower().endswith('.png'):
                    return f'data:image/png;base64,{imagen_base64}'
                elif ruta_imagen.lower().endswith(('.jpg', '.jpeg')):
                    return f'data:image/jpeg;base64,{imagen_base64}'
                elif ruta_imagen.lower().endswith('.gif'):
                    return f'data:image/gif;base64,{imagen_base64}'
                else:
                    return f'data:image/png;base64,{imagen_base64}'  # Por defecto PNG
        except Exception as e:
            print(f"Error al leer imagen {ruta_imagen}: {e}")
            return None
    
    # Convertir logo a base64
    logo_base64 = None
    logo_path = os.path.join(current_app.static_folder, 'logo.png')
    logo_base64 = convertir_imagen_a_base64(logo_path)
    
    return {
        'factura': factura,
        'pedido': pedido,
        'lineas': lineas,
        'logo_base64': logo_base64
    }

@facturacion_bp.route('/facturacion/factura/<int:factura_id>/descargar-pdf')
@login_required
def descargar_pdf_factura(factura_id):
    """Descargar factura en formato PDF (con precios)"""
    try:
        datos = preparar_datos_imprimir_factura(factura_id)
        
        # Renderizar el HTML como factura (con precios)
        html = render_template('imprimir_factura_pdf.html', 
                             **datos,
                             use_base64=True,
                             es_albaran=False)
        
        # Crear el PDF en memoria usando playwright
        pdf_buffer = BytesIO()
        
        try:
            # Guardar HTML temporalmente para que playwright pueda acceder a él
            # Crear un archivo HTML temporal
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as temp_file:
                temp_file.write(html)
                temp_html_path = temp_file.name
            
            # Usar playwright para generar el PDF
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                # Cargar el HTML desde el archivo temporal
                page.goto(f'file://{temp_html_path}')
                
                # Generar PDF
                pdf_bytes = page.pdf(
                    format='A4',
                    print_background=True,
                    margin={
                        'top': '10mm',
                        'right': '10mm',
                        'bottom': '10mm',
                        'left': '10mm'
                    }
                )
                
                browser.close()
            
            # Escribir el PDF al buffer
            pdf_buffer.write(pdf_bytes)
            
            # Limpiar archivo temporal
            try:
                os.unlink(temp_html_path)
            except:
                pass
            
        except Exception as pdf_error:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Error al crear PDF con playwright: {error_trace}")
            flash(f'Error al generar PDF: {str(pdf_error)}', 'error')
            return redirect(url_for('facturacion.facturacion'))
        
        # Preparar la respuesta con el PDF
        pdf_buffer.seek(0)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=factura_{datos["factura"].serie}_{datos["factura"].numero}.pdf'
        
        return response
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error completo al generar PDF: {error_trace}")
        flash(f'Error al generar PDF: {str(e)}', 'error')
        return redirect(url_for('facturacion.facturacion'))

@facturacion_bp.route('/facturacion/factura/<int:factura_id>/descargar-albaran')
@login_required
def descargar_pdf_albaran_factura(factura_id):
    """Descargar albarán en formato PDF desde una factura formalizada"""
    try:
        datos = preparar_datos_imprimir_albaran(factura_id=factura_id)
        
        # Renderizar el HTML del albarán
        html = render_template('imprimir_albaran_pdf.html', 
                             **datos,
                             use_base64=True)
        
        # Crear el PDF en memoria usando playwright
        pdf_buffer = BytesIO()
        
        try:
            # Guardar HTML temporalmente para que playwright pueda acceder a él
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as temp_file:
                temp_file.write(html)
                temp_html_path = temp_file.name
            
            # Usar playwright para generar el PDF
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                # Cargar el HTML desde el archivo temporal
                page.goto(f'file://{temp_html_path}')
                
                # Generar PDF
                pdf_bytes = page.pdf(
                    format='A4',
                    print_background=True,
                    margin={
                        'top': '10mm',
                        'right': '10mm',
                        'bottom': '10mm',
                        'left': '10mm'
                    }
                )
                
                browser.close()
            
            # Escribir el PDF al buffer
            pdf_buffer.write(pdf_bytes)
            
            # Limpiar archivo temporal
            try:
                os.unlink(temp_html_path)
            except:
                pass
            
        except Exception as pdf_error:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Error al crear PDF con playwright: {error_trace}")
            flash(f'Error al generar PDF: {str(pdf_error)}', 'error')
            return redirect(url_for('facturacion.facturacion'))
        
        # Preparar la respuesta con el PDF
        pdf_buffer.seek(0)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        numero_pedido = datos['pedido'].id if datos['pedido'] else 'N/A'
        response.headers['Content-Disposition'] = f'inline; filename=albaran_pedido_{numero_pedido}.pdf'
        
        return response
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error completo al generar PDF: {error_trace}")
        flash(f'Error al generar PDF: {str(e)}', 'error')
        return redirect(url_for('facturacion.facturacion'))

@facturacion_bp.route('/facturacion/pedido/<int:pedido_id>/descargar-albaran')
@login_required
def descargar_pdf_albaran_pedido(pedido_id):
    """Descargar albarán en formato PDF desde un pedido (prefactura)"""
    try:
        datos = preparar_datos_imprimir_albaran(pedido_id=pedido_id)
        
        # Renderizar el HTML del albarán
        html = render_template('imprimir_albaran_pdf.html', 
                             **datos,
                             use_base64=True)
        
        # Crear el PDF en memoria usando playwright
        pdf_buffer = BytesIO()
        
        try:
            # Guardar HTML temporalmente para que playwright pueda acceder a él
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as temp_file:
                temp_file.write(html)
                temp_html_path = temp_file.name
            
            # Usar playwright para generar el PDF
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                # Cargar el HTML desde el archivo temporal
                page.goto(f'file://{temp_html_path}')
                
                # Generar PDF
                pdf_bytes = page.pdf(
                    format='A4',
                    print_background=True,
                    margin={
                        'top': '10mm',
                        'right': '10mm',
                        'bottom': '10mm',
                        'left': '10mm'
                    }
                )
                
                browser.close()
            
            # Escribir el PDF al buffer
            pdf_buffer.write(pdf_bytes)
            
            # Limpiar archivo temporal
            try:
                os.unlink(temp_html_path)
            except:
                pass
            
        except Exception as pdf_error:
            import traceback
            error_trace = traceback.format_exc()
            print(f"Error al crear PDF con playwright: {error_trace}")
            flash(f'Error al generar PDF: {str(pdf_error)}', 'error')
            return redirect(url_for('facturacion.facturacion'))
        
        # Preparar la respuesta con el PDF
        pdf_buffer.seek(0)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=albaran_pedido_{pedido_id}.pdf'
        
        return response
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error completo al generar PDF: {error_trace}")
        flash(f'Error al generar PDF: {str(e)}', 'error')
        return redirect(url_for('facturacion.facturacion'))

