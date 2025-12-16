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
    
    # Relación con usuario
    usuario = db.relationship('Usuario', backref='comercial', lazy=True)
    
    # Relación con pedidos
    pedidos = db.relationship('Pedido', backref='comercial', lazy=True)
    # Relación con presupuestos
    presupuestos = db.relationship('Presupuesto', backref='comercial', lazy=True)
    
    @property
    def nombre(self):
        """Obtener el nombre del usuario asociado"""
        return self.usuario.usuario if self.usuario else ''
    
    def __repr__(self):
        return f'<Comercial {self.nombre}>'

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
    email = db.Column(db.String(100))
    categoria = db.Column(db.String(50))  # Categoría: hosteleria, clinica, colegio, emerita, carnaval, transporte, varios
    personas_contacto = db.Column(db.Text)  # Personas de contacto
    anotaciones = db.Column(db.Text)  # Anotaciones adicionales
    
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
    
    # Estado de la línea
    estado = db.Column(db.String(50), nullable=False, default='pendiente')  # pendiente, en confección, en bordado, listo
    
    def __repr__(self):
        return f'<LineaPedido {self.id} - {self.nombre} x{self.cantidad}>'
    
class Presupuesto(db.Model):
    """Presupuestos del sistema (pedidos en estado anterior)"""
    __tablename__ = 'presupuestos'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relaciones
    comercial_id = db.Column(db.Integer, db.ForeignKey('comerciales.id'), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    
    # Tipo de presupuesto
    tipo_pedido = db.Column(db.String(50), nullable=False)  # confeccion, bordado, serigrafia, sublimacion, varios
    
    # Estado del presupuesto
    estado = db.Column(db.String(50), nullable=False, default='Pendiente de enviar')  # Pendiente de enviar, Diseño, Enviado, Aceptado, Rechazado
    
    # Forma de pago
    forma_pago = db.Column(db.Text)
    
    # Imagen del diseño
    imagen_diseno = db.Column(db.String(255))
    
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
    
    # Fechas
    fecha_pendiente_enviar = db.Column(db.Date)  # Fecha en que se marcó como Pendiente de enviar
    fecha_diseno = db.Column(db.Date)  # Fecha en que se marcó como Diseño
    fecha_envio = db.Column(db.Date)  # Fecha en que se envió el presupuesto
    fecha_respuesta = db.Column(db.Date)  # Fecha de aceptación o rechazo
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relación con líneas de presupuesto
    lineas = db.relationship('LineaPresupuesto', backref='presupuesto', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Presupuesto {self.id} - {self.cliente.nombre if self.cliente else "Sin cliente"}>'

class LineaPresupuesto(db.Model):
    """Líneas de prendas dentro de un presupuesto"""
    __tablename__ = 'lineas_presupuesto'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relaciones
    presupuesto_id = db.Column(db.Integer, db.ForeignKey('presupuestos.id'), nullable=False)
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
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=True)  # Precio unitario de la línea
    
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
    
    # Relación con pedido
    pedido_id = db.Column(db.Integer, db.ForeignKey('pedidos.id'), nullable=False)
    pedido = db.relationship('Pedido', backref='facturas', lazy=True)
    
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
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    importe = db.Column(db.Numeric(10, 2), nullable=False)  # cantidad * precio_unitario
    
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
    correo = db.Column(db.String(100))
    
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
