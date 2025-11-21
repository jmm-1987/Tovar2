from datetime import datetime

# Las clases se definirán después de importar db desde app
# Esto evita el import circular
def create_models(db):
    """Crear todos los modelos con la instancia de db"""
    
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
        tipo_pedido = db.Column(db.String(50), nullable=False)  # confeccion, bordado, serigrafia, sublimacion, varios
        
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
        nombre = db.Column(db.String(200), nullable=False)
        cargo = db.Column(db.String(100))
        cantidad = db.Column(db.Integer, nullable=False, default=1)
        color = db.Column(db.String(50))
        forma = db.Column(db.String(100))
        tipo_manda = db.Column(db.String(100))
        sexo = db.Column(db.String(20))  # Masculino, Femenino, Unisex
        talla = db.Column(db.String(20))
        tejido = db.Column(db.String(100))
        
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
        nombre = db.Column(db.String(200), nullable=False)
        cargo = db.Column(db.String(100))
        cantidad = db.Column(db.Integer, nullable=False, default=1)
        color = db.Column(db.String(50))
        forma = db.Column(db.String(100))
        tipo_manda = db.Column(db.String(100))
        sexo = db.Column(db.String(20))  # Masculino, Femenino, Unisex
        talla = db.Column(db.String(20))
        tejido = db.Column(db.String(100))
        
        def __repr__(self):
            return f'<LineaPresupuesto {self.id} - {self.nombre} x{self.cantidad}>'
    
    return Comercial, Cliente, Prenda, Pedido, LineaPedido, Presupuesto, LineaPresupuesto
