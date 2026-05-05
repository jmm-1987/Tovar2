#!/usr/bin/env python3
"""
Migra facturas directas antiguas a presupuestos.

Criterio de factura directa antigua:
- Factura sin pedido ni presupuesto
- No anticipo
- No rectificativa
- Número que NO corresponde a albarán de retirada (AyyMM_XXX)

Resultado:
- Crea un presupuesto por factura con numero_solicitud distintivo "FDyymm_XX"
- Copia líneas de factura a lineas_presupuesto
- Enlaza factura.presupuesto_id al presupuesto creado
"""

from datetime import datetime
from decimal import Decimal

from app import app
from extensions import db
from models import (
    Cliente,
    Comercial,
    Factura,
    LineaPresupuesto,
    Presupuesto,
    RegistroEstadoSolicitud,
)


def _es_albaran_retirada(numero: str | None) -> bool:
    if not numero:
        return False
    return numero.startswith("A") and "_" in numero


def _resolver_cliente(factura: Factura) -> Cliente | None:
    if factura.cliente_id:
        return Cliente.query.get(factura.cliente_id)

    if factura.nif:
        cliente = Cliente.query.filter(Cliente.nif == factura.nif).first()
        if cliente:
            return cliente

    if factura.nombre:
        return Cliente.query.filter(Cliente.nombre == factura.nombre).first()

    return None


def _resolver_comercial_id(cliente: Cliente | None, comercial_default_id: int | None) -> int | None:
    if cliente and cliente.comercial_id:
        return cliente.comercial_id
    return comercial_default_id


def _siguiente_numero_fd(fecha_base, usados: set[str]) -> str:
    prefijo = f"FD{fecha_base.strftime('%y%m')}"
    existentes = Presupuesto.query.filter(
        Presupuesto.numero_solicitud.like(f"{prefijo}_%")
    ).all()

    max_contador = 0
    for p in existentes:
        if not p.numero_solicitud:
            continue
        partes = p.numero_solicitud.split("_")
        if len(partes) == 2 and partes[0] == prefijo and partes[1].isdigit():
            max_contador = max(max_contador, int(partes[1]))

    contador = max_contador + 1
    while True:
        numero = f"{prefijo}_{contador:02d}"
        if numero not in usados:
            usados.add(numero)
            return numero
        contador += 1


def migrar():
    with app.app_context():
        comercial_default = Comercial.query.order_by(Comercial.id.asc()).first()
        comercial_default_id = comercial_default.id if comercial_default else None

        candidatas = (
            Factura.query.filter(
                Factura.pedido_id.is_(None),
                Factura.presupuesto_id.is_(None),
                Factura.es_anticipo.is_(False),
                Factura.es_rectificativa.is_(False),
            )
            .order_by(Factura.id.asc())
            .all()
        )

        usadas_en_ejecucion: set[str] = set()
        creadas = 0
        saltadas = 0

        for factura in candidatas:
            if _es_albaran_retirada(factura.numero):
                saltadas += 1
                continue

            cliente = _resolver_cliente(factura)
            comercial_id = _resolver_comercial_id(cliente, comercial_default_id)

            if not cliente or not comercial_id:
                print(
                    f"- Saltada factura {factura.id} ({factura.numero}): "
                    "sin cliente resoluble o sin comercial disponible."
                )
                saltadas += 1
                continue

            fecha_base = factura.fecha_expedicion or datetime.now().date()
            numero_solicitud = _siguiente_numero_fd(fecha_base, usadas_en_ejecucion)

            solicitud = Presupuesto(
                numero_solicitud=numero_solicitud,
                comercial_id=comercial_id,
                cliente_id=cliente.id,
                tipo_pedido="varios",
                estado="presupuesto",
                forma_pago="",
                seguimiento=f"Migrado desde factura directa {factura.serie}-{factura.numero}",
                comentarios_cliente=f"Origen: factura directa {factura.serie}-{factura.numero}",
                tipo_producto="N/A",
                colores_principales="",
                colores_secundarios="",
                ubicacion_logo="",
                referencias_web="[]",
                datos_adicionales="[]",
                fecha_presupuesto=fecha_base,
                fecha_creacion=factura.fecha_creacion or datetime.now(),
            )
            db.session.add(solicitud)
            db.session.flush()

            if factura.lineas:
                for lf in factura.lineas:
                    linea = LineaPresupuesto(
                        presupuesto_id=solicitud.id,
                        prenda_id=None,
                        nombre=(lf.descripcion or "Concepto"),
                        cargo="",
                        nombre_mostrar=(lf.descripcion or "Concepto"),
                        prenda_nombre_texto=(lf.descripcion or "Concepto"),
                        cantidad=int(lf.cantidad) if lf.cantidad is not None else 1,
                        color="",
                        forma="",
                        tipo_manda="",
                        sexo="",
                        talla=lf.talla or "",
                        tejido="",
                        precio_unitario=lf.precio_unitario if lf.precio_unitario is not None else Decimal("0"),
                        descuento=lf.descuento if lf.descuento is not None else Decimal("0"),
                        precio_final=lf.precio_final if lf.precio_final is not None else lf.precio_unitario,
                        estado="pendiente",
                    )
                    db.session.add(linea)
            else:
                linea = LineaPresupuesto(
                    presupuesto_id=solicitud.id,
                    prenda_id=None,
                    nombre=factura.descripcion or "Factura directa migrada",
                    cargo="",
                    nombre_mostrar=factura.descripcion or "Factura directa migrada",
                    prenda_nombre_texto=factura.descripcion or "Factura directa migrada",
                    cantidad=1,
                    color="",
                    forma="",
                    tipo_manda="",
                    sexo="",
                    talla="",
                    tejido="",
                    precio_unitario=factura.importe_total if factura.importe_total is not None else Decimal("0"),
                    descuento=Decimal("0"),
                    precio_final=factura.importe_total if factura.importe_total is not None else Decimal("0"),
                    estado="pendiente",
                )
                db.session.add(linea)

            factura.presupuesto_id = solicitud.id

            registro = RegistroEstadoSolicitud(
                presupuesto_id=solicitud.id,
                estado="presupuesto",
                subestado=None,
                usuario_id=None,
            )
            db.session.add(registro)

            creadas += 1
            print(f"+ Factura {factura.id} ({factura.numero}) -> Presupuesto {numero_solicitud}")

        db.session.commit()
        print(f"\nMigración completada. Creados: {creadas}. Saltados: {saltadas}.")


if __name__ == "__main__":
    migrar()
