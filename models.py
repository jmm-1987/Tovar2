from datetime import datetime
from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import hashlib

# Crear todos los modelos directamente
# Esto se ejecuta una sola vez cuando se importa el módulo

class Comercial(db.Model):
    """Comerciales que pueden crear pedidos (vinculados a usuarios)"""
    __tablename__ = 'comerciales'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, unique=True)
    # Columna _nombre almacenada en BD para compatibilidad con tablas antiguas que tienen NOT NULL
    # Se establece automáticamente al crear el comercial
    _nombre = db.Column('nombre', db.String(200), nullable=True)
    
    # Relación con usuario
    usuario = db.relationship('Usuario', backref='comercial', lazy=True)
    
    # Relación con pedidos
    pedidos = db.relationship('Pedido', backref='comercial', lazy=True)
    # Relación con presupuestos
    presupuestos = db.relationship('Presupuesto', backref='comercial', lazy=True)
    
    @property
    def nombre(self):
        """Propiedad que devuelve el nombre del usuario asociado"""
        if self.usuario:
            return self.usuario.usuario
        return self._nombre or ''
    
    def __repr__(self):
        return f'<Comercial {self.nombre}>'

class CategoriaCliente(db.Model):
    """Categorías de clientes configurables"""
    __tablename__ = 'categorias_cliente'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relación con clientes
    clientes = db.relationship('Cliente', backref='categoria_obj', lazy=True, foreign_keys='Cliente.categoria_id')
    
    def __repr__(self):
        return f'<CategoriaCliente {self.nombre}>'

class Cliente(db.Model, UserMixin):
    """Clientes del sistema con acceso web"""
    __tablename__ = 'clientes'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    alias = db.Column(db.String(200))  # Alias o nombre alternativo
    nif = db.Column(db.String(20))  # NIF/CIF del cliente
    direccion = db.Column(db.Text)
    poblacion = db.Column(db.String(100))  # Población
    provincia = db.Column(db.String(100))  # Provincia
    codigo_postal = db.Column(db.String(10))  # Código Postal
    pais = db.Column(db.String(100), default='España')  # País
    telefono = db.Column(db.String(50))  # Teléfono fijo
    movil = db.Column(db.String(50))  # Teléfono móvil
    email = db.Column(db.String(100))  # Email general (mantener para compatibilidad)
    email_general = db.Column(db.String(100))  # Email general
    email_comunicaciones = db.Column(db.String(100))  # Email para avisos de estados
    categoria = db.Column(db.String(50))  # Categoría antigua (mantener para compatibilidad)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias_cliente.id'), nullable=True)  # Nueva categoría desde tabla
    personas_contacto = db.Column(db.Text)  # Personas de contacto
    anotaciones = db.Column(db.Text)  # Anotaciones adicionales
    numero_cuenta = db.Column(db.String(29))  # Número de cuenta bancaria (24 dígitos con guiones: XXXX-XXXX-XXXX-XXXX-XXXX-XXXX)
    
    # Campos de autenticación web
    usuario_web = db.Column(db.String(80), unique=True, nullable=True)  # Usuario para acceso web
    password_hash = db.Column(db.String(255), nullable=True)  # Contraseña hash
    
    # Timestamps
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_alta = db.Column(db.Date)  # Fecha de alta del cliente
    ultimo_acceso = db.Column(db.DateTime)
    
    # Comercial asignado
    comercial_id = db.Column(db.Integer, db.ForeignKey('comerciales.id'), nullable=True)
    comercial = db.relationship('Comercial', backref='clientes_asignados', lazy=True)
    
    # Relación con pedidos
    pedidos = db.relationship('Pedido', backref='cliente', lazy=True)
    # Relación con presupuestos
    presupuestos = db.relationship('Presupuesto', backref='cliente', lazy=True)
    # Relación con direcciones de envío
    direcciones_envio = db.relationship('DireccionEnvio', backref='cliente', lazy=True, cascade='all, delete-orphan')
    # Relación con personas de contacto
    personas_contacto_list = db.relationship('PersonaContacto', backref='cliente', lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        """Establecer contraseña con hash"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verificar contraseña"""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def tiene_acceso_web(self):
        """Verificar si el cliente tiene acceso web configurado"""
        return self.usuario_web is not None and self.usuario_web != '' and self.password_hash is not None
    
    def get_id(self):
        """Obtener ID para Flask-Login (prefijo 'cliente_' para distinguir de usuarios)"""
        return f'cliente_{self.id}'
    
    def __repr__(self):
        return f'<Cliente {self.nombre}>'

class Prenda(db.Model):
    """Modelos base de prendas"""
    __tablename__ = 'prendas'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)  # pantalon, camisa, zapato, camiseta, etc.
    precio_coste = db.Column(db.Numeric(10, 2), nullable=False, default=0)  # Precio de coste
    precio_venta = db.Column(db.Numeric(10, 2), nullable=False, default=0)  # Precio de venta
    
    # Relación con líneas de pedido
    lineas_pedido = db.relationship('LineaPedido', backref='prenda', lazy=True)
    # Relación con líneas de presupuesto
    lineas_presupuesto = db.relationship('LineaPresupuesto', backref='prenda', lazy=True)
    
    def __repr__(self):
        return f'<Prenda {self.nombre} ({self.tipo})>'
    
