from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import os
from sqlalchemy import inspect, text, case, event
from extensions import db
from dotenv import load_dotenv

# Cargar variables de entorno desde archivo .env (solo en desarrollo)
load_dotenv()

app = Flask(__name__)

# Configuración de la clave secreta (usar variable de entorno en producción)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tu-clave-secreta-aqui-cambiar-en-produccion')

# Configuración de la base de datos (SQLite para producción)
# Usar SQLite siempre, tanto en desarrollo como en producción
database_path_env = os.environ.get('DATABASE_PATH')
if database_path_env:
    # Si se proporciona una ruta en la variable de entorno, usarla
    database_path = database_path_env
else:
    # Usar ruta relativa al directorio de la aplicación
    base_dir = os.path.abspath(os.path.dirname(__file__))
    instance_dir = os.path.join(base_dir, 'instance')
    database_path = os.path.join(instance_dir, 'pedidos.db')

# Asegurarse de que el directorio existe y tiene permisos de escritura
database_dir = os.path.dirname(database_path)
if database_dir:
    os.makedirs(database_dir, exist_ok=True)
    # Verificar permisos de escritura
    if not os.access(database_dir, os.W_OK):
        print(f"⚠ Advertencia: El directorio {database_dir} no tiene permisos de escritura")

# Usar ruta absoluta para SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.abspath(database_path)}'
print(f"✓ Base de datos configurada en: {os.path.abspath(database_path)}")

# Función para configurar SQLite con PRAGMA cuando se crea la conexión
def set_sqlite_pragma(dbapi_conn, connection_record):
    """Configurar SQLite con parámetros optimizados para producción"""
    cursor = dbapi_conn.cursor()
    try:
        # Habilitar WAL mode para mejor concurrencia (permite lecturas simultáneas)
        cursor.execute("PRAGMA journal_mode=WAL")
        # Habilitar foreign keys
        cursor.execute("PRAGMA foreign_keys=ON")
        # Configurar timeout de escritura (30 segundos)
        cursor.execute("PRAGMA busy_timeout=30000")
        # Optimizar para mejor rendimiento (balance entre seguridad y velocidad)
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=10000")  # Cache de ~10MB
        cursor.execute("PRAGMA temp_store=MEMORY")  # Almacenar temporales en memoria
    except Exception as e:
        print(f"⚠ Advertencia al configurar SQLite: {e}")
    finally:
        cursor.close()

# Configuración de SQLite para producción
# Habilitar WAL mode para mejor concurrencia y rendimiento
# Configurar timeouts más largos para evitar errores de bloqueo
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {
        'timeout': 30,  # Timeout de 30 segundos para operaciones
        'check_same_thread': False  # Permitir uso desde múltiples threads
    },
    'pool_pre_ping': True,  # Verificar conexiones antes de usarlas
    'pool_recycle': 3600,  # Reciclar conexiones cada hora
}

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Crear carpeta de uploads si no existe
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Inicializar db con la aplicación
db.init_app(app)

# Registrar el evento de conexión para SQLite (después de crear db)
# Esto se ejecutará cuando se cree cualquier conexión a la base de datos
def configure_sqlite():
    """Configurar SQLite con eventos de conexión"""
    try:
        with app.app_context():
            # Registrar el evento de conexión para SQLite
            @event.listens_for(db.engine, "connect")
            def receive_connect(dbapi_conn, connection_record):
                set_sqlite_pragma(dbapi_conn, connection_record)
    except Exception as e:
        print(f"⚠ Advertencia al configurar eventos SQLite: {e}")

# Importar modelos (se crean automáticamente al importar models.py)
from models import Comercial, Cliente, Prenda, Pedido, LineaPedido, Presupuesto, LineaPresupuesto, Ticket, LineaTicket, Factura, LineaFactura

# Importar y registrar blueprints
from routes.index import index_bp
from routes.pedidos import pedidos_bp
from routes.presupuestos import presupuestos_bp
from routes.clientes import clientes_bp
from routes.comerciales import comerciales_bp
from routes.prendas import prendas_bp
from routes.facturacion import facturacion_bp
from routes.tickets import tickets_bp

# Registrar blueprints
app.register_blueprint(index_bp)
app.register_blueprint(pedidos_bp)
app.register_blueprint(presupuestos_bp)
app.register_blueprint(clientes_bp)
app.register_blueprint(comerciales_bp)
app.register_blueprint(prendas_bp)
app.register_blueprint(facturacion_bp)
app.register_blueprint(tickets_bp)

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
            tablas_requeridas = ['comerciales', 'clientes', 'prendas', 'pedidos', 'lineas_pedido', 'presupuestos', 'lineas_presupuesto', 'tickets', 'lineas_ticket', 'facturas', 'lineas_factura']
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
            # Configurar SQLite con eventos de conexión
            configure_sqlite()
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
