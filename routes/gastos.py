"""Rutas para gestión de gastos (proveedores, facturas de proveedor y nóminas)"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from datetime import datetime
from decimal import Decimal
from extensions import db
from models import Proveedor, FacturaProveedor, Empleado, Nomina

gastos_bp = Blueprint('gastos', __name__)

# ========== PROVEEDORES ==========

@gastos_bp.route('/gastos/proveedores')
@login_required
def listado_proveedores():
    """Listado de proveedores"""
    proveedores = Proveedor.query.order_by(Proveedor.nombre).all()
    return render_template('gastos/listado_proveedores.html', proveedores=proveedores)

@gastos_bp.route('/gastos/proveedores/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_proveedor():
    """Crear nuevo proveedor"""
    if request.method == 'POST':
        try:
            proveedor = Proveedor(
                nombre=request.form.get('nombre'),
                cif=request.form.get('cif', ''),
                telefono=request.form.get('telefono', ''),
                correo=request.form.get('correo', '')
            )
            db.session.add(proveedor)
            db.session.commit()
            
            # Si es una petición AJAX, devolver JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': True,
                    'message': 'Proveedor creado correctamente',
                    'proveedor': {
                        'id': proveedor.id,
                        'nombre': proveedor.nombre
                    }
                }), 200
            
            flash('Proveedor creado correctamente', 'success')
            return redirect(url_for('gastos.listado_proveedores'))
        except Exception as e:
            db.session.rollback()
            error_msg = f'Error al crear proveedor: {str(e)}'
            
            # Si es una petición AJAX, devolver JSON con error
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': False,
                    'message': error_msg
                }), 400
            
            flash(error_msg, 'error')
    
    return render_template('gastos/nuevo_proveedor.html')

@gastos_bp.route('/gastos/proveedores/<int:proveedor_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_proveedor(proveedor_id):
    """Editar proveedor existente"""
    proveedor = Proveedor.query.get_or_404(proveedor_id)
    
    if request.method == 'POST':
        try:
            proveedor.nombre = request.form.get('nombre')
            proveedor.cif = request.form.get('cif', '')
            proveedor.telefono = request.form.get('telefono', '')
            proveedor.correo = request.form.get('correo', '')
            db.session.commit()
            flash('Proveedor actualizado correctamente', 'success')
            return redirect(url_for('gastos.listado_proveedores'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar proveedor: {str(e)}', 'error')
    
    return render_template('gastos/editar_proveedor.html', proveedor=proveedor)

@gastos_bp.route('/gastos/proveedores/<int:proveedor_id>/toggle', methods=['POST'])
@login_required
def toggle_proveedor(proveedor_id):
    """Activar/Desactivar proveedor"""
    proveedor = Proveedor.query.get_or_404(proveedor_id)
    try:
        proveedor.activo = not proveedor.activo
        db.session.commit()
        estado = 'activado' if proveedor.activo else 'desactivado'
        flash(f'Proveedor {estado} correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar estado del proveedor: {str(e)}', 'error')
    
    return redirect(url_for('gastos.editar_proveedor', proveedor_id=proveedor_id))

# ========== FACTURAS DE PROVEEDOR ==========

@gastos_bp.route('/gastos/facturas-proveedor')
@login_required
def listado_facturas_proveedor():
    """Listado de facturas de proveedor"""
    query = FacturaProveedor.query
    
    # Filtro por estado
    estado_filtro = request.args.get('estado', '')
    if estado_filtro:
        query = query.filter(FacturaProveedor.estado == estado_filtro)
    
    # Filtro por fecha desde
    fecha_desde = request.args.get('fecha_desde', '')
    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            query = query.filter(FacturaProveedor.fecha_factura >= fecha_desde_obj)
        except ValueError:
            pass
    
    # Filtro por fecha hasta
    fecha_hasta = request.args.get('fecha_hasta', '')
    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            query = query.filter(FacturaProveedor.fecha_factura <= fecha_hasta_obj)
        except ValueError:
            pass
    
    facturas = query.order_by(FacturaProveedor.fecha_factura.desc()).all()
    
    # Obtener estados únicos para el filtro
    estados = db.session.query(FacturaProveedor.estado).distinct().all()
    estados_list = [estado[0] for estado in estados if estado[0]]
    
    return render_template('gastos/listado_facturas_proveedor.html', 
                         facturas=facturas,
                         estados=estados_list,
                         estado_filtro=estado_filtro,
                         fecha_desde=fecha_desde,
                         fecha_hasta=fecha_hasta)

@gastos_bp.route('/gastos/facturas-proveedor/nueva', methods=['GET', 'POST'])
@login_required
def nueva_factura_proveedor():
    """Crear nueva factura de proveedor"""
    if request.method == 'POST':
        try:
            proveedor_id = request.form.get('proveedor_id')
            numero_factura = request.form.get('numero_factura')
            fecha_factura_str = request.form.get('fecha_factura')
            fecha_vencimiento_str = request.form.get('fecha_vencimiento')
            base_imponible = Decimal(str(request.form.get('base_imponible', 0)))
            tipo_iva = Decimal(str(request.form.get('tipo_iva', 21)))
            observaciones = request.form.get('observaciones', '')
            
            # Calcular IVA y total
            importe_iva = base_imponible * tipo_iva / Decimal('100')
            total = base_imponible + importe_iva
            
            # Convertir fechas
            fecha_factura = datetime.strptime(fecha_factura_str, '%Y-%m-%d').date()
            fecha_vencimiento = None
            if fecha_vencimiento_str:
                fecha_vencimiento = datetime.strptime(fecha_vencimiento_str, '%Y-%m-%d').date()
            
            factura = FacturaProveedor(
                proveedor_id=proveedor_id,
                numero_factura=numero_factura,
                fecha_factura=fecha_factura,
                fecha_vencimiento=fecha_vencimiento,
                base_imponible=base_imponible,
                tipo_iva=tipo_iva,
                importe_iva=importe_iva,
                total=total,
                observaciones=observaciones
            )
            db.session.add(factura)
            db.session.commit()
            flash('Factura de proveedor creada correctamente', 'success')
            return redirect(url_for('gastos.listado_facturas_proveedor'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear factura: {str(e)}', 'error')
    
    proveedores = Proveedor.query.order_by(Proveedor.nombre).all()
    return render_template('gastos/nueva_factura_proveedor.html', proveedores=proveedores)

@gastos_bp.route('/gastos/facturas-proveedor/<int:factura_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_factura_proveedor(factura_id):
    """Editar factura de proveedor existente"""
    factura = FacturaProveedor.query.get_or_404(factura_id)
    
    if request.method == 'POST':
        try:
            factura.proveedor_id = request.form.get('proveedor_id')
            factura.numero_factura = request.form.get('numero_factura')
            factura.fecha_factura = datetime.strptime(request.form.get('fecha_factura'), '%Y-%m-%d').date()
            if request.form.get('fecha_vencimiento'):
                factura.fecha_vencimiento = datetime.strptime(request.form.get('fecha_vencimiento'), '%Y-%m-%d').date()
            else:
                factura.fecha_vencimiento = None
            
            base_imponible = Decimal(str(request.form.get('base_imponible', 0)))
            tipo_iva = Decimal(str(request.form.get('tipo_iva', 21)))
            
            # Recalcular IVA y total
            factura.base_imponible = base_imponible
            factura.tipo_iva = tipo_iva
            factura.importe_iva = base_imponible * tipo_iva / Decimal('100')
            factura.total = base_imponible + factura.importe_iva
            
            factura.estado = request.form.get('estado', 'pendiente')
            factura.observaciones = request.form.get('observaciones', '')
            
            db.session.commit()
            flash('Factura de proveedor actualizada correctamente', 'success')
            return redirect(url_for('gastos.listado_facturas_proveedor'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar factura: {str(e)}', 'error')
    
    proveedores = Proveedor.query.order_by(Proveedor.nombre).all()
    return render_template('gastos/editar_factura_proveedor.html', factura=factura, proveedores=proveedores)

@gastos_bp.route('/gastos/facturas-proveedor/<int:factura_id>/eliminar', methods=['POST'])
@login_required
def eliminar_factura_proveedor(factura_id):
    """Eliminar factura de proveedor"""
    factura = FacturaProveedor.query.get_or_404(factura_id)
    try:
        db.session.delete(factura)
        db.session.commit()
        flash('Factura de proveedor eliminada correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar factura: {str(e)}', 'error')
    
    return redirect(url_for('gastos.listado_facturas_proveedor'))

# ========== EMPLEADOS ==========

@gastos_bp.route('/gastos/empleados')
@login_required
def listado_empleados():
    """Listado de empleados"""
    empleados = Empleado.query.order_by(Empleado.nombre).all()
    return render_template('gastos/listado_empleados.html', empleados=empleados)

@gastos_bp.route('/gastos/empleados/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_empleado():
    """Crear nuevo empleado"""
    if request.method == 'POST':
        try:
            empleado = Empleado(
                nombre=request.form.get('nombre'),
                dni=request.form.get('dni', ''),
                telefono=request.form.get('telefono', ''),
                correo=request.form.get('correo', '')
            )
            db.session.add(empleado)
            db.session.commit()
            
            # Si es una petición AJAX, devolver JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': True,
                    'message': 'Empleado creado correctamente',
                    'empleado': {
                        'id': empleado.id,
                        'nombre': empleado.nombre
                    }
                }), 200
            
            flash('Empleado creado correctamente', 'success')
            return redirect(url_for('gastos.listado_empleados'))
        except Exception as e:
            db.session.rollback()
            error_msg = f'Error al crear empleado: {str(e)}'
            
            # Si es una petición AJAX, devolver JSON con error
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': False,
                    'message': error_msg
                }), 400
            
            flash(error_msg, 'error')
    
    return render_template('gastos/nuevo_empleado.html')

@gastos_bp.route('/gastos/empleados/<int:empleado_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_empleado(empleado_id):
    """Editar empleado existente"""
    empleado = Empleado.query.get_or_404(empleado_id)
    
    if request.method == 'POST':
        try:
            empleado.nombre = request.form.get('nombre')
            empleado.dni = request.form.get('dni', '')
            empleado.telefono = request.form.get('telefono', '')
            empleado.correo = request.form.get('correo', '')
            db.session.commit()
            flash('Empleado actualizado correctamente', 'success')
            return redirect(url_for('gastos.listado_empleados'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar empleado: {str(e)}', 'error')
    
    return render_template('gastos/editar_empleado.html', empleado=empleado)

@gastos_bp.route('/gastos/empleados/<int:empleado_id>/eliminar', methods=['POST'])
@login_required
def eliminar_empleado(empleado_id):
    """Eliminar empleado"""
    empleado = Empleado.query.get_or_404(empleado_id)
    try:
        # Verificar si tiene nóminas asociadas
        if empleado.nominas:
            flash('No se puede eliminar el empleado porque tiene nóminas asociadas', 'error')
            return redirect(url_for('gastos.listado_empleados'))
        
        db.session.delete(empleado)
        db.session.commit()
        flash('Empleado eliminado correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar empleado: {str(e)}', 'error')
    
    return redirect(url_for('gastos.listado_empleados'))

# ========== NÓMINAS ==========

@gastos_bp.route('/gastos/nominas')
@login_required
def listado_nominas():
    """Listado de nóminas"""
    query = Nomina.query
    
    # Filtro por fecha desde (año-mes)
    año_desde = request.args.get('año_desde', '')
    mes_desde = request.args.get('mes_desde', '')
    if año_desde:
        try:
            año_desde_int = int(año_desde)
            if mes_desde:
                mes_desde_int = int(mes_desde)
                from sqlalchemy import or_, and_
                query = query.filter(
                    or_(
                        Nomina.año > año_desde_int,
                        and_(Nomina.año == año_desde_int, Nomina.mes >= mes_desde_int)
                    )
                )
            else:
                query = query.filter(Nomina.año >= año_desde_int)
        except ValueError:
            pass
    
    # Filtro por fecha hasta (año-mes)
    año_hasta = request.args.get('año_hasta', '')
    mes_hasta = request.args.get('mes_hasta', '')
    if año_hasta:
        try:
            año_hasta_int = int(año_hasta)
            if mes_hasta:
                mes_hasta_int = int(mes_hasta)
                from sqlalchemy import or_, and_
                query = query.filter(
                    or_(
                        Nomina.año < año_hasta_int,
                        and_(Nomina.año == año_hasta_int, Nomina.mes <= mes_hasta_int)
                    )
                )
            else:
                query = query.filter(Nomina.año <= año_hasta_int)
        except ValueError:
            pass
    
    nominas = query.order_by(Nomina.año.desc(), Nomina.mes.desc()).all()
    
    # Obtener años únicos para el filtro
    años = db.session.query(Nomina.año).distinct().order_by(Nomina.año.desc()).all()
    años_list = [año[0] for año in años if año[0]]
    
    return render_template('gastos/listado_nominas.html', 
                         nominas=nominas,
                         años=años_list,
                         año_desde=año_desde,
                         mes_desde=mes_desde,
                         año_hasta=año_hasta,
                         mes_hasta=mes_hasta)

@gastos_bp.route('/gastos/nominas/nueva', methods=['GET', 'POST'])
@login_required
def nueva_nomina():
    """Crear nueva nómina"""
    if request.method == 'POST':
        try:
            nomina = Nomina(
                empleado_id=request.form.get('empleado_id'),
                mes=int(request.form.get('mes')),
                año=int(request.form.get('año')),
                total_devengado=Decimal(str(request.form.get('total_devengado', 0))),
                observaciones=request.form.get('observaciones', '')
            )
            db.session.add(nomina)
            db.session.commit()
            flash('Nómina creada correctamente', 'success')
            return redirect(url_for('gastos.listado_nominas'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear nómina: {str(e)}', 'error')
    
    from datetime import datetime
    año_actual = datetime.now().year
    empleados = Empleado.query.order_by(Empleado.nombre).all()
    return render_template('gastos/nueva_nomina.html', año_actual=año_actual, empleados=empleados)

@gastos_bp.route('/gastos/nominas/<int:nomina_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_nomina(nomina_id):
    """Editar nómina existente"""
    nomina = Nomina.query.get_or_404(nomina_id)
    
    if request.method == 'POST':
        try:
            nomina.empleado_id = request.form.get('empleado_id')
            nomina.mes = int(request.form.get('mes'))
            nomina.año = int(request.form.get('año'))
            nomina.total_devengado = Decimal(str(request.form.get('total_devengado', 0)))
            nomina.observaciones = request.form.get('observaciones', '')
            db.session.commit()
            flash('Nómina actualizada correctamente', 'success')
            return redirect(url_for('gastos.listado_nominas'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar nómina: {str(e)}', 'error')
    
    empleados = Empleado.query.order_by(Empleado.nombre).all()
    return render_template('gastos/editar_nomina.html', nomina=nomina, empleados=empleados)

@gastos_bp.route('/gastos/nominas/<int:nomina_id>/eliminar', methods=['POST'])
@login_required
def eliminar_nomina(nomina_id):
    """Eliminar nómina"""
    nomina = Nomina.query.get_or_404(nomina_id)
    try:
        db.session.delete(nomina)
        db.session.commit()
        flash('Nómina eliminada correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar nómina: {str(e)}', 'error')
    
    return redirect(url_for('gastos.listado_nominas'))

