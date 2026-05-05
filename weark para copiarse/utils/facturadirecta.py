from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import requests


class FacturaDirectaError(RuntimeError):
    pass


def _fd_base_url() -> str:
    return (os.environ.get("FACTURADIRECTA_BASE_URL") or "https://app.facturadirecta.com/api").rstrip("/")


def _fd_company_id() -> str:
    company_id = (os.environ.get("FACTURADIRECTA_COMPANY_ID") or "").strip()
    if not company_id:
        raise FacturaDirectaError("Falta FACTURADIRECTA_COMPANY_ID en variables de entorno.")
    return company_id


def _fd_headers() -> Dict[str, str]:
    headers = {"Accept": "application/json"}

    api_key = (os.environ.get("FACTURADIRECTA_API_KEY") or "").strip()
    bearer = (os.environ.get("FACTURADIRECTA_BEARER_TOKEN") or "").strip()

    if api_key:
        headers["facturadirecta-api-key"] = api_key
        return headers
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
        return headers

    raise FacturaDirectaError(
        "Falta credencial de FacturaDirecta. Define FACTURADIRECTA_API_KEY o FACTURADIRECTA_BEARER_TOKEN."
    )


def _request(method: str, path: str, *, params: Optional[dict] = None, json_body: Optional[dict] = None) -> dict:
    url = f"{_fd_base_url()}{path}"
    headers = _fd_headers()
    headers["Content-Type"] = "application/json"

    try:
        resp = requests.request(method, url, headers=headers, params=params, json=json_body, timeout=30)
    except requests.RequestException as e:
        raise FacturaDirectaError(f"Error de conexión con FacturaDirecta: {e}") from e

    if resp.status_code >= 400:
        payload_hint = ""
        if json_body is not None:
            try:
                import json as _json

                payload_hint = f"\nPAYLOAD_ENVIADO={_json.dumps(json_body, ensure_ascii=False)[:2000]}"
            except Exception:
                payload_hint = "\nPAYLOAD_ENVIADO=(no se pudo serializar)"
        raise FacturaDirectaError(f"FacturaDirecta {resp.status_code}: {resp.text}{payload_hint}")

    try:
        return resp.json()
    except ValueError as e:
        raise FacturaDirectaError(f"Respuesta no-JSON de FacturaDirecta: {resp.text[:500]}") from e


_tax_cache: Tuple[float, List[dict]] = (0.0, [])


def get_sales_taxes(force_refresh: bool = False) -> List[dict]:
    """
    Devuelve lista de impuestos de venta.
    Cada item incluye al menos: id (TaxId string), taxGroup, value (0.21), title, shortTitle.
    Requiere scope: settings:read
    """
    global _tax_cache
    ts, cached = _tax_cache
    if cached and not force_refresh and (time.time() - ts) < 300:
        return cached

    company_id = _fd_company_id()
    data = _request("GET", f"/{company_id}/settings/taxes/sales")
    items = data.get("items") or []
    if not isinstance(items, list):
        items = []
    _tax_cache = (time.time(), items)
    return items


def find_sales_tax_id_by_percent(percent: Decimal) -> Optional[str]:
    """
    Busca un TaxId de grupo IVA cuyo value coincida con el porcentaje.
    Ej: 21 -> value 0.21
    """
    try:
        p = Decimal(str(percent))
    except Exception:
        return None
    value = (p / Decimal("100")).quantize(Decimal("0.0001"))

    for t in get_sales_taxes():
        try:
            if (t.get("taxGroup") == "IVA") and Decimal(str(t.get("value"))).quantize(Decimal("0.0001")) == value:
                return t.get("id")
        except Exception:
            continue
    return None


def _normalize_fiscal_id_es(nif: str) -> str:
    """Mayúsculas y solo caracteres alfanuméricos (sin espacios, guiones ni puntos)."""
    s = (nif or "").strip().upper()
    return "".join(c for c in s if c.isalnum())


