import os

# Render proporciona el puerto en la variable de entorno PORT
port = os.environ.get('PORT', '10000')
bind = f"0.0.0.0:{port}"
workers = 2
threads = 2
timeout = 120