class Pedido(db.Model):
    """Pedidos del sistema"""
    __tablename__ = 'pedidos'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relaciones
    comercial_id = db.Column(db.Integer, db.ForeignKey('comerciales.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    presupuesto_id = db.Column(db.Integer, db.ForeignKey('presupuestos.id'), nullable=True)  # Presupuesto del que proviene este pedido
    
    # Tipo de pedido
    tipo_pedido = db.Column(db.String(50), nullable=False)  # fabricacion, no fabricacion, cliente web
    
    # Estado del pedido
    estado = db.Column(db.String(50), nullable=False, default='Pendiente')  # Pendiente, Diseño, En preparación, Todo listo, Enviado, Entregado al cliente
    
    # Forma de pago
    forma_pago = db.Column(db.Text)
    
    # Campo de seguimiento para actualizaciones de comerciales
    seguimiento = db.Column(db.Text)
    
    # Imagen del diseño
    imagen_diseno = db.Column(db.String(255))
    
    # Imágenes para el PDF del pedido
    imagen_portada = db.Column(db.String(255))  # Imagen de portada (primera página)
    imagen_adicional_1 = db.Column(db.String(255))  # Imagen adicional 1 (segunda página)
    descripcion_imagen_1 = db.Column(db.Text)  # Descripción de imagen adicional 1
    imagen_adicional_2 = db.Column(db.String(255))  # Imagen adicional 2 (segunda página)
    descripcion_imagen_2 = db.Column(db.Text)  # Descripción de imagen adicional 2
    imagen_adicional_3 = db.Column(db.String(255))  # Imagen adicional 3 (segunda página)
    descripcion_imagen_3 = db.Column(db.Text)  # Descripción de imagen adicional 3
    imagen_adicional_4 = db.Column(db.String(255))  # Imagen adicional 4 (segunda página)
    descripcion_imagen_4 = db.Column(db.Text)  # Descripción de imagen adicional 4
    imagen_adicional_5 = db.Column(db.String(255))  # Imagen adicional 5 (segunda página)
    descripcion_imagen_5 = db.Column(db.Text)  # Descripción de imagen adicional 5
    
    # Fechas del proceso
    fecha_aceptacion = db.Column(db.Date)
    fecha_objetivo = db.Column(db.Date)  # Fecha objetivo de entrega (calculada automáticamente: 20 días desde aceptación)
    fecha_entrega_trabajo = db.Column(db.Date)
    fecha_envio_taller = db.Column(db.Date)
    fecha_entrega_bordados = db.Column(db.Date)
    fecha_entrega_cliente = db.Column(db.Date)
    
    # Fechas por estado (se guardan y no se sobrescriben)
    fecha_pendiente = db.Column(db.Date)  # Fecha cuando se marcó como Pendiente (usa fecha_creacion si no existe)
    fecha_diseno = db.Column(db.Date)  # Fecha cuando se marcó como Diseño
    fecha_todo_listo = db.Column(db.Date)  # Fecha cuando se marcó como Todo listo
    fecha_enviado = db.Column(db.Date)  # Fecha cuando se marcó como Enviado
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relación con líneas de pedido
    lineas = db.relationship('LineaPedido', backref='pedido', lazy=True, cascade='all, delete-orphan')
    
    # Relación con presupuesto
    presupuesto = db.relationship('Presupuesto', backref='pedidos', lazy=True)
    
    def __repr__(self):
        return f'<Pedido {self.id} - {self.cliente.nombre if self.cliente else "Sin cliente"}>'

class LineaPedido(db.Model):
    """Líneas de prendas dentro de un pedido"""
    __tablename__ = 'lineas_pedido'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relaciones
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedidos.id'), nullable=False)
    prenda_id = db.Column(db.Integer, db.ForeignKey('prendas.id'), nullable=False)
    
    # Campos específicos de la línea
    nombre = db.Column(db.String(200), nullable=False)  # Mantenido para compatibilidad, no se usa en la UI
    cargo = db.Column(db.String(100))  # Mantenido para compatibilidad, no se usa en la UI
    nombre_mostrar = db.Column(db.String(200), nullable=True)  # Nombre para mostrar al cliente
    cantidad = db.Column(db.Integer, nullable=False, default=1)
    color = db.Column(db.String(50))
    forma = db.Column(db.String(100))
    tipo_manda = db.Column(db.String(100))
    sexo = db.Column(db.String(20))  # Masculino, Femenino, Unisex
    talla = db.Column(db.String(20))
    tejido = db.Column(db.String(100))
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=True)  # Precio unitario de la línea (copiado del presupuesto)
    descuento = db.Column(db.Numeric(5, 2), nullable=False, default=0)  # Porcentaje de descuento (0-100)
    precio_final = db.Column(db.Numeric(10, 2), nullable=True)  # Precio unitario con descuento aplicado
    
    # Estado de la línea
    estado = db.Column(db.String(50), nullable=False, default='pendiente')  # pendiente, en confección, en bordado, listo
    
    def __repr__(self):
        return f'<LineaPedido {self.id} - {self.nombre} x{self.cantidad}>'
    
class Presupuesto(db.Model):
    """Presupuestos del sistema (pedidos en estado anterior)"""
    __tablename__ = 'presupuestos'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Número de solicitud con formato aamm_contador (ej: 2601_01)
    numero_solicitud = db.Column(db.String(10), unique=True, nullable=True)
    
    # Relaciones
    comercial_id = db.Column(db.Integer, db.ForeignKey('comerciales.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    
    # Tipo de presupuesto
    tipo_pedido = db.Column(db.String(50), nullable=False)  # confeccion, bordado, serigrafia, sublimacion, varios
    
    # Estado unificado de la solicitud (presupuesto/pedido)
    estado = db.Column(db.String(50), nullable=False, default='presupuesto')  # presupuesto, rechazado, aceptado, mockup, en preparacion, revision y empaquetado, entregado al cliente
    
    # Subestado para estados que tienen subestados
    subestado = db.Column(db.String(50), nullable=True)  # Para mockup: encargado a, REVISIÓN CLIENTE, CAMBIOS 1, CAMBIOS 2, RECHAZADO, aceptado. Para en preparacion: hacer marcada, imprimir, calandra, corte, confeccion, sublimacion, bordado
    
    # Fecha límite para mockup (3 días desde que entra al estado)
    fecha_limite_mockup = db.Column(db.Date, nullable=True)
    
    # Usuario al que se encarga el mockup
    mockup_encargado_a_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    
    # Usuario al que se encarga hacer marcada
    marcada_encargado_a_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    
    # Forma de pago
    forma_pago = db.Column(db.Text)
    
    # Imagen del diseño
    imagen_diseno = db.Column(db.String(255))
    
    # Imagen del mockup (PDF)
    imagen_mockup = db.Column(db.String(255))  # Mockup en formato PDF
    
    # Imágenes para el PDF del presupuesto
    imagen_portada = db.Column(db.String(255))  # Imagen de portada (primera página)
    imagen_adicional_1 = db.Column(db.String(255))  # Imagen adicional 1 (segunda página)
    descripcion_imagen_1 = db.Column(db.Text)  # Descripción de imagen adicional 1
    imagen_adicional_2 = db.Column(db.String(255))  # Imagen adicional 2 (segunda página)
    descripcion_imagen_2 = db.Column(db.Text)  # Descripción de imagen adicional 2
    imagen_adicional_3 = db.Column(db.String(255))  # Imagen adicional 3 (segunda página)
    descripcion_imagen_3 = db.Column(db.Text)  # Descripción de imagen adicional 3
    imagen_adicional_4 = db.Column(db.String(255))  # Imagen adicional 4 (segunda página)
    descripcion_imagen_4 = db.Column(db.Text)  # Descripción de imagen adicional 4
    imagen_adicional_5 = db.Column(db.String(255))  # Imagen adicional 5 (segunda página)
    descripcion_imagen_5 = db.Column(db.Text)  # Descripción de imagen adicional 5
    
    # Campo de seguimiento para actualizaciones de comerciales
    seguimiento = db.Column(db.Text)
    
    # Información para la fabricación
    tipo_producto = db.Column(db.String(200), nullable=False)  # Tipo de producto
    colores_principales = db.Column(db.String(200), nullable=False)  # Colores principales
    colores_secundarios = db.Column(db.String(200), nullable=False)  # Colores secundarios
    ubicacion_logo = db.Column(db.String(200), nullable=False)  # Ubicación del logo
    referencias_web = db.Column(db.Text, nullable=False)  # Referencias web
    datos_adicionales = db.Column(db.Text, nullable=False)  # Datos/Info adicional
    
    # Fechas por estado (se guardan y no se sobrescriben)
    fecha_presupuesto = db.Column(db.Date)  # Fecha cuando se marcó como presupuesto (usa fecha_creacion si no existe)
    fecha_aceptado = db.Column(db.Date)  # Fecha cuando se aceptó
    fecha_mockup = db.Column(db.Date)  # Fecha cuando entró en estado mockup
    fecha_en_preparacion = db.Column(db.Date)  # Fecha cuando se marcó como en preparación
    fecha_terminado = db.Column(db.Date)  # Fecha cuando se marcó como terminado
    fecha_entregado_cliente = db.Column(db.Date)  # Fecha cuando se entregó al cliente
    
    # Fechas antiguas (mantener para compatibilidad)
    fecha_diseno = db.Column(db.Date)  # Deprecated
    fecha_diseno_finalizado = db.Column(db.Date)  # Deprecated
    fecha_todo_listo = db.Column(db.Date)  # Deprecated
    fecha_enviado = db.Column(db.Date)  # Deprecated
    fecha_rechazado = db.Column(db.Date)  # Deprecated
    
    # Fechas adicionales del proceso (compatibilidad con pedidos)
    fecha_aceptacion = db.Column(db.Date)  # Alias de fecha_aceptado para compatibilidad
    fecha_objetivo = db.Column(db.Date)  # Fecha objetivo de entrega (deprecated, usar fecha_objetivo_25 y fecha_objetivo_17)
    fecha_objetivo_25 = db.Column(db.Date)  # Fecha objetivo de 25 días hábiles desde aceptación del mockup
    fecha_objetivo_17 = db.Column(db.Date)  # Fecha objetivo de 17 días hábiles desde aceptación del mockup
    fecha_entrega_trabajo = db.Column(db.Date)
    fecha_envio_taller = db.Column(db.Date)
    fecha_entrega_bordados = db.Column(db.Date)
    fecha_entrega_cliente = db.Column(db.Date)
    
    # Fechas antiguas (mantener para compatibilidad)
    fecha_pendiente_enviar = db.Column(db.Date)  # Deprecated: usar fecha_presupuesto
    fecha_envio = db.Column(db.Date)  # Deprecated: usar fecha_enviado
    fecha_respuesta = db.Column(db.Date)  # Deprecated: usar fecha_aceptado o fecha_rechazado
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relación con líneas de presupuesto
    lineas = db.relationship('LineaPresupuesto', backref='presupuesto', lazy=True, cascade='all, delete-orphan')
    
    # Relación con usuario al que se encarga el mockup
    mockup_encargado_a = db.relationship('Usuario', foreign_keys=[mockup_encargado_a_id], backref='mockups_encargados')
    
    # Relación con usuario al que se encarga hacer marcada
    marcada_encargado_a = db.relationship('Usuario', foreign_keys=[marcada_encargado_a_id], backref='marcadas_encargadas')
    
    def __repr__(self):
        return f'<Presupuesto {self.id} - {self.cliente.nombre if self.cliente else "Sin cliente"}>'

class LineaPresupuesto(db.Model):
    """Líneas de prendas dentro de un presupuesto"""
    __tablename__ = 'lineas_presupuesto'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relaciones
    presupuesto_id = db.Column(db.Integer, db.ForeignKey('presupuestos.id'), nullable=False)
    prenda_id = db.Column(db.Integer, db.ForeignKey('prendas.id'), nullable=True)  # Nullable para permitir texto libre
    
    # Campos específicos de la línea
    nombre = db.Column(db.String(200), nullable=False)  # Mantenido para compatibilidad, no se usa en la UI
    cargo = db.Column(db.String(100))  # Mantenido para compatibilidad, no se usa en la UI
    nombre_mostrar = db.Column(db.String(200), nullable=True)  # Nombre para mostrar al cliente
    cantidad = db.Column(db.Integer, nullable=False, default=1)
    color = db.Column(db.String(50))
    forma = db.Column(db.String(100))
    tipo_manda = db.Column(db.String(100))
    sexo = db.Column(db.String(20))  # Masculino, Femenino, Unisex
    talla = db.Column(db.String(20))
    tejido = db.Column(db.String(100))
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=True)  # Precio unitario de la línea
    descuento = db.Column(db.Numeric(5, 2), nullable=False, default=0)  # Porcentaje de descuento (0-100)
    precio_final = db.Column(db.Numeric(10, 2), nullable=True)  # Precio unitario con descuento aplicado
    
    # Estado de la línea
    estado = db.Column(db.String(50), nullable=False, default='pendiente')  # pendiente, en confección, en bordado, listo
    
    def __repr__(self):
        return f'<LineaPresupuesto {self.id} - {self.nombre} x{self.cantidad}>'

class Ticket(db.Model):
    """Tickets de tienda (Facturas simplificadas)"""
    __tablename__ = 'tickets'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Datos de la factura simplificada
    serie = db.Column(db.String(10), nullable=False, default='A')
    numero = db.Column(db.String(50), nullable=False)
    fecha_expedicion = db.Column(db.Date, nullable=False)
    tipo_factura = db.Column(db.String(10), nullable=False, default='F2')  # F2 = Factura simplificada
    descripcion = db.Column(db.Text)
    
    # Datos del cliente
    nif = db.Column(db.String(20))
    nombre = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(100))  # Email del cliente
    categoria = db.Column(db.String(50))  # Categoría: hosteleria, clinica, colegio, emerita, carnaval, transporte, varios
    
    # Forma de pago
    forma_pago = db.Column(db.String(100))
    
    # Importe total
    importe_total = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Tipo de cálculo de IVA: 'incrementar' (precio base + IVA) o 'desglosar' (precio total incluye IVA)
    tipo_calculo_iva = db.Column(db.String(20), default='desglosar')
    
    # Estado y huella de Verifactu
    estado = db.Column(db.String(50), nullable=False, default='pendiente')  # pendiente, enviado, confirmado, error
    huella_verifactu = db.Column(db.Text)  # Respuesta de la API Verifactu
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_confirmacion = db.Column(db.DateTime)  # Fecha en que se recibió la huella
    
    # Relación con líneas de ticket
    lineas = db.relationship('LineaTicket', backref='ticket', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Ticket {self.serie}-{self.numero} - {self.nombre}>'

class LineaTicket(db.Model):
    """Líneas de productos dentro de un ticket"""
    __tablename__ = 'lineas_ticket'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relación
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    
    # Campos de la línea
    descripcion = db.Column(db.String(500), nullable=False)
    cantidad = db.Column(db.Numeric(10, 2), nullable=False, default=1)
    talla = db.Column(db.String(20), nullable=True)  # Talla del producto
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    importe = db.Column(db.Numeric(10, 2), nullable=False)  # cantidad * precio_unitario
    
    def __repr__(self):
        return f'<LineaTicket {self.id} - {self.descripcion} x{self.cantidad}>'

class ClienteTienda(db.Model):
    """Clientes de tienda creados desde tickets"""
    __tablename__ = 'clientes_tienda'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    nif = db.Column(db.String(20))
    email = db.Column(db.String(100))
    categoria = db.Column(db.String(50))  # hosteleria, clinica, colegio, emerita, carnaval, transporte, varios
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<ClienteTienda {self.nombre} ({self.categoria})>'

class Factura(db.Model):
    """Facturas formales (tipo F1)"""
    __tablename__ = 'facturas'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relación con pedido (opcional, puede ser None para facturas directas)
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedidos.id'), nullable=True)
    pedido = db.relationship('Pedido', backref='facturas', lazy=True)
    
    # Relación con presupuesto/solicitud (opcional, puede ser None para facturas directas)
    presupuesto_id = db.Column(db.Integer, db.ForeignKey('presupuestos.id'), nullable=True)
    presupuesto = db.relationship('Presupuesto', backref='facturas', lazy=True)
    
    # Datos de la factura
    serie = db.Column(db.String(10), nullable=False, default='A')
    numero = db.Column(db.String(50), nullable=False)
    fecha_expedicion = db.Column(db.Date, nullable=False)
    tipo_factura = db.Column(db.String(10), nullable=False, default='F1')  # F1 = Factura completa
    descripcion = db.Column(db.Text)
    
    # Datos del cliente (copiados del pedido)
    nif = db.Column(db.String(20))
    nombre = db.Column(db.String(200), nullable=False)
    
    # Importe total
    importe_total = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Descuento por pronto pago
    descuento_pronto_pago = db.Column(db.Numeric(5, 2), nullable=False, default=0)  # Porcentaje de descuento por pronto pago (0-100)
    
    # Estado y huella de Verifactu
    estado = db.Column(db.String(50), nullable=False, default='pendiente')  # pendiente, enviado, confirmado, error
    huella_verifactu = db.Column(db.Text)  # Respuesta de la API Verifactu
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_confirmacion = db.Column(db.DateTime)  # Fecha en que se recibió la huella
    
    # Relación con líneas de factura
    lineas = db.relationship('LineaFactura', backref='factura', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Factura {self.serie}-{self.numero} - {self.nombre}>'

class LineaFactura(db.Model):
    """Líneas de productos dentro de una factura"""
    __tablename__ = 'lineas_factura'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relación
    factura_id = db.Column(db.Integer, db.ForeignKey('facturas.id'), nullable=False)
    
    # Relación con línea de pedido original
    linea_pedido_id = db.Column(db.Integer, db.ForeignKey('lineas_pedido.id'), nullable=True)
    
    # Campos de la línea
    descripcion = db.Column(db.String(500), nullable=False)
    cantidad = db.Column(db.Numeric(10, 2), nullable=False, default=1)
    talla = db.Column(db.String(20), nullable=True)  # Talla del producto
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    descuento = db.Column(db.Numeric(5, 2), nullable=False, default=0)  # Porcentaje de descuento (0-100)
    precio_final = db.Column(db.Numeric(10, 2), nullable=True)  # Precio unitario con descuento aplicado
    importe = db.Column(db.Numeric(10, 2), nullable=False)  # cantidad * precio_unitario (o precio_final si existe)
    
    def __repr__(self):
        return f'<LineaFactura {self.id} - {self.descripcion} x{self.cantidad}>'

class Usuario(db.Model, UserMixin):
    """Usuarios del sistema con autenticación"""
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    correo = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(50))
    rol = db.Column(db.String(50), nullable=False)  # comercial, administracion, supervisor, usuario
    
    # Timestamps
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_acceso = db.Column(db.DateTime)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    
    def set_password(self, password):
        """Establecer contraseña con hash"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verificar contraseña"""
        return check_password_hash(self.password_hash, password)
    
    def is_supervisor(self):
        """Verificar si el usuario es supervisor"""
        return self.rol == 'supervisor'
    
    def __repr__(self):
        return f'<Usuario {self.usuario} ({self.rol})>'

class PlantillaEmail(db.Model):
    """Plantillas de email configurables por el supervisor"""
    __tablename__ = 'plantillas_email'
    
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False, unique=True)  # 'presupuesto', 'cambio_estado_pedido'
    asunto = db.Column(db.String(200), nullable=False)
    cuerpo = db.Column(db.Text, nullable=False)
    enviar_activo = db.Column(db.Boolean, nullable=False, default=True)  # Permite desactivar temporalmente el envío
    
    # Timestamps
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<PlantillaEmail {self.tipo}>'

class RegistroCambioEstado(db.Model):
    """Registro de cambios de estado en pedidos y líneas de pedido"""
    __tablename__ = 'registro_cambio_estado'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Tipo de cambio: 'pedido' o 'linea_pedido'
    tipo_cambio = db.Column(db.String(20), nullable=False)
    
    # Referencia al pedido (siempre presente)
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedidos.id'), nullable=False)
    
    # Referencia a la línea (solo si tipo_cambio es 'linea_pedido')
    linea_id = db.Column(db.Integer, nullable=True)
    
    # Estados
    estado_anterior = db.Column(db.String(50))
    estado_nuevo = db.Column(db.String(50), nullable=False)
    
    # Usuario que realizó el cambio
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    
    # Fecha y hora del cambio
    fecha_cambio = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relaciones
    pedido = db.relationship('Pedido', backref='registros_cambio_estado')
    usuario = db.relationship('Usuario', backref='registros_cambio_estado')
    
    def __repr__(self):
        return f'<RegistroCambioEstado {self.id} - {self.tipo_cambio} - {self.estado_anterior} -> {self.estado_nuevo}>'

class Proveedor(db.Model):
    """Proveedores del sistema"""
    __tablename__ = 'proveedores'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    cif = db.Column(db.String(20))  # CIF del proveedor
    telefono = db.Column(db.String(50))
    movil = db.Column(db.String(50))  # Teléfono móvil
    correo = db.Column(db.String(100))
    persona_contacto = db.Column(db.String(200))  # Persona de contacto
    activo = db.Column(db.Boolean, nullable=False, default=True)  # Estado activo/inactivo
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relación con facturas de proveedor
    facturas = db.relationship('FacturaProveedor', backref='proveedor', lazy=True)
    
    def __repr__(self):
        return f'<Proveedor {self.nombre}>'

class FacturaProveedor(db.Model):
    """Facturas de proveedores"""
    __tablename__ = 'facturas_proveedor'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relación con proveedor
    proveedor_id = db.Column(db.Integer, db.ForeignKey('proveedores.id'), nullable=False)
    
    # Datos de la factura
    numero_factura = db.Column(db.String(100), nullable=False)  # Número de factura del proveedor
    fecha_factura = db.Column(db.Date, nullable=False)
    fecha_vencimiento = db.Column(db.Date)  # Fecha de vencimiento para pago
    
    # Importes
    base_imponible = db.Column(db.Numeric(10, 2), nullable=False)
    tipo_iva = db.Column(db.Numeric(5, 2), nullable=False, default=21.00)  # Porcentaje de IVA
    importe_iva = db.Column(db.Numeric(10, 2), nullable=False)
    total = db.Column(db.Numeric(10, 2), nullable=False)  # base_imponible + importe_iva
    
    # Estado
    estado = db.Column(db.String(50), nullable=False, default='pendiente')  # pendiente, pagada, vencida
    
    # Observaciones
    observaciones = db.Column(db.Text)
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<FacturaProveedor {self.numero_factura} - {self.proveedor.nombre if self.proveedor else "Sin proveedor"}>'

class Empleado(db.Model):
    """Empleados del sistema"""
    __tablename__ = 'empleados'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    dni = db.Column(db.String(20))  # DNI del empleado
    telefono = db.Column(db.String(50))
    correo = db.Column(db.String(100))
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relación con nóminas
    nominas = db.relationship('Nomina', backref='empleado', lazy=True)
    
    def __repr__(self):
        return f'<Empleado {self.nombre}>'

class Nomina(db.Model):
    """Nóminas de empleados"""
    __tablename__ = 'nominas'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relación con empleado
    empleado_id = db.Column(db.Integer, db.ForeignKey('empleados.id'), nullable=False)
    
    # Datos de la nómina
    mes = db.Column(db.Integer, nullable=False)  # Mes (1-12)
    año = db.Column(db.Integer, nullable=False)  # Año
    
    # Importe
    total_devengado = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Observaciones
    observaciones = db.Column(db.Text)
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Nomina {self.empleado.nombre if self.empleado else "Sin empleado"} - {self.mes}/{self.año}>'

class Configuracion(db.Model):
    """Configuraciones del sistema"""
    __tablename__ = 'configuracion'
    
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(100), unique=True, nullable=False)
    valor = db.Column(db.Text)
    descripcion = db.Column(db.Text)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Configuracion {self.clave}={self.valor}>'

