from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import os
from sqlalchemy import inspect, text
from extensions import db, login_manager, mail
from dotenv import load_dotenv
from markupsafe import Markup

# Cargar variables de entorno desde archivo .env (solo en desarrollo)
load_dotenv()

app = Flask(__name__)

# Filtro personalizado para convertir saltos de línea en <br>
@app.template_filter('nl2br')
def nl2br_filter(value):
    """Convertir saltos de línea en <br> tags"""
    if value:
        return Markup(value.replace('\n', '<br>'))
    return ''

# Configuración de la clave secreta (usar variable de entorno en producción)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tu-clave-secreta-aqui-cambiar-en-produccion')

# Configuración de la base de datos PostgreSQL
# Usar DATABASE_URL (misma para local y producción)
database_url = os.environ.get('DATABASE_URL')
if not database_url:
    raise ValueError(
        "DATABASE_URL no está configurada. "
        "Por favor, configura la variable de entorno DATABASE_URL con la URL completa de PostgreSQL. "
        "Ejemplo: postgresql://usuario:password@host:puerto/nombre_base_datos"
    )

# Render usa postgres:// pero SQLAlchemy necesita postgresql://
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url

# Configuración de PostgreSQL para producción
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,  # Verificar conexiones antes de usarlas
    'pool_recycle': 3600,  # Reciclar conexiones cada hora
    'pool_size': 10,  # Tamaño del pool de conexiones
    'max_overflow': 20,  # Máximo de conexiones adicionales
}

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Configuración de email
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', 'False').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', os.environ.get('MAIL_USERNAME', ''))

# Crear carpeta de uploads si no existe
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Inicializar db con la aplicación
db.init_app(app)

# Inicializar Mail con la aplicación
mail.init_app(app)

# Configurar Flask-Login
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Por favor, inicia sesión para acceder a esta página.'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    """Cargar usuario o cliente desde la sesión"""
    from models import Usuario, Cliente
    
    # Si el ID empieza con 'cliente_', es un cliente
    if user_id.startswith('cliente_'):
        cliente_id = int(user_id.replace('cliente_', ''))
        cliente = Cliente.query.get(cliente_id)
        # Verificar que el cliente tenga acceso web configurado
        if cliente and cliente.tiene_acceso_web():
            return cliente
        return None
    else:
        # Es un usuario del sistema
        return Usuario.query.get(int(user_id))

# Importar modelos (se crean automáticamente al importar models.py)
from models import Comercial, Cliente, Prenda, Pedido, LineaPedido, Presupuesto, LineaPresupuesto, Ticket, LineaTicket, Factura, LineaFactura, Usuario, PlantillaEmail, Proveedor, FacturaProveedor, Empleado, Nomina

# Importar y registrar blueprints
from routes.index import index_bp
from routes.auth import auth_bp
from routes.pedidos import pedidos_bp
from routes.presupuestos import presupuestos_bp
from routes.clientes import clientes_bp
# from routes.comerciales import comerciales_bp  # Ya no se usa
from routes.prendas import prendas_bp
from routes.facturacion import facturacion_bp
from routes.tickets import tickets_bp
from routes.maestros import maestros_bp
from routes.configuracion import configuracion_bp
from routes.cliente_web import cliente_web_bp
from routes.gastos import gastos_bp
from routes.informes import informes_bp

