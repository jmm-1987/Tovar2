#!/usr/bin/env python3
"""
Quita la marca de FacturaDirecta (FD) de presupuestos que coincidan con un listado
por cliente + importe total (con IVA), y opcionalmente por fecha.

Columnas del fichero: cliente, total, fecha (opcional pero recomendada)

Uso:
  python desmarcar_presupuestos_fd_desde_listado.py --input lista.tsv --dry-run
  python desmarcar_presupuestos_fd_desde_listado.py --input lista.tsv --apply
  python desmarcar_presupuestos_fd_desde_listado.py --embebido --dry-run
  python desmarcar_presupuestos_fd_desde_listado.py --embebido --apply
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import joinedload

from app import app
from extensions import db
from models import Presupuesto


# Presupuestos a desmarcar FD: (nombre cliente, fecha YYYY-MM-DD, total con coma o punto)
LISTADO_EMBEBIDO: list[tuple[str, str, str]] = [
    ("VERONICA PEREZ CORCHO", "2026-04-07", "1506,3"),
    ("LIBERTRUCKS VEHICULOS INDUSTRIALES SL", "2026-04-06", "314,72"),
    ("RODRÍGUEZ ALMENDROS OPTICOS S.L.", "2026-04-01", "0"),
    ("Airmagic World S.L", "2026-03-31", "1001,88"),
    ("RADIX HUMAN CAPITAL SL", "2026-03-31", "2238,26"),
    ("ALDITRAEX SL", "2026-03-26", "252,16"),
    ("DOWN MÉRIDA", "2026-03-26", "292,58"),
    ("MARTA GIRALDO DONCEL", "2026-03-25", "220,95"),
    ("RAFAEL PATIÑO ESPINOSA", "2026-03-23", "24,2"),
    ("RC Laser Medical Estética España", "2026-03-17", "188,28"),
    # Nombre incompleto en el Excel; si no hace match, corrige aquí como en WEARK
    ("Hermandad de la Sagrada Cena y Ntra Sra del Pat", "2026-03-13", "72,6"),
    ("FUNDACIÓN ACCIÓN CONTRA EL HAMBRE", "2026-02-26", "653,4"),
    ("PERIBERICOS ESPJ", "2026-02-25", "601,49"),
    ("MANUEL SALVADOR", "2026-02-24", "325,49"),
    ("INCORPORESALUD SL", "2026-02-23", "910,22"),
    ("PABLO JAVIER LÓPEZ LÓPEZ", "2026-02-19", "454,14"),
    ("NAV VESTUARIO LABORAL SL", "2026-02-11", "865,15"),
    ("INST. E. SEC. SANTA EULALIA", "2026-01-29", "737,47"),
    ("CARNICAS MALDONADO S.L.", "2026-01-29", "382,55"),
    ("FARMACIA RAYO CORTÉS CB", "2026-01-26", "1305,83"),
    ("PILAR HERNÁNDEZ RINCÓN", "2026-01-23", "2047,32"),
    ("FERNANDO MOLINA LAZCANO", "2026-01-23", "53,24"),
    ("ROCIO PALOMO GARCÍA", "2026-01-22", "65,34"),
    ("GRUPO BRUMA ESPJ", "2026-01-22", "2450,98"),
    ("BURBUR PET CARE SL", "2026-01-21", "1781,1"),
    ("CACHIZARO S.L", "2026-01-20", "292,82"),
    ("AR GESTION DENTAL SLP", "2026-01-20", "1983,65"),
    ("T-EQUIPAMOS S. L.", "2026-01-15", "1715,04"),
    ("CONFEDERACION HIDROGRAFICA DEL GUADIAN", "2026-01-14", "17446,7"),
    ("FARMACIA BECERRA", "2026-01-10", "966,31"),
    ("CLINICA VETERINARIA NAMBROCA C.B.", "2026-01-10", "590,82"),
]


def normalizar_texto(texto: str) -> str:
    if not texto:
        return ""
    t = texto.strip().upper()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^A-Z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_decimal_eur(valor: str) -> Decimal:
    if valor is None:
        return Decimal("0")
    s = str(valor).strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return Decimal(s or "0")


def parse_fecha(valor: str):
    """Devuelve date o None."""
    if not valor or not str(valor).strip():
        return None
    s = str(valor).strip()
    if len(s) >= 19 and s[4] == "-" and s[7] == "-":
        try:
            return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            pass
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    if "/" in s[:10]:
        try:
            return datetime.strptime(s[:10], "%d/%m/%Y").date()
        except ValueError:
            pass
    return None


def total_presupuesto_con_iva(p: Presupuesto) -> Decimal:
    base = Decimal("0")
    for linea in p.lineas:
        cantidad = Decimal(str(linea.cantidad)) if linea.cantidad else Decimal("0")
        precio_unit = Decimal(str(linea.precio_unitario)) if linea.precio_unitario else Decimal("0")
        descuento = Decimal(str(linea.descuento)) if linea.descuento else Decimal("0")
        if linea.precio_final is not None:
            precio_final = Decimal(str(linea.precio_final))
        elif descuento > 0:
            precio_final = precio_unit * (Decimal("1") - descuento / Decimal("100"))
        else:
            precio_final = precio_unit
        base += cantidad * precio_final

    tipo_iva = Decimal("21")
    if p.cliente and getattr(p.cliente, "tipo_iva", None) is not None:
        try:
            tipo_iva = Decimal(str(p.cliente.tipo_iva))
        except Exception:
            pass
    iva = (base * tipo_iva / Decimal("100")).quantize(Decimal("0.01"))
    return (base + iva).quantize(Decimal("0.01"))


def fecha_presupuesto(p: Presupuesto):
    if p.fecha_creacion:
        return p.fecha_creacion.date()
    return None


def leer_listado(path: str) -> list[dict]:
    filas = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        muestra = f.read(2048)
        f.seek(0)
        delimitador = "\t" if "\t" in muestra else ","
        reader = csv.DictReader(f, delimiter=delimitador)
        fieldnames = set(reader.fieldnames or [])
        if "cliente" not in fieldnames or "total" not in fieldnames:
            raise ValueError("El archivo debe incluir columnas: cliente, total (y opcionalmente fecha)")
        for r in reader:
            fecha_raw = (r.get("fecha") or "").strip()
            filas.append(
                {
                    "cliente": (r.get("cliente") or "").strip(),
                    "total": parse_decimal_eur(r.get("total") or ""),
                    "fecha": parse_fecha(fecha_raw) if fecha_raw else None,
                    "cliente_norm": normalizar_texto(r.get("cliente") or ""),
                }
            )
    return filas


def listado_desde_embebido() -> list[dict]:
    filas = []
    for cliente, fecha_s, total_s in LISTADO_EMBEBIDO:
        fecha_raw = (fecha_s or "").strip()
        filas.append(
            {
                "cliente": (cliente or "").strip(),
                "total": parse_decimal_eur(total_s),
                "fecha": parse_fecha(fecha_raw) if fecha_raw else None,
                "cliente_norm": normalizar_texto(cliente or ""),
            }
        )
    return filas


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        help="CSV/TSV: cliente, total, fecha (omitir si usas --embebido)",
    )
    parser.add_argument(
        "--embebido",
        action="store_true",
        help="Usar LISTADO_EMBEBIDO definido en este script (sin fichero)",
    )
    parser.add_argument("--tolerancia", default="0.02", help="Tolerancia importe (default 0.02)")
    parser.add_argument(
        "--ignorar-fecha",
        action="store_true",
        help="No filtrar por fecha (solo cliente + total)",
    )
    parser.add_argument(
        "--incluir-sin-marca-fd",
        action="store_true",
        help="Por defecto solo se consideran presupuestos que ya tienen FD; con esta flag se buscan en todos",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.dry_run == args.apply:
        raise SystemExit("Indica exactamente uno: --dry-run o --apply")

    if bool(args.embebido) == bool(args.input):
        raise SystemExit("Indica exactamente uno: --embebido o --input fichero")

    tolerancia = Decimal(args.tolerancia)
    listado = listado_desde_embebido() if args.embebido else leer_listado(args.input)

    with app.app_context():
        presupuestos = Presupuesto.query.options(
            joinedload(Presupuesto.cliente),
            joinedload(Presupuesto.lineas),
        ).all()

        candidatos = []
        for p in presupuestos:
            if not p.cliente:
                continue
            if not args.incluir_sin_marca_fd and not p.fd_deliverynote_uuid:
                continue
            candidatos.append(
                {
                    "obj": p,
                    "cliente_norm": normalizar_texto(p.cliente.nombre or ""),
                    "total": total_presupuesto_con_iva(p),
                    "fecha": fecha_presupuesto(p),
                }
            )

        matches = []
        ambiguos = []
        sin_match = []
        usados = set()

        for ext in listado:
            encontrados = []
            for c in candidatos:
                if c["obj"].id in usados:
                    continue
                if c["cliente_norm"] != ext["cliente_norm"]:
                    continue
                if abs(c["total"] - ext["total"]) > tolerancia:
                    continue
                if not args.ignorar_fecha and ext["fecha"] is not None:
                    if c["fecha"] is None or c["fecha"] != ext["fecha"]:
                        continue
                encontrados.append(c)

            if len(encontrados) == 1:
                m = encontrados[0]
                usados.add(m["obj"].id)
                matches.append((ext, m))
            elif len(encontrados) > 1:
                ambiguos.append((ext, encontrados))
            else:
                sin_match.append(ext)

        print(f"Entradas listado: {len(listado)}")
        print(f"Desmarcar (match único): {len(matches)}")
        print(f"Ambiguos: {len(ambiguos)}")
        print(f"Sin match: {len(sin_match)}")
        print()

        for ext, m in matches:
            p = m["obj"]
            ref = p.numero_solicitud or str(p.id)
            fd_antes = "sí" if p.fd_deliverynote_uuid else "no"
            print(
                f"QUITAR_FD | {ext['cliente']} | total listado={ext['total']} presup={m['total']} "
                f"| fecha listado={ext['fecha']} presup_fecha={m['fecha']} -> {ref} (FD antes: {fd_antes})"
            )

        if ambiguos:
            print("\n--- AMBIGUOS ---")
            for ext, opts in ambiguos[:40]:
                refs = ", ".join([str(o["obj"].numero_solicitud or o["obj"].id) for o in opts])
                print(f"{ext['cliente']} {ext['total']} -> {refs}")

        if sin_match:
            print("\n--- SIN MATCH ---")
            for ext in sin_match[:40]:
                print(f"{ext['cliente']} | {ext['total']} | fecha={ext['fecha']}")

        if args.apply:
            for ext, m in matches:
                p = m["obj"]
                p.fd_deliverynote_uuid = None
                p.fd_deliverynote_doc_number = None
                p.fd_deliverynote_sent_at = None
                p.fd_deliverynote_last_error = None
            db.session.commit()
            print(f"\nAplicado: quitada marca FD en {len(matches)} presupuestos.")


if __name__ == "__main__":
    main()