class DireccionEnvio(db.Model):
    """Direcciones de envío alternativas para clientes"""
    __tablename__ = 'direcciones_envio'
    
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)  # Nombre de la dirección (ej: "Dirección envío 2")
    direccion = db.Column(db.Text)
    poblacion = db.Column(db.String(100))
    provincia = db.Column(db.String(100))
    codigo_postal = db.Column(db.String(10))
    pais = db.Column(db.String(100), default='España')
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<DireccionEnvio {self.nombre} - {self.cliente.nombre if self.cliente else "Sin cliente"}>'

class PersonaContacto(db.Model):
    """Personas de contacto para clientes"""
    __tablename__ = 'personas_contacto'
    
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    cargo = db.Column(db.String(200))
    movil = db.Column(db.String(50))
    email = db.Column(db.String(100))
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<PersonaContacto {self.nombre} - {self.cliente.nombre if self.cliente else "Sin cliente"}>'

class DiaFestivo(db.Model):
    """Días festivos que no se tienen en cuenta para cálculos de fechas"""
    __tablename__ = 'dias_festivos'
    
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False)
    nombre = db.Column(db.String(200), nullable=False)  # Nombre/explicación del día festivo
    activo = db.Column(db.Boolean, nullable=False, default=True)
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<DiaFestivo {self.fecha} - {self.nombre}>'

class RegistroEstadoSolicitud(db.Model):
    """Registro de cambios de estado y subestado en solicitudes con fechas"""
    __tablename__ = 'registro_estado_solicitud'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relación con presupuesto/solicitud
    presupuesto_id = db.Column(db.Integer, db.ForeignKey('presupuestos.id'), nullable=False)
    presupuesto = db.relationship('Presupuesto', backref='registros_estado', lazy=True)
    
    # Estado y subestado
    estado = db.Column(db.String(50), nullable=False)
    subestado = db.Column(db.String(50), nullable=True)
    
    # Fecha del cambio
    fecha_cambio = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Usuario que realizó el cambio (opcional)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    usuario = db.relationship('Usuario', backref='registros_estado_solicitud', lazy=True)
    
    def __repr__(self):
        return f'<RegistroEstadoSolicitud {self.id} - {self.estado}/{self.subestado} - {self.fecha_cambio}>'
