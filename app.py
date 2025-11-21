from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import os
from sqlalchemy import inspect, text, case

app = Flask(__name__)

# Configuración de la clave secreta (usar variable de entorno en producción)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tu-clave-secreta-aqui-cambiar-en-produccion')

# Configuración de la base de datos (SQLite para desarrollo local)
# En Render, puedes usar PostgreSQL configurando DATABASE_URL como variable de entorno
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Si hay DATABASE_URL (PostgreSQL en Render), usarla
    # Render usa postgres:// pero SQLAlchemy necesita postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # SQLite para desarrollo local
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pedidos.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Crear carpeta de uploads si no existe
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Importar y crear modelos después de inicializar db
from models import create_models
Comercial, Cliente, Prenda, Pedido, LineaPedido, Presupuesto, LineaPresupuesto = create_models(db)

def migrate_database():
    """Migrar la base de datos agregando columnas faltantes"""
    with app.app_context():
        try:
            # Verificar si existe la tabla pedidos
            inspector = inspect(db.engine)
            table_names = inspector.get_table_names()
            
            if 'pedidos' in table_names:
                # Verificar si existe la columna fecha_objetivo
                columns = [col['name'] for col in inspector.get_columns('pedidos')]
                
                if 'fecha_objetivo' not in columns:
                    # Agregar la columna fecha_objetivo usando SQL directo
                    with db.engine.connect() as conn:
                        conn.execute(text('ALTER TABLE pedidos ADD COLUMN fecha_objetivo DATE'))
                        conn.commit()
                    print("✓ Columna fecha_objetivo agregada correctamente")
                else:
                    print("✓ La columna fecha_objetivo ya existe")
            else:
                # Si no existe la tabla, crearla
                db.create_all()
                print("✓ Tablas creadas correctamente")
            
            # Verificar si existe la tabla lineas_pedido y agregar columna estado si no existe
            if 'lineas_pedido' in table_names:
                columns_lineas = [col['name'] for col in inspector.get_columns('lineas_pedido')]
                
                if 'estado' not in columns_lineas:
                    # Agregar la columna estado usando SQL directo
                    with db.engine.connect() as conn:
                        conn.execute(text('ALTER TABLE lineas_pedido ADD COLUMN estado VARCHAR(50) DEFAULT "pendiente"'))
                        conn.commit()
                    print("✓ Columna estado agregada a lineas_pedido correctamente")
                else:
                    print("✓ La columna estado ya existe en lineas_pedido")
            
            # Verificar si existe la tabla presupuestos, si no existe crearla
            if 'presupuestos' not in table_names:
                db.create_all()
                print("✓ Tablas de presupuestos creadas correctamente")
            else:
                # Verificar si existe la columna seguimiento
                columns_presupuesto = [col['name'] for col in inspector.get_columns('presupuestos')]
                if 'seguimiento' not in columns_presupuesto:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text('ALTER TABLE presupuestos ADD COLUMN seguimiento TEXT'))
                            conn.commit()
                        print("✓ Columna seguimiento agregada a presupuestos correctamente")
                    except Exception as e:
                        print(f"⚠ No se pudo agregar columna seguimiento (puede que ya exista): {e}")
                else:
                    print("✓ La columna seguimiento ya existe en presupuestos")
            
            # Verificar que todas las tablas necesarias existan
            tablas_requeridas = ['comerciales', 'clientes', 'prendas', 'pedidos', 'lineas_pedido', 'presupuestos', 'lineas_presupuesto']
            tablas_faltantes = [t for t in tablas_requeridas if t not in table_names]
            if tablas_faltantes:
                print(f"⚠ Creando tablas faltantes: {tablas_faltantes}")
                db.create_all()
            print("✓ Verificación de tablas completada")
        except Exception as e:
            print(f"Error en migración: {e}")
            # Si hay error, intentar crear todas las tablas
            try:
                db.create_all()
                print("✓ Tablas creadas como fallback")
            except Exception as e2:
                print(f"Error al crear tablas: {e2}")

@app.route('/')
def index():
    """Página principal con lista de pedidos"""
    try:
        # Obtener todos los pedidos
        pedidos = Pedido.query.all()
        
        # Calcular fecha objetivo de entrega (20 días desde aceptación) y clasificar
        hoy = datetime.now().date()
        
        for pedido in pedidos:
            # Si no tiene fecha objetivo pero tiene fecha de aceptación, calcularla (20 días)
            if pedido.fecha_aceptacion and not pedido.fecha_objetivo:
                pedido.fecha_objetivo = pedido.fecha_aceptacion + timedelta(days=20)
            
            if pedido.fecha_objetivo:
                # Calcular días restantes hasta la fecha objetivo
                dias_restantes = (pedido.fecha_objetivo - hoy).days
                
                # Clasificar fecha objetivo según días restantes
                if dias_restantes <= 5:
                    # 5 días o menos (incluye vencidos): Rojo
                    pedido.fecha_class = 'urgente'
                elif dias_restantes <= 10:
                    # Entre 6 y 10 días: Naranja
                    pedido.fecha_class = 'proxima'
                else:
                    # Más de 10 días: Verde
                    pedido.fecha_class = 'ok'
            else:
                pedido.fecha_class = ''
        
        # Ordenar por fecha objetivo (más próximos primero), los que no tienen fecha objetivo al final
        pedidos.sort(key=lambda p: (
            p.fecha_objetivo if p.fecha_objetivo else datetime.max.date(),
            p.fecha_aceptacion if p.fecha_aceptacion else datetime.max.date()
        ))
        
        return render_template('index.html', pedidos=pedidos)
    except Exception as e:
        import traceback
        error_msg = f"Error en index: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        flash(f'Error al cargar el panel de control: {str(e)}', 'error')
        return render_template('index.html', pedidos=[])

