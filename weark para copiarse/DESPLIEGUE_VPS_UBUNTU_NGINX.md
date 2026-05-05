# Despliegue desde cero (Ubuntu 24.04 + Nginx + root)

Guia actualizada para desplegar este proyecto Flask en un VPS Ubuntu 24.04 usando `root`, `gunicorn`, `systemd`, `nginx` y HTTPS con Let's Encrypt.

---

## 0) Supuestos

- Dominio ya apuntando al VPS (registro `A`).
- Acceso SSH como `root`.
- Proyecto local en tu PC para copiar al VPS.

> Nota: usar `root` funciona, pero en produccion es mas seguro ejecutar la app como `www-data` (como haremos en `systemd`).

---

## 1) Preparar servidor base

```bash
apt update && apt upgrade -y
timedatectl set-timezone Europe/Madrid
apt install -y curl unzip rsync software-properties-common
```

---

## 2) Instalar runtime y dependencias del sistema

```bash
apt install -y \
  python3 python3-venv python3-pip \
  nginx ufw certbot python3-certbot-nginx \
  build-essential libffi-dev libssl-dev \
  libcairo2 libpango-1.0-0 libgdk-pixbuf-2.0-0 \
  libjpeg-dev libopenjp2-7 libxml2 libxslt1.1 \
  shared-mime-info fonts-dejavu-core
```

Estas librerias cubren PDF/HTML render (`playwright`, `weasyprint`, `xhtml2pdf`).

---

## 3) Copiar proyecto al VPS (sin Git)

```bash
mkdir -p /var/www/weark
```

Ahora, desde tu **ordenador local** (PowerShell), copia el proyecto completo al VPS:

```powershell
scp -r C:\Users\jmm87\Trabajos\weark\* root@IP_DEL_VPS:/var/www/weark/
```

Si prefieres sincronizar (mas rapido en cambios posteriores), usa `rsync` desde un terminal Linux/WSL:

```bash
rsync -avz --delete /ruta/local/weark/ root@IP_DEL_VPS:/var/www/weark/
```

Verifica en el VPS:

```bash
ls -la /var/www/weark
```

---

## 4) Crear entorno virtual e instalar dependencias Python

```bash
cd /var/www/weark
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -r requirements.txt
```

Instalar Chromium para Playwright:

```bash
python -m playwright install chromium
```

---

## 5) Crear y configurar `.env` (obligatorio)

Si no existe:

```bash
cd /var/www/weark
cp env.example .env
```

Editar:

```bash
nano /var/www/weark/.env
```

Minimo recomendado para arrancar en VPS:

- `SECRET_KEY` (larga y aleatoria)
- `DATABASE_PATH=instance/pedidos.db`
- `MAIL_*` / `EMAIL_*` (si hay envio de correos)
- `SFTP_*` (si guardas imagenes remotas)
- `APP_BASE_URL=https://weark.jm2-tech.es`

Crear directorios y permisos:

```bash
mkdir -p /var/www/weark/instance
mkdir -p /var/www/weark/static/uploads
chown -R www-data:www-data /var/www/weark
chmod -R 775 /var/www/weark/instance /var/www/weark/static/uploads
chmod 640 /var/www/weark/.env
```

---

## 6) Probar arranque manual una vez

```bash
cd /var/www/weark
source .venv/bin/activate
python app.py
```

Si arranca sin error, para con `Ctrl + C`.

---

## 7) Configurar servicio systemd

Crear archivo:

```bash
nano /etc/systemd/system/weark.service
```

Contenido:

```ini
[Unit]
Description=Weark Flask App
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/weark
Environment="PATH=/var/www/weark/.venv/bin"
EnvironmentFile=/var/www/weark/.env
ExecStart=/var/www/weark/.venv/bin/gunicorn --workers 3 --bind unix:/var/www/weark/weark.sock --timeout 300 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Activar servicio:

```bash
systemctl daemon-reload
systemctl enable weark
systemctl start weark
systemctl status weark --no-pager
```

Logs en vivo:

```bash
journalctl -u weark -f
```

---

## 8) Configurar Nginx (HTTP)

Crear config:

```bash
nano /etc/nginx/sites-available/weark
```

Contenido:

```nginx
server {
    listen 80;
    server_name weark.jm2-tech.es;

    client_max_body_size 30M;

    location /static/ {
        alias /var/www/weark/static/;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000";
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/var/www/weark/weark.sock;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}
```

Activar sitio:

```bash
ln -sf /etc/nginx/sites-available/weark /etc/nginx/sites-enabled/weark
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
```

---

## 9) Firewall

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
ufw status
```

---

## 10) SSL con Let's Encrypt

```bash
certbot --nginx -d weark.jm2-tech.es
```

Probar renovacion automatica:

```bash
certbot renew --dry-run
systemctl status certbot.timer --no-pager
```

---

## 11) Verificacion final

1. `systemctl status weark`
2. `systemctl status nginx`
3. Abrir `https://weark.jm2-tech.es`
4. Probar login
5. Probar generacion de PDF
6. Revisar logs:
   - `journalctl -u weark -n 200 --no-pager`
   - `tail -n 200 /var/log/nginx/error.log`

---

## 12) Comandos de operacion diaria

Reiniciar app:

```bash
systemctl restart weark
```

Reiniciar Nginx:

```bash
systemctl restart nginx
```

Ver logs:

```bash
journalctl -u weark -f
```

Actualizar codigo (sin Git):

```bash
# 1) Desde tu PC, vuelve a copiar/sincronizar archivos al VPS
# 2) En el VPS:
cd /var/www/weark
source .venv/bin/activate
pip install -r requirements.txt
systemctl restart weark
```

---

## 13) Problemas tipicos

- `502 Bad Gateway`
  - `systemctl status weark`
  - comprobar `/var/www/weark/weark.sock`
  - `journalctl -u weark -n 200 --no-pager`

- `ModuleNotFoundError`
  - activar `.venv` y reinstalar: `pip install -r requirements.txt`

- fallo al generar PDFs
  - `python -m playwright install chromium`
  - revisar dependencias del paso 2

- imagenes no suben/no cargan
  - revisar variables `SFTP_*`
  - revisar permisos de `instance/` y `static/uploads`

---

## 14) Recomendaciones de hardening (despues de desplegar)

- Cambiar puerto SSH y desactivar login por password si usas llaves.
- Activar `fail2ban`.
- Hacer backup diario de `instance/pedidos.db`.
- (Recomendado) dejar de usar `root` para operaciones de app y crear usuario de despliegue.

