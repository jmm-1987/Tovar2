from datetime import datetime
from extensions import db

# Crear todos los modelos directamente
# Esto se ejecuta una sola vez cuando se importa el módulo

class Comercial(db.Model):
    """Comerciales que pueden crear pedidos"""
    __tablename__ = 'comerciales'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    
    # Relación con pedidos
    pedidos = db.relationship('Pedido', backref='comercial', lazy=True)
    # Relación con presupuestos
    presupuestos = db.relationship('Presupuesto', backref='comercial', lazy=True)
    
    def __repr__(self):
        return f'<Comercial {self.nombre}>'

class Cliente(db.Model):
    """Clientes del sistema"""
    __tablename__ = 'clientes'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    nif = db.Column(db.String(20))  # NIF/CIF del cliente
    direccion = db.Column(db.Text)
    telefono = db.Column(db.String(50))
    email = db.Column(db.String(100))
    
    # Relación con pedidos
    pedidos = db.relationship('Pedido', backref='cliente', lazy=True)
    # Relación con presupuestos
    presupuestos = db.relationship('Presupuesto', backref='cliente', lazy=True)
    
    def __repr__(self):
        return f'<Cliente {self.nombre}>'

class Prenda(db.Model):
    """Modelos base de prendas"""
    __tablename__ = 'prendas'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)  # pantalon, camisa, zapato, camiseta, etc.
    
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
    
    # Tipo de pedido
    tipo_pedido = db.Column(db.String(50), nullable=False)  # fabricacion, no fabricacion
    
    # Estado del pedido
    estado = db.Column(db.String(50), nullable=False, default='Pendiente')  # Pendiente, En preparación, Todo listo, Enviado, Entregado al cliente
    
    # Forma de pago
    forma_pago = db.Column(db.Text)
    
    # Imagen del diseño
    imagen_diseno = db.Column(db.String(255))
    
    # Fechas del proceso
    fecha_aceptacion = db.Column(db.Date)
    fecha_objetivo = db.Column(db.Date)  # Fecha objetivo de entrega (calculada automáticamente: 20 días desde aceptación)
    fecha_entrega_trabajo = db.Column(db.Date)
    fecha_envio_taller = db.Column(db.Date)
    fecha_entrega_bordados = db.Column(db.Date)
    fecha_entrega_cliente = db.Column(db.Date)
    
    # Timestamp
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relación con líneas de pedido
    lineas = db.relationship('LineaPedido', backref='pedido', lazy=True, cascade='all, delete-orphan')
    
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
    estado = db.Column(db.String(50), nullable=False, default='Pendiente de enviar')  # Pendiente de enviar, Enviado, Aceptado, Rechazado
    
    # Forma de pago
    forma_pago = db.Column(db.Text)
    
    # Imagen del diseño
    imagen_diseno = db.Column(db.String(255))
    
    # Campo de seguimiento para actualizaciones de comerciales
    seguimiento = db.Column(db.Text)
    
    # Fechas
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
    
    # Importe total
    importe_total = db.Column(db.Numeric(10, 2), nullable=False)
    
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