@app.route('/pedidos')
def listado_pedidos():
    """Listado de pedidos con opciones de editar y eliminar"""
    # Obtener todos los pedidos
    pedidos = Pedido.query.order_by(Pedido.id.desc()).all()
    
    # Calcular fecha objetivo de entrega (20 días desde aceptación) y clasificar
    hoy = datetime.now().date()
    
    for pedido in pedidos:
        # Si no tiene fecha objetivo pero tiene fecha de aceptación, calcularla (20 días)
        if pedido.fecha_aceptacion and not pedido.fecha_objetivo:
            pedido.fecha_objetivo = pedido.fecha_aceptacion + timedelta(days=20)
        
        if pedido.fecha_objetivo:
            # Calcular días restantes hasta la fecha objetivo
            dias_restantes = (pedido.fecha_objetivo - hoy).days
            
            # Clasificar fecha objetivo según días restantes
            if dias_restantes <= 5:
                # 5 días o menos (incluye vencidos): Rojo
                pedido.fecha_class = 'urgente'
            elif dias_restantes <= 10:
                # Entre 6 y 10 días: Naranja
                pedido.fecha_class = 'proxima'
            else:
                # Más de 10 días: Verde
                pedido.fecha_class = 'ok'
        else:
            pedido.fecha_class = ''
    
    return render_template('listado_pedidos.html', pedidos=pedidos)