# Registrar blueprints
app.register_blueprint(index_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(pedidos_bp)
app.register_blueprint(presupuestos_bp)
app.register_blueprint(clientes_bp)
# app.register_blueprint(comerciales_bp)  # Ya no se usa
app.register_blueprint(prendas_bp)
app.register_blueprint(facturacion_bp)
app.register_blueprint(tickets_bp)
app.register_blueprint(maestros_bp)
app.register_blueprint(configuracion_bp)
app.register_blueprint(cliente_web_bp)
app.register_blueprint(gastos_bp)
app.register_blueprint(informes_bp)

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
            else:
                # Si no existe la tabla, crearla
                db.create_all()
            
            # Verificar si existe la tabla lineas_pedido y agregar columna estado si no existe
            if 'lineas_pedido' in table_names:
                columns_lineas = [col['name'] for col in inspector.get_columns('lineas_pedido')]
                
                if 'estado' not in columns_lineas:
                    # Agregar la columna estado usando SQL directo
                    with db.engine.connect() as conn:
                        conn.execute(text("ALTER TABLE lineas_pedido ADD COLUMN estado VARCHAR(50) DEFAULT 'pendiente'"))
                        conn.commit()
            
            # Verificar si existe la tabla presupuestos, si no existe crearla
            if 'presupuestos' not in table_names:
                db.create_all()
            else:
                # Verificar si existe la columna seguimiento
                columns_presupuesto = [col['name'] for col in inspector.get_columns('presupuestos')]
                if 'seguimiento' not in columns_presupuesto:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text('ALTER TABLE presupuestos ADD COLUMN seguimiento TEXT'))
                            conn.commit()
                    except Exception:
                        pass
                
                # Verificar y agregar columnas de imágenes para el PDF
                nuevas_columnas_imagenes = {
                    'imagen_portada': 'VARCHAR(255)',
                    'imagen_adicional_1': 'VARCHAR(255)',
                    'imagen_adicional_2': 'VARCHAR(255)',
                    'imagen_adicional_3': 'VARCHAR(255)',
                    'imagen_adicional_4': 'VARCHAR(255)',
                    'imagen_adicional_5': 'VARCHAR(255)',
                    'imagen_adicional_6': 'VARCHAR(255)'
                }
                for columna, tipo in nuevas_columnas_imagenes.items():
                    if columna not in columns_presupuesto:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE presupuestos ADD COLUMN {columna} {tipo}'))
                                conn.commit()
                        except Exception:
                            pass
            
            # Verificar que todas las tablas necesarias existan
            tablas_requeridas = ['comerciales', 'clientes', 'prendas', 'pedidos', 'lineas_pedido', 'presupuestos', 'lineas_presupuesto', 'tickets', 'lineas_ticket', 'facturas', 'lineas_factura', 'usuarios', 'plantillas_email', 'proveedores', 'facturas_proveedor', 'empleados', 'nominas']
            tablas_faltantes = [t for t in tablas_requeridas if t not in table_names]
            if tablas_faltantes:
                db.create_all()
            
            # Verificar y crear tabla plantillas_email si no existe
            if 'plantillas_email' not in table_names:
                db.create_all()
            
            # Inicializar plantillas por defecto si no existen
            from models import PlantillaEmail
            plantillas_por_defecto = [
                {
                    'tipo': 'presupuesto',
                    'asunto': 'Presupuesto #{presupuesto_id} - {cliente_nombre}',
                    'cuerpo': '''Estimado/a {cliente_nombre},

Adjuntamos el presupuesto #{presupuesto_id} solicitado.

Detalles del presupuesto:
- Tipo: {tipo_pedido}
- Fecha: {fecha_creacion}
- Total: {total_con_iva} €

Quedamos a su disposición para cualquier consulta.

Saludos cordiales,
{empresa_nombre}'''
                },
                {
                    'tipo': 'cambio_estado_pedido',
                    'asunto': 'Actualización del pedido #{pedido_id} - Estado: {nuevo_estado}',
                    'cuerpo': '''Estimado/a {cliente_nombre},

Le informamos que el estado de su pedido #{pedido_id} ha cambiado.

Nuevo estado: {nuevo_estado}
Fecha de actualización: {fecha_actualizacion}

Detalles del pedido:
- Tipo: {tipo_pedido}
- Fecha de aceptación: {fecha_aceptacion}
- Fecha objetivo de entrega: {fecha_objetivo}

Quedamos a su disposición para cualquier consulta.

Saludos cordiales,
{empresa_nombre}'''
                }
            ]
            
            for plantilla_data in plantillas_por_defecto:
                plantilla_existente = PlantillaEmail.query.filter_by(tipo=plantilla_data['tipo']).first()
                if not plantilla_existente:
                    nueva_plantilla = PlantillaEmail(
                        tipo=plantilla_data['tipo'],
                        asunto=plantilla_data['asunto'],
                        cuerpo=plantilla_data['cuerpo']
                    )
                    db.session.add(nueva_plantilla)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
            
            # Verificar y agregar columnas nuevas en clientes
            if 'clientes' in table_names:
                columns_clientes = [col['name'] for col in inspector.get_columns('clientes')]
                nuevas_columnas = {
                    'nif': 'VARCHAR(20)',
                    'alias': 'VARCHAR(200)',
                    'poblacion': 'VARCHAR(100)',
                    'provincia': 'VARCHAR(100)',
                    'codigo_postal': 'VARCHAR(10)',
                    'pais': 'VARCHAR(100)',
                    'personas_contacto': 'TEXT',
                    'anotaciones': 'TEXT',
                    'usuario_web': 'VARCHAR(80)',
                    'password_hash': 'VARCHAR(255)',
                    'fecha_creacion': 'TIMESTAMP',
                    'ultimo_acceso': 'TIMESTAMP'
                }
                for columna, tipo in nuevas_columnas.items():
                    if columna not in columns_clientes:
                        try:
                            with db.engine.connect() as conn:
                                if columna == 'usuario_web':
                                    conn.execute(text(f'ALTER TABLE clientes ADD COLUMN {columna} {tipo} UNIQUE'))
                                else:
                                    conn.execute(text(f'ALTER TABLE clientes ADD COLUMN {columna} {tipo}'))
                                conn.commit()
                        except Exception:
                            pass
            
            # Verificar y agregar columnas nuevas en prendas
            if 'prendas' in table_names:
                columns_prendas = [col['name'] for col in inspector.get_columns('prendas')]
                nuevas_columnas_prendas = {
                    'precio_coste': 'NUMERIC(10, 2) DEFAULT 0',
                    'precio_venta': 'NUMERIC(10, 2) DEFAULT 0'
                }
                for columna, tipo in nuevas_columnas_prendas.items():
                    if columna not in columns_prendas:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE prendas ADD COLUMN {columna} {tipo}'))
                                conn.commit()
                        except Exception:
                            pass
            
            # Migrar tabla comerciales para usar usuario_id en lugar de nombre
            if 'comerciales' in table_names:
                columns_comerciales = [col['name'] for col in inspector.get_columns('comerciales')]
                if 'usuario_id' not in columns_comerciales:
                    try:
                        with db.engine.connect() as conn:
                            # Agregar columna usuario_id
                            conn.execute(text('ALTER TABLE comerciales ADD COLUMN usuario_id INTEGER'))
                            conn.execute(text('ALTER TABLE comerciales ADD CONSTRAINT fk_comercial_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id)'))
                            # Eliminar la columna nombre antigua si existe
                            if 'nombre' in columns_comerciales:
                                # Primero eliminar la restricción unique si existe
                                try:
                                    conn.execute(text('ALTER TABLE comerciales DROP CONSTRAINT IF EXISTS comerciales_nombre_key'))
                                except:
                                    pass
                                conn.execute(text('ALTER TABLE comerciales DROP COLUMN nombre'))
                            conn.commit()
                    except Exception:
                        pass
            
            # Verificar y agregar columnas nuevas en tickets
            if 'tickets' in table_names:
                columns_tickets = [col['name'] for col in inspector.get_columns('tickets')]
                nuevas_columnas_tickets = {
                    'forma_pago': 'VARCHAR(100)',
                    'tipo_calculo_iva': 'VARCHAR(20) DEFAULT \'desglosar\''
                }
                for columna, tipo in nuevas_columnas_tickets.items():
                    if columna not in columns_tickets:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE tickets ADD COLUMN {columna} {tipo}'))
                                conn.commit()
                        except Exception:
                            pass
            
            # Verificar y crear tablas de gastos si no existen
            tablas_gastos = ['proveedores', 'facturas_proveedor', 'empleados', 'nominas']
            for tabla in tablas_gastos:
                if tabla not in table_names:
                    try:
                        db.create_all()
                        break  # Si se crean las tablas, salir del bucle
                    except Exception:
                        pass
            
            # Asegurar que la tabla empleados existe antes de migrar nominas
            if 'empleados' not in table_names:
                try:
                    db.create_all()
                    # Refrescar lista de tablas
                    inspector = inspect(db.engine)
                    table_names = inspector.get_table_names()
                except Exception as e:
                    print(f"Error creando tabla empleados: {e}")
            
            # Migrar tabla nominas para usar empleado_id en lugar de empleado (string)
            if 'nominas' in table_names and 'empleados' in table_names:
                columns_nominas = [col['name'] for col in inspector.get_columns('nominas')]
                if 'empleado_id' not in columns_nominas:
                    try:
                        with db.engine.connect() as conn:
                            # Si existe la columna empleado (string), migrar datos primero
                            if 'empleado' in columns_nominas:
                                # Agregar columna empleado_id (temporalmente nullable)
                                conn.execute(text('ALTER TABLE nominas ADD COLUMN empleado_id INTEGER'))
                                conn.commit()
                                
                                # Migrar datos: crear empleados desde los nombres existentes y asignar IDs
                                result = conn.execute(text('SELECT DISTINCT empleado FROM nominas WHERE empleado IS NOT NULL AND empleado != \'\''))
                                empleados_nombres = [row[0] for row in result]
                                
                                # Crear empleados y asignar IDs
                                for nombre_empleado in empleados_nombres:
                                    if nombre_empleado:
                                        # Crear empleado si no existe
                                        check_result = conn.execute(text('SELECT id FROM empleados WHERE nombre = :nombre'), {'nombre': nombre_empleado})
                                        empleado_row = check_result.fetchone()
                                        if not empleado_row:
                                            conn.execute(text('INSERT INTO empleados (nombre, fecha_creacion) VALUES (:nombre, CURRENT_TIMESTAMP)'), {'nombre': nombre_empleado})
                                            conn.commit()
                                            check_result = conn.execute(text('SELECT id FROM empleados WHERE nombre = :nombre'), {'nombre': nombre_empleado})
                                            empleado_row = check_result.fetchone()
                                        
                                        if empleado_row:
                                            empleado_id = empleado_row[0]
                                            # Actualizar nóminas con este empleado_id
                                            conn.execute(text('UPDATE nominas SET empleado_id = :empleado_id WHERE empleado = :nombre'), {'empleado_id': empleado_id, 'nombre': nombre_empleado})
                                            conn.commit()
                                
                                # Agregar constraint de foreign key
                                try:
                                    conn.execute(text('ALTER TABLE nominas ADD CONSTRAINT fk_nomina_empleado FOREIGN KEY (empleado_id) REFERENCES empleados(id)'))
                                    conn.commit()
                                except Exception as e:
                                    # Si la constraint ya existe o hay error, continuar
                                    print(f"Nota al agregar constraint: {e}")
                                    pass
                                
                                # Eliminar columna empleado antigua
                                conn.execute(text('ALTER TABLE nominas DROP COLUMN empleado'))
                                conn.commit()
                            else:
                                # Si no existe empleado, solo agregar la columna empleado_id
                                conn.execute(text('ALTER TABLE nominas ADD COLUMN empleado_id INTEGER'))
                                try:
                                    conn.execute(text('ALTER TABLE nominas ADD CONSTRAINT fk_nomina_empleado FOREIGN KEY (empleado_id) REFERENCES empleados(id)'))
                                    conn.commit()
                                except Exception as e:
                                    print(f"Nota al agregar constraint: {e}")
                                    pass
                        print("Migración de nominas completada exitosamente")
                    except Exception as e:
                        print(f"Error en migración de nominas: {e}")
                        import traceback
                        traceback.print_exc()
                        # Intentar crear todas las tablas como fallback
                        try:
                            db.create_all()
                        except Exception as e2:
                            print(f"Error en create_all: {e2}")
        except Exception:
            # Si hay error, intentar crear todas las tablas
            try:
                db.create_all()
            except Exception:
                pass

