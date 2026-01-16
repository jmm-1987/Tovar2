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
from models import Factura, LineaFactura, Cliente, Presupuesto, LineaPresupuesto, Pedido
from utils.numeracion import obtener_siguiente_numero_factura, obtener_siguiente_numero_albaran
from playwright.sync_api import sync_playwright
from utils.auth import not_usuario_required

facturacion_bp = Blueprint('facturacion', __name__)

@facturacion_bp.route('/facturacion')
@login_required
@not_usuario_required
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
        
        # Obtener albaranes: facturas pendientes con número que empieza con 'A' seguido de año y mes (formato A2601_XXX)
        # Los albaranes son facturas directas (sin presupuesto_id ni pedido_id) con estado='pendiente'
        from sqlalchemy import and_
        
        query_albaranes = Factura.query.filter(
            and_(
                Factura.estado == 'pendiente',
                Factura.presupuesto_id.is_(None),
                Factura.pedido_id.is_(None),
                Factura.numero.like('A%_%')  # Formato: A2601_001, A2601_002, etc.
            )
        )
        
        # Aplicar filtros de fecha a albaranes
        if fecha_desde:
            try:
                fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
                query_albaranes = query_albaranes.filter(Factura.fecha_expedicion >= fecha_desde_obj)
            except ValueError:
                pass
        
        if fecha_hasta:
            try:
                fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
                query_albaranes = query_albaranes.filter(Factura.fecha_expedicion <= fecha_hasta_obj)
            except ValueError:
                pass
        
        albaranes = query_albaranes.order_by(Factura.fecha_creacion.desc()).all()
        
        # Las solicitudes son las prefacturas
        prefacturas = list(solicitudes)
        # Agregar albaranes a las prefacturas
        prefacturas.extend(albaranes)
        # Ordenar por fecha de creación descendente
        def obtener_fecha_ordenacion(item):
            if hasattr(item, 'fecha_creacion') and item.fecha_creacion:
                return item.fecha_creacion
            elif hasattr(item, 'fecha_expedicion') and item.fecha_expedicion:
                return datetime.combine(item.fecha_expedicion, datetime.min.time())
            elif hasattr(item, 'fecha_aceptado') and item.fecha_aceptado:
                return datetime.combine(item.fecha_aceptado, datetime.min.time())
            else:
                return datetime.min
        
        prefacturas.sort(key=obtener_fecha_ordenacion, reverse=True)
        
        # Obtener estados únicos de presupuestos para el filtro
        estados_presupuestos = db.session.query(Presupuesto.estado).distinct().all()
        estados_list = list(set([estado[0] for estado in estados_presupuestos if estado[0]]))
    else:
        # Obtener facturas formalizadas (excluir albaranes)
        from sqlalchemy import and_
        query = Factura.query.filter(
            # Excluir albaranes: facturas con número en formato A2601_XXX
            not_(Factura.numero.like('A%_%'))
        )
        
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
@not_usuario_required
def ver_factura_solicitud(presupuesto_id):
    """Vista detallada de una factura para introducir importes desde una solicitud"""
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    
    # Verificar si ya existe una factura para este presupuesto
    factura_existente = Factura.query.filter_by(presupuesto_id=presupuesto_id).first()
    
    return render_template('ver_factura_solicitud.html', solicitud=presupuesto, factura_existente=factura_existente)

@facturacion_bp.route('/facturacion/solicitud/<int:presupuesto_id>/formalizar', methods=['POST'])
@login_required
@not_usuario_required
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
        descuento_pronto_pago = data.get('descuento_pronto_pago', 0)
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
        
        # Calcular base imponible (suma de importes de líneas sin IVA)
        base_imponible = Decimal('0.00')
        for linea_data in lineas_data:
            importe = Decimal(str(linea_data.get('importe', 0)))
            base_imponible += importe
        
        # Calcular IVA (21% sobre la base imponible)
        tipo_iva = Decimal('21')
        iva_total = base_imponible * (tipo_iva / Decimal('100'))
        subtotal = base_imponible + iva_total
        
        # Procesar descuento por pronto pago
        descuento_pronto_pago_decimal = Decimal('0')
        try:
            descuento_pronto_pago_decimal = Decimal(str(descuento_pronto_pago))
        except:
            descuento_pronto_pago_decimal = Decimal('0')
        
        # Aplicar descuento por pronto pago al subtotal (base + IVA)
        if descuento_pronto_pago_decimal > 0:
            descuento_aplicado = subtotal * (descuento_pronto_pago_decimal / Decimal('100'))
            importe_total = subtotal - descuento_aplicado
        else:
            importe_total = subtotal
        
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
            descuento_pronto_pago=descuento_pronto_pago_decimal,
            tipo_iva=Decimal('21.00'),  # IVA por defecto 21%
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
            
            # Obtener descuento del formulario o de la línea de presupuesto
            descuento = Decimal('0')
            if 'descuento' in linea_data:
                descuento = Decimal(str(linea_data.get('descuento', 0)))
            elif linea_presupuesto_id:
                linea_presupuesto = LineaPresupuesto.query.get(linea_presupuesto_id)
                if linea_presupuesto:
                    descuento = Decimal(str(linea_presupuesto.descuento)) if linea_presupuesto.descuento else Decimal('0')
            
            # Calcular precio final con descuento
            precio_final = None
            if descuento > 0:
                precio_final = precio_unitario * (Decimal('1') - descuento / Decimal('100'))
            else:
                precio_final = precio_unitario
            
            # Obtener talla de la línea de presupuesto si existe
            talla = None
            if linea_presupuesto_id:
                linea_presupuesto = LineaPresupuesto.query.get(linea_presupuesto_id)
                if linea_presupuesto and linea_presupuesto.talla:
                    talla = linea_presupuesto.talla
            
            linea_factura = LineaFactura(
                factura_id=factura.id,
                linea_pedido_id=None,  # No hay línea de pedido, es de presupuesto
                descripcion=descripcion_linea,
                cantidad=cantidad,
                talla=talla,
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
                    flash('Factura formalizada y enviada a Verifactu correctamente.', 'success')
                    return redirect(url_for('facturacion.facturacion'))
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
            flash('Factura creada. El envío automático a Verifactu está desactivado.', 'success')
            return redirect(url_for('facturacion.facturacion'))
        else:
            factura.estado = 'pendiente'
            db.session.commit()
            flash('Factura creada. Configure VERIFACTU_TOKEN para enviar automáticamente.', 'success')
            return redirect(url_for('facturacion.facturacion'))
            
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Error al formalizar la factura: {str(e)}'
        }), 500