@app.route('/pedidos/nuevo', methods=['GET', 'POST'])
def nuevo_pedido():
    """Crear nuevo pedido"""
    if request.method == 'POST':
        try:
            # Procesar fechas
            fecha_aceptacion = None
            if request.form.get('fecha_aceptacion'):
                fecha_aceptacion = datetime.strptime(request.form.get('fecha_aceptacion'), '%Y-%m-%d').date()
            
            fecha_objetivo = None
            if request.form.get('fecha_objetivo'):
                # Si se proporciona fecha objetivo, usarla
                fecha_objetivo = datetime.strptime(request.form.get('fecha_objetivo'), '%Y-%m-%d').date()
            elif fecha_aceptacion:
                # Si no se proporciona pero hay fecha de aceptación, calcularla automáticamente (20 días)
                fecha_objetivo = fecha_aceptacion + timedelta(days=20)
            
            # Crear pedido
            pedido = Pedido(
                comercial_id=request.form.get('comercial_id'),
                cliente_id=request.form.get('cliente_id'),
                tipo_pedido=request.form.get('tipo_pedido'),
                estado=request.form.get('estado', 'Pendiente'),
                forma_pago=request.form.get('forma_pago', ''),
                fecha_aceptacion=fecha_aceptacion,
                fecha_objetivo=fecha_objetivo
            )
            
            # Manejar imagen de diseño
            if 'imagen_diseno' in request.files:
                file = request.files['imagen_diseno']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                    filename = timestamp + filename
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    pedido.imagen_diseno = filename
            
            db.session.add(pedido)
            db.session.flush()  # Para obtener el ID del pedido
            
            # Crear líneas de pedido
            prenda_ids = request.form.getlist('prenda_id[]')
            nombres = request.form.getlist('nombre[]')
            cargos = request.form.getlist('cargo[]')
            cantidades = request.form.getlist('cantidad[]')
            colores = request.form.getlist('color[]')
            formas = request.form.getlist('forma[]')
            tipos_manda = request.form.getlist('tipo_manda[]')
            sexos = request.form.getlist('sexo[]')
            tallas = request.form.getlist('talla[]')
            tejidos = request.form.getlist('tejido[]')
            estados_lineas = request.form.getlist('estado_linea[]')
            
            for i in range(len(prenda_ids)):
                if prenda_ids[i] and nombres[i]:
                    linea = LineaPedido(
                        pedido_id=pedido.id,
                        prenda_id=prenda_ids[i],
                        nombre=nombres[i],
                        cargo=cargos[i] if i < len(cargos) else '',
                        cantidad=int(cantidades[i]) if cantidades[i] else 1,
                        color=colores[i] if i < len(colores) else '',
                        forma=formas[i] if i < len(formas) else '',
                        tipo_manda=tipos_manda[i] if i < len(tipos_manda) else '',
                        sexo=sexos[i] if i < len(sexos) else '',
                        talla=tallas[i] if i < len(tallas) else '',
                        tejido=tejidos[i] if i < len(tejidos) else '',
                        estado=estados_lineas[i] if i < len(estados_lineas) and estados_lineas[i] else 'pendiente'
                    )
                    db.session.add(linea)
            
            db.session.commit()
            flash('Pedido creado correctamente', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear pedido: {str(e)}', 'error')
    
    comerciales = Comercial.query.all()
    clientes = Cliente.query.all()
    prendas = Prenda.query.all()
    return render_template('nuevo_pedido.html', 
                         comerciales=comerciales, 
                         clientes=clientes, 
                         prendas=prendas)

@app.route('/pedidos/<int:pedido_id>/editar', methods=['GET', 'POST'])
def editar_pedido(pedido_id):
    """Editar pedido existente"""
    pedido = Pedido.query.get_or_404(pedido_id)
    
    if request.method == 'POST':
        try:
            pedido.comercial_id = request.form.get('comercial_id')
            pedido.cliente_id = request.form.get('cliente_id')
            pedido.tipo_pedido = request.form.get('tipo_pedido')
            pedido.estado = request.form.get('estado')
            pedido.forma_pago = request.form.get('forma_pago', '')
            
            # Fechas
            if request.form.get('fecha_aceptacion'):
                pedido.fecha_aceptacion = datetime.strptime(request.form.get('fecha_aceptacion'), '%Y-%m-%d')
            if request.form.get('fecha_entrega_trabajo'):
                pedido.fecha_entrega_trabajo = datetime.strptime(request.form.get('fecha_entrega_trabajo'), '%Y-%m-%d')
            if request.form.get('fecha_envio_taller'):
                pedido.fecha_envio_taller = datetime.strptime(request.form.get('fecha_envio_taller'), '%Y-%m-%d')
            if request.form.get('fecha_entrega_bordados'):
                pedido.fecha_entrega_bordados = datetime.strptime(request.form.get('fecha_entrega_bordados'), '%Y-%m-%d')
            if request.form.get('fecha_entrega_cliente'):
                pedido.fecha_entrega_cliente = datetime.strptime(request.form.get('fecha_entrega_cliente'), '%Y-%m-%d')
            
            # Manejar nueva imagen de diseño
            if 'imagen_diseno' in request.files:
                file = request.files['imagen_diseno']
                if file and file.filename:
                    # Eliminar imagen anterior si existe
                    if pedido.imagen_diseno:
                        old_path = os.path.join(app.config['UPLOAD_FOLDER'], pedido.imagen_diseno)
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                    filename = timestamp + filename
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    pedido.imagen_diseno = filename
            
            # Eliminar líneas existentes
            LineaPedido.query.filter_by(pedido_id=pedido.id).delete()
            
            # Crear nuevas líneas
            prenda_ids = request.form.getlist('prenda_id[]')
            nombres = request.form.getlist('nombre[]')
            cargos = request.form.getlist('cargo[]')
            cantidades = request.form.getlist('cantidad[]')
            colores = request.form.getlist('color[]')
            formas = request.form.getlist('forma[]')
            tipos_manda = request.form.getlist('tipo_manda[]')
            sexos = request.form.getlist('sexo[]')
            tallas = request.form.getlist('talla[]')
            tejidos = request.form.getlist('tejido[]')
            estados_lineas = request.form.getlist('estado_linea[]')
            
            for i in range(len(prenda_ids)):
                if prenda_ids[i] and nombres[i]:
                    linea = LineaPedido(
                        pedido_id=pedido.id,
                        prenda_id=prenda_ids[i],
                        nombre=nombres[i],
                        cargo=cargos[i] if i < len(cargos) else '',
                        cantidad=int(cantidades[i]) if cantidades[i] else 1,
                        color=colores[i] if i < len(colores) else '',
                        forma=formas[i] if i < len(formas) else '',
                        tipo_manda=tipos_manda[i] if i < len(tipos_manda) else '',
                        sexo=sexos[i] if i < len(sexos) else '',
                        talla=tallas[i] if i < len(tallas) else '',
                        tejido=tejidos[i] if i < len(tejidos) else '',
                        estado=estados_lineas[i] if i < len(estados_lineas) and estados_lineas[i] else 'pendiente'
                    )
                    db.session.add(linea)
            
            db.session.commit()
            flash('Pedido actualizado correctamente', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar pedido: {str(e)}', 'error')
    
    comerciales = Comercial.query.all()
    clientes = Cliente.query.all()
    prendas = Prenda.query.all()
    return render_template('editar_pedido.html', 
                         pedido=pedido,
                         comerciales=comerciales, 
                         clientes=clientes, 
                         prendas=prendas)

@app.route('/pedidos/<int:pedido_id>')
def ver_pedido(pedido_id):
    """Vista detallada del pedido"""
    pedido = Pedido.query.get_or_404(pedido_id)
    # Calcular fecha objetivo
    hoy = datetime.now().date()
    fecha_objetivo = None
    fecha_class = ''
    
    # Usar fecha objetivo guardada, o calcularla si no existe (20 días desde aceptación)
    if pedido.fecha_objetivo:
        fecha_objetivo = pedido.fecha_objetivo
    elif pedido.fecha_aceptacion:
        fecha_objetivo = pedido.fecha_aceptacion + timedelta(days=20)
    else:
        fecha_objetivo = None
    
    if fecha_objetivo:
        # Calcular días restantes hasta la fecha objetivo
        dias_restantes = (fecha_objetivo - hoy).days
        
        # Clasificar fecha objetivo según días restantes
        if dias_restantes <= 5:
            # 5 días o menos (incluye vencidos): Rojo
            fecha_class = 'urgente'
        elif dias_restantes <= 10:
            # Entre 6 y 10 días: Naranja
            fecha_class = 'proxima'
        else:
            # Más de 10 días: Verde
            fecha_class = 'ok'
    else:
        fecha_class = ''
    
    return render_template('ver_pedido.html', 
                         pedido=pedido, 
                         fecha_objetivo=fecha_objetivo,
                         fecha_class=fecha_class)

@app.route('/pedidos/<int:pedido_id>/cambiar-estado', methods=['POST'])
def cambiar_estado_pedido(pedido_id):
    """Cambiar el estado del pedido y actualizar la fecha correspondiente"""
    pedido = Pedido.query.get_or_404(pedido_id)
    nuevo_estado = request.form.get('estado')
    hoy = datetime.now().date()
    
    try:
        # Mapeo de estados a fechas y nombres de estado
        estados_fechas = {
            'Pendiente': (None, 'Pendiente'),
            'En preparación': ('fecha_aceptacion', 'En preparación'),
            'Todo listo': (None, 'Todo listo'),
            'Enviado': (None, 'Enviado'),
            'Entregado al cliente': ('fecha_entrega_cliente', 'Entregado al cliente')
        }
        
        if nuevo_estado in estados_fechas:
            fecha_campo, estado_nombre = estados_fechas[nuevo_estado]
            
            # Actualizar el estado
            pedido.estado = estado_nombre
            
            # Si tiene fecha asociada, actualizar la fecha a hoy
            if fecha_campo:
                setattr(pedido, fecha_campo, hoy)
            
            db.session.commit()
            flash(f'Estado del pedido cambiado a "{estado_nombre}"', 'success')
        else:
            flash('Estado no válido', 'error')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar el estado: {str(e)}', 'error')
    
    return redirect(url_for('ver_pedido', pedido_id=pedido_id))

@app.route('/pedidos/<int:pedido_id>/lineas/<int:linea_id>/cambiar-estado', methods=['POST'])
def cambiar_estado_linea(pedido_id, linea_id):
    """Cambiar el estado de una línea de pedido"""
    linea = LineaPedido.query.get_or_404(linea_id)
    nuevo_estado = request.form.get('estado')
    
    # Validar que la línea pertenece al pedido
    if linea.pedido_id != pedido_id:
        flash('La línea no pertenece a este pedido', 'error')
        return redirect(url_for('ver_pedido', pedido_id=pedido_id))
    
    # Validar estados permitidos
    estados_permitidos = ['pendiente', 'en confección', 'en bordado', 'listo']
    
    try:
        if nuevo_estado in estados_permitidos:
            linea.estado = nuevo_estado
            db.session.commit()
            flash(f'Estado de la línea "{linea.nombre}" cambiado a "{nuevo_estado}"', 'success')
        else:
            flash('Estado no válido', 'error')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar el estado: {str(e)}', 'error')
    
    return redirect(url_for('ver_pedido', pedido_id=pedido_id))

@app.route('/pedidos/<int:pedido_id>/imprimir')
def imprimir_pedido(pedido_id):
    """Vista de impresión del pedido"""
    pedido = Pedido.query.get_or_404(pedido_id)
    return render_template('imprimir_pedido.html', pedido=pedido)

@app.route('/pedidos/<int:pedido_id>/eliminar', methods=['POST'])
def eliminar_pedido(pedido_id):
    """Eliminar pedido"""
    pedido = Pedido.query.get_or_404(pedido_id)
    try:
        # Eliminar imagen si existe
        if pedido.imagen_diseno:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], pedido.imagen_diseno)
            if os.path.exists(filepath):
                os.remove(filepath)
        
        db.session.delete(pedido)
        db.session.commit()
        flash('Pedido eliminado correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar pedido: {str(e)}', 'error')
    
    return redirect(url_for('index'))

