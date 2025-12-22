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

# Configuración de la base de datos SQLite
# Detectar si estamos en producción (Render)
# Render establece la variable RENDER=true automáticamente
is_production = os.environ.get('RENDER', '').lower() == 'true'

if is_production:
    # En producción (Render), usar /data/pedidos.db (disco persistente)
    # IMPORTANTE: Configurar un volumen persistente en Render montado en /data
    database_path = os.environ.get('DATABASE_PATH', '/data/pedidos.db')
    print(f"[PRODUCCION] Usando base de datos en: {database_path}")
else:
    # En local, usar instance/pedidos.db
    database_path = os.environ.get('DATABASE_PATH', 'instance/pedidos.db')
    print(f"[LOCAL] Usando base de datos en: {database_path}")

# Convertir a ruta absoluta y asegurar que el directorio existe
if not os.path.isabs(database_path):
    # Si es ruta relativa, hacerla absoluta desde el directorio del proyecto
    database_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), database_path)

# Normalizar la ruta (convierte barras y maneja rutas de Windows)
database_path = os.path.normpath(database_path)

# Asegurar que el directorio padre existe
db_dir = os.path.dirname(database_path)
if db_dir:  # Solo crear directorio si hay un directorio padre
    try:
        # En producción, si el directorio es /data (disco persistente), ya existe y no necesita crearse
        # Solo crear el directorio si no existe
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        # Verificar que el directorio es escribible
        if not os.access(db_dir, os.W_OK):
            raise PermissionError(f"No se tienen permisos de escritura en el directorio: {db_dir}")
    except PermissionError:
        # Re-lanzar PermissionError tal cual
        raise
    except Exception as e:
        raise RuntimeError(f"Error al crear el directorio de la base de datos '{db_dir}': {e}")

# Configurar URI de SQLite
# SQLite requiere rutas absolutas con 3 barras (sqlite:///)
# Para Windows, convertir barras a formato SQLite (usar / en lugar de \)
sqlite_path = database_path.replace('\\', '/')
# En Windows, si la ruta empieza con letra de unidad (C:, D:, etc.), mantenerla
# SQLAlchemy maneja correctamente las rutas absolutas con 3 barras
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{sqlite_path}'

# Configuración de SQLite
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {'check_same_thread': False},  # Permitir conexiones desde múltiples threads
}

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Configuración de email (usando variables de entorno existentes: EMAIL_HOST, EMAIL_USER, EMAIL_PASS)
app.config['MAIL_SERVER'] = os.environ.get('EMAIL_HOST', os.environ.get('MAIL_SERVER', 'smtp.ionos.es'))
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', 'False').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('EMAIL_USER', os.environ.get('MAIL_USERNAME', ''))
app.config['MAIL_PASSWORD'] = os.environ.get('EMAIL_PASS', os.environ.get('MAIL_PASSWORD', ''))
# Configurar remitente por defecto: usar MAIL_DEFAULT_SENDER si existe, sino EMAIL_USER, sino un valor por defecto
mail_default_sender = os.environ.get('MAIL_DEFAULT_SENDER', '')
if not mail_default_sender:
    mail_default_sender = os.environ.get('EMAIL_USER', os.environ.get('MAIL_USERNAME', ''))
if not mail_default_sender:
    mail_default_sender = 'noreply@tovar.com'  # Valor por defecto si no hay configuración
app.config['MAIL_DEFAULT_SENDER'] = mail_default_sender

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
from models import Comercial, Cliente, Prenda, Presupuesto, LineaPresupuesto, Ticket, LineaTicket, Factura, LineaFactura, Usuario, PlantillaEmail, Proveedor, FacturaProveedor, Empleado, Nomina, RegistroCambioEstado, Configuracion

