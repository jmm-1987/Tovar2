import base64
import json
import os
from datetime import datetime

import requests
from flask import Blueprint, current_app, jsonify, request

from extensions import db
from models import FacturaProveedorIA, NominaIA


telegram_bp = Blueprint('telegram_bot', __name__, url_prefix='/telegram')


def _get_env_tokens():
    """Obtener tokens desde variables de entorno."""
    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    openai_key = os.environ.get('OPENAI_API_KEY')
    return telegram_token, openai_key


def _send_telegram_message(token: str, chat_id: int, text: str):
    """Enviar un mensaje sencillo a Telegram."""
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
    except Exception:
        # No interrumpir el flujo por errores de notificación
        pass


def _download_telegram_file(token: str, file_id: str) -> bytes:
    """Descargar un fichero desde Telegram y devolver los bytes."""
    base_url = f"https://api.telegram.org/bot{token}"
    # Primero obtener la ruta real del fichero
    resp = requests.get(f"{base_url}/getFile", params={"file_id": file_id}, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    file_path = data["result"]["file_path"]

    # Descargar el fichero
    file_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    file_resp = requests.get(file_url, timeout=60)
    file_resp.raise_for_status()
    return file_resp.content, os.path.basename(file_path)


def _save_image(content: bytes, subfolder: str, filename_hint: str) -> str:
    """Guardar imagen en static/uploads/<subfolder> y devolver la ruta relativa desde la raíz del proyecto."""
    upload_root = current_app.config.get("UPLOAD_FOLDER", "static/uploads")
    # Nos aseguramos de que la ruta sea relativa a la app
    base_dir = os.path.dirname(os.path.abspath(__file__))
    upload_root_abs = os.path.join(base_dir, upload_root)
    target_dir = os.path.join(upload_root_abs, subfolder)
    os.makedirs(target_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"{timestamp}_{filename_hint or 'imagen'}.jpg"
    safe_filename = filename.replace(" ", "_")
    full_path = os.path.join(target_dir, safe_filename)

    with open(full_path, "wb") as f:
        f.write(content)

    # Ruta que se guardará en BD (siempre empezando por static/)
    rel_path = os.path.relpath(full_path, base_dir)
    return rel_path.replace("\\", "/")


def _call_openai_vision(openai_key: str, image_bytes: bytes) -> dict:
    """Llamar a OpenAI para extraer campos de la imagen."""
    api_url = "https://api.openai.com/v1/chat/completions"
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    prompt = (
        "Eres un asistente que lee facturas de gasto y nóminas en español.\n"
        "Devuelve SIEMPRE un JSON válido con esta estructura:\n"
        "{\n"
        '  "tipo_documento": "factura" o "nomina",\n'
        '  "proveedor": "texto o null",\n'
        '  "numero_factura": "texto o null",\n'
        '  "fecha": "YYYY-MM-DD o null",\n'
        '  "vencimiento": "YYYY-MM-DD o null",\n'
        '  "base": número o null,\n'
        '  "iva_porcentaje": número o null,\n'
        '  "total": número o null,\n'
        '  "empleado": "nombre del empleado o null",\n'
        '  "mes": número de 1 a 12 o null,\n'
        '  "anio": número de año o null,\n'
        '  "total_devengado": número o null\n'
        "}\n"
        "Si algún dato no aparece claro, pon null. No añadas texto fuera del JSON."
    )

    headers = {
        "Authorization": f"Bearer {openai_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": "Asistente experto en lectura de facturas y nóminas.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}",
                        },
                    },
                ],
            },
        ],
        "temperature": 0.0,
    }

    resp = requests.post(api_url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except Exception:
        # Si no es JSON puro, intentar extraer el primer bloque JSON
        import re

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


@telegram_bp.route("/webhook", methods=["POST"])
def telegram_webhook():
    """Webhook de Telegram para recibir fotos de facturas/nóminas."""
    telegram_token, openai_key = _get_env_tokens()
    if not telegram_token or not openai_key:
        return "Faltan TELEGRAM_BOT_TOKEN u OPENAI_API_KEY", 500

    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify(ok=True)

    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    # Determinar si viene como foto o como documento imagen
    file_id = None
    is_nomina = False

    if "photo" in message and message["photo"]:
        # Tomamos la foto de mayor resolución (último elemento)
        file_id = message["photo"][-1]["file_id"]
    elif "document" in message:
        doc = message["document"]
        mime = doc.get("mime_type", "")
        if mime.startswith("image/"):
            file_id = doc["file_id"]

    caption = (message.get("caption") or "").lower()
    if "nomina" in caption or "nómina" in caption:
        is_nomina = True

    if not file_id:
        if chat_id:
            _send_telegram_message(
                telegram_token,
                chat_id,
                "Envía una foto o imagen de la factura o nómina. "
                "Opcionalmente escribe en el pie de foto la palabra 'nomina' para que lo tratemos como tal.",
            )
        return jsonify(ok=True)

    try:
        # Descargar imagen desde Telegram
        image_bytes, filename_hint = _download_telegram_file(telegram_token, file_id)

        # Llamar a OpenAI
        ia_data = _call_openai_vision(openai_key, image_bytes)

        # Decidir tipo de documento (prioriza lo que venga en el pie de foto)
        tipo_documento = ia_data.get("tipo_documento", "factura")
        if is_nomina:
            tipo_documento = "nomina"

        if tipo_documento == "nomina":
            rel_path = _save_image(image_bytes, "nominas_ia", filename_hint)
            nomina_ia = NominaIA(
                empleado_nombre=ia_data.get("empleado"),
                mes=ia_data.get("mes"),
                año=ia_data.get("anio"),
                total_devengado=ia_data.get("total_devengado"),
                imagen_ruta=rel_path,
                datos_ia_json=json.dumps(ia_data, ensure_ascii=False),
            )
            db.session.add(nomina_ia)
            db.session.commit()

            if chat_id:
                _send_telegram_message(
                    telegram_token,
                    chat_id,
                    "✅ Nómina recibida y analizada. Ya aparece como 'Nómina IA pendiente' en el sistema para que la validéis.",
                )
        else:
            rel_path = _save_image(image_bytes, "facturas_ia", filename_hint)

            fecha = ia_data.get("fecha")
            fecha_dt = None
            if fecha:
                try:
                    fecha_dt = datetime.strptime(str(fecha), "%Y-%m-%d").date()
                except Exception:
                    fecha_dt = None

            venc = ia_data.get("vencimiento")
            venc_dt = None
            if venc:
                try:
                    venc_dt = datetime.strptime(str(venc), "%Y-%m-%d").date()
                except Exception:
                    venc_dt = None

            factura_ia = FacturaProveedorIA(
                proveedor_nombre=ia_data.get("proveedor"),
                numero_factura=ia_data.get("numero_factura"),
                fecha_factura=fecha_dt,
                fecha_vencimiento=venc_dt,
                base_imponible=ia_data.get("base"),
                tipo_iva=ia_data.get("iva_porcentaje"),
                importe_iva=None,
                total=ia_data.get("total"),
                imagen_ruta=rel_path,
                datos_ia_json=json.dumps(ia_data, ensure_ascii=False),
            )
            db.session.add(factura_ia)
            db.session.commit()

            if chat_id:
                _send_telegram_message(
                    telegram_token,
                    chat_id,
                    "✅ Factura recibida y analizada. Ya aparece como 'Factura IA pendiente' en el sistema para que la validéis.",
                )

    except Exception as e:
        if chat_id:
            _send_telegram_message(
                telegram_token,
                chat_id,
                f"❌ Ha ocurrido un error procesando la imagen: {e}",
            )

    return jsonify(ok=True)

