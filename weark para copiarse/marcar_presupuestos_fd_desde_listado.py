#!/usr/bin/env python3
"""
Cruza un listado externo de facturas con presupuestos locales por:
- nombre de cliente (normalizado)
- importe total con IVA (tolerancia configurable)

Uso:
  1) Crear fichero TSV/CSV con columnas: numero,cliente,fecha,total
  2) Ejecutar en dry-run para revisar:
       python marcar_presupuestos_fd_desde_listado.py --input facturas.tsv --dry-run
  3) Ejecutar para aplicar:
       python marcar_presupuestos_fd_desde_listado.py --input facturas.tsv --apply
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
    s = valor.strip().replace("€", "").replace("EUR", "").replace(" ", "")
    # Formatos esperados: 1.234,56 o 1234.56
    if "," in s and "." in s:
        # asume separador miles con punto y decimal coma
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return Decimal(s or "0")


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


def leer_listado(path: str) -> list[dict]:
    filas = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        muestra = f.read(2048)
        f.seek(0)
        delimitador = "\t" if "\t" in muestra else ","
        reader = csv.DictReader(f, delimiter=delimitador)
        required = {"cliente", "total"}
        if not required.issubset(set((reader.fieldnames or []))):
            raise ValueError("El archivo debe incluir al menos las columnas: cliente,total")
        for r in reader:
            filas.append(
                {
                    "numero": (r.get("numero") or "").strip(),
                    "cliente": (r.get("cliente") or "").strip(),
                    "fecha": (r.get("fecha") or "").strip(),
                    "total": parse_decimal_eur(r.get("total") or ""),
                    "cliente_norm": normalizar_texto(r.get("cliente") or ""),
                }
            )
    return filas


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Ruta a CSV/TSV con columnas numero,cliente,fecha,total")
    parser.add_argument("--tolerancia", default="0.02", help="Tolerancia de importe para match (por defecto 0.02)")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar coincidencias, sin guardar")
    parser.add_argument("--apply", action="store_true", help="Aplicar cambios en BD")
    args = parser.parse_args()

    if args.dry_run and args.apply:
        raise SystemExit("Usa solo una opción: --dry-run o --apply")
    if not args.dry_run and not args.apply:
        raise SystemExit("Debes indicar --dry-run o --apply")

    tolerancia = Decimal(args.tolerancia)
    listado = leer_listado(args.input)

    with app.app_context():
        presupuestos = Presupuesto.query.options(
            joinedload(Presupuesto.cliente),
            joinedload(Presupuesto.lineas),
        ).all()

        candidatos = []
        for p in presupuestos:
            if not p.cliente:
                continue
            candidatos.append(
                {
                    "obj": p,
                    "cliente_norm": normalizar_texto(p.cliente.nombre or ""),
                    "total": total_presupuesto_con_iva(p),
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
                if abs(c["total"] - ext["total"]) <= tolerancia:
                    encontrados.append(c)

            if len(encontrados) == 1:
                m = encontrados[0]
                usados.add(m["obj"].id)
                matches.append((ext, m))
            elif len(encontrados) > 1:
                ambiguos.append((ext, encontrados))
            else:
                sin_match.append(ext)

        print(f"Entradas externas: {len(listado)}")
        print(f"Matches únicos: {len(matches)}")
        print(f"Ambiguos: {len(ambiguos)}")
        print(f"Sin match: {len(sin_match)}")
        print("")

        for ext, m in matches:
            p = m["obj"]
            print(
                f"MATCH | ext={ext['numero'] or '-'} {ext['cliente']} {ext['total']} "
                f"-> pres={p.numero_solicitud or p.id} total={m['total']}"
            )

        if ambiguos:
            print("\n--- AMBIGUOS ---")
            for ext, opts in ambiguos[:30]:
                refs = ", ".join([str(o["obj"].numero_solicitud or o["obj"].id) for o in opts])
                print(f"{ext['numero'] or '-'} {ext['cliente']} {ext['total']} -> {refs}")

        if sin_match:
            print("\n--- SIN MATCH ---")
            for ext in sin_match[:50]:
                print(f"{ext['numero'] or '-'} {ext['cliente']} {ext['total']}")

        if args.apply:
            ahora = datetime.utcnow()
            for ext, m in matches:
                p = m["obj"]
                p.fd_deliverynote_uuid = p.fd_deliverynote_uuid or f"MATCH-{ext['numero'] or p.numero_solicitud or p.id}"
                p.fd_deliverynote_doc_number = ext["numero"] or p.fd_deliverynote_doc_number or "MATCH-MANUAL"
                p.fd_deliverynote_sent_at = p.fd_deliverynote_sent_at or ahora
                p.fd_deliverynote_last_error = None
            db.session.commit()
            print(f"\nAplicado: {len(matches)} presupuestos marcados como enviados a FD.")


if __name__ == "__main__":
    main()