# Importar y registrar blueprints
from routes.index import index_bp
from routes.auth import auth_bp
from routes.solicitudes import solicitudes_bp
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
app.register_blueprint(solicitudes_bp)
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
            # Habilitar foreign keys en SQLite
            with db.engine.connect() as conn:
                conn.execute(text('PRAGMA foreign_keys = ON'))
                conn.commit()
            
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
                
                # Verificar y agregar columnas de fechas por estado
                nuevas_fechas_estado = {
                    'fecha_pendiente': 'DATE',
                    'fecha_diseno': 'DATE',
                    'fecha_todo_listo': 'DATE',
                    'fecha_enviado': 'DATE'
                }
                for columna, tipo in nuevas_fechas_estado.items():
                    if columna not in columns:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE pedidos ADD COLUMN {columna} {tipo}'))
                                conn.commit()
                                print(f"Migración: Columna {columna} agregada exitosamente a pedidos")
                        except Exception as e:
                            print(f"Error al agregar columna {columna} a pedidos: {e}")
                            pass
                
                # Verificar y agregar columna presupuesto_id
                if 'presupuesto_id' not in columns:
                    try:
                        with db.engine.connect() as conn:
                            # SQLite no soporta ADD CONSTRAINT en ALTER TABLE, se maneja en el modelo
                            conn.execute(text('ALTER TABLE pedidos ADD COLUMN presupuesto_id INTEGER'))
                            conn.commit()
                            print("Migración: Columna presupuesto_id agregada exitosamente a pedidos")
                    except Exception as e:
                        print(f"Error al agregar columna presupuesto_id a pedidos: {e}")
                        pass
                
                # Verificar y agregar columnas de imágenes para el PDF
                nuevas_columnas_imagenes = {
                    'imagen_portada': 'VARCHAR(255)',
                    'imagen_adicional_1': 'VARCHAR(255)',
                    'imagen_adicional_2': 'VARCHAR(255)',
                    'imagen_adicional_3': 'VARCHAR(255)',
                    'imagen_adicional_4': 'VARCHAR(255)',
                    'imagen_adicional_5': 'VARCHAR(255)'
                }
                for columna, tipo in nuevas_columnas_imagenes.items():
                    if columna not in columns:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE pedidos ADD COLUMN {columna} {tipo}'))
                                conn.commit()
                                print(f"Migración: Columna {columna} agregada exitosamente a pedidos")
                        except Exception as e:
                            print(f"Error al agregar columna {columna} a pedidos: {e}")
                            pass
                
                # Verificar y agregar columnas de descripciones de imágenes
                columnas_descripciones = {
                    'descripcion_imagen_1': 'TEXT',
                    'descripcion_imagen_2': 'TEXT',
                    'descripcion_imagen_3': 'TEXT',
                    'descripcion_imagen_4': 'TEXT',
                    'descripcion_imagen_5': 'TEXT'
                }
                for columna, tipo in columnas_descripciones.items():
                    if columna not in columns:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE pedidos ADD COLUMN {columna} {tipo}'))
                                conn.commit()
                                print(f"Migración: Columna {columna} agregada exitosamente a pedidos")
                        except Exception as e:
                            print(f"Error al agregar columna {columna} a pedidos: {e}")
                
                # Verificar y agregar columna seguimiento
                if 'seguimiento' not in columns:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text('ALTER TABLE pedidos ADD COLUMN seguimiento TEXT'))
                            conn.commit()
                            print("Migración: Columna seguimiento agregada exitosamente a pedidos")
                    except Exception as e:
                        print(f"Error al agregar columna seguimiento a pedidos: {e}")
                        pass
            else:
                # Si no existe la tabla, crearla
                db.create_all()
            
            # Verificar si existe la tabla lineas_pedido y agregar columnas si no existen
            if 'lineas_pedido' in table_names:
                columns_lineas = [col['name'] for col in inspector.get_columns('lineas_pedido')]
                
                if 'estado' not in columns_lineas:
                    # Agregar la columna estado usando SQL directo
                    with db.engine.connect() as conn:
                        conn.execute(text("ALTER TABLE lineas_pedido ADD COLUMN estado VARCHAR(50) DEFAULT 'pendiente'"))
                        conn.commit()
                # Añadir columnas de descuento y precio_final
                if 'descuento' not in columns_lineas:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text("ALTER TABLE lineas_pedido ADD COLUMN descuento NUMERIC(5, 2) DEFAULT 0"))
                            conn.commit()
                            print("Migración: Columna descuento agregada exitosamente a lineas_pedido")
                    except Exception as e:
                        print(f"Error al agregar columna descuento a lineas_pedido: {e}")
                if 'precio_final' not in columns_lineas:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text("ALTER TABLE lineas_pedido ADD COLUMN precio_final NUMERIC(10, 2)"))
                            conn.commit()
                            print("Migración: Columna precio_final agregada exitosamente a lineas_pedido")
                    except Exception as e:
                        print(f"Error al agregar columna precio_final a lineas_pedido: {e}")
            
            # Verificar si existe la tabla lineas_presupuesto y agregar columnas si no existen
            if 'lineas_presupuesto' in table_names:
                columns_lineas_presupuesto = [col['name'] for col in inspector.get_columns('lineas_presupuesto')]
                
                if 'estado' not in columns_lineas_presupuesto:
                    # Agregar la columna estado usando SQL directo
                    with db.engine.connect() as conn:
                        conn.execute(text("ALTER TABLE lineas_presupuesto ADD COLUMN estado VARCHAR(50) DEFAULT 'pendiente'"))
                        conn.commit()
                        print("Migración: Columna estado agregada exitosamente a lineas_presupuesto")
                # Añadir columnas de descuento y precio_final
                if 'descuento' not in columns_lineas_presupuesto:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text("ALTER TABLE lineas_presupuesto ADD COLUMN descuento NUMERIC(5, 2) DEFAULT 0"))
                            conn.commit()
                            print("Migración: Columna descuento agregada exitosamente a lineas_presupuesto")
                    except Exception as e:
                        print(f"Error al agregar columna descuento a lineas_presupuesto: {e}")
                if 'precio_final' not in columns_lineas_presupuesto:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text("ALTER TABLE lineas_presupuesto ADD COLUMN precio_final NUMERIC(10, 2)"))
                            conn.commit()
                            print("Migración: Columna precio_final agregada exitosamente a lineas_presupuesto")
                    except Exception as e:
                        print(f"Error al agregar columna precio_final a lineas_presupuesto: {e}")
            
            # Verificar si existe la tabla facturas y hacer pedido_id nullable si no lo es
            if 'facturas' in table_names:
                columns_facturas = [col['name'] for col in inspector.get_columns('facturas')]
                # Verificar si pedido_id existe y es NOT NULL
                pedido_id_not_null = False
                for col_info in inspector.get_columns('facturas'):
                    if col_info['name'] == 'pedido_id' and col_info.get('nullable') == False:
                        pedido_id_not_null = True
                        break
                
                # Si pedido_id es NOT NULL, necesitamos recrear la tabla para hacerla nullable
                if pedido_id_not_null:
                    try:
                        with db.engine.connect() as conn:
                            # Desactivar temporalmente las foreign keys para poder recrear la tabla
                            conn.execute(text('PRAGMA foreign_keys = OFF'))
                            
                            # Crear tabla temporal con la estructura correcta
                            conn.execute(text('''
                                CREATE TABLE facturas_temp (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    pedido_id INTEGER,
                                    presupuesto_id INTEGER,
                                    serie VARCHAR(10) NOT NULL DEFAULT 'A',
                                    numero VARCHAR(50) NOT NULL,
                                    fecha_expedicion DATE NOT NULL,
                                    tipo_factura VARCHAR(10) NOT NULL DEFAULT 'F1',
                                    descripcion TEXT,
                                    nif VARCHAR(20),
                                    nombre VARCHAR(200) NOT NULL,
                                    importe_total NUMERIC(10, 2) NOT NULL,
                                    estado VARCHAR(50) NOT NULL DEFAULT 'pendiente',
                                    huella_verifactu TEXT,
                                    fecha_creacion TIMESTAMP,
                                    fecha_confirmacion TIMESTAMP
                                )
                            '''))
                            
                            # Copiar datos de la tabla antigua a la nueva
                            # Verificar si presupuesto_id existe en la tabla original
                            if 'presupuesto_id' in columns_facturas:
                                conn.execute(text('''
                                    INSERT INTO facturas_temp 
                                    SELECT id, pedido_id, presupuesto_id, serie, numero, fecha_expedicion, 
                                           tipo_factura, descripcion, nif, nombre, importe_total, estado, 
                                           huella_verifactu, fecha_creacion, fecha_confirmacion
                                    FROM facturas
                                '''))
                            else:
                                conn.execute(text('''
                                    INSERT INTO facturas_temp 
                                    SELECT id, pedido_id, NULL, serie, numero, fecha_expedicion, 
                                           tipo_factura, descripcion, nif, nombre, importe_total, estado, 
                                           huella_verifactu, fecha_creacion, fecha_confirmacion
                                    FROM facturas
                                '''))
                            
                            # Eliminar tabla antigua
                            conn.execute(text('DROP TABLE facturas'))
                            
                            # Renombrar tabla temporal
                            conn.execute(text('ALTER TABLE facturas_temp RENAME TO facturas'))
                            
                            # Reactivar foreign keys
                            conn.execute(text('PRAGMA foreign_keys = ON'))
                            
                            conn.commit()
                            print("Migración: Columna pedido_id en facturas ahora es nullable")
                    except Exception as e:
                        print(f"Error al migrar pedido_id a nullable en facturas: {e}")
                        import traceback
                        traceback.print_exc()
                        # Intentar reactivar foreign keys en caso de error
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text('PRAGMA foreign_keys = ON'))
                                conn.commit()
                        except:
                            pass
                
                # Añadir columna presupuesto_id si no existe
                if 'presupuesto_id' not in columns_facturas:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text('ALTER TABLE facturas ADD COLUMN presupuesto_id INTEGER'))
                            conn.commit()
                            print("Migración: Columna presupuesto_id agregada exitosamente a facturas")
                    except Exception as e:
                        print(f"Error al agregar columna presupuesto_id a facturas: {e}")
            
            # Verificar si existe la tabla presupuestos, si no existe crearla
            if 'presupuestos' not in table_names:
                db.create_all()
            else:
                # Verificar si existe la columna seguimiento
                columns_presupuesto = [col['name'] for col in inspector.get_columns('presupuestos')]
                
                # Migrar estados antiguos a nuevos estados unificados
                try:
                    with db.engine.connect() as conn:
                        # Mapeo de estados antiguos a nuevos
                        estados_migracion = {
                            'Pendiente de enviar': 'presupuesto',
                            'Diseño': 'diseño',
                            'Enviado': 'presupuesto',  # Si estaba enviado, volver a presupuesto
                            'Aceptado': 'aceptado',
                            'Rechazado': 'pedido rechazado'
                        }
                        for estado_antiguo, estado_nuevo in estados_migracion.items():
                            conn.execute(text("UPDATE presupuestos SET estado = :estado_nuevo WHERE estado = :estado_antiguo"), 
                                       {'estado_nuevo': estado_nuevo, 'estado_antiguo': estado_antiguo})
                        conn.commit()
                        print("Migración: Estados de presupuestos actualizados a estados unificados")
                except Exception as e:
                    print(f"Error al migrar estados de presupuestos: {e}")
                
                # Añadir nuevas columnas de fechas si no existen
                nuevas_fechas = {
                    'fecha_presupuesto': 'DATE',
                    'fecha_aceptado': 'DATE',
                    'fecha_diseno_finalizado': 'DATE',
                    'fecha_en_preparacion': 'DATE',
                    'fecha_todo_listo': 'DATE',
                    'fecha_enviado': 'DATE',
                    'fecha_entregado_cliente': 'DATE',
                    'fecha_rechazado': 'DATE',
                    'fecha_aceptacion': 'DATE',
                    'fecha_objetivo': 'DATE',
                    'fecha_entrega_trabajo': 'DATE',
                    'fecha_envio_taller': 'DATE',
                    'fecha_entrega_bordados': 'DATE',
                    'fecha_entrega_cliente': 'DATE'
                }
                for columna, tipo in nuevas_fechas.items():
                    if columna not in columns_presupuesto:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE presupuestos ADD COLUMN {columna} {tipo}'))
                                conn.commit()
                                print(f"Migración: Columna {columna} agregada exitosamente a presupuestos")
                        except Exception as e:
                            print(f"Error al agregar columna {columna} a presupuestos: {e}")
                
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
                    'imagen_adicional_5': 'VARCHAR(255)'
                }
                for columna, tipo in nuevas_columnas_imagenes.items():
                    if columna not in columns_presupuesto:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE presupuestos ADD COLUMN {columna} {tipo}'))
                                conn.commit()
                                print(f"Migración: Columna {columna} agregada exitosamente")
                        except Exception as e:
                            print(f"Error al agregar columna {columna}: {e}")
                            pass
                
                # Verificar y agregar columnas de descripciones de imágenes
                columnas_descripciones = {
                    'descripcion_imagen_1': 'TEXT',
                    'descripcion_imagen_2': 'TEXT',
                    'descripcion_imagen_3': 'TEXT',
                    'descripcion_imagen_4': 'TEXT',
                    'descripcion_imagen_5': 'TEXT'
                }
                for columna, tipo in columnas_descripciones.items():
                    if columna not in columns_presupuesto:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE presupuestos ADD COLUMN {columna} {tipo}'))
                                conn.commit()
                                print(f"Migración: Columna {columna} agregada exitosamente")
                        except Exception as e:
                            print(f"Error al agregar columna {columna}: {e}")
                            pass
                
                # Verificar y agregar columnas de fechas de estados
                nuevas_fechas = {
                    'fecha_pendiente_enviar': 'DATE',
                    'fecha_diseno': 'DATE'
                }
                for columna, tipo in nuevas_fechas.items():
                    if columna not in columns_presupuesto:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE presupuestos ADD COLUMN {columna} {tipo}'))
                                conn.commit()
                                print(f"Migración: Columna {columna} agregada exitosamente")
                        except Exception as e:
                            print(f"Error al agregar columna {columna}: {e}")
                            pass
                
                # Eliminar columna de imagen 6 si existe (ya no se usa, pero mantenemos imagen_adicional_5)
                # Nota: SQLite no soporta DROP COLUMN directamente, se omite esta migración
                # La columna se puede ignorar si existe
                            pass
            
            # Verificar que todas las tablas necesarias existan
            tablas_requeridas = ['comerciales', 'clientes', 'prendas', 'pedidos', 'lineas_pedido', 'presupuestos', 'lineas_presupuesto', 'tickets', 'lineas_ticket', 'facturas', 'lineas_factura', 'usuarios', 'plantillas_email', 'proveedores', 'facturas_proveedor', 'empleados', 'nominas', 'registro_cambio_estado']
            tablas_faltantes = [t for t in tablas_requeridas if t not in table_names]
            if tablas_faltantes:
                db.create_all()
            
            # Verificar si existe la tabla proveedores y agregar columnas faltantes
            if 'proveedores' in table_names:
                columns_proveedor = [col['name'] for col in inspector.get_columns('proveedores')]
                
                # Agregar columna activo si no existe
                if 'activo' not in columns_proveedor:
                    try:
                        with db.engine.connect() as conn:
                            # SQLite usa INTEGER para booleanos (0/1), pero SQLAlchemy lo maneja
                            conn.execute(text('ALTER TABLE proveedores ADD COLUMN activo INTEGER DEFAULT 1'))
                            conn.commit()
                            print("Migración: Columna activo agregada exitosamente a proveedores")
                    except Exception as e:
                        print(f"Error al agregar columna activo a proveedores: {e}")
                        pass
                
                # Agregar columna movil si no existe
                if 'movil' not in columns_proveedor:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text('ALTER TABLE proveedores ADD COLUMN movil VARCHAR(50)'))
                            conn.commit()
                            print("Migración: Columna movil agregada exitosamente a proveedores")
                    except Exception as e:
                        print(f"Error al agregar columna movil a proveedores: {e}")
                        pass
                
                # Agregar columna persona_contacto si no existe
                if 'persona_contacto' not in columns_proveedor:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text('ALTER TABLE proveedores ADD COLUMN persona_contacto VARCHAR(200)'))
                            conn.commit()
                            print("Migración: Columna persona_contacto agregada exitosamente a proveedores")
                    except Exception as e:
                        print(f"Error al agregar columna persona_contacto a proveedores: {e}")
                        pass
            
            # Verificar y crear tabla plantillas_email si no existe
            if 'plantillas_email' not in table_names:
                db.create_all()
            else:
                # Asegurar columna enviar_activo en plantillas_email
                columns_plantillas = [col['name'] for col in inspector.get_columns('plantillas_email')]
                if 'enviar_activo' not in columns_plantillas:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text("ALTER TABLE plantillas_email ADD COLUMN enviar_activo BOOLEAN DEFAULT TRUE"))
                            conn.commit()
                            print("Migración: Columna enviar_activo agregada exitosamente a plantillas_email")
                    except Exception as e:
                        print(f"Error al agregar columna enviar_activo a plantillas_email: {e}")
            
            # Inicializar plantillas por defecto si no existen
            from models import PlantillaEmail
            # Plantillas por defecto (se crean solo si no existen)
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
                # Plantillas específicas por estado de pedido
                {
                    'tipo': 'cambio_estado_pedido_pendiente',
                    'asunto': 'Pedido #{pedido_id} recibido - Estado: Pendiente',
                    'cuerpo': '''Estimado/a {cliente_nombre},

Hemos recibido su pedido #{pedido_id} y se encuentra en estado PENDIENTE.

En breve empezaremos a trabajar en él. Le iremos informando de los siguientes pasos.

Detalles del pedido:
- Tipo: {tipo_pedido}
- Fecha de actualización: {fecha_actualizacion}

Saludos cordiales,
{empresa_nombre}'''
                },
                {
                    'tipo': 'cambio_estado_pedido_diseno',
                    'asunto': 'Pedido #{pedido_id} en fase de diseño',
                    'cuerpo': '''Estimado/a {cliente_nombre},

Su pedido #{pedido_id} ha pasado al estado DISEÑO.

Nuestro equipo está trabajando en las propuestas de diseño. En cuanto estén listas se las enviaremos para su revisión.

Detalles del pedido:
- Tipo: {tipo_pedido}
- Fecha de actualización: {fecha_actualizacion}

Saludos cordiales,
{empresa_nombre}'''
                },
                {
                    'tipo': 'cambio_estado_pedido_en_preparacion',
                    'asunto': 'Pedido #{pedido_id} en preparación',
                    'cuerpo': '''Estimado/a {cliente_nombre},

Su pedido #{pedido_id} ha pasado al estado EN PREPARACIÓN.

Estamos preparando la producción de su pedido.

Detalles del pedido:
- Tipo: {tipo_pedido}
- Fecha de aceptación: {fecha_aceptacion}
- Fecha objetivo de entrega: {fecha_objetivo}

Saludos cordiales,
{empresa_nombre}'''
                },
                {
                    'tipo': 'cambio_estado_pedido_todo_listo',
                    'asunto': 'Pedido #{pedido_id} listo',
                    'cuerpo': '''Estimado/a {cliente_nombre},

Su pedido #{pedido_id} se encuentra en estado TODO LISTO.

Estamos ultimando los detalles para su envío o recogida.

Detalles del pedido:
- Tipo: {tipo_pedido}
- Fecha objetivo de entrega: {fecha_objetivo}

Saludos cordiales,
{empresa_nombre}'''
                },
                {
                    'tipo': 'cambio_estado_pedido_enviado',
                    'asunto': 'Pedido #{pedido_id} enviado',
                    'cuerpo': '''Estimado/a {cliente_nombre},

Su pedido #{pedido_id} ha sido ENVIADO.

En breve lo recibirá en la dirección acordada.

Detalles del pedido:
- Tipo: {tipo_pedido}
- Fecha objetivo de entrega: {fecha_objetivo}

Saludos cordiales,
{empresa_nombre}'''
                },
                {
                    'tipo': 'cambio_estado_pedido_entregado_al_cliente',
                    'asunto': 'Pedido #{pedido_id} entregado',
                    'cuerpo': '''Estimado/a {cliente_nombre},

Su pedido #{pedido_id} ha sido ENTREGADO.

Esperamos que quede satisfecho con el trabajo realizado.

Detalles del pedido:
- Tipo: {tipo_pedido}
- Fecha de entrega: {fecha_actualizacion}

Muchas gracias por confiar en nosotros.

Saludos cordiales,
{empresa_nombre}'''
                },
            ]
            
            for plantilla_data in plantillas_por_defecto:
                plantilla_existente = PlantillaEmail.query.filter_by(tipo=plantilla_data['tipo']).first()
                if not plantilla_existente:
                    nueva_plantilla = PlantillaEmail(
                        tipo=plantilla_data['tipo'],
                        asunto=plantilla_data['asunto'],
                        cuerpo=plantilla_data['cuerpo'],
                        enviar_activo=True
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
                    'fecha_alta': 'DATE',
                    'ultimo_acceso': 'TIMESTAMP',
                    'movil': 'VARCHAR(50)',
                    'comercial_id': 'INTEGER REFERENCES comerciales(id)'
                }
                for columna, tipo in nuevas_columnas.items():
                    if columna not in columns_clientes:
                        try:
                            with db.engine.connect() as conn:
                                # SQLite no soporta UNIQUE en ALTER TABLE ADD COLUMN, se maneja en el modelo
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
                
                # Agregar usuario_id si no existe
                if 'usuario_id' not in columns_comerciales:
                    try:
                        with db.engine.connect() as conn:
                            # Agregar columna usuario_id
                            conn.execute(text('ALTER TABLE comerciales ADD COLUMN usuario_id INTEGER'))
                            conn.commit()
                    except Exception:
                        pass
                
                # Si existe la columna nombre y hay registros con nombre NULL pero usuario_id válido,
                # actualizar el nombre desde el usuario
                if 'nombre' in columns_comerciales and 'usuario_id' in columns_comerciales:
                    try:
                        with db.engine.connect() as conn:
                            # Actualizar registros que tienen usuario_id pero nombre es NULL
                            conn.execute(text("""
                                UPDATE comerciales 
                                SET nombre = (SELECT usuario FROM usuarios WHERE usuarios.id = comerciales.usuario_id)
                                WHERE nombre IS NULL AND usuario_id IS NOT NULL
                            """))
                            conn.commit()
                    except Exception:
                        pass
            
            # Verificar y agregar columnas nuevas en tickets
            if 'tickets' in table_names:
                columns_tickets = [col['name'] for col in inspector.get_columns('tickets')]
                nuevas_columnas_tickets = {
                    'forma_pago': 'VARCHAR(100)',
                    'tipo_calculo_iva': 'VARCHAR(20) DEFAULT \'desglosar\'',
                    'email': 'VARCHAR(100)',
                    'categoria': 'VARCHAR(50)'
                }
                for columna, tipo in nuevas_columnas_tickets.items():
                    if columna not in columns_tickets:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE tickets ADD COLUMN {columna} {tipo}'))
                                conn.commit()
                                print(f"Migración: Columna {columna} agregada exitosamente a tickets")
                        except Exception as e:
                            print(f"Error al agregar columna {columna} a tickets: {e}")
                            pass
            
            # Verificar y agregar columna categoria en clientes
            if 'clientes' in table_names:
                columns_clientes = [col['name'] for col in inspector.get_columns('clientes')]
                if 'categoria' not in columns_clientes:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text('ALTER TABLE clientes ADD COLUMN categoria VARCHAR(50)'))
                            conn.commit()
                            print("Migración: Columna categoria agregada exitosamente a clientes")
                    except Exception as e:
                        print(f"Error al agregar columna categoria a clientes: {e}")
                        pass
            
            # Verificar y crear tabla clientes_tienda si no existe
            if 'clientes_tienda' not in table_names:
                try:
                    db.create_all()
                    print("Migración: Tabla clientes_tienda creada exitosamente")
                except Exception as e:
                    print(f"Error al crear tabla clientes_tienda: {e}")
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
                                
                                # SQLite no soporta ADD CONSTRAINT en ALTER TABLE, se maneja en el modelo
                                # Eliminar columna empleado antigua
                                # Nota: SQLite no soporta DROP COLUMN directamente, se omite esta migración
                                # La columna se puede ignorar si existe
                                pass
                            else:
                                # Si no existe empleado, solo agregar la columna empleado_id
                                conn.execute(text('ALTER TABLE nominas ADD COLUMN empleado_id INTEGER'))
                                # SQLite no soporta ADD CONSTRAINT en ALTER TABLE, se maneja en el modelo
                                conn.commit()
                        print("Migración de nominas completada exitosamente")
                    except Exception as e:
                        print(f"Error en migración de nominas: {e}")
                        import traceback
                        traceback.print_exc()
                        # Intentar crear todas las tablas como fallback
            
            # Verificar si existe la tabla lineas_factura y agregar columnas de descuento si no existen
            if 'lineas_factura' in table_names:
                columns_lineas_factura = [col['name'] for col in inspector.get_columns('lineas_factura')]
                
                if 'descuento' not in columns_lineas_factura:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text('ALTER TABLE lineas_factura ADD COLUMN descuento NUMERIC(5, 2) DEFAULT 0'))
                            conn.commit()
                            print("Migración: Columna descuento agregada exitosamente a lineas_factura")
                    except Exception as e:
                        print(f"Error al agregar columna descuento a lineas_factura: {e}")
                
                if 'precio_final' not in columns_lineas_factura:
                    try:
                        with db.engine.connect() as conn:
                            conn.execute(text('ALTER TABLE lineas_factura ADD COLUMN precio_final NUMERIC(10, 2)'))
                            conn.commit()
                            print("Migración: Columna precio_final agregada exitosamente a lineas_factura")
                    except Exception as e:
                        print(f"Error al agregar columna precio_final a lineas_factura: {e}")
            
            # Verificar si existe la tabla configuracion
            if 'configuracion' not in table_names:
                try:
                    db.create_all()
                    print("Migración: Tabla configuracion creada exitosamente")
                except Exception as e:
                    print(f"Error al crear tabla configuracion: {e}")
                    pass
            else:
                # Verificar que existe la configuración de verifactu activado
                from models import Configuracion
                verifactu_config = Configuracion.query.filter_by(clave='verifactu_enviar_activo').first()
                if not verifactu_config:
                    # Crear configuración por defecto (activado)
                    verifactu_config = Configuracion(
                        clave='verifactu_enviar_activo',
                        valor='true',
                        descripcion='Activar/desactivar el envío automático de facturas y tickets a Verifactu'
                    )
                    db.session.add(verifactu_config)
                    db.session.commit()
                    print("Migración: Configuración verifactu_enviar_activo creada con valor por defecto 'true'")
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