# Las rutas ahora están en los blueprints en routes/
# ========== FUNCIONES DE UTILIDAD ==========

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
        from decimal import Decimal
        for prenda_data in prendas_data:
            # Verificar si ya existe
            existe = Prenda.query.filter_by(nombre=prenda_data['nombre']).first()
            if not existe:
                prenda = Prenda(
                    nombre=prenda_data['nombre'],
                    tipo=prenda_data['tipo'],
                    precio_coste=Decimal('0'),
                    precio_venta=Decimal('0')
                )
                db.session.add(prenda)
        
        db.session.commit()
    except Exception:
        db.session.rollback()

# Inicializar base de datos
def init_db():
    """Inicializar la base de datos"""
    with app.app_context():
        db.create_all()
        # Inicializar prendas predefinidas
        init_prendas()

# Función para inicializar usuario supervisor
def init_supervisor():
    """Crear usuario supervisor inicial (jmurillo) si no existe"""
    try:
        from models import Usuario, Comercial
        supervisor = Usuario.query.filter_by(usuario='jmurillo').first()
        if not supervisor:
            supervisor = Usuario(
                usuario='jmurillo',
                correo='jmurillo@example.com',
                telefono='',
                rol='supervisor',
                activo=True
            )
            # Contraseña por defecto: cambiar en producción
            supervisor.set_password('admin123')
            db.session.add(supervisor)
            db.session.flush()  # Para obtener el ID
            
            # Si el supervisor tiene rol administracion, también crear comercial
            # Nota: El supervisor por defecto no es comercial, pero si se cambia a administracion, se creará automáticamente
            db.session.commit()
    except Exception:
        db.session.rollback()

# Función para inicializar la aplicación (se ejecuta después de que todas las rutas estén registradas)
def initialize_app():
    """Inicializar la aplicación y la base de datos"""
    try:
        with app.app_context():
            try:
                migrate_database()
                # Inicializar prendas predefinidas
                init_prendas()
                # Inicializar usuario supervisor
                init_supervisor()
            except Exception:
                # Intentar crear tablas básicas como fallback
                try:
                    db.create_all()
                    init_supervisor()
                except Exception:
                    pass
    except Exception:
        pass

# Inicializar la aplicación cuando se importa el módulo
# Esto asegura que la base de datos esté lista cuando Gunicorn inicie
# Usar un try-except para asegurar que la aplicación se cargue incluso si hay errores
try:
    initialize_app()
except Exception:
    pass

if __name__ == '__main__':
    # Ejecutar migraciones antes de iniciar la aplicación
    migrate_database()
    app.run(debug=True)