def _spanish_cif_checksum_ok(cif: str) -> bool:
    """
    Comprueba dígito/letra de control de un CIF español (9 caracteres: letra + 7 dígitos + control).
    No aplica a NIF de extranjeros (X/Y/Z) ni a DNIs 8+1.
    """
    if len(cif) != 9 or not cif[0].isalpha() or not cif[1:8].isdigit():
        return False
    if cif[0] in "XYZ":
        return True
    pares = sum(int(cif[i]) for i in range(2, 8, 2))
    impares = 0
    for i in range(1, 8, 2):
        n = int(cif[i]) * 2
        impares += (n // 10) + (n % 10)
    suma = pares + impares
    dig_control = (10 - (suma % 10)) % 10
    letras = "JABCDEFGHI"
    ultimo = cif[8]
    primera = cif[0]
    if primera in "ABEH":
        return ultimo == str(dig_control)
    if primera in "KPQRSNW":
        return ultimo == letras[dig_control]
    return ultimo == str(dig_control) or ultimo == letras[dig_control]


def _spanish_cif_expected_control_chars(cif: str) -> Tuple[str, str]:
    """Devuelve (dígito esperado, letra alternativa si aplica) para mensajes de error."""
    pares = sum(int(cif[i]) for i in range(2, 8, 2))
    impares = 0
    for i in range(1, 8, 2):
        n = int(cif[i]) * 2
        impares += (n // 10) + (n % 10)
    suma = pares + impares
    dig_control = (10 - (suma % 10)) % 10
    letras = "JABCDEFGHI"
    return str(dig_control), letras[dig_control]


def _spanish_dni_nie_valid(nif: str) -> bool:
    """
    Valida DNI (8 dígitos + letra) y NIE (X/Y/Z + 7 dígitos + letra).
    """
    letras = "TRWAGMYFPDXBNJZSQVHLCKE"
    if len(nif) != 9:
        return False

    if nif[:8].isdigit() and nif[8].isalpha():
        numero = int(nif[:8])
        return nif[8] == letras[numero % 23]

    if nif[0] in "XYZ" and nif[1:8].isdigit() and nif[8].isalpha():
        pref = {"X": "0", "Y": "1", "Z": "2"}[nif[0]]
        numero = int(pref + nif[1:8])
        return nif[8] == letras[numero % 23]

    return False


def _assert_spanish_fiscal_valid_for_fd(nif: str) -> None:
    """
    Antes de POST a FacturaDirecta: si parece CIF español (no X/Y/Z), exige dígito de control correcto.
    Así el error es claro en WEARK y no un 400 genérico de FD.
    """
    if len(nif) != 9:
        return

    # DNI/NIE persona física
    if (nif[:8].isdigit() and nif[8].isalpha()) or (nif[0] in "XYZ" and nif[1:8].isdigit() and nif[8].isalpha()):
        if not _spanish_dni_nie_valid(nif):
            letras = "TRWAGMYFPDXBNJZSQVHLCKE"
            if nif[:8].isdigit():
                esperado = letras[int(nif[:8]) % 23]
            else:
                pref = {"X": "0", "Y": "1", "Z": "2"}[nif[0]]
                esperado = letras[int(pref + nif[1:8]) % 23]
            raise FacturaDirectaError(
                f"NIF incorrecto: «{nif}». "
                f"La letra correcta para ese número es «{esperado}». "
                "Corrija el NIF del cliente en WEARK."
            )
        return

    # CIF persona jurídica
    if not (nif[0].isalpha() and nif[1:8].isdigit()):
        return
    if _spanish_cif_checksum_ok(nif):
        return
    dig, letra = _spanish_cif_expected_control_chars(nif)
    primera = nif[0]
    if primera in "KPQRSNW":
        esperado = f"la letra {letra}"
    elif primera in "ABEH":
        esperado = f"el dígito {dig}"
    else:
        esperado = f"el dígito {dig} o la letra {letra}"
    raise FacturaDirectaError(
        f"CIF/NIF incorrecto (dígito de control): «{nif}». "
        f"El último carácter debería ser {esperado}. "
        "Corrija el NIF del cliente en WEARK."
    )


def _compact_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """
    Elimina claves con None para cumplir esquemas que no aceptan null.
    Mantiene strings vacíos solo si se pasan explícitamente (aquí no los enviamos).
    """
    return {k: v for k, v in d.items() if v is not None}


def net_unit_price_for_fd_line(
    precio_unitario: Optional[Any],
    precio_final: Optional[Any],
    descuento: Optional[Any],
) -> Decimal:
    """
    Precio unitario neto que debe enviarse a FacturaDirecta en unitPrice.

    NO debemos enviar además discountRate si el precio ya es neto: FD aplicaría el dto. dos veces,
    o interpretaría mal la escala (p. ej. 1 como 100% en lugar de 1%).
    """
    if precio_final is not None:
        return Decimal(str(precio_final)).quantize(Decimal("0.01"))
    if precio_unitario is None:
        raise FacturaDirectaError("Falta precio unitario en una línea.")
    pu = Decimal(str(precio_unitario))
    try:
        d = Decimal(str(descuento if descuento is not None else 0))
    except Exception:
        d = Decimal(0)
    if d > 0:
        return (pu * (Decimal("1") - d / Decimal("100"))).quantize(Decimal("0.01"))
    return pu.quantize(Decimal("0.01"))


def find_or_create_contact_for_cliente(cliente: Any) -> str:
    """
    Devuelve uuid del contacto en FD. Busca por fiscalId (NIF/CIF) y si no existe lo crea.
    """
    company_id = _fd_company_id()
    nif = _normalize_fiscal_id_es(getattr(cliente, "nif", None) or "")
    nombre = (getattr(cliente, "nombre", None) or "").strip()

    if not nif:
        raise FacturaDirectaError("El cliente no tiene NIF/CIF. FacturaDirecta requiere fiscalId para crear/encontrar contacto.")
    if not nombre:
        raise FacturaDirectaError("El cliente no tiene nombre. FacturaDirecta requiere nombre para crear contacto.")

    _assert_spanish_fiscal_valid_for_fd(nif)

    search = _request("GET", f"/{company_id}/contacts", params={"fiscalId": nif})
    items = search.get("items") or []
    if isinstance(items, list) and items:
        content = items[0].get("content") or {}
        uuid = content.get("uuid")
        if uuid:
            return uuid

    # Crear contacto mínimo
    country = "ES"
    address = (getattr(cliente, "direccion", None) or "").strip()
    zipcode = (getattr(cliente, "codigo_postal", None) or "").strip()
    city = (getattr(cliente, "poblacion", None) or "").strip()

    contact_main = _compact_dict(
        {
            "name": nombre,
            "fiscalId": nif,
            # FD: identificador sin separadores; país y tipo explícitos (VeriFactu / validación NIF español, incl. CIF tipo G).
            "fiscalIdCountry": country,
            "fiscalIdType": "NIF",
            "currency": "EUR",
            "country": country,
            "address": address or None,
            "zipcode": zipcode or None,
            "city": city or None,
            # Algunas cuentas de FD requieren cuentas contables al crear contactos.
            "accounts": {
                "client": (os.environ.get("FACTURADIRECTA_CONTACT_ACCOUNT_CLIENT") or "430000").strip(),
                "clientCredit": (os.environ.get("FACTURADIRECTA_CONTACT_ACCOUNT_CLIENT_CREDIT") or "438000").strip(),
            },
        }
    )

    payload = {
        "content": {
            "type": "contact",
            "main": contact_main,
        }
    }
    created = _request("POST", f"/{company_id}/contacts", json_body=payload)
    return created.get("content", {}).get("uuid") or created.get("content", {}).get("main", {}).get("uuid") or created.get("content", {}).get("id") or created.get("content", {}).get("uuid")


def build_delivery_note_payload(
    *,
    doc_reference: str,
    cliente: Any,
    lines: List[dict],
    tipo_iva_percent: Decimal,
    notes: Optional[str] = None,
) -> dict:
    """
    Construye CreateDeliveryNoteRequest.
    - doc_reference: tu número interno (presupuesto.numero_solicitud o factura.numero)
    - lines: lista de {text, quantity, unitPrice} con precio unitario ya neto (ver net_unit_price_for_fd_line).
    """
    contact_uuid = find_or_create_contact_for_cliente(cliente)
    tax_id = find_sales_tax_id_by_percent(tipo_iva_percent)
    if not tax_id:
        raise FacturaDirectaError(
            f"No se encontró TaxId en FacturaDirecta para IVA {tipo_iva_percent}%. "
            f"Revisa impuestos de venta y permisos (settings:read)."
        )
    # Evitar errores típicos: poner "21" en vez de un TaxId real (tax_xxx / id interno)
    if tax_id.isdigit():
        raise FacturaDirectaError(
            f"TaxId inválido para IVA {tipo_iva_percent}%: '{tax_id}'. "
            f"Debes poner el ID interno del impuesto en FacturaDirecta (no el porcentaje)."
        )

    fd_lines: List[dict] = []
    for idx, l in enumerate(lines, start=1):
        qty = l.get("quantity")
        text = (l.get("text") or "").strip()
        unit_price = l.get("unitPrice")
        if qty is None or text == "" or unit_price is None:
            raise FacturaDirectaError(f"Línea {idx}: faltan campos (quantity/text/unitPrice).")
        fd_line = {
            "quantity": float(qty),
            "text": text,
            "unitPrice": float(unit_price),
            "tax": [tax_id],
        }
        fd_lines.append(fd_line)

    payload = {
        "content": {
            "type": "deliveryNote",
            "main": {
                "baseState": "pending",
                # Dejar que FD asigne número: solo serie obligatoria
                "docNumber": {"series": "WEARK"},
                # Algunas cuentas exigen cuentas contables en main.
                # Se deja configurable por entorno.
                "account": (os.environ.get("FACTURADIRECTA_SALES_ACCOUNT") or "700000").strip(),
                "contact": contact_uuid,
                "date": date.today().isoformat(),
                "notes": notes or f"Documento WEARK: {doc_reference}",
                "lines": fd_lines,
                "taxIncludedPrices": False,
                "taxCalculationMode": "lines",
            },
        }
    }
    return payload


def create_delivery_note(payload: dict) -> dict:
    company_id = _fd_company_id()
    return _request("POST", f"/{company_id}/deliveryNotes", json_body=payload)