@facturacion_bp.route('/facturacion/<int:pedido_id>')
@login_required
@not_usuario_required
def ver_factura(pedido_id):
    """Vista detallada de una factura para introducir importes"""
    pedido = Pedido.query.get_or_404(pedido_id)
    
    # Verificar si ya existe una factura para este pedido
    factura_existente = Factura.query.filter_by(pedido_id=pedido_id).first()
    
    return render_template('ver_factura.html', pedido=pedido, factura_existente=factura_existente)

@facturacion_bp.route('/facturacion/<int:pedido_id>/formalizar', methods=['POST'])
@login_required
@not_usuario_required
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
            tipo_iva=Decimal('21.00'),  # IVA por defecto 21%
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
            
            # Obtener talla de la línea de pedido si existe
            talla = None
            if linea_pedido_id:
                from models import LineaPedido
                linea_pedido = LineaPedido.query.get(linea_pedido_id)
                if linea_pedido and linea_pedido.talla:
                    talla = linea_pedido.talla
            
            linea_factura = LineaFactura(
                factura_id=factura.id,
                linea_pedido_id=linea_pedido_id,
                descripcion=descripcion_linea,
                cantidad=cantidad,
                talla=talla,
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
@not_usuario_required
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
            direccion_cliente = request.form.get('direccion_cliente', '')
            poblacion_cliente = request.form.get('poblacion_cliente', '')
            provincia_cliente = request.form.get('provincia_cliente', '')
            codigo_postal_cliente = request.form.get('codigo_postal_cliente', '')
            telefono_cliente = request.form.get('telefono_cliente', '')
            email_cliente = request.form.get('email_cliente', '')
            cliente_id = request.form.get('cliente_id', '')
            descuento_pronto_pago = request.form.get('descuento_pronto_pago', '0') or '0'
            tipo_iva = request.form.get('tipo_iva', '21') or '21'
            
            # Obtener líneas de factura
            descripciones = request.form.getlist('descripcion_linea[]')
            cantidades = request.form.getlist('cantidad[]')
            tallas = request.form.getlist('talla[]')
            precios_unitarios = request.form.getlist('precio_unitario[]')
            descuentos = request.form.getlist('descuento[]')
            precios_finales = request.form.getlist('precio_final[]')
            
            if not fecha_expedicion_str:
                flash('La fecha de expedición es obligatoria', 'error')
                return redirect(url_for('facturacion.nueva_factura'))
            
            if not nombre_cliente:
                flash('El nombre del cliente es obligatorio', 'error')
                return redirect(url_for('facturacion.nueva_factura'))
            
            if not nif_cliente:
                flash('El NIF/CIF del cliente es obligatorio', 'error')
                return redirect(url_for('facturacion.nueva_factura'))
            
            if not direccion_cliente:
                flash('La dirección del cliente es obligatoria', 'error')
                return redirect(url_for('facturacion.nueva_factura'))
            
            if not poblacion_cliente:
                flash('La población del cliente es obligatoria', 'error')
                return redirect(url_for('facturacion.nueva_factura'))
            
            if not provincia_cliente:
                flash('La provincia del cliente es obligatoria', 'error')
                return redirect(url_for('facturacion.nueva_factura'))
            
            if not codigo_postal_cliente:
                flash('El código postal del cliente es obligatorio', 'error')
                return redirect(url_for('facturacion.nueva_factura'))
            
            if not descripciones or not any(descripciones):
                flash('Debe haber al menos una línea en la factura', 'error')
                return redirect(url_for('facturacion.nueva_factura'))
            
            # Procesar fecha
            fecha_expedicion = datetime.strptime(fecha_expedicion_str, '%Y-%m-%d').date()
            
            # Si hay cliente_id, obtener datos del cliente (pero permitir sobrescribir con los del formulario)
            if cliente_id:
                cliente = Cliente.query.get(cliente_id)
                if cliente:
                    if not nombre_cliente:
                        nombre_cliente = cliente.nombre
                    if not nif_cliente and cliente.nif:
                        nif_cliente = cliente.nif
                    if not direccion_cliente and cliente.direccion:
                        direccion_cliente = cliente.direccion
                    if not poblacion_cliente and cliente.poblacion:
                        poblacion_cliente = cliente.poblacion
                    if not provincia_cliente and cliente.provincia:
                        provincia_cliente = cliente.provincia
                    if not codigo_postal_cliente and cliente.codigo_postal:
                        codigo_postal_cliente = cliente.codigo_postal
                    if not telefono_cliente and cliente.telefono:
                        telefono_cliente = cliente.telefono
                    if not email_cliente and cliente.email:
                        email_cliente = cliente.email
            
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
                    
                    # Procesar descuento
                    descuento = Decimal('0')
                    if i < len(descuentos) and descuentos[i]:
                        try:
                            descuento = Decimal(str(descuentos[i]))
                        except:
                            descuento = Decimal('0')
                    
                    # Procesar precio final (si existe, usar ese; sino calcular con descuento)
                    precio_final = None
                    if i < len(precios_finales) and precios_finales[i]:
                        try:
                            precio_final = Decimal(str(precios_finales[i]))
                        except:
                            precio_final = None
                    
                    # Si no hay precio_final pero hay descuento, calcularlo
                    if precio_final is None and descuento > 0:
                        precio_final = precio_unitario * (Decimal('1') - descuento / Decimal('100'))
                    elif precio_final is None:
                        precio_final = precio_unitario
                    
                    # Calcular importe usando precio_final si existe
                    importe = cantidad * precio_final
                    importe_total += importe
                    
                    talla = tallas[i] if i < len(tallas) and tallas[i] else None
                    lineas_data.append({
                        'descripcion': descripciones[i],
                        'cantidad': cantidad,
                        'talla': talla,
                        'precio_unitario': precio_unitario,
                        'descuento': descuento,
                        'precio_final': precio_final,
                        'importe': importe
                    })
            
            # Calcular IVA según el tipo seleccionado
            # Los precios unitarios son sin IVA, así que importe_total es la base imponible
            base_imponible = importe_total
            tipo_iva_decimal = Decimal(str(tipo_iva))
            iva = base_imponible * (tipo_iva_decimal / Decimal('100'))
            subtotal = base_imponible + iva
            
            # Procesar descuento por pronto pago
            descuento_pronto_pago_decimal = Decimal('0')
            try:
                descuento_pronto_pago_decimal = Decimal(str(descuento_pronto_pago))
            except:
                descuento_pronto_pago_decimal = Decimal('0')
            
            # Aplicar descuento por pronto pago al subtotal (base + IVA)
            if descuento_pronto_pago_decimal > 0:
                descuento_aplicado = subtotal * (descuento_pronto_pago_decimal / Decimal('100'))
                importe_total = subtotal - descuento_aplicado
            else:
                importe_total = subtotal
            
            # Obtener cliente_id si se proporcionó
            cliente_id_int = None
            if cliente_id:
                try:
                    cliente_id_int = int(cliente_id)
                except:
                    cliente_id_int = None
            
            # Crear factura sin pedido
            factura = Factura(
                pedido_id=None,  # Factura directa sin pedido
                cliente_id=cliente_id_int,  # Cliente asociado si se seleccionó uno
                serie=serie,
                numero=numero,
                fecha_expedicion=fecha_expedicion,
                tipo_factura=tipo_factura,
                descripcion=descripcion,
                nif=nif_cliente,
                nombre=nombre_cliente,
                importe_total=importe_total,
                descuento_pronto_pago=descuento_pronto_pago_decimal,
                tipo_iva=tipo_iva_decimal,
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
                    talla=linea_data.get('talla'),
                    precio_unitario=linea_data['precio_unitario'],
                    descuento=linea_data['descuento'],
                    precio_final=linea_data['precio_final'],
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

@facturacion_bp.route('/facturacion/factura/<int:factura_id>/editar', methods=['GET', 'POST'])
@login_required
@not_usuario_required
def editar_factura(factura_id):
    """Editar una factura directa existente"""
    factura = Factura.query.get_or_404(factura_id)
    
    # Verificar que es una factura directa (sin pedido ni presupuesto)
    if factura.pedido_id is not None or factura.presupuesto_id is not None:
        flash('Esta factura no es una factura directa y no se puede editar desde aquí', 'error')
        return redirect(url_for('facturacion.facturacion', tipo_vista='formalizadas'))
    
    if request.method == 'POST':
        try:
            # Obtener datos del formulario
            fecha_expedicion_str = request.form.get('fecha_expedicion', '')
            tipo_factura = request.form.get('tipo_factura', 'F1')
            descripcion = request.form.get('descripcion', '')
            nombre_cliente = request.form.get('nombre_cliente', '')
            nif_cliente = request.form.get('nif_cliente', '')
            direccion_cliente = request.form.get('direccion_cliente', '')
            poblacion_cliente = request.form.get('poblacion_cliente', '')
            provincia_cliente = request.form.get('provincia_cliente', '')
            codigo_postal_cliente = request.form.get('codigo_postal_cliente', '')
            telefono_cliente = request.form.get('telefono_cliente', '')
            email_cliente = request.form.get('email_cliente', '')
            cliente_id = request.form.get('cliente_id', '')
            descuento_pronto_pago = request.form.get('descuento_pronto_pago', '0') or '0'
            tipo_iva = request.form.get('tipo_iva', '21') or '21'
            
            # Obtener líneas de factura
            descripciones = request.form.getlist('descripcion_linea[]')
            cantidades = request.form.getlist('cantidad[]')
            tallas = request.form.getlist('talla[]')
            precios_unitarios = request.form.getlist('precio_unitario[]')
            descuentos = request.form.getlist('descuento[]')
            precios_finales = request.form.getlist('precio_final[]')
            
            if not fecha_expedicion_str:
                flash('La fecha de expedición es obligatoria', 'error')
                return redirect(url_for('facturacion.editar_factura', factura_id=factura_id))
            
            if not nombre_cliente:
                flash('El nombre del cliente es obligatorio', 'error')
                return redirect(url_for('facturacion.editar_factura', factura_id=factura_id))
            
            if not nif_cliente:
                flash('El NIF/CIF del cliente es obligatorio', 'error')
                return redirect(url_for('facturacion.editar_factura', factura_id=factura_id))
            
            if not descripciones or not any(descripciones):
                flash('Debe haber al menos una línea en la factura', 'error')
                return redirect(url_for('facturacion.editar_factura', factura_id=factura_id))
            
            # Procesar fecha
            fecha_expedicion = datetime.strptime(fecha_expedicion_str, '%Y-%m-%d').date()
            
            # Obtener cliente_id si se proporcionó
            cliente_id_int = None
            if cliente_id:
                try:
                    cliente_id_int = int(cliente_id)
                except:
                    cliente_id_int = None
            
            # Actualizar datos de la factura
            factura.fecha_expedicion = fecha_expedicion
            factura.tipo_factura = tipo_factura
            factura.descripcion = descripcion
            factura.nombre = nombre_cliente
            factura.nif = nif_cliente
            factura.cliente_id = cliente_id_int
            factura.tipo_iva = Decimal(str(tipo_iva))
            factura.descuento_pronto_pago = Decimal(str(descuento_pronto_pago))
            
            # Eliminar líneas existentes
            for linea in factura.lineas:
                db.session.delete(linea)
            db.session.flush()
            
            # Calcular importe total
            importe_total = Decimal('0.00')
            lineas_data = []
            for i in range(len(descripciones)):
                if descripciones[i]:
                    cantidad = Decimal(str(cantidades[i])) if i < len(cantidades) and cantidades[i] else Decimal('1')
                    precio_unitario = Decimal(str(precios_unitarios[i])) if i < len(precios_unitarios) and precios_unitarios[i] else Decimal('0')
                    
                    # Procesar descuento
                    descuento = Decimal('0')
                    if i < len(descuentos) and descuentos[i]:
                        try:
                            descuento = Decimal(str(descuentos[i]))
                        except:
                            descuento = Decimal('0')
                    
                    # Procesar precio final (si existe, usar ese; sino calcular con descuento)
                    precio_final = None
                    if i < len(precios_finales) and precios_finales[i]:
                        try:
                            precio_final = Decimal(str(precios_finales[i]))
                        except:
                            precio_final = None
                    
                    # Si no hay precio_final pero hay descuento, calcularlo
                    if precio_final is None and descuento > 0:
                        precio_final = precio_unitario * (Decimal('1') - descuento / Decimal('100'))
                    elif precio_final is None:
                        precio_final = precio_unitario
                    
                    # Calcular importe usando precio_final si existe
                    importe = cantidad * precio_final
                    importe_total += importe
                    
                    talla = tallas[i] if i < len(tallas) and tallas[i] else None
                    
                    # Crear nueva línea
                    linea_factura = LineaFactura(
                        factura_id=factura.id,
                        linea_pedido_id=None,
                        descripcion=descripciones[i],
                        cantidad=cantidad,
                        talla=talla,
                        precio_unitario=precio_unitario,
                        descuento=descuento,
                        precio_final=precio_final,
                        importe=importe
                    )
                    db.session.add(linea_factura)
            
            # Calcular IVA según el tipo seleccionado
            base_imponible = importe_total
            tipo_iva_decimal = Decimal(str(tipo_iva))
            iva = base_imponible * (tipo_iva_decimal / Decimal('100'))
            subtotal = base_imponible + iva
            
            # Aplicar descuento por pronto pago
            descuento_pronto_pago_decimal = Decimal(str(descuento_pronto_pago))
            if descuento_pronto_pago_decimal > 0:
                descuento_aplicado = subtotal * (descuento_pronto_pago_decimal / Decimal('100'))
                importe_total = subtotal - descuento_aplicado
            else:
                importe_total = subtotal
            
            factura.importe_total = importe_total
            
            db.session.commit()
            flash('Factura actualizada correctamente', 'success')
            return redirect(url_for('facturacion.facturacion', tipo_vista='formalizadas'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar la factura: {str(e)}', 'error')
            import traceback
            traceback.print_exc()
    
    # GET: mostrar formulario con datos existentes
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    cliente_directo = factura.cliente if factura.cliente_id else None
    
    return render_template('facturacion/editar_factura.html', 
                         factura=factura,
                         clientes=clientes,
                         cliente_directo=cliente_directo)

@facturacion_bp.route('/facturacion/nuevo_albaran', methods=['GET', 'POST'])
@login_required
@not_usuario_required
def nuevo_albaran():
    """Crear un albarán directamente sin pedido (factura pendiente de formalizar)"""
    if request.method == 'POST':
        try:
            # Obtener datos del formulario
            fecha_expedicion_str = request.form.get('fecha_expedicion', '')
            descripcion = request.form.get('descripcion', '')
            nombre_cliente = request.form.get('nombre_cliente', '')
            nif_cliente = request.form.get('nif_cliente', '')
            direccion_cliente = request.form.get('direccion_cliente', '')
            poblacion_cliente = request.form.get('poblacion_cliente', '')
            provincia_cliente = request.form.get('provincia_cliente', '')
            codigo_postal_cliente = request.form.get('codigo_postal_cliente', '')
            telefono_cliente = request.form.get('telefono_cliente', '')
            email_cliente = request.form.get('email_cliente', '')
            cliente_id = request.form.get('cliente_id', '')
            # Los albaranes no tienen descuento por pronto pago
            descuento_pronto_pago = '0'
            
            # Obtener líneas de albarán
            descripciones = request.form.getlist('descripcion_linea[]')
            cantidades = request.form.getlist('cantidad[]')
            tallas = request.form.getlist('talla[]')
            precios_unitarios = request.form.getlist('precio_unitario[]')
            descuentos = request.form.getlist('descuento[]')
            precios_finales = request.form.getlist('precio_final[]')
            es_linea_texto = request.form.getlist('es_linea_texto[]')
            
            if not fecha_expedicion_str:
                flash('La fecha de expedición es obligatoria', 'error')
                return redirect(url_for('facturacion.nuevo_albaran'))
            
            if not nombre_cliente:
                flash('El nombre del cliente es obligatorio', 'error')
                return redirect(url_for('facturacion.nuevo_albaran'))
            
            if not nif_cliente:
                flash('El NIF/CIF del cliente es obligatorio', 'error')
                return redirect(url_for('facturacion.nuevo_albaran'))
            
            if not direccion_cliente:
                flash('La dirección del cliente es obligatoria', 'error')
                return redirect(url_for('facturacion.nuevo_albaran'))
            
            if not poblacion_cliente:
                flash('La población del cliente es obligatoria', 'error')
                return redirect(url_for('facturacion.nuevo_albaran'))
            
            if not provincia_cliente:
                flash('La provincia del cliente es obligatoria', 'error')
                return redirect(url_for('facturacion.nuevo_albaran'))
            
            if not codigo_postal_cliente:
                flash('El código postal del cliente es obligatorio', 'error')
                return redirect(url_for('facturacion.nuevo_albaran'))
            
            if not descripciones or not any(descripciones):
                flash('Debe haber al menos una línea en el albarán', 'error')
                return redirect(url_for('facturacion.nuevo_albaran'))
            
            # Procesar fecha
            fecha_expedicion = datetime.strptime(fecha_expedicion_str, '%Y-%m-%d').date()
            
            # Si hay cliente_id, obtener datos del cliente (pero permitir sobrescribir con los del formulario)
            if cliente_id:
                cliente = Cliente.query.get(cliente_id)
                if cliente:
                    if not nombre_cliente:
                        nombre_cliente = cliente.nombre
                    if not nif_cliente and cliente.nif:
                        nif_cliente = cliente.nif
                    if not direccion_cliente and cliente.direccion:
                        direccion_cliente = cliente.direccion
                    if not poblacion_cliente and cliente.poblacion:
                        poblacion_cliente = cliente.poblacion
                    if not provincia_cliente and cliente.provincia:
                        provincia_cliente = cliente.provincia
                    if not codigo_postal_cliente and cliente.codigo_postal:
                        codigo_postal_cliente = cliente.codigo_postal
                    if not telefono_cliente and cliente.telefono:
                        telefono_cliente = cliente.telefono
                    if not email_cliente and cliente.email:
                        email_cliente = cliente.email
            
            # Generar número de albarán automáticamente
            serie = 'A'
            numero = obtener_siguiente_numero_albaran(fecha_expedicion)
            
            # Calcular importe total
            importe_total = Decimal('0.00')
            lineas_data = []
            for i in range(len(descripciones)):
                if descripciones[i]:
                    # Verificar si es línea de texto
                    es_texto = i < len(es_linea_texto) and es_linea_texto[i] == '1'
                    
                    if es_texto:
                        # Línea de texto: cantidad 0, sin precios
                        cantidad = Decimal('0')
                        precio_unitario = Decimal('0')
                        descuento = Decimal('0')
                        precio_final = Decimal('0')
                        importe = Decimal('0')
                        talla = None
                    else:
                        cantidad = Decimal(str(cantidades[i])) if i < len(cantidades) and cantidades[i] else Decimal('1')
                        # Permitir precio vacío (None) para albaranes sin precio
                        precio_unitario = None
                        if i < len(precios_unitarios) and precios_unitarios[i] and precios_unitarios[i].strip():
                            try:
                                precio_unitario = Decimal(str(precios_unitarios[i]))
                            except:
                                precio_unitario = None
                    
                    # Procesar descuento
                    descuento = Decimal('0')
                    if i < len(descuentos) and descuentos[i]:
                        try:
                            descuento = Decimal(str(descuentos[i]))
                        except:
                            descuento = Decimal('0')
                    
                    # Procesar precio final (si existe, usar ese; sino calcular con descuento)
                    precio_final = None
                    if i < len(precios_finales) and precios_finales[i] and precios_finales[i].strip():
                        try:
                            precio_final = Decimal(str(precios_finales[i]))
                        except:
                            precio_final = None
                    
                    # Si no hay precio_unitario, precio_final e importe serán 0
                    if precio_unitario is None:
                        precio_unitario = Decimal('0')
                        precio_final = Decimal('0')
                        importe = Decimal('0')
                    else:
                        # Si no hay precio_final pero hay descuento, calcularlo
                        if precio_final is None and descuento > 0:
                            precio_final = precio_unitario * (Decimal('1') - descuento / Decimal('100'))
                        elif precio_final is None:
                            precio_final = precio_unitario
                        
                        # Calcular importe usando precio_final si existe
                        importe = cantidad * precio_final
                    
                    talla = tallas[i] if i < len(tallas) and tallas[i] else None
                    
                    importe_total += importe
                    
                    lineas_data.append({
                        'descripcion': descripciones[i],
                        'cantidad': cantidad,
                        'talla': talla,
                        'precio_unitario': precio_unitario,
                        'descuento': descuento,
                        'precio_final': precio_final,
                        'importe': importe
                    })
            
            # Calcular IVA (21% sobre la base imponible)
            # Los precios unitarios son sin IVA, así que importe_total es la base imponible
            base_imponible = importe_total
            iva = base_imponible * Decimal('0.21')
            # Los albaranes no tienen descuento por pronto pago, el total es base + IVA
            importe_total = base_imponible + iva
            descuento_pronto_pago_decimal = Decimal('0')
            
            # Crear albarán (factura pendiente de formalizar)
            factura = Factura(
                pedido_id=None,  # Albarán directo sin pedido
                presupuesto_id=None,  # Albarán directo sin presupuesto
                serie=serie,
                numero=numero,
                fecha_expedicion=fecha_expedicion,
                tipo_factura='F1',  # Factura completa (se formalizará después)
                descripcion=descripcion,
                nif=nif_cliente,
                nombre=nombre_cliente,
                importe_total=importe_total,
                descuento_pronto_pago=descuento_pronto_pago_decimal,
                tipo_iva=Decimal('21.00'),  # IVA por defecto 21%
                estado='pendiente'  # Pendiente de formalizar
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
                    talla=linea_data.get('talla'),
                    precio_unitario=linea_data['precio_unitario'],
                    descuento=linea_data['descuento'],
                    precio_final=linea_data['precio_final'],
                    importe=linea_data['importe']
                )
                db.session.add(linea_factura)
            
            # Los albaranes siempre se crean como pendientes (no se envían a Verifactu)
            factura.estado = 'pendiente'
            db.session.commit()
            flash('Albarán creado correctamente. Está pendiente de formalizar.', 'success')
            
            return redirect(url_for('facturacion.facturacion', tipo_vista='pendientes'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear el albarán: {str(e)}', 'error')
            import traceback
            traceback.print_exc()
    
    # GET: mostrar formulario
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    # Establecer fecha de hoy por defecto
    fecha_hoy = datetime.now().strftime('%Y-%m-%d')
    return render_template('facturacion/nuevo_albaran.html', clientes=clientes, fecha_hoy=fecha_hoy)

@facturacion_bp.route('/facturacion/albaran/<int:factura_id>/editar', methods=['GET', 'POST'])
@login_required
@not_usuario_required
def editar_albaran(factura_id):
    """Editar un albarán existente"""
    factura = Factura.query.get_or_404(factura_id)
    
    # Verificar que es un albarán (número que empieza con 'A' y contiene '_', estado='pendiente')
    if not (factura.numero.startswith('A') and '_' in factura.numero and factura.estado == 'pendiente'):
        flash('Esta factura no es un albarán pendiente de formalizar', 'error')
        return redirect(url_for('facturacion.facturacion', tipo_vista='pendientes'))
    
    if request.method == 'POST':
        try:
            # Obtener datos del formulario
            fecha_expedicion_str = request.form.get('fecha_expedicion', '')
            descripcion = request.form.get('descripcion', '')
            nombre_cliente = request.form.get('nombre_cliente', '')
            nif_cliente = request.form.get('nif_cliente', '')
            direccion_cliente = request.form.get('direccion_cliente', '')
            poblacion_cliente = request.form.get('poblacion_cliente', '')
            provincia_cliente = request.form.get('provincia_cliente', '')
            codigo_postal_cliente = request.form.get('codigo_postal_cliente', '')
            telefono_cliente = request.form.get('telefono_cliente', '')
            email_cliente = request.form.get('email_cliente', '')
            cliente_id = request.form.get('cliente_id', '')
            descuento_pronto_pago = request.form.get('descuento_pronto_pago', '0') or '0'
            
            # Obtener líneas de albarán
            descripciones = request.form.getlist('descripcion_linea[]')
            cantidades = request.form.getlist('cantidad[]')
            tallas = request.form.getlist('talla[]')
            precios_unitarios = request.form.getlist('precio_unitario[]')
            descuentos = request.form.getlist('descuento[]')
            precios_finales = request.form.getlist('precio_final[]')
            es_linea_texto = request.form.getlist('es_linea_texto[]')
            
            if not fecha_expedicion_str:
                flash('La fecha de expedición es obligatoria', 'error')
                return redirect(url_for('facturacion.editar_albaran', factura_id=factura_id))
            
            if not nombre_cliente:
                flash('El nombre del cliente es obligatorio', 'error')
                return redirect(url_for('facturacion.editar_albaran', factura_id=factura_id))
            
            if not nif_cliente:
                flash('El NIF/CIF del cliente es obligatorio', 'error')
                return redirect(url_for('facturacion.editar_albaran', factura_id=factura_id))
            
            if not direccion_cliente:
                flash('La dirección del cliente es obligatoria', 'error')
                return redirect(url_for('facturacion.editar_albaran', factura_id=factura_id))
            
            if not poblacion_cliente:
                flash('La población del cliente es obligatoria', 'error')
                return redirect(url_for('facturacion.editar_albaran', factura_id=factura_id))
            
            if not provincia_cliente:
                flash('La provincia del cliente es obligatoria', 'error')
                return redirect(url_for('facturacion.editar_albaran', factura_id=factura_id))
            
            if not codigo_postal_cliente:
                flash('El código postal del cliente es obligatorio', 'error')
                return redirect(url_for('facturacion.editar_albaran', factura_id=factura_id))
            
            if not descripciones or not any(descripciones):
                flash('Debe haber al menos una línea en el albarán', 'error')
                return redirect(url_for('facturacion.editar_albaran', factura_id=factura_id))
            
            # Procesar fecha
            fecha_expedicion = datetime.strptime(fecha_expedicion_str, '%Y-%m-%d').date()
            
            # Si hay cliente_id, obtener datos del cliente (pero permitir sobrescribir con los del formulario)
            if cliente_id:
                cliente = Cliente.query.get(cliente_id)
                if cliente:
                    if not nombre_cliente:
                        nombre_cliente = cliente.nombre
                    if not nif_cliente and cliente.nif:
                        nif_cliente = cliente.nif
                    if not direccion_cliente and cliente.direccion:
                        direccion_cliente = cliente.direccion
                    if not poblacion_cliente and cliente.poblacion:
                        poblacion_cliente = cliente.poblacion
                    if not provincia_cliente and cliente.provincia:
                        provincia_cliente = cliente.provincia
                    if not codigo_postal_cliente and cliente.codigo_postal:
                        codigo_postal_cliente = cliente.codigo_postal
                    if not telefono_cliente and cliente.telefono:
                        telefono_cliente = cliente.telefono
                    if not email_cliente and cliente.email:
                        email_cliente = cliente.email
            
            # Calcular importe total
            importe_total = Decimal('0.00')
            lineas_data = []
            for i in range(len(descripciones)):
                if descripciones[i]:
                    # Verificar si es línea de texto
                    es_texto = i < len(es_linea_texto) and es_linea_texto[i] == '1'
                    
                    if es_texto:
                        # Línea de texto: cantidad 0, sin precios
                        cantidad = Decimal('0')
                        precio_unitario = Decimal('0')
                        descuento = Decimal('0')
                        precio_final = Decimal('0')
                        importe = Decimal('0')
                        talla = None
                    else:
                        cantidad = Decimal(str(cantidades[i])) if i < len(cantidades) and cantidades[i] else Decimal('1')
                        # Permitir precio vacío (None) para albaranes sin precio
                        precio_unitario = None
                        if i < len(precios_unitarios) and precios_unitarios[i] and precios_unitarios[i].strip():
                            try:
                                precio_unitario = Decimal(str(precios_unitarios[i]))
                            except:
                                precio_unitario = None
                    
                    # Procesar descuento
                    descuento = Decimal('0')
                    if i < len(descuentos) and descuentos[i]:
                        try:
                            descuento = Decimal(str(descuentos[i]))
                        except:
                            descuento = Decimal('0')
                    
                    # Procesar precio final (si existe, usar ese; sino calcular con descuento)
                    precio_final = None
                    if i < len(precios_finales) and precios_finales[i] and precios_finales[i].strip():
                        try:
                            precio_final = Decimal(str(precios_finales[i]))
                        except:
                            precio_final = None
                    
                    # Si no hay precio_unitario, precio_final e importe serán 0
                    if precio_unitario is None:
                        precio_unitario = Decimal('0')
                        precio_final = Decimal('0')
                        importe = Decimal('0')
                    else:
                        # Si no hay precio_final pero hay descuento, calcularlo
                        if precio_final is None and descuento > 0:
                            precio_final = precio_unitario * (Decimal('1') - descuento / Decimal('100'))
                        elif precio_final is None:
                            precio_final = precio_unitario
                        
                        # Calcular importe usando precio_final si existe
                        importe = cantidad * precio_final
                    
                    talla = tallas[i] if i < len(tallas) and tallas[i] else None
                    
                    importe_total += importe
                    
                    lineas_data.append({
                        'descripcion': descripciones[i],
                        'cantidad': cantidad,
                        'talla': talla,
                        'precio_unitario': precio_unitario,
                        'descuento': descuento,
                        'precio_final': precio_final,
                        'importe': importe
                    })
            
            # Calcular IVA (21% sobre la base imponible)
            base_imponible = importe_total
            iva = base_imponible * Decimal('0.21')
            subtotal = base_imponible + iva
            
            # Procesar descuento por pronto pago
            descuento_pronto_pago_decimal = Decimal('0')
            try:
                descuento_pronto_pago_decimal = Decimal(str(descuento_pronto_pago))
            except:
                descuento_pronto_pago_decimal = Decimal('0')
            
            # Aplicar descuento por pronto pago al subtotal (base + IVA)
            if descuento_pronto_pago_decimal > 0:
                descuento_aplicado = subtotal * (descuento_pronto_pago_decimal / Decimal('100'))
                importe_total = subtotal - descuento_aplicado
            else:
                importe_total = subtotal
            
            # Actualizar factura (albarán)
            factura.fecha_expedicion = fecha_expedicion
            factura.descripcion = descripcion
            factura.nif = nif_cliente
            factura.nombre = nombre_cliente
            factura.importe_total = importe_total
            factura.descuento_pronto_pago = descuento_pronto_pago_decimal
            
            # Eliminar líneas antiguas
            LineaFactura.query.filter_by(factura_id=factura.id).delete()
            
            # Crear nuevas líneas de factura
            for linea_data in lineas_data:
                linea_factura = LineaFactura(
                    factura_id=factura.id,
                    linea_pedido_id=None,
                    descripcion=linea_data['descripcion'],
                    cantidad=linea_data['cantidad'],
                    talla=linea_data.get('talla'),
                    precio_unitario=linea_data['precio_unitario'],
                    descuento=linea_data['descuento'],
                    precio_final=linea_data['precio_final'],
                    importe=linea_data['importe']
                )
                db.session.add(linea_factura)
            
            db.session.commit()
            flash('Albarán actualizado correctamente.', 'success')
            
            return redirect(url_for('facturacion.facturacion', tipo_vista='pendientes'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar el albarán: {str(e)}', 'error')
            import traceback
            traceback.print_exc()
    
    # GET: mostrar formulario con datos del albarán
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    
    # Preparar datos del albarán para el formulario
    fecha_hoy = factura.fecha_expedicion.strftime('%Y-%m-%d') if factura.fecha_expedicion else datetime.now().strftime('%Y-%m-%d')
    
    # Buscar cliente por NIF si existe
    cliente_seleccionado = None
    datos_cliente = {
        'nombre': factura.nombre or '',
        'nif': factura.nif or '',
        'direccion': '',
        'poblacion': '',
        'provincia': '',
        'codigo_postal': '',
        'telefono': '',
        'email': ''
    }
    
    if factura.nif:
        cliente_seleccionado = Cliente.query.filter_by(nif=factura.nif).first()
        if cliente_seleccionado:
            datos_cliente['direccion'] = cliente_seleccionado.direccion or ''
            datos_cliente['poblacion'] = cliente_seleccionado.poblacion or ''
            datos_cliente['provincia'] = cliente_seleccionado.provincia or ''
            datos_cliente['codigo_postal'] = cliente_seleccionado.codigo_postal or ''
            datos_cliente['telefono'] = cliente_seleccionado.telefono or ''
            datos_cliente['email'] = cliente_seleccionado.email or ''
    
    return render_template('facturacion/editar_albaran.html', 
                         factura=factura,
                         clientes=clientes, 
                         fecha_hoy=fecha_hoy,
                         cliente_seleccionado=cliente_seleccionado,
                         datos_cliente=datos_cliente)

def preparar_datos_imprimir_factura(factura_id):
    """Función auxiliar para preparar todos los datos necesarios para imprimir la factura"""
    from decimal import Decimal
    from sqlalchemy.orm import joinedload
    
    # Cargar factura con todas las relaciones necesarias
    factura = Factura.query.options(
        joinedload(Factura.cliente),  # Cliente directo de la factura
        joinedload(Factura.pedido).joinedload(Pedido.cliente),
        joinedload(Factura.pedido).joinedload(Pedido.presupuesto).joinedload(Presupuesto.cliente),
        joinedload(Factura.presupuesto).joinedload(Presupuesto.cliente)
    ).get_or_404(factura_id)
    
    pedido = factura.pedido
    presupuesto = factura.presupuesto
    cliente_directo = factura.cliente  # Cliente directo de la factura (para facturas directas)
    
    # Si no hay presupuesto directo pero hay pedido, intentar obtenerlo del pedido
    if not presupuesto and pedido and pedido.presupuesto:
        presupuesto = pedido.presupuesto
    
    # Calcular totales usando precio_unitario y descuento de las líneas
    # Usar el tipo de IVA guardado en la factura, o 21% por defecto
    tipo_iva = float(factura.tipo_iva) if factura.tipo_iva else 21
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
    subtotal = base_imponible + iva_total
    
    # Aplicar descuento por pronto pago si existe
    descuento_pronto_pago = Decimal(str(factura.descuento_pronto_pago)) if factura.descuento_pronto_pago else Decimal('0')
    if descuento_pronto_pago > 0:
        descuento_aplicado = subtotal * (descuento_pronto_pago / Decimal('100'))
        descuento_aplicado = descuento_aplicado.quantize(Decimal('0.01'))
        total_con_iva = subtotal - descuento_aplicado
        total_con_iva = total_con_iva.quantize(Decimal('0.01'))
    else:
        total_con_iva = subtotal
    
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
    logo_path = os.path.join(current_app.static_folder, 'logo1.png')
    logo_base64 = convertir_imagen_a_base64(logo_path)
    
    # Detectar si es un albarán: número que empieza con 'A' seguido de año y mes (formato A2601_XXX)
    # y estado='pendiente' (aún no formalizado)
    es_albaran = (factura.numero.startswith('A') and 
                  '_' in factura.numero and 
                  factura.estado == 'pendiente' and
                  factura.presupuesto_id is None and
                  factura.pedido_id is None)
    
    return {
        'factura': factura,
        'pedido': pedido,
        'presupuesto': presupuesto,
        'cliente_directo': cliente_directo,  # Cliente directo de la factura
        'base_imponible': float(base_imponible),
        'iva_total': float(iva_total),
        'total_con_iva': float(total_con_iva),
        'tipo_iva': tipo_iva,
        'logo_base64': logo_base64,
        'es_albaran': es_albaran
    }

@facturacion_bp.route('/facturacion/factura/<int:factura_id>/imprimir')
@login_required
@not_usuario_required
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
        presupuesto = factura.presupuesto
        lineas = factura.lineas
    elif pedido_id:
        # Si solo tenemos pedido_id (prefactura), obtener pedido y usar sus líneas
        pedido = Pedido.query.get_or_404(pedido_id)
        factura = None
        presupuesto = pedido.presupuesto if pedido else None
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
    logo_path = os.path.join(current_app.static_folder, 'logo1.png')
    logo_base64 = convertir_imagen_a_base64(logo_path)
    
    return {
        'factura': factura,
        'pedido': pedido,
        'presupuesto': presupuesto,
        'lineas': lineas,
        'logo_base64': logo_base64
    }

@facturacion_bp.route('/facturacion/factura/<int:factura_id>/descargar-pdf')
@login_required
@not_usuario_required
def descargar_pdf_factura(factura_id):
    """Descargar factura en formato PDF (con precios) o albarán si es tipo albarán"""
    try:
        datos = preparar_datos_imprimir_factura(factura_id)
        
        # Si es un albarán, usar el template de albarán (sin precios)
        if datos.get('es_albaran', False):
            # Preparar datos para albarán
            datos_albaran = preparar_datos_imprimir_albaran(factura_id=factura_id)
            html = render_template('imprimir_albaran_pdf.html', 
                                 **datos_albaran,
                                 use_base64=True)
        else:
            # Renderizar el HTML como factura (con precios)
            html = render_template('imprimir_factura_pdf.html', 
                                 **datos,
                                 use_base64=True)
        
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
        
        # Nombre del archivo según si es albarán o factura
        if datos.get('es_albaran', False):
            numero_pedido = datos_albaran['pedido'].id if datos_albaran.get('pedido') else 'N/A'
            response.headers['Content-Disposition'] = f'inline; filename=albaran_pedido_{numero_pedido}.pdf'
        else:
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
@not_usuario_required
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
@not_usuario_required
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

@facturacion_bp.route('/facturacion/facturar_albaranes', methods=['GET', 'POST'])
@login_required
@not_usuario_required
def facturar_albaranes():
    """Seleccionar cliente y mostrar sus albaranes pendientes para facturar"""
    if request.method == 'POST':
        # Obtener cliente seleccionado
        cliente_id = request.form.get('cliente_id', '')
        if not cliente_id:
            flash('Debe seleccionar un cliente', 'error')
            return redirect(url_for('facturacion.facturar_albaranes'))
        
        cliente = Cliente.query.get_or_404(cliente_id)
        
        # Obtener albaranes pendientes del cliente (por NIF)
        from sqlalchemy import and_
        albaranes = Factura.query.filter(
            and_(
                Factura.estado == 'pendiente',
                Factura.presupuesto_id.is_(None),
                Factura.pedido_id.is_(None),
                Factura.numero.like('A%_%'),
                Factura.nif == cliente.nif
            )
        ).order_by(Factura.fecha_expedicion.asc()).all()
        
        if not albaranes:
            flash(f'El cliente {cliente.nombre} no tiene albaranes pendientes de facturar', 'info')
            return redirect(url_for('facturacion.facturar_albaranes'))
        
        fecha_hoy = datetime.now().strftime('%Y-%m-%d')
        return render_template('facturacion/seleccionar_albaranes.html', 
                             cliente=cliente, 
                             albaranes=albaranes,
                             fecha_hoy=fecha_hoy)
    
    # GET: mostrar formulario de selección de cliente
    clientes = Cliente.query.order_by(Cliente.nombre).all()
    return render_template('facturacion/seleccionar_cliente_albaranes.html', clientes=clientes)

@facturacion_bp.route('/facturacion/facturar_albaranes/procesar', methods=['POST'])
@login_required
@not_usuario_required
def procesar_facturacion_albaranes():
    """Procesar la facturación de múltiples albaranes seleccionados"""
    try:
        # Obtener datos del formulario
        cliente_id = request.form.get('cliente_id', '')
        fecha_expedicion_str = request.form.get('fecha_expedicion', '')
        descripcion = request.form.get('descripcion', '')
        descuento_pronto_pago = request.form.get('descuento_pronto_pago', '0') or '0'
        albaranes_ids = request.form.getlist('albaranes_seleccionados[]')
        
        if not cliente_id:
            flash('Debe seleccionar un cliente', 'error')
            return redirect(url_for('facturacion.facturar_albaranes'))
        
        if not fecha_expedicion_str:
            flash('La fecha de expedición es obligatoria', 'error')
            return redirect(url_for('facturacion.facturar_albaranes'))
        
        if not albaranes_ids:
            flash('Debe seleccionar al menos un albarán para facturar', 'error')
            return redirect(url_for('facturacion.facturar_albaranes'))
        
        # Procesar fecha
        fecha_expedicion = datetime.strptime(fecha_expedicion_str, '%Y-%m-%d').date()
        
        # Obtener cliente
        cliente = Cliente.query.get_or_404(cliente_id)
        
        # Obtener albaranes seleccionados
        albaranes = Factura.query.filter(
            Factura.id.in_([int(id) for id in albaranes_ids]),
            Factura.estado == 'pendiente',
            Factura.numero.like('A%_%')
        ).all()
        
        if not albaranes:
            flash('No se encontraron albaranes válidos para facturar', 'error')
            return redirect(url_for('facturacion.facturar_albaranes'))
        
        # Verificar que todos los albaranes pertenecen al mismo cliente (mismo NIF)
        nif_cliente = cliente.nif
        for albaran in albaranes:
            if albaran.nif != nif_cliente:
                flash('Todos los albaranes deben pertenecer al mismo cliente', 'error')
                return redirect(url_for('facturacion.facturar_albaranes'))
        
        # Generar número de factura automáticamente
        serie = 'A'
        numero = obtener_siguiente_numero_factura(fecha_expedicion)
        
        # Agregar todas las líneas de todos los albaranes seleccionados
        lineas_data = []
        importe_total = Decimal('0.00')
        
        for albaran in albaranes:
            for linea in albaran.lineas:
                cantidad = Decimal(str(linea.cantidad)) if linea.cantidad else Decimal('1')
                precio_unitario = Decimal(str(linea.precio_unitario)) if linea.precio_unitario else Decimal('0')
                descuento = Decimal(str(linea.descuento)) if linea.descuento else Decimal('0')
                precio_final = Decimal(str(linea.precio_final)) if linea.precio_final else precio_unitario
                importe = Decimal(str(linea.importe)) if linea.importe else (cantidad * precio_final)
                
                importe_total += importe
                
                lineas_data.append({
                    'descripcion': linea.descripcion or f'Albarán {albaran.numero}',
                    'cantidad': cantidad,
                    'talla': linea.talla if linea.talla else None,
                    'precio_unitario': precio_unitario,
                    'descuento': descuento,
                    'precio_final': precio_final,
                    'importe': importe,
                    'albaran_id': albaran.id
                })
        
        # Calcular IVA (21% sobre la base imponible)
        base_imponible = importe_total
        iva = base_imponible * Decimal('0.21')
        subtotal = base_imponible + iva
        
        # Procesar descuento por pronto pago
        descuento_pronto_pago_decimal = Decimal('0')
        try:
            descuento_pronto_pago_decimal = Decimal(str(descuento_pronto_pago))
        except:
            descuento_pronto_pago_decimal = Decimal('0')
        
        # Aplicar descuento por pronto pago al subtotal (base + IVA)
        if descuento_pronto_pago_decimal > 0:
            descuento_aplicado = subtotal * (descuento_pronto_pago_decimal / Decimal('100'))
            importe_total = subtotal - descuento_aplicado
        else:
            importe_total = subtotal
        
        # Crear factura consolidada
        factura = Factura(
            pedido_id=None,
            presupuesto_id=None,
            serie=serie,
            numero=numero,
            fecha_expedicion=fecha_expedicion,
            tipo_factura='F1',
            descripcion=descripcion or f'Factura consolidada de {len(albaranes)} albarán(es)',
            nif=cliente.nif or '',
            nombre=cliente.nombre,
            importe_total=importe_total,
            descuento_pronto_pago=descuento_pronto_pago_decimal,
            estado='pendiente'
        )
        
        db.session.add(factura)
        db.session.flush()
        
        # Crear líneas de factura desde los albaranes
        for linea_data in lineas_data:
            linea_factura = LineaFactura(
                factura_id=factura.id,
                linea_pedido_id=None,
                descripcion=linea_data['descripcion'],
                cantidad=linea_data['cantidad'],
                talla=linea_data.get('talla'),
                precio_unitario=linea_data['precio_unitario'],
                descuento=linea_data['descuento'],
                precio_final=linea_data['precio_final'],
                importe=linea_data['importe']
            )
            db.session.add(linea_factura)
        
        # Marcar albaranes como facturados (cambiar estado a 'confirmado')
        for albaran in albaranes:
            albaran.estado = 'confirmado'
        
        # Verificar si el envío a Verifactu está activado
        from models import Configuracion
        config = Configuracion.query.filter_by(clave='verifactu_enviar_activo').first()
        verifactu_enviar_activo = True
        if config:
            verifactu_enviar_activo = config.valor.lower() == 'true'
        
        # Enviar a Verifactu solo si está activado y hay token
        verifactu_url = os.environ.get('VERIFACTU_URL', 'https://api.verifacti.com/verifactu/create')
        verifactu_token = os.environ.get('VERIFACTU_TOKEN', '')
        
        if verifactu_token and verifactu_enviar_activo:
            # Preparar datos para la API
            tipo_impositivo = 21
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
                    factura.fecha_confirmacion = datetime.utcnow()
                    db.session.commit()
                    flash(f'Factura {factura.serie}-{factura.numero} creada y enviada a Verifactu correctamente. {len(albaranes)} albarán(es) facturado(s).', 'success')
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
            flash(f'Factura {factura.serie}-{factura.numero} creada. El envío automático a Verifactu está desactivado. {len(albaranes)} albarán(es) facturado(s).', 'info')
        else:
            factura.estado = 'pendiente'
            db.session.commit()
            flash(f'Factura {factura.serie}-{factura.numero} creada. Configure VERIFACTU_TOKEN para enviar automáticamente. {len(albaranes)} albarán(es) facturado(s).', 'warning')
        
        return redirect(url_for('facturacion.facturacion', tipo_vista='formalizadas'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al facturar los albaranes: {str(e)}', 'error')
        import traceback
        traceback.print_exc()
        return redirect(url_for('facturacion.facturar_albaranes'))