# Función para verificar e instalar Playwright si es necesario
def ensure_playwright_installed():
    """Verificar e instalar Playwright chromium si no está instalado"""
    try:
        from playwright.sync_api import sync_playwright
        # Intentar lanzar chromium para verificar si está instalado
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                browser.close()
                print("[Playwright] Chromium ya está instalado y funcionando")
                return True
            except Exception as e:
                # Si falla, intentar instalar
                print(f"[Playwright] Chromium no está instalado. Error: {str(e)}")
                print("[Playwright] Intentando instalar Chromium...")
                import subprocess
                import sys
                try:
                    result = subprocess.run(
                        [sys.executable, '-m', 'playwright', 'install', 'chromium'],
                        capture_output=True,
                        text=True,
                        timeout=300  # 5 minutos de timeout
                    )
                    if result.returncode == 0:
                        print("[Playwright] Chromium instalado exitosamente")
                        return True
                    else:
                        print(f"[Playwright] Error al instalar Chromium: {result.stderr}")
                        return False
                except subprocess.TimeoutExpired:
                    print("[Playwright] Timeout al instalar Chromium")
                    return False
                except Exception as install_error:
                    print(f"[Playwright] Error al ejecutar instalación: {str(install_error)}")
                    return False
    except ImportError:
        print("[Playwright] Playwright no está instalado. Asegúrate de que esté en requirements.txt")
        return False
    except Exception as e:
        print(f"[Playwright] Error al verificar Playwright: {e}")
        return False

# Función para inicializar la aplicación (se ejecuta después de que todas las rutas estén registradas)
def initialize_app():
    """Inicializar la aplicación y la base de datos"""
    try:
        # Verificar Playwright en producción
        if is_production:
            ensure_playwright_installed()
        
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
