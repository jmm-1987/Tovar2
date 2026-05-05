"""Utilidades para subir archivos a SFTP de Ionos"""
import os
import paramiko
from io import BytesIO
from flask import current_app


def get_sftp_config():
    """Obtener configuración SFTP desde variables de entorno"""
    return {
        'host': os.environ.get('SFTP_HOST'),
        'port': int(os.environ.get('SFTP_PORT', 22)),
        'username': os.environ.get('SFTP_USER'),
        'password': os.environ.get('SFTP_PASS'),
        'base_dir': os.environ.get('SFTP_DIR', '/'),
        'base_url': os.environ.get('SFTP_BASE_URL', '')
    }


def upload_file_to_sftp(file_content, remote_path):
    """
    Subir un archivo a SFTP
    
    Args:
        file_content: Contenido del archivo (bytes o BytesIO)
        remote_path: Ruta remota donde guardar el archivo (ej: '/uploads/solicitudes/imagen.jpg')
    
    Returns:
        str: Ruta relativa del archivo subido o None si hay error
    """
    config = get_sftp_config()
    
    if not all([config['host'], config['username'], config['password']]):
        print("Error: Faltan credenciales SFTP en variables de entorno")
        return None
    
    try:
        # Crear conexión SFTP
        transport = paramiko.Transport((config['host'], config['port']))
        transport.connect(username=config['username'], password=config['password'])
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        try:
            # Asegurar que el directorio existe
            dir_path = os.path.dirname(remote_path)
            if dir_path and dir_path != '/':
                # Crear directorios si no existen (paramiko no tiene makedirs, hay que hacerlo manualmente)
                try:
                    sftp.stat(dir_path)
                except IOError:
                    # El directorio no existe, crearlo recursivamente
                    partes = dir_path.strip('/').split('/')
                    path_actual = ''
                    for parte in partes:
                        path_actual = f"{path_actual}/{parte}" if path_actual else f"/{parte}"
                        try:
                            sftp.stat(path_actual)
                        except IOError:
                            sftp.mkdir(path_actual)
            
            # Convertir file_content a bytes si es necesario
            if isinstance(file_content, BytesIO):
                file_content.seek(0)
                file_bytes = file_content.read()
            elif isinstance(file_content, bytes):
                file_bytes = file_content
            else:
                # Si es un objeto file, leerlo
                file_content.seek(0)
                file_bytes = file_content.read()
            
            # Subir archivo
            file_obj = BytesIO(file_bytes)
            sftp.putfo(file_obj, remote_path)
            
            # Retornar ruta relativa (sin el directorio base)
            return remote_path.lstrip('/')
            
        finally:
            sftp.close()
            transport.close()
            
    except Exception as e:
        print(f"Error al subir archivo a SFTP: {e}")
        import traceback
        traceback.print_exc()
        return None


def download_file_from_sftp(remote_path):
    """
    Descargar un archivo desde SFTP
    
    Args:
        remote_path: Ruta remota del archivo
    
    Returns:
        bytes: Contenido del archivo o None si hay error
    """
    config = get_sftp_config()
    
    if not all([config['host'], config['username'], config['password']]):
        print("Error: Faltan credenciales SFTP en variables de entorno")
        return None
    
    try:
        # Crear conexión SFTP
        transport = paramiko.Transport((config['host'], config['port']))
        transport.connect(username=config['username'], password=config['password'])
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        try:
            # Descargar archivo
            file_obj = BytesIO()
            sftp.getfo(remote_path, file_obj)
            file_obj.seek(0)
            return file_obj.read()
            
        finally:
            sftp.close()
            transport.close()
            
    except Exception as e:
        print(f"Error al descargar archivo desde SFTP: {e}")
        return None


def get_file_url(remote_path):
    """
    Obtener URL pública de un archivo en SFTP
    
    Args:
        remote_path: Ruta remota del archivo
    
    Returns:
        str: URL completa del archivo o None si no hay base_url configurada
    """
    config = get_sftp_config()
    
    if not config['base_url']:
        return None
    
    # Normalizar la ruta
    normalized_path = remote_path.lstrip('/')
    
    # Construir URL
    base_url = config['base_url'].rstrip('/')
    return f"{base_url}/{normalized_path}"


def file_exists_on_sftp(remote_path):
    """
    Verificar si un archivo existe en SFTP
    
    Args:
        remote_path: Ruta remota del archivo
    
    Returns:
        bool: True si existe, False si no
    """
    config = get_sftp_config()
    
    if not all([config['host'], config['username'], config['password']]):
        return False
    
    try:
        transport = paramiko.Transport((config['host'], config['port']))
        transport.connect(username=config['username'], password=config['password'])
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        try:
            sftp.stat(remote_path)
            return True
        except IOError:
            return False
        finally:
            sftp.close()
            transport.close()
            
    except Exception as e:
        print(f"Error al verificar archivo en SFTP: {e}")
        return False