# Rutas para gestión de comerciales
@app.route('/comerciales', methods=['GET', 'POST'])
def gestion_comerciales():
    if request.method == 'POST':
        try:
            comercial = Comercial(nombre=request.form.get('nombre'))
            db.session.add(comercial)
            db.session.commit()
            flash('Comercial creado correctamente', 'success')
            return redirect(url_for('gestion_comerciales'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    comerciales = Comercial.query.all()
    return render_template('comerciales.html', comerciales=comerciales)

@app.route('/comerciales/<int:id>/eliminar', methods=['POST'])
def eliminar_comercial(id):
    comercial = Comercial.query.get_or_404(id)
    db.session.delete(comercial)
    db.session.commit()
    flash('Comercial eliminado', 'success')
    return redirect(url_for('gestion_comerciales'))

# Rutas para gestión de clientes
@app.route('/clientes', methods=['GET', 'POST'])
def gestion_clientes():
    if request.method == 'POST':
        try:
            cliente = Cliente(
                nombre=request.form.get('nombre'),
                direccion=request.form.get('direccion', ''),
                telefono=request.form.get('telefono', ''),
                email=request.form.get('email', '')
            )
            db.session.add(cliente)
            db.session.commit()
            flash('Cliente creado correctamente', 'success')
            return redirect(url_for('gestion_clientes'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    clientes = Cliente.query.all()
    return render_template('clientes.html', clientes=clientes)

@app.route('/clientes/<int:id>/eliminar', methods=['POST'])
def eliminar_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    db.session.delete(cliente)
    db.session.commit()
    flash('Cliente eliminado', 'success')
    return redirect(url_for('gestion_clientes'))

# Rutas para gestión de prendas
@app.route('/prendas', methods=['GET', 'POST'])
def gestion_prendas():
    if request.method == 'POST':
        try:
            prenda = Prenda(
                nombre=request.form.get('nombre'),
                tipo=request.form.get('tipo')
            )
            db.session.add(prenda)
            db.session.commit()
            flash('Prenda creada correctamente', 'success')
            return redirect(url_for('gestion_prendas'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    prendas = Prenda.query.all()
    return render_template('prendas.html', prendas=prendas)

@app.route('/prendas/<int:id>/eliminar', methods=['POST'])
def eliminar_prenda(id):
    prenda = Prenda.query.get_or_404(id)
    db.session.delete(prenda)
    db.session.commit()
    flash('Prenda eliminada', 'success')
    return redirect(url_for('gestion_prendas'))

# Ruta para facturación
@app.route('/facturacion')
def facturacion():
    """Página de facturación con facturas pendientes de formalizar"""
    # Obtener todos los pedidos
    pedidos = Pedido.query.order_by(Pedido.id.desc()).all()
    
    return render_template('facturacion.html', pedidos=pedidos)

@app.route('/facturacion/<int:pedido_id>')
def ver_factura(pedido_id):
    """Vista detallada de una factura para introducir importes"""
    pedido = Pedido.query.get_or_404(pedido_id)
    
    return render_template('ver_factura.html', pedido=pedido)

# ========== RUTAS PARA PRESUPUESTOS ==========

@app.route('/presupuestos')
def listado_presupuestos():
    """Listado de presupuestos"""
    presupuestos = Presupuesto.query.order_by(Presupuesto.id.desc()).all()
    return render_template('listado_presupuestos.html', presupuestos=presupuestos)

@app.route('/presupuestos/nuevo', methods=['GET', 'POST'])
def nuevo_presupuesto():
    """Crear nuevo presupuesto"""
    if request.method == 'POST':
        try:
            # Crear presupuesto
            presupuesto = Presupuesto(
                comercial_id=request.form.get('comercial_id'),
                cliente_id=request.form.get('cliente_id'),
                tipo_pedido=request.form.get('tipo_pedido'),
                estado=request.form.get('estado', 'Pendiente de enviar'),
                forma_pago=request.form.get('forma_pago', ''),
                seguimiento=request.form.get('seguimiento', '')
            )
            
            # Manejar imagen de diseño
            if 'imagen_diseno' in request.files:
                file = request.files['imagen_diseno']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                    filename = timestamp + filename
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    presupuesto.imagen_diseno = filename
            
            db.session.add(presupuesto)
            db.session.flush()  # Para obtener el ID del presupuesto
            
            # Crear líneas de presupuesto
            prenda_ids = request.form.getlist('prenda_id[]')
            nombres = request.form.getlist('nombre[]')
            cargos = request.form.getlist('cargo[]')
            cantidades = request.form.getlist('cantidad[]')
            colores = request.form.getlist('color[]')
            formas = request.form.getlist('forma[]')
            tipos_manda = request.form.getlist('tipo_manda[]')
            sexos = request.form.getlist('sexo[]')
            tallas = request.form.getlist('talla[]')
            tejidos = request.form.getlist('tejido[]')
            
            for i in range(len(prenda_ids)):
                if prenda_ids[i] and nombres[i]:
                    linea = LineaPresupuesto(
                        presupuesto_id=presupuesto.id,
                        prenda_id=prenda_ids[i],
                        nombre=nombres[i],
                        cargo=cargos[i] if i < len(cargos) else '',
                        cantidad=int(cantidades[i]) if cantidades[i] else 1,
                        color=colores[i] if i < len(colores) else '',
                        forma=formas[i] if i < len(formas) else '',
                        tipo_manda=tipos_manda[i] if i < len(tipos_manda) else '',
                        sexo=sexos[i] if i < len(sexos) else '',
                        talla=tallas[i] if i < len(tallas) else '',
                        tejido=tejidos[i] if i < len(tejidos) else ''
                    )
                    db.session.add(linea)
            
            db.session.commit()
            flash('Presupuesto creado correctamente', 'success')
            return redirect(url_for('listado_presupuestos'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear presupuesto: {str(e)}', 'error')
    
    comerciales = Comercial.query.all()
    clientes = Cliente.query.all()
    prendas = Prenda.query.all()
    return render_template('nuevo_presupuesto.html', 
                         comerciales=comerciales, 
                         clientes=clientes, 
                         prendas=prendas)

@app.route('/presupuestos/<int:presupuesto_id>')
def ver_presupuesto(presupuesto_id):
    """Vista detallada del presupuesto"""
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    return render_template('ver_presupuesto.html', presupuesto=presupuesto)

@app.route('/presupuestos/<int:presupuesto_id>/editar', methods=['GET', 'POST'])
def editar_presupuesto(presupuesto_id):
    """Editar presupuesto existente"""
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    
    if request.method == 'POST':
        try:
            presupuesto.comercial_id = request.form.get('comercial_id')
            presupuesto.cliente_id = request.form.get('cliente_id')
            presupuesto.tipo_pedido = request.form.get('tipo_pedido')
            presupuesto.estado = request.form.get('estado')
            presupuesto.forma_pago = request.form.get('forma_pago', '')
            presupuesto.seguimiento = request.form.get('seguimiento', '')
            
            # Fechas
            if request.form.get('fecha_envio'):
                presupuesto.fecha_envio = datetime.strptime(request.form.get('fecha_envio'), '%Y-%m-%d').date()
            if request.form.get('fecha_respuesta'):
                presupuesto.fecha_respuesta = datetime.strptime(request.form.get('fecha_respuesta'), '%Y-%m-%d').date()
            
            # Manejar nueva imagen de diseño
            if 'imagen_diseno' in request.files:
                file = request.files['imagen_diseno']
                if file and file.filename:
                    # Eliminar imagen anterior si existe
                    if presupuesto.imagen_diseno:
                        old_path = os.path.join(app.config['UPLOAD_FOLDER'], presupuesto.imagen_diseno)
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                    filename = timestamp + filename
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    presupuesto.imagen_diseno = filename
            
            # Eliminar líneas existentes
            LineaPresupuesto.query.filter_by(presupuesto_id=presupuesto.id).delete()
            
            # Crear nuevas líneas
            prenda_ids = request.form.getlist('prenda_id[]')
            nombres = request.form.getlist('nombre[]')
            cargos = request.form.getlist('cargo[]')
            cantidades = request.form.getlist('cantidad[]')
            colores = request.form.getlist('color[]')
            formas = request.form.getlist('forma[]')
            tipos_manda = request.form.getlist('tipo_manda[]')
            sexos = request.form.getlist('sexo[]')
            tallas = request.form.getlist('talla[]')
            tejidos = request.form.getlist('tejido[]')
            
            for i in range(len(prenda_ids)):
                if prenda_ids[i] and nombres[i]:
                    linea = LineaPresupuesto(
                        presupuesto_id=presupuesto.id,
                        prenda_id=prenda_ids[i],
                        nombre=nombres[i],
                        cargo=cargos[i] if i < len(cargos) else '',
                        cantidad=int(cantidades[i]) if cantidades[i] else 1,
                        color=colores[i] if i < len(colores) else '',
                        forma=formas[i] if i < len(formas) else '',
                        tipo_manda=tipos_manda[i] if i < len(tipos_manda) else '',
                        sexo=sexos[i] if i < len(sexos) else '',
                        talla=tallas[i] if i < len(tallas) else '',
                        tejido=tejidos[i] if i < len(tejidos) else ''
                    )
                    db.session.add(linea)
            
            db.session.commit()
            flash('Presupuesto actualizado correctamente', 'success')
            return redirect(url_for('listado_presupuestos'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar presupuesto: {str(e)}', 'error')
    
    comerciales = Comercial.query.all()
    clientes = Cliente.query.all()
    prendas = Prenda.query.all()
    return render_template('editar_presupuesto.html', 
                         presupuesto=presupuesto,
                         comerciales=comerciales, 
                         clientes=clientes, 
                         prendas=prendas)

@app.route('/presupuestos/<int:presupuesto_id>/cambiar-estado', methods=['POST'])
def cambiar_estado_presupuesto(presupuesto_id):
    """Cambiar el estado del presupuesto y actualizar la fecha correspondiente"""
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    nuevo_estado = request.form.get('estado')
    hoy = datetime.now().date()
    
    print(f"DEBUG: cambiar_estado_presupuesto llamado - presupuesto_id: {presupuesto_id}, nuevo_estado: {nuevo_estado}")
    
    try:
        # Guardar el estado anterior antes de actualizarlo
        estado_anterior = presupuesto.estado
        print(f"DEBUG: estado_anterior: {estado_anterior}")
        
        # Mapeo de estados a fechas
        estados_fechas = {
            'Pendiente de enviar': (None, 'Pendiente de enviar'),
            'Enviado': ('fecha_envio', 'Enviado'),
            'Aceptado': ('fecha_respuesta', 'Aceptado'),
            'Rechazado': ('fecha_respuesta', 'Rechazado')
        }
        
        if nuevo_estado in estados_fechas:
            fecha_campo, estado_nombre = estados_fechas[nuevo_estado]
            
            # Actualizar el estado
            presupuesto.estado = estado_nombre
            
            # Si tiene fecha asociada, actualizar la fecha a hoy
            if fecha_campo:
                setattr(presupuesto, fecha_campo, hoy)
            
            # Si el presupuesto se acepta, crear un pedido automáticamente
            if nuevo_estado == 'Aceptado' and estado_anterior != 'Aceptado':
                print(f"DEBUG: Condición cumplida - nuevo_estado es 'Aceptado' y estado_anterior no es 'Aceptado'")
                # Solo crear pedido si el presupuesto no estaba ya aceptado
                # Asegurarse de que las líneas estén cargadas
                lineas_presupuesto = LineaPresupuesto.query.filter_by(presupuesto_id=presupuesto.id).all()
                print(f"DEBUG: Líneas encontradas: {len(lineas_presupuesto)}")
                
                if not lineas_presupuesto:
                    db.session.commit()
                    flash('Presupuesto aceptado, pero no se pudo crear el pedido porque no tiene prendas asociadas', 'error')
                    return redirect(url_for('ver_presupuesto', presupuesto_id=presupuesto_id))
                
                try:
                    print(f"DEBUG: Creando pedido para presupuesto {presupuesto.id}")
                    # Crear nuevo pedido basado en el presupuesto
                    pedido = Pedido(
                        comercial_id=presupuesto.comercial_id,
                        cliente_id=presupuesto.cliente_id,
                        tipo_pedido=presupuesto.tipo_pedido,
                        estado='Pendiente',
                        forma_pago=presupuesto.forma_pago or '',
                        imagen_diseno=presupuesto.imagen_diseno,
                        fecha_aceptacion=hoy,
                        fecha_objetivo=hoy + timedelta(days=20)  # 20 días desde aceptación
                    )
                    db.session.add(pedido)
                    db.session.flush()  # Para obtener el ID del pedido
                    print(f"DEBUG: Pedido creado con ID: {pedido.id}")
                    
                    # Copiar las líneas del presupuesto al pedido
                    for linea_presupuesto in lineas_presupuesto:
                        linea_pedido = LineaPedido(
                            pedido_id=pedido.id,
                            prenda_id=linea_presupuesto.prenda_id,
                            nombre=linea_presupuesto.nombre,
                            cargo=linea_presupuesto.cargo or '',
                            cantidad=linea_presupuesto.cantidad,
                            color=linea_presupuesto.color or '',
                            forma=linea_presupuesto.forma or '',
                            tipo_manda=linea_presupuesto.tipo_manda or '',
                            sexo=linea_presupuesto.sexo or '',
                            talla=linea_presupuesto.talla or '',
                            tejido=linea_presupuesto.tejido or '',
                            estado='pendiente'
                        )
                        db.session.add(linea_pedido)
                    
                    print(f"DEBUG: Líneas agregadas, haciendo commit...")
                    db.session.commit()
                    print(f"DEBUG: Commit exitoso. Pedido #{pedido.id} creado")
                    flash(f'Presupuesto aceptado. Se ha creado el pedido #{pedido.id} en estado Pendiente', 'success')
                except Exception as e_inner:
                    db.session.rollback()
                    import traceback
                    print(f"ERROR al crear pedido: {traceback.format_exc()}")
                    flash(f'Error al crear el pedido: {str(e_inner)}', 'error')
            else:
                print(f"DEBUG: No se cumple la condición para crear pedido - nuevo_estado: {nuevo_estado}, estado_anterior: {estado_anterior}")
                db.session.commit()
                if nuevo_estado == 'Aceptado' and estado_anterior == 'Aceptado':
                    flash(f'El presupuesto ya estaba aceptado. Estado actualizado.', 'success')
                else:
                    flash(f'Estado del presupuesto cambiado a "{estado_nombre}"', 'success')
        else:
            flash(f'Estado no válido: {nuevo_estado}', 'error')
            
    except Exception as e:
        db.session.rollback()
        import traceback
        error_msg = f'Error al cambiar el estado: {str(e)}'
        print(f"Error completo: {traceback.format_exc()}")
        flash(error_msg, 'error')
    
    return redirect(url_for('ver_presupuesto', presupuesto_id=presupuesto_id))

@app.route('/presupuestos/<int:presupuesto_id>/actualizar-seguimiento', methods=['POST'])
def actualizar_seguimiento(presupuesto_id):
    """Actualizar el campo de seguimiento del presupuesto"""
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    nuevo_seguimiento = request.form.get('seguimiento', '')
    
    try:
        presupuesto.seguimiento = nuevo_seguimiento
        db.session.commit()
        flash('Seguimiento actualizado correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar seguimiento: {str(e)}', 'error')
    
    return redirect(url_for('ver_presupuesto', presupuesto_id=presupuesto_id))

@app.route('/presupuestos/<int:presupuesto_id>/eliminar', methods=['POST'])
def eliminar_presupuesto(presupuesto_id):
    """Eliminar presupuesto"""
    presupuesto = Presupuesto.query.get_or_404(presupuesto_id)
    try:
        # Eliminar imagen si existe
        if presupuesto.imagen_diseno:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], presupuesto.imagen_diseno)
            if os.path.exists(filepath):
                os.remove(filepath)
        
        db.session.delete(presupuesto)
        db.session.commit()
        flash('Presupuesto eliminado correctamente', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar presupuesto: {str(e)}', 'error')
    
    return redirect(url_for('listado_presupuestos'))

# Función para inicializar prendas predefinidas
def init_prendas():
    """Inicializar prendas predefinidas en la base de datos"""
    # Lista de prendas con sus tipos (todos los valores de la imagen)
    prendas_data = [
        # Primer valor (puntos)
        {'nombre': '.........', 'tipo': 'otro'},
        # Códigos/Tallas
        {'nombre': 'T1', 'tipo': 'otro'},
        {'nombre': 'T2', 'tipo': 'otro'},
        {'nombre': 'T3', 'tipo': 'otro'},
        {'nombre': 'T4', 'tipo': 'otro'},
        {'nombre': 'T5', 'tipo': 'otro'},
        {'nombre': 'T201', 'tipo': 'otro'},
        {'nombre': 'T301', 'tipo': 'otro'},
        {'nombre': 'T401', 'tipo': 'otro'},
        # Delantales/Mandiles
        {'nombre': 'COCINA', 'tipo': 'otro'},
        {'nombre': 'MAD.CORTO', 'tipo': 'otro'},
        {'nombre': 'MAD.PETO', 'tipo': 'otro'},
        {'nombre': 'MAD.FRANCES', 'tipo': 'otro'},
        # Camisas
        {'nombre': 'CAMISA.CELEST', 'tipo': 'camisa'},
        {'nombre': 'CAMISA.BLANC.', 'tipo': 'camisa'},
        {'nombre': 'CAMISA OTRO', 'tipo': 'camisa'},
        {'nombre': 'CAM. NEGRA', 'tipo': 'camisa'},
        {'nombre': 'CAM.NARAN.', 'tipo': 'camisa'},
        {'nombre': 'CAM.AZ.MAR.', 'tipo': 'camisa'},
        {'nombre': 'CAM. AMARL.', 'tipo': 'camisa'},
        {'nombre': 'CAM. AZ.CEL.', 'tipo': 'camisa'},
    ]
    
    try:
        for prenda_data in prendas_data:
            # Verificar si ya existe
            existe = Prenda.query.filter_by(nombre=prenda_data['nombre']).first()
            if not existe:
                prenda = Prenda(
                    nombre=prenda_data['nombre'],
                    tipo=prenda_data['tipo']
                )
                db.session.add(prenda)
        
        db.session.commit()
        print(f"✓ Prendas inicializadas correctamente")
    except Exception as e:
        db.session.rollback()
        print(f"Error al inicializar prendas: {e}")

# Inicializar base de datos
def init_db():
    """Inicializar la base de datos"""
    with app.app_context():
        db.create_all()
        # Inicializar prendas predefinidas
        init_prendas()

# Función para inicializar la aplicación (se ejecuta después de que todas las rutas estén registradas)
def initialize_app():
    """Inicializar la aplicación y la base de datos"""
    try:
        with app.app_context():
            try:
                migrate_database()
                # Inicializar prendas predefinidas
                init_prendas()
                print("✓ Aplicación inicializada correctamente")
            except Exception as e:
                print(f"⚠ Error en inicialización: {e}")
                import traceback
                print(traceback.format_exc())
                # Intentar crear tablas básicas como fallback
                try:
                    db.create_all()
                    print("✓ Tablas creadas como fallback")
                except Exception as e2:
                    print(f"⚠ Error al crear tablas: {e2}")
    except Exception as e:
        # Si hay un error crítico, al menos registrar que ocurrió
        print(f"⚠ Error crítico en initialize_app: {e}")
        import traceback
        print(traceback.format_exc())

# Inicializar la aplicación cuando se importa el módulo
# Esto asegura que la base de datos esté lista cuando Gunicorn inicie
# Usar un try-except para asegurar que la aplicación se cargue incluso si hay errores
try:
    initialize_app()
except Exception as e:
    print(f"⚠ Error al inicializar aplicación (continuando de todos modos): {e}")

if __name__ == '__main__':
    print("✓ Aplicación iniciada correctamente")
    print(f"✓ Rutas disponibles: {[rule.rule for rule in app.url_map.iter_rules()]}")
    app.run(debug=True)

